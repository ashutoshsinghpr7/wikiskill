"""Agent backend registry (issue #13).
``wikiskill init --backend`` / ``wikiskill evolve --backend``). Workspaces
created before backends existed have no such file and resolve to Hermes —
full backward compatibility.
"""

from __future__ import annotations

import json
import os

from .base import AgentBackend
from .claude import ClaudeBackend
from .hermes import HermesBackend

BACKENDS: dict[str, AgentBackend] = {
    "hermes": HermesBackend(),
    "claude": ClaudeBackend(),
}
DEFAULT_BACKEND = "hermes"


def workspace_file(ws: str) -> str:
    return os.path.join(ws, "workspace.json")


def read_backend(ws: str) -> str:
    try:
        with open(workspace_file(ws), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return DEFAULT_BACKEND
    # tolerate valid-but-wrong-type JSON (null/[]/42/"x") — corrupt configs
    # fall back, they never crash the loop
    return d.get("backend", DEFAULT_BACKEND) if isinstance(d, dict) else DEFAULT_BACKEND


def write_backend(ws: str, name: str) -> None:
    if name not in BACKENDS:
        raise ValueError(f"unknown backend {name!r}; available: {sorted(BACKENDS)}")
    os.makedirs(ws, exist_ok=True)  # fresh `init` workspaces don't exist yet
    with open(workspace_file(ws), "w", encoding="utf-8") as f:
        json.dump({"backend": name}, f, indent=2)


def get_backend(name: str) -> AgentBackend:
    if name not in BACKENDS:
        raise ValueError(f"unknown backend {name!r}; available: {sorted(BACKENDS)}")
    return BACKENDS[name]


def resolve(ws: str) -> AgentBackend:
    # get_backend (not raw dict access) so a hand-edited workspace.json
    # raises a clear ValueError instead of a KeyError
    return get_backend(read_backend(ws))
