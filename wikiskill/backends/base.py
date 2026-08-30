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
