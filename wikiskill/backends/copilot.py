"""GitHub Copilot CLI agent backend (issue #24).

Runs the loop with the GitHub Copilot CLI in non-interactive print mode
(`copilot -p <prompt>` piped via stdin), isolated per workspace via
COPILOT_HOME. Copilot reads project skills from `.github/skills/` of a
trusted directory (`--add-dir`); the active skill set is symlinked into the
run's working directory (the task sandbox) so gating sees exactly S_k.

Transcripts: the CLI writes streaming session events under
$COPILOT_HOME/session-state/<session-id>/events.jsonl — normalized into the
Raw Layer shape (header + events). When no session file is present (dry runs
or launch failure), stdout.txt is used, and empty output is never served as
a transcript.

Notes / caveats
---------------
- Authentication: `copilot login` once on the host stores ~/.copilot/config.json
  (GitHub OAuth); bootstrap_profile() copies it into the isolated profile.
  The CLI also accepts GH_TOKEN/GITHUB_TOKEN env vars, so headless CI runs can
  pass `GH_TOKEN=$(gh auth token)` instead of a stored login.
- ``--allow-all-tools --allow-all-paths --no-ask-user`` are required for
  non-interactive runs; the run's blast radius is contained by pinning
  ``cwd=`` to the task sandbox (and ``--add-dir`` to that same directory).
- Copilot has no max-turns/budget flags in the CLI contract; runs proceed to
  completion per prompt (documented deviation from claude/codex backends).
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import time

from .base import RunResult
from . import transcript

PROFILE_DIR = ".copilot-home"
FRAMEWORK_SKILLS = ("wikiskill-maintainer", "wikiskill-proposer")
DEFAULT_TOOLSETS = "terminal,file,code_execution"


def _real_config_dir() -> str:
    return os.environ.get("COPILOT_HOME") or os.path.expanduser("~/.copilot")


def profile_dir(ws: str) -> str:
    return os.path.join(ws, PROFILE_DIR)


def env(ws: str) -> dict:
    e = dict(os.environ)
    e["COPILOT_HOME"] = profile_dir(ws)
    return e


def bootstrap_profile(ws: str, real: str | None = None) -> str:
    """Isolated profile: copy Copilot credentials (GitHub OAuth config)."""
    real = real or _real_config_dir()
    prof = profile_dir(ws)
    os.makedirs(prof, exist_ok=True)
    for f in ("config.json",):
        src = os.path.join(real, f)
        dst = os.path.join(prof, f)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    return prof


def _sandbox_skills_dir(workdir: str | None, ws: str) -> str:
    """Copilot's project-skill dir (.github/skills) in the run context.

    Inference runs pin the task sandbox (workdir); maintainer/proposer turns
    operate at the workspace level, so the fallback is the workspace root.
    """
    d = os.path.join(workdir or ws, ".github", "skills")
    os.makedirs(d, exist_ok=True)
    return d


def set_active_skills(ws: str, include_framework: bool = False,
                      workdir: str | None = None) -> None:
    """Symlink the active skill set into the run context's .github/skills/."""
    dest = _sandbox_skills_dir(workdir, ws)
    for name in os.listdir(dest):
        p = os.path.join(dest, name)
        if os.path.islink(p):
            os.unlink(p)
        elif os.path.isdir(p):
            shutil.rmtree(p)
    sources = []
    active = os.path.join(ws, "skills", "active")
    if os.path.isdir(active):
        for name in sorted(os.listdir(active)):
            sources.append(os.path.join(active, name))
    if include_framework:
        fw = os.path.join(ws, "skills", "framework")
        if os.path.isdir(fw):
            for name in sorted(os.listdir(fw)):
                sources.append(os.path.join(fw, name))
    for src in sources:
        os.symlink(src, os.path.join(dest, os.path.basename(src)))


def patch_model(ws: str, model: str, provider: str | None = None) -> None:
    """Store the model for run-time use (Copilot selects models via --model)."""
    os.makedirs(profile_dir(ws), exist_ok=True)
    with open(os.path.join(profile_dir(ws), "model.txt"), "w", encoding="utf-8") as f:
        f.write(model)


