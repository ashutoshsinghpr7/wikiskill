"""Task graders. Every grader returns a float score in [0, 1].

Graders operate on the task's sandbox directory *after* the agent finished,
so they can check produced files or run produced scripts.

Grader schemas (task["grader"]):
  {"type": "exact",        "file": "output.txt",  "expected": "..."}   normalized equality
  {"type": "contains",     "file": "output.txt",  "needle": "..."}     substring check
  {"type": "json_field",   "file": "out.json",    "path": ["a","b"], "expected": "..."}
  {"type": "code_stdout",  "script": "solve.py",  "expected": "..."}   run python3 script, compare stdout
"""

from __future__ import annotations

import json
import os
import re
import subprocess


def normalize(s: str) -> str:
    """Whitespace-normalized string for forgiving exact comparisons."""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def read_sandbox_file(sandbox: str, rel: str) -> str:
    path = rel if os.path.isabs(rel) else os.path.join(sandbox, rel)
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def grade(task: dict, sandbox: str) -> float:
    g = task["grader"]
    t = g["type"]
    if t == "exact":
        got = read_sandbox_file(sandbox, g["file"])
        return 1.0 if normalize(got) == normalize(g["expected"]) else 0.0
    if t == "contains":
        got = read_sandbox_file(sandbox, g["file"])
        return 1.0 if g["needle"] in got else 0.0
    if t == "json_field":
        data = json.loads(read_sandbox_file(sandbox, g["file"]))
        val = data
        for key in g["path"]:
            val = val[key]
        return 1.0 if normalize(val) == normalize(g["expected"]) else 0.0
    if t == "code_stdout":
        script = g.get("script", "solve.py")
        p = subprocess.run(
            ["python3", script],
            cwd=sandbox,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return 1.0 if normalize(p.stdout) == normalize(g["expected"]) else 0.0
    raise ValueError(f"unknown grader type: {t!r}")
