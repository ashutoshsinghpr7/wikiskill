"""Skill transfer across workspaces/models (issue #1).

The paper shows evolved skills transfer across models and model families.
`transfer` exports the active skill set from one workspace and installs it
into another workspace's active set, where the destination's own model can be
gated against it (`wikiskill gate` / `evolve`). The destination's previous
skill state is preserved in its own git history, so a rejected transfer rolls
back exactly like any other rejected proposal.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def active_skills(ws: str) -> list[str]:
    d = os.path.join(ws, "skills", "active")
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d)
                  if os.path.isdir(os.path.join(d, n)) and not n.startswith("."))


def transfer_skills(src: str, dst: str, *, force: bool = False) -> dict:
    """Copy src's active skills into dst's active set. Returns a manifest."""
    src_dir = os.path.join(src, "skills", "active")
    dst_dir = os.path.join(dst, "skills", "active")
    if not os.path.isdir(src_dir):
        raise ValueError(f"no active skills in source workspace: {src}")
    if not os.path.isdir(dst_dir):
        raise ValueError(f"no active skills in destination workspace: {dst}")
    if not active_skills(src):
        raise ValueError(f"no active skills in source workspace: {src}")
    # destination must have its own git history so transfers can be rolled back
    if not os.path.isdir(os.path.join(dst_dir, ".git")):
        subprocess.run(["git", "init", "-q"], cwd=dst_dir, check=False)

    names = active_skills(src)
    transferred, skipped = [], []
    for n in names:
        s = os.path.join(src_dir, n)
        if not os.path.isfile(os.path.join(s, "SKILL.md")):
            skipped.append(n)
            continue
        t = os.path.join(dst_dir, n)
        if os.path.exists(t) and not force:
            skipped.append(n)
            continue
        if os.path.exists(t):
            shutil.rmtree(t)
        shutil.copytree(s, t)
        transferred.append(n)
    if transferred:
        subprocess.run(["git", "-c", "user.email=wikiskill@local",
                        "-c", "user.name=wikiskill", "add", "-A"],
                       cwd=dst_dir, check=False)
        subprocess.run(["git", "-c", "user.email=wikiskill@local",
                        "-c", "user.name=wikiskill", "commit", "-q",
                        "-m", f"transfer from {os.path.basename(src)}: "
                              f"{', '.join(transferred)}"],
                       cwd=dst_dir, check=False)
    return {"transferred": transferred, "skipped": skipped,
            "source": os.path.basename(src), "destination": os.path.basename(dst)}


def format_report(m: dict) -> str:
    lines = [f"transfer {m['source']} → {m['destination']}"]
    if m["transferred"]:
        lines.append("  installed: " + ", ".join(m["transferred"]))
    if m["skipped"]:
        lines.append("  skipped:   " + ", ".join(m["skipped"]) +
                     " (no SKILL.md or already present; use --force to overwrite)")
    if not m["transferred"]:
        lines.append("  nothing to transfer")
    lines.append("  next: `wikiskill gate --iter 0` in the destination to test "
                 "the transferred skills against its own model")
    return "\n".join(lines)
