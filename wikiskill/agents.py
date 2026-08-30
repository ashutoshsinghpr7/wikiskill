"""Agent runner facade (issue #13).

Pre-backend API kept intact so harness/gating/cli/tests are untouched: every
function here used to live in this module and now dispatches to the workspace's
pinned backend (see wikiskill.backends). Workspaces without a workspace.json
resolve to Hermes — identical behavior to before this refactor.

The module-level Hermes helpers are re-exported for backward compatibility and
for tests that assert on hermes-specific behavior.
"""

from __future__ import annotations

from .backends import resolve


def bootstrap_profile(ws: str, real: str | None = None) -> str:
    """Isolated profile for the workspace's backend (config + creds copy)."""
    return resolve(ws).bootstrap_profile(ws, real=real)


def set_active_skills(ws: str, include_framework: bool = False) -> None:
    """Rebuild the isolated profile's skills as symlinks of the active set."""
    resolve(ws).set_active_skills(ws, include_framework=include_framework)


def patch_profile_model(ws: str, model: str, provider: str | None = None) -> None:
    """Point the workspace's backend at `model` (Hermes: config patch; Claude: no-op)."""
    resolve(ws).patch_model(ws, model, provider)


def run_agent(ws: str, prompt: str, *, tag: str, toolsets: str | None = None,
              model: str | None = None, max_turns: int = 15, run_budget: int = 300,
              workdir: str | None = None, include_framework: bool = False,
              dry_run: bool = False) -> dict:
    """Run one agent turn on the workspace's backend. Returns the legacy dict
    shape consumed by gating.run_task (cmd/exit_code/duration_s/stdout_path/
    session_file + dry-run extras)."""
    res = resolve(ws).run(ws, prompt, tag=tag, toolsets=toolsets, model=model,
                          max_turns=max_turns, run_budget=run_budget,
                          workdir=workdir, include_framework=include_framework,
                          dry_run=dry_run)
    return {"cmd": res.cmd, "exit_code": res.exit_code,
            "duration_s": res.duration_s, "stdout_path": res.stdout_path,
            "session_file": res.session_file, "dry_run": res.dry_run,
            **res.extra}