def _resolved_model(ws: str, model: str | None) -> str | None:
    if model:
        return model
    p = os.path.join(profile_dir(ws), "model.txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            m = f.read().strip()
        if m:
            return m
    return None


def run(ws: str, prompt: str, *, tag: str, toolsets: str = DEFAULT_TOOLSETS,
        model: str | None = None, max_turns: int = 15, run_budget: int = 300,
        workdir: str | None = None, include_framework: bool = False,
        dry_run: bool = False) -> RunResult:
    """Run one Copilot CLI turn (non-interactive print mode)."""
    set_active_skills(ws, include_framework=include_framework, workdir=workdir)
    run_dir = os.path.join(ws, "runs", tag)
    os.makedirs(run_dir, exist_ok=True)
    qfile = os.path.join(run_dir, "query.txt")
    with open(qfile, "w", encoding="utf-8") as f:
        f.write(prompt)

    cmd = ["copilot", "-p", "-s", "--allow-all-tools", "--allow-all-paths",
           "--no-ask-user"]
    add_dir = workdir or ws
    cmd += ["--add-dir", add_dir]
    model = _resolved_model(ws, model)
    if model:
        cmd += ["--model", model]

    if dry_run:
        return RunResult(cmd=cmd, dry_run=True, extra={"run_dir": run_dir,
                                                       "qfile": qfile})

    cwd = workdir or ws
    t0 = time.time()
    out_path = os.path.join(run_dir, "stdout.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        p = subprocess.run(cmd, env=env(ws), cwd=cwd, input=prompt,
                           stdout=f, stderr=subprocess.STDOUT, text=True)
    dur = round(time.time() - t0, 1)
    session_file = None
    if os.path.getsize(out_path) > 0:
        session_file = export_session(ws, run_dir)
    return RunResult(cmd=cmd, exit_code=p.returncode, duration_s=dur,
                     stdout_path=out_path, session_file=session_file)


def _newest_session_events(ws: str) -> str | None:
    """Newest events.jsonl under $COPILOT_HOME/session-state/<id>/."""
    root = os.path.join(profile_dir(ws), "session-state")
    if not os.path.isdir(root):
        return None
    cands = glob.glob(os.path.join(root, "*", "events.jsonl"))
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def export_session(ws: str, run_dir: str, session_id: str | None = None) -> str | None:
    """Copilot transcripts: normalize the newest session events.jsonl."""
    out_path = os.path.join(run_dir, "stdout.txt")
    dest = os.path.join(run_dir, "session.jsonl")
    src = _newest_session_events(ws)
    if src:
        tool_calls, messages = 0, 0
        kept = []
        with open(src, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(ev, dict):
                    continue
                # real copilot events.jsonl schema (v1.0.x):
                # user.message / assistant.message / tool.execution_start
                # tool.execution_complete / system.message / session.*
                t = ev.get("type", "")
                if t in ("user.message", "assistant.message"):
                    messages += 1
                elif t == "tool.execution_start":
                    tool_calls += 1
                kept.append(ev)
        header = {"backend": "copilot", "tool_call_count": tool_calls,
                  "message_count": messages}
        with open(dest, "w", encoding="utf-8") as out:
            out.write(json.dumps(header) + "\n")
            for ev in kept:
                out.write(json.dumps(ev) + "\n")
        return dest
    if os.path.exists(out_path):
        if os.path.getsize(out_path) == 0:
            if os.path.exists(dest):
                os.remove(dest)
            return None
        return transcript.normalize_hermes(out_path, dest)
    return dest if os.path.exists(dest) else None


class CopilotBackend:
    """Protocol-compliant facade over the module-level copilot functions."""

    name = "copilot"
    profile_dir_name = PROFILE_DIR

    def profile_dir(self, ws: str) -> str:
        return profile_dir(ws)

    def env(self, ws: str) -> dict:
        return env(ws)

    def bootstrap_profile(self, ws: str, real: str | None = None) -> str:
        return bootstrap_profile(ws, real=real)

    def set_active_skills(self, ws: str, include_framework: bool = False,
                          workdir: str | None = None) -> None:
        return set_active_skills(ws, include_framework=include_framework,
                                 workdir=workdir)

    def patch_model(self, ws: str, model: str, provider: str | None = None) -> None:
        return patch_model(ws, model, provider)

    def run(self, ws: str, prompt: str, *, tag: str,
            toolsets: str | None = None, model: str | None = None,
            max_turns: int = 15, run_budget: int = 300,
            workdir: str | None = None, include_framework: bool = False,
            dry_run: bool = False) -> RunResult:
        return run(ws, prompt, tag=tag,
                   toolsets=toolsets or DEFAULT_TOOLSETS, model=model,
                   max_turns=max_turns, run_budget=run_budget,
                   workdir=workdir, include_framework=include_framework,
                   dry_run=dry_run)

    def export_session(self, ws: str, run_dir: str,
                       session_id: str | None = None) -> str | None:
        return export_session(ws, run_dir, session_id)
