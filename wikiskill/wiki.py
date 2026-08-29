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


def ensure(ws: str) -> None:
    w = wiki_dir(ws)
    for d in ("", "patterns"):
        os.makedirs(os.path.join(w, d), exist_ok=True)
    for f, content in {
        "index.md": "# Pattern Index\n\n_No patterns yet._\n",
        "log.md": "# Evolution Log\n\n_No iterations yet._\n",
        "skill-impact.md": "# Skill Impact\n\n_No proposals yet._\n",
    }.items():
        p = os.path.join(w, f)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(content)
    if not os.path.isdir(os.path.join(w, ".git")):
        subprocess.run(["git", "init", "-q"], cwd=w, check=False)


def append_skill_impact(ws: str, entry: str) -> None:
    p = os.path.join(wiki_dir(ws), "skill-impact.md")
    with open(p, "a", encoding="utf-8") as f:
        f.write("\n" + entry + "\n")


def append_log(ws: str, line: str) -> None:
    p = os.path.join(wiki_dir(ws), "log.md")
    with open(p, "a", encoding="utf-8") as f:
        f.write(line + "\n")
