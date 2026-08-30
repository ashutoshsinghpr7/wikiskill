"""Wiki Layer: persistent knowledge base structure + programmatic helpers.

The wiki is maintained by the Wiki Maintainer agent (direct edits via its file
tools); the harness only guarantees the skeleton and appends the machine-readable
gate outcomes (skill-impact.md entries, log lines).
"""

from __future__ import annotations

import os
import subprocess


def wiki_dir(ws: str) -> str:
    return os.path.join(ws, "wiki")


def _git(w: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=wikiskill@local", "-c", "user.name=wikiskill",
                    *args], cwd=w, capture_output=True, text=True)


def commit(ws: str, message: str) -> None:
    """Audit-trail commit for the wiki (knowledge is never rolled back, but
    every change is recorded — including who made it and when)."""
    w = wiki_dir(ws)
    if not os.path.isdir(os.path.join(w, ".git")):
        subprocess.run(["git", "init", "-q"], cwd=w)
    _git(w, "add", "-A")
    _git(w, "commit", "-q", "--allow-empty", "-m", message)


def ensure(ws: str) -> None:
    w = wiki_dir(ws)
    for d in ("", "patterns"):
        os.makedirs(os.path.join(w, d), exist_ok=True)
    fresh = False
    for f, content in {
        "index.md": "# Pattern Index\n\n_No patterns yet._\n",
        "log.md": "# Evolution Log\n\n_No iterations yet._\n",
        "skill-impact.md": "# Skill Impact\n\n_No proposals yet._\n",
    }.items():
        p = os.path.join(w, f)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(content)
            fresh = True
    if fresh or not os.path.isdir(os.path.join(w, ".git")):
        commit(ws, "wiki skeleton")


def append_skill_impact(ws: str, entry: str) -> None:
    p = os.path.join(wiki_dir(ws), "skill-impact.md")
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n" + entry + "\n")


def append_log(ws: str, line: str) -> None:
    p = os.path.join(wiki_dir(ws), "log.md")
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
