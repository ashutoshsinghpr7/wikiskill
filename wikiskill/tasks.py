"""Task registry: load/validate tasks.json, split bookkeeping, sandbox materialization.

Task schema (tasks.json, list of dicts):
  {
    "id": "unique-slug",
    "split": "train" | "val",
    "title": "short title",
    "prompt": "instructions given to the agent",
    "sandbox": {"rel/path.txt": "file content", ...},
    "grader": {...scoring schema...}
  }
"""

from __future__ import annotations

import json
import os

from .scoring import grade  # noqa: F401  (re-export for graders registry)
from . import scoring as _scoring

KNOWN_GRADERS = {"exact", "contains", "json_field", "code_stdout"}
TASKS_FILE = "tasks.json"
SANDBOX_ROOT = os.path.join("bench", "tasks")


def tasks_path(ws: str) -> str:
    return os.path.join(ws, TASKS_FILE)


def load(ws: str) -> list[dict]:
    p = tasks_path(ws)
    if not os.path.exists(p):
        raise FileNotFoundError(f"no {TASKS_FILE} in workspace {ws!r} (run `wikiskill bench`)")
    with open(p, encoding="utf-8") as f:
        tasks = json.load(f)
    validate(tasks)
    return tasks


def validate(tasks: list[dict]) -> None:
    ids = set()
    for t in tasks:
        if not t.get("id") or not re_slug(t["id"]):
            raise ValueError(f"task id must be a slug: {t.get('id')!r}")
        if t["id"] in ids:
            raise ValueError(f"duplicate task id: {t['id']}")
        ids.add(t["id"])
        if t.get("split") not in ("train", "val"):
            raise ValueError(f"task {t['id']}: split must be train|val")
        if not t.get("prompt"):
            raise ValueError(f"task {t['id']}: missing prompt")
        g = t.get("grader", {})
        if not t.get("sandbox") and g.get("type") != "code_stdout":
            raise ValueError(f"task {t['id']}: empty sandbox")
        if g.get("type") not in KNOWN_GRADERS:
            raise ValueError(f"task {t['id']}: unknown grader {g.get('type')!r}")


def re_slug(s: str) -> bool:
    import re

    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", s))


def save(ws: str, tasks: list[dict]) -> None:
    validate(tasks)
    with open(tasks_path(ws), "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)


def splits(ws: str) -> dict[str, list[dict]]:
    tasks = load(ws)
    return {"train": [t for t in tasks if t["split"] == "train"],
            "val": [t for t in tasks if t["split"] == "val"]}


def sandbox_dir(ws: str, task_id: str) -> str:
    return os.path.join(ws, SANDBOX_ROOT, task_id)


def materialize(ws: str, task: dict, force: bool = False) -> str:
    """Write the task's sandbox files into the workspace. Returns the sandbox dir.

    Materialization is idempotent: files are only written if missing (agents may
    legitimately create/overwrite files during a run; `reset` re-materializes).
    """
    d = sandbox_dir(ws, task["id"])
    os.makedirs(d, exist_ok=True)
    for rel, content in task["sandbox"].items():
        p = os.path.join(d, rel)
        if force or not os.path.exists(p):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
    return d


def materialize_all(ws: str, tasks: list[dict], force: bool = False) -> None:
    for t in tasks:
        materialize(ws, t, force=force)
