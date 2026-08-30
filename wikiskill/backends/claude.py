"""Claude Code agent backend (issue #13).

Runs the loop with Anthropic's Claude Code CLI in print mode (`claude -p`),
isolated per workspace via CLAUDE_CONFIG_DIR. Skills are symlinked into the
profile's `.claude/skills/` — the same open SKILL.md format Hermes uses, so
skills evolved on one backend transfer to the other as-is.

Transcripts come from `--output-format stream-json`: the stream IS the session
log (every assistant/user event), normalized by backends/transcript.py into
the Raw Layer shape.

Notes / caveats
---------------
- ``patch_model`` is a no-op: Claude selects models via the ``--model`` flag
  at run time, so there is no profile config to rewrite.
- ``run_budget`` (Hermes unit, cents-ish) maps to ``--max-budget-usd``
  (dollars): budget/100, floored at 0.05 (Claude's system-prompt cache floor).
- The working directory is pinned via ``cwd=`` on the subprocess — Claude Code
  genuinely operates in its CWD, unlike Hermes' ``--in`` flag (which does not
  anchor the agent; see docs/RUNS.md bug #1).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

from .base import RunResult
from . import transcript

PROFILE_DIR = ".claude-home"
FRAMEWORK_SKILLS = ("wikiskill-maintainer", "wikiskill-proposer")
DEFAULT_TOOLSETS = "terminal,file,code_execution"

# Hermes toolset name -> Claude Code --allowedTools entries
_TOOLSET_MAP = {
    "terminal": "Bash",
    "file": "Read,Write,Edit",
    "code_execution": "Bash",
}


def _real_config_dir() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def profile_dir(ws: str) -> str:
    return os.path.join(ws, PROFILE_DIR)


def env(ws: str) -> dict:
    e = dict(os.environ)
    e["CLAUDE_CONFIG_DIR"] = profile_dir(ws)
    return e


def bootstrap_profile(ws: str, real: str | None = None) -> str:
    """Isolated profile: copy Claude config + credentials, empty skills dir.

    Skills are symlinked per-run by set_active_skills(); the copied credentials
    (settings.json / .credentials.json / ~/.claude.json) let runs authenticate
    without touching the user's real config. If the real config dir is missing,
    the profile still works for runs authenticated via ANTHROPIC_API_KEY.
    """
    real = real or _real_config_dir()
    prof = profile_dir(ws)
    os.makedirs(os.path.join(prof, "skills"), exist_ok=True)
    os.makedirs(os.path.join(prof, "projects"), exist_ok=True)
    for f in ("settings.json", ".credentials.json", ".claude.json"):
        src = os.path.join(real, f)
        dst = os.path.join(prof, f)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    return prof


def set_active_skills(ws: str, include_framework: bool = False) -> None:
    """Rebuild the profile's .claude/skills as symlinks of the active set."""
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
    """No-op: Claude selects models via --model at run time."""
    return None


def _allowed_tools(toolsets: str) -> str:
    seen, parts = set(), []
    for ts in toolsets.split(","):
        for t in _TOOLSET_MAP.get(ts.strip(), "").split(","):
            if t and t not in seen:
                seen.add(t)
                parts.append(t)
    return ",".join(parts)


def run(ws: str, prompt: str, *, tag: str, toolsets: str = DEFAULT_TOOLSETS,
        model: str | None = None, max_turns: int = 15, run_budget: int = 300,
        workdir: str | None = None, include_framework: bool = False,
        dry_run: bool = False) -> RunResult:
    """Run one Claude Code turn (print mode) in the isolated profile."""
    set_active_skills(ws, include_framework=include_framework)
    run_dir = os.path.join(ws, "runs", tag)
    os.makedirs(run_dir, exist_ok=True)
    qfile = os.path.join(run_dir, "query.txt")
    with open(qfile, "w", encoding="utf-8") as f:
        f.write(prompt)

    cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
           "--max-turns", str(max_turns),
           "--permission-mode", "acceptEdits",
           "--allowedTools", _allowed_tools(toolsets)]
    if model:
        cmd += ["--model", model]
    budget = max(0.05, run_budget / 100.0)
    cmd += ["--max-budget-usd", f"{budget:.2f}"]

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
        session_file = transcript.normalize_claude_stream(
            out_path, os.path.join(run_dir, "session.jsonl"))
    return RunResult(cmd=cmd, exit_code=p.returncode, duration_s=dur,
                     stdout_path=out_path, session_file=session_file)


def export_session(ws: str, run_dir: str, session_id: str | None = None) -> str | None:
    """Claude transcripts come from the captured stream; nothing more to do
    unless stdout.txt exists but session.jsonl wasn't written (edge: dry run
    or empty output)."""
    out_path = os.path.join(run_dir, "stdout.txt")
    dest = os.path.join(run_dir, "session.jsonl")
    if os.path.exists(out_path) and not os.path.exists(dest):
        if os.path.getsize(out_path) == 0:
            return None
        return transcript.normalize_claude_stream(out_path, dest)
    return dest if os.path.exists(dest) else None


class ClaudeBackend:
    """Protocol-compliant facade over the module-level claude functions."""

    name = "claude"
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
