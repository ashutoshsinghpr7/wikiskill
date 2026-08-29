"""Gating: validation runs, strict-improvement acceptance, skill-set git
management (apply proposal / rollback), and the persisted evolution state.

Implements Algorithm 1's gating semantics:
  if R(T_val,k) > R_best: accept (S_k <- S'_k, R_best <- R)
  else: reject, roll back skills only; wiki retained.
"""

from __future__ import annotations

import json
import os
import subprocess

from . import agents, prompts, scoring, traces

STATE_FILE = os.path.join("runs", "state.json")


def state_path(ws: str) -> str:
    return os.path.join(ws, STATE_FILE)


def load_state(ws: str) -> dict:
    p = state_path(ws)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"domain": os.path.basename(ws.rstrip("/")), "r_best": None,
            "baseline": None, "next_iter": 1, "history": []}


def save_state(ws: str, state: dict) -> None:
    os.makedirs(os.path.dirname(state_path(ws)), exist_ok=True)
    with open(state_path(ws), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------- git (skills)

def active_dir(ws: str) -> str:
    return os.path.join(ws, "skills", "active")


def ensure_active_repo(ws: str) -> None:
    d = active_dir(ws)
    os.makedirs(d, exist_ok=True)
    if not os.path.isdir(os.path.join(d, ".git")):
        subprocess.run(["git", "init", "-q"], cwd=d, check=False)
        subprocess.run(["git", "-c", "user.email=wikiskill@local",
                        "-c", "user.name=wikiskill", "commit", "-q", "--allow-empty",
                        "-m", "S0: empty skill set"], cwd=d, check=False)


def git_active(ws: str, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=active_dir(ws),
                          capture_output=True, text=True, check=check)


def commit_base(ws: str, k: int) -> None:
    """Snapshot the active skill set before a proposal is applied."""
    git_active(ws, "add", "-A")
    git_active(ws, "-c", "user.email=wikiskill@local", "-c", "user.name=wikiskill",
               "commit", "-q", "--allow-empty", "-m", f"base iter-{k}")


def apply_proposal(ws: str, proposal: dict) -> str:
    """Apply a proposer proposal to the active skill set. Returns a description."""
    action = proposal.get("action")
    if action == "no_action":
        return "no_action"
    name = proposal["name"]
    dest = os.path.join(active_dir(ws), name)
    os.makedirs(dest, exist_ok=True)
    if action == "create":
        with open(os.path.join(dest, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(proposal["skill_md"])
        if proposal.get("purpose_md"):
            with open(os.path.join(dest, "PURPOSE.md"), "w", encoding="utf-8") as f:
                f.write(proposal["purpose_md"])
        return f"create {name}"
    if action == "patch":
        target_file = os.path.join(dest, proposal.get("file", "SKILL.md"))
        with open(target_file, encoding="utf-8") as f:
            content = f.read()
        for edit in proposal["edits"]:
            op = edit["op"]
            if op == "append":
                content += "\n" + edit["content"]
            elif op == "replace":
                if edit["target"] not in content:
                    raise ValueError(f"patch replace target not found in {name}: {edit['target'][:60]!r}")
                content = content.replace(edit["target"], edit["content"], 1)
            elif op == "insert_after":
                if edit["target"] not in content:
                    raise ValueError(f"patch insert_after target not found in {name}: {edit['target'][:60]!r}")
                content = content.replace(edit["target"],
                                          edit["target"] + "\n" + edit["content"], 1)
            else:
                raise ValueError(f"unknown patch op {op!r}")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)
        return f"patch {name}"
    raise ValueError(f"unknown proposal action {action!r}")


def rollback(ws: str) -> None:
    """Restore the active skill set to the last committed base (reject case)."""
    git_active(ws, "reset", "--hard", "-q")
    git_active(ws, "clean", "-fd", "-q")


def skill_diff(ws: str) -> str:
    """Unified diff of uncommitted changes in the active skill set."""
    p = git_active(ws, "diff")
    return p.stdout


def accept_commit(ws: str, k: int, r_val: float) -> None:
    git_active(ws, "add", "-A")
    git_active(ws, "-c", "user.email=wikiskill@local", "-c", "user.name=wikiskill",
               "commit", "-q", "-m", f"accept iter-{k} R={r_val}")


# ---------------------------------------------------------------- run helpers

def run_task(ws: str, task: dict, it: int, *, model: str | None = None,
             runner=agents.run_agent, dry_run: bool = False,
             overwrite: bool = False) -> dict:
    """Inference rollout on one task + grading + trace capture."""
    from . import tasks as tasks_mod

    sandbox = tasks_mod.sandbox_dir(ws, task["id"])
    if not os.path.isdir(sandbox):
        sandbox = tasks_mod.materialize(ws, task)
    tag = f"iter-{it:02d}/{task['split']}/{task['id']}"
    prompt = prompts.inference_prompt(task, sandbox=sandbox)
    res = runner(ws, prompt, tag=tag, workdir=sandbox, model=model, dry_run=dry_run)
    score = None if dry_run else scoring.grade(task, sandbox)
    meta = {
        "task_id": task["id"], "split": task["split"], "iter": it,
        "title": task["title"], "score": score, "model": model,
        "exit_code": res.get("exit_code"), "duration_s": res.get("duration_s"),
    }
    traces.save_trace(ws, it, task["split"], task["id"], meta,
                      transcript_src=res.get("session_file"),
                      overwrite=overwrite or bool(dry_run))
    return {**task, "score": score, "result": res}


def mean_score(results: list[dict]) -> float:
    scores = [r["score"] for r in results if r["score"] is not None]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def run_gate(ws: str, tasks: list[dict], it: int, *, model: str | None = None,
             runner=agents.run_agent, dry_run: bool = False,
             overwrite: bool = False) -> dict:
    """Validation rollout over a task split with the *current* active skills."""
    results = [run_task(ws, t, it, model=model, runner=runner, dry_run=dry_run,
                        overwrite=overwrite)
               for t in tasks]
    return {"iter": it, "results": results, "mean": mean_score(results)}
