"""OpenAI Codex CLI agent backend (issue #15).

Runs the loop with OpenAI's Codex CLI in exec mode (`codex exec`), isolated per
workspace via CODEX_HOME. Skills are symlinked into the profile's skills/ dir —
Codex reads skills from $CODEX_HOME/skills, the same open SKILL.md format, so
skills evolved on one backend transfer to the others as-is.

Transcripts come from the session JSONL Codex writes under
$CODEX_HOME/sessions/ (tracked in session_index.jsonl), normalized by
backends/transcript.py into the Raw Layer shape.

Notes / caveats
---------------
- The `codex` binary must be on PATH (`npm i -g @openai/codex` or the Rust
  installer). Authentication lives in ~/.codex/auth.json, which
  bootstrap_profile() copies into the isolated profile — `codex login` once
  on the host, then every workspace run authenticates from its own copy.
- ``patch_model`` stores the model in the profile (model.txt) and it is passed
  through ``--model`` at run time.
- Transcript export reads the newest session JSONL under the profile's
  sessions/ dir; run metadata is parsed from the session_index when present.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

from .base import RunResult
from . import transcript

PROFILE_DIR = ".codex-home"
FRAMEWORK_SKILLS = ("wikiskill-maintainer", "wikiskill-proposer")
DEFAULT_TOOLSETS = "terminal,file,code_execution"


def _real_config_dir() -> str:
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def profile_dir(ws: str) -> str:
    return os.path.join(ws, PROFILE_DIR)


def env(ws: str) -> dict:
    e = dict(os.environ)
    e["CODEX_HOME"] = profile_dir(ws)
    return e


def bootstrap_profile(ws: str, real: str | None = None) -> str:
    """Isolated profile: copy Codex credentials, empty skills dir."""
    real = real or _real_config_dir()
    prof = profile_dir(ws)
    os.makedirs(os.path.join(prof, "skills"), exist_ok=True)
    os.makedirs(os.path.join(prof, "sessions"), exist_ok=True)
    for f in ("auth.json", "config.toml"):
        src = os.path.join(real, f)
        dst = os.path.join(prof, f)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    return prof


def set_active_skills(ws: str, include_framework: bool = False) -> None:
    """Rebuild the profile's skills/ as symlinks of the active set."""
    prof_skills = os.path.join(profile_dir(ws), "skills")
    os.makedirs(prof_skills, exist_ok=True)
    for name in os.listdir(prof_skills):
        p = os.path.join(prof_skills, name)
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
        os.symlink(src, os.path.join(prof_skills, os.path.basename(src)))


def patch_model(ws: str, model: str, provider: str | None = None) -> None:
    """Store the model for run-time use (Codex selects models via --model)."""
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
    """Run one Codex exec turn in the isolated profile."""
    set_active_skills(ws, include_framework=include_framework)
    run_dir = os.path.join(ws, "runs", tag)
    os.makedirs(run_dir, exist_ok=True)
    qfile = os.path.join(run_dir, "query.txt")
    with open(qfile, "w", encoding="utf-8") as f:
        f.write(prompt)

    cmd = ["codex", "exec", "--json", "--full-auto"]
    model = _resolved_model(ws, model)
    if model:
        cmd += ["--model", model]
    # max_turns is accepted by the protocol for interface compatibility, but
    # `codex exec` has no --max-turns flag — the CLI runs to completion per
    # prompt. Passing an unknown flag would break every live run.
    # (No run_budget mapping either: codex has no budget flag in exec mode.)

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


def _newest_session_jsonl(ws: str) -> str | None:
    """Newest *.jsonl under the profile's sessions/ dir (session transcript)."""
    sessions = os.path.join(profile_dir(ws), "sessions")
    if not os.path.isdir(sessions):
        return None
    cands = [os.path.join(sessions, f) for f in os.listdir(sessions)
             if f.endswith(".jsonl")]
    if not cands:
        return None
    return max(cands, key=os.path.getmtime)


def export_session(ws: str, run_dir: str, session_id: str | None = None) -> str | None:
    """Codex transcripts come from the profile's session JSONL files."""
    out_path = os.path.join(run_dir, "stdout.txt")
    dest = os.path.join(run_dir, "session.jsonl")
    src = _newest_session_jsonl(ws)
    if src:
        # codex session files are line-delimited JSONL already carrying
        # message/tool-call structure — normalize to the header shape
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
                # codex session JSONL schema: session_init / user_message /
                # agent_message / tool_call / tool_result (payload-carrying).
                t = ev.get("type", "")
                if t in ("user_message", "agent_message"):
                    messages += 1
                elif t == "tool_call":
                    tool_calls += 1
                kept.append(ev)
        header = {"backend": "codex", "tool_call_count": tool_calls,
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


class CodexBackend:
    """Protocol-compliant facade over the module-level codex functions."""

    name = "codex"
    profile_dir_name = PROFILE_DIR

    def profile_dir(self, ws: str) -> str:
        return profile_dir(ws)

    def env(self, ws: str) -> dict:
        return env(ws)

    def bootstrap_profile(self, ws: str, real: str | None = None) -> str:
        return bootstrap_profile(ws, real=real)

    def set_active_skills(self, ws: str, include_framework: bool = False) -> None:
        return set_active_skills(ws, include_framework=include_framework)

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
