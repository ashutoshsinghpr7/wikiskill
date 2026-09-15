"""Agent backend protocol (issue #13).

The whole Algorithm-1 loop is agent-agnostic: it talks to an AgentBackend for
exactly five operations. Hermes is the reference backend; Claude Code ships in
this PR; Codex and OpenCode are follow-ups.

Contract notes
--------------
- ``run()`` must return a ``RunResult`` even on failure (exit_code != 0).
- ``run(dry_run=True)`` must return the constructed argv without executing.
- ``export_session()`` must write a NORMALIZED transcript: a JSONL file whose
  first line is an object carrying ``tool_call_count`` and ``message_count``
  (the gating layer's launch-failure check reads exactly those two fields),
  followed by one JSON object per raw message/event when available.
- Profiles must be isolated per workspace so gating sees exactly the active
  skill set and no user memory/state leaks in.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class RunResult:
    cmd: list[str]
    exit_code: int | None = None
    duration_s: float = 0.0
    stdout_path: str | None = None
    session_file: str | None = None
    dry_run: bool = False
    extra: dict = field(default_factory=dict)


@runtime_checkable
class AgentBackend(Protocol):
    name: str
    profile_dir_name: str

    def profile_dir(self, ws: str) -> str: ...
    def env(self, ws: str) -> dict: ...
    def bootstrap_profile(self, ws: str, real: str | None = None) -> str: ...
    def set_active_skills(self, ws: str, include_framework: bool = False) -> None: ...
    def patch_model(self, ws: str, model: str, provider: str | None = None) -> None: ...
    def run(self, ws: str, prompt: str, *, tag: str,
            toolsets: str | None = None, model: str | None = None,
            max_turns: int = 15, run_budget: int = 300,
            workdir: str | None = None, include_framework: bool = False,
            dry_run: bool = False) -> RunResult: ...
    def export_session(self, ws: str, run_dir: str,
                       session_id: str | None = None) -> str | None: ...


FRAMEWORK_SKILLS: tuple[str, ...] = ("wikiskill-maintainer", "wikiskill-proposer")


def framework_skill_names(ws: str) -> list[str]:
    """Framework skills actually staged (with a SKILL.md) in the workspace."""
    fw = os.path.join(ws, "skills", "framework")
    return [n for n in FRAMEWORK_SKILLS
            if os.path.isfile(os.path.join(fw, n, "SKILL.md"))]


def warn_if_missing_framework_skills(ws: str) -> list[str]:
    """Complain loudly when a framework turn is about to run under-skilled.

    The maintainer/proposer prompts tell the agent to load the framework skill,
    so a missing (or half-staged) `skills/framework/` silently degrades the run:
    the scores stay well-formed and nothing is logged (issue #29).
    `harness.ensure_framework_skills` is the fix; this is the last-resort tripwire
    for any path that reaches a backend without going through it.
    """
    missing = [n for n in FRAMEWORK_SKILLS if n not in framework_skill_names(ws)]
    if missing:
        print(
            f"[wikiskill] WARNING: include_framework=True but {missing} are not "
            f"staged in {os.path.join(ws, 'skills', 'framework')!r} — this turn is "
            f"running with NO framework skill loaded and its output is not "
            f"trustworthy. Reinstall wikiskill>=0.1.5 or re-run `wikiskill init`.",
            file=sys.stderr,
        )
    return missing
