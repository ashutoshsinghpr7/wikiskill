"""Algorithm 1 orchestration: the full WikiSkill evolution loop for Hermes.

    for k in 1..K:
      if R_best == 1.0: break
      train rollouts (S_{k-1})        → raw layer
      stratified sample (≤5 fail, ≤3 pass)
      wiki maintenance (maintainer)   → wiki layer  (never rolled back)
      skill proposal (proposer)       → candidate S'_k
      apply proposal, gate on val
      if R_val > R_best: accept, commit
      else: roll back skills only; wiki retained
      update skill-impact.md + log.md
"""

from __future__ import annotations

import json
import os
import random
import shutil

from . import agents, gating, prompts, tasks as tasks_mod, traces, wiki

FRAMEWORK_SKILLS = ("wikiskill-maintainer", "wikiskill-proposer")


def repo_skills_dir() -> str:
    """The repo's skills/ dir (framework skills shipped with the package)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "skills")


def init_workspace(ws: str) -> None:
    """Create a fresh evolution workspace (idempotent)."""
    for d in ("raw/traces", "wiki/patterns", "skills/active", "skills/framework",
              "runs/proposals", "bench"):
        os.makedirs(os.path.join(ws, d), exist_ok=True)
    gating.ensure_active_repo(ws)
    wiki.ensure(ws)
    agents.bootstrap_profile(ws)
    fw = os.path.join(ws, "skills", "framework")
    for name in FRAMEWORK_SKILLS:
        src = os.path.join(repo_skills_dir(), name)
        dst = os.path.join(fw, name)
        if os.path.isdir(src) and not os.path.isdir(dst):
            shutil.copytree(src, dst)


def sample_traces(ws: str, it: int, train_results: list[dict],
                  max_total: int = 8, max_fail: int = 5, max_pass: int = 3) -> list[dict]:
    """Stratified trace sampling per Appendix C: ≤5 failing + ≤3 passing."""
    fails = [r for r in train_results if (r.get("score") or 0) < 1.0]
    passes = [r for r in train_results if (r.get("score") or 0) == 1.0]
    rng = random.Random(it)
    picked = (rng.sample(fails, min(max_fail, len(fails))) +
              rng.sample(passes, min(max_pass, len(passes))))
    out = []
    for r in picked:
        p = traces.transcript_path(ws, it, "train", r["id"])
        out.append({"task_id": r["id"], "score": r.get("score"),
                    "path": p if os.path.exists(p) else traces.meta_path(ws, it, "train", r["id"])})
    return out


def maintain_step(ws: str, k: int, sampled: list[dict], runner=agents.run_agent,
                  dry_run: bool = False) -> dict:
    prompt = prompts.maintainer_prompt(ws, k, sampled)
    return runner(ws, prompt, tag=f"maintain-{k:02d}",
                  toolsets=agents.MAINTAINER_TOOLSETS, include_framework=True,
                  dry_run=dry_run, max_turns=25, run_budget=600)


def propose_step(ws: str, k: int, train_results: list[dict], runner=agents.run_agent,
                 dry_run: bool = False) -> tuple[dict | None, dict]:
    prompt = prompts.proposer_prompt(ws, k, train_results)
    res = runner(ws, prompt, tag=f"propose-{k:02d}",
                 toolsets=agents.PROPOSER_TOOLSETS, include_framework=True,
                 dry_run=dry_run, max_turns=30, run_budget=900)
    ppath = os.path.join(ws, "runs", "proposals", f"iter-{k:02d}.json")
    if dry_run or not os.path.exists(ppath):
        return None, res
    with open(ppath, encoding="utf-8") as f:
        proposal = json.load(f)
    return proposal, res


def evolve(ws: str, iters: int = 3, model: str | None = None,
           runner=agents.run_agent, dry_run: bool = False, verbose: bool = True) -> dict:
    def log(msg: str) -> None:
        if verbose:
            print(f"[wikiskill] {msg}")

    splits = tasks_mod.splits(ws)
    train, val = splits["train"], splits["val"]
    state = gating.load_state(ws)
    wiki.ensure(ws)

    if state.get("baseline") is None:
        log(f"baseline validation: {len(val)} val tasks, S0=∅")
        gate0 = gating.run_gate(ws, val, 0, model=model, runner=runner, dry_run=dry_run)
        state["baseline"] = gate0["mean"]
        state["r_best"] = gate0["mean"]
        wiki.append_log(ws, f"iter-00 baseline: R={gate0['mean']} (S0=∅, {len(val)} val tasks)")
        gating.save_state(ws, state)

    for k in range(state["next_iter"], iters + 1):
        if state["r_best"] == 1.0:
            log("R_best == 1.0 → early stop")
            break
        log(f"iter {k}/{iters}: train rollouts ({len(train)} tasks)")
        train_results = [gating.run_task(ws, t, k, model=model, runner=runner,
                                         dry_run=dry_run, overwrite=True)
                         for t in train]
        train_mean = gating.mean_score(train_results)

        sampled = sample_traces(ws, k, train_results)
        log(f"iter {k}: wiki maintenance (sampled {len(sampled)} traces)")
        maintain_step(ws, k, sampled, runner=runner, dry_run=dry_run)

        log(f"iter {k}: skill proposal")
        proposal, _ = propose_step(ws, k, train_results, runner=runner, dry_run=dry_run)
        if proposal is None or proposal.get("action") == "no_action":
            wiki.append_skill_impact(
                ws, prompts.gate_outcome_entry(ws, k, {"action": "no_action"},
                                               None, False, "", None))
            wiki.append_log(ws, f"iter-{k:02d}: train={train_mean} proposal=no_action")
            state["next_iter"] = k + 1
            gating.save_state(ws, state)
            continue

        log(f"iter {k}: apply proposal ({proposal.get('action')} {proposal.get('name')})")
        gating.commit_base(ws, k)
        desc = gating.apply_proposal(ws, proposal)
        diff = gating.skill_diff(ws)

        log(f"iter {k}: validation gating ({len(val)} val tasks)")
        gatek = gating.run_gate(ws, val, k, model=model, runner=runner, dry_run=dry_run)
        r_val = gatek["mean"]
        prev_best = state["r_best"]
        accepted = r_val > prev_best
        if accepted:
            gating.accept_commit(ws, k, r_val)
            state["r_best"] = r_val
        else:
            gating.rollback(ws)
        state["history"].append({"iter": k, "train_mean": train_mean, "r_val": r_val,
                                 "accepted": accepted, "proposal": desc})
        state["next_iter"] = k + 1
        gating.save_state(ws, state)
        wiki.append_skill_impact(
            ws, prompts.gate_outcome_entry(ws, k, proposal, r_val, accepted, diff, prev_best))
        wiki.append_log(
            ws, f"iter-{k:02d}: train={train_mean} propose={desc} R_val={r_val} "
                f"{'ACCEPT' if accepted else 'reject'} (R_best={state['r_best']})")
        log(f"iter {k}: R_val={r_val} → {'ACCEPTED' if accepted else 'REJECTED (rolled back)'} "
            f"(R_best={state['r_best']})")

    return state
