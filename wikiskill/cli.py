"""wikiskill CLI — drive a WikiSkill evolution workspace."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import agents, bench, gating, harness, prompts, tasks as tasks_mod, traces, wiki

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WS_ROOT = os.path.join(REPO_ROOT, "workspaces")


def resolve_ws(domain: str, ws: str | None) -> str:
    if ws:
        return os.path.abspath(ws)
    return os.path.join(DEFAULT_WS_ROOT, domain)


def cmd_init(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    if os.path.exists(ws) and os.listdir(ws):
        print(f"workspace already exists: {ws}")
        return 1
    harness.init_workspace(ws)
    tasks = bench.generate(args.seed)
    tasks_mod.save(ws, tasks)
    tasks_mod.materialize_all(ws, tasks)
    print(f"workspace initialized: {ws}")
    print(f"  tasks: {len(tasks)} ({sum(1 for t in tasks if t['split']=='train')} train, "
          f"{sum(1 for t in tasks if t['split']=='val')} val)")
    print(f"  next: `wikiskill status` or `wikiskill evolve --iters 3`")
    return 0


def cmd_bench(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    harness.init_workspace(ws)
    tasks = bench.generate(args.seed)
    tasks_mod.save(ws, tasks)
    tasks_mod.materialize_all(ws, tasks, force=args.reset)
    print(f"bench regenerated ({len(tasks)} tasks, seed={args.seed})")
    return 0


def cmd_status(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    if not os.path.exists(tasks_mod.tasks_path(ws)):
        print(f"no workspace at {ws} (run `wikiskill init <domain>`)")
        return 1
    splits = tasks_mod.splits(ws)
    state = gating.load_state(ws)
    tr = traces.list_traces(ws)
    active = os.listdir(gating.active_dir(ws))
    patterns = os.listdir(os.path.join(ws, "wiki", "patterns"))
    print(f"workspace: {ws}")
    print(f"tasks: {len(splits['train'])} train / {len(splits['val'])} val")
    print(f"state: baseline={state.get('baseline')} r_best={state.get('r_best')} "
          f"next_iter={state.get('next_iter')} iters_done={len(state.get('history', []))}")
    print(f"traces: {len(tr)} | active skills: {sorted(active) or ['∅ (S0)']} "
          f"| wiki patterns: {len(patterns)}")
    for h in state.get("history", []):
        print(f"  iter-{h['iter']:02d}: {h.get('proposal')} R_val={h.get('r_val')} "
              f"{'ACCEPT' if h.get('accepted') else 'reject'}")
    return 0


def cmd_evolve(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    if not os.path.exists(tasks_mod.tasks_path(ws)):
        print(f"no workspace at {ws} (run `wikiskill init <domain>`)")
        return 1
    state = harness.evolve(ws, iters=args.iters, model=args.model,
                           dry_run=args.dry_run, verbose=True,
                           max_turns=args.max_turns,
                           no_early_stop=args.no_early_stop)
    print(f"done: baseline={state.get('baseline')} r_best={state.get('r_best')}")
    return 0


def cmd_gate(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    splits = tasks_mod.splits(ws)
    tasks = splits[args.split]
    print(f"gating {len(tasks)} {args.split} tasks (iter {args.iter}) with active skills…")
    g = gating.run_gate(ws, tasks, args.iter, model=args.model, dry_run=args.dry_run)
    if not args.dry_run:
        for r in g["results"]:
            print(f"  {r['id']}: {r['score']}")
        print(f"mean R: {g['mean']}")
    return 0


def cmd_run_task(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    tasks = tasks_mod.load(ws)
    t = next((t for t in tasks if t["id"] == args.task_id), None)
    if not t:
        print(f"unknown task: {args.task_id}")
        return 1
    r = gating.run_task(ws, t, args.iter, model=args.model, dry_run=args.dry_run,
                        runner=lambda *a, **k: agents.run_agent(
                            *a, **k, max_turns=args.max_turns,
                            run_budget=args.run_budget))
    print(f"task {t['id']}: score={r.get('score')}")
    if r.get("result", {}).get("cmd") and args.dry_run:
        print("cmd: " + " ".join(r["result"]["cmd"]))
    return 0


def cmd_maintain(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    tr = [t for t in traces.list_traces(ws, it=args.iter, split="train")]
    print(f"maintainer input: {len(tr)} train traces from iter {args.iter}")
    res = harness.maintain_step(ws, args.iter, tr, dry_run=args.dry_run)
    if args.dry_run:
        print("cmd: " + " ".join(res["cmd"]))
    return 0


def cmd_propose(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    results = [traces.load_trace(ws, args.iter, "train", t["task_id"])
               for t in traces.list_traces(ws, it=args.iter, split="train")]
    tr = [{"id": t["task_id"], "split": "train", "title": t.get("title", ""),
           "score": t.get("score")} for t in traces.list_traces(ws, it=args.iter, split="train")]
    proposal, res = harness.propose_step(ws, args.iter, tr, dry_run=args.dry_run)
    if args.dry_run:
        print("cmd: " + " ".join(res["cmd"]))
    elif proposal:
        print(f"proposal: {proposal.get('action')} {proposal.get('name', '')}")
    else:
        print("no proposal file found")
    return 0


def cmd_reset(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    import shutil
    for d in ("raw", "runs"):
        shutil.rmtree(os.path.join(ws, d), ignore_errors=True)
    gating.git_active(ws, "reset", "--hard", "-q")
    gating.git_active(ws, "clean", "-fd", "-q")
    print(f"reset {ws}: raw/, runs/ cleared; skills rolled back to last commit")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wikiskill", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_ws(sp):
        sp.add_argument("domain")
        sp.add_argument("--ws", help="explicit workspace path (default: <repo>/workspaces/<domain>)")

    sp = sub.add_parser("init", help="create a workspace with the demo bench")
    add_ws(sp); sp.add_argument("--seed", type=int, default=42)
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("bench", help="(re)generate the demo bench")
    add_ws(sp); sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("--reset", action="store_true", help="re-materialize sandbox files")
    sp.set_defaults(fn=cmd_bench)

    sp = sub.add_parser("status", help="workspace summary")
    add_ws(sp); sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("evolve", help="run the full evolution loop (Algorithm 1)")
    add_ws(sp)
    sp.add_argument("--iters", type=int, default=3)
    sp.add_argument("--model")
    sp.add_argument("--max-turns", type=int, default=15,
                    help="per-task inference turn budget (tighter = harder)")
    sp.add_argument("--no-early-stop", action="store_true",
                    help="run iterations even when R_best=1.0 (dev/demo knob; "
                         "Algorithm 1 would halt)")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(fn=cmd_evolve)

    sp = sub.add_parser("gate", help="validation gate on a split with active skills")
    add_ws(sp)
    sp.add_argument("--iter", type=int, default=0)
    sp.add_argument("--split", choices=["train", "val"], default="val")
    sp.add_argument("--model")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(fn=cmd_gate)

    sp = sub.add_parser("run-task", help="single inference rollout")
    add_ws(sp); sp.add_argument("task_id")
    sp.add_argument("--iter", type=int, default=1)
    sp.add_argument("--model")
    sp.add_argument("--max-turns", type=int, default=15)
    sp.add_argument("--run-budget", type=int, default=300)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(fn=cmd_run_task)

    sp = sub.add_parser("maintain", help="run the wiki maintainer for an iter")
    add_ws(sp); sp.add_argument("--iter", type=int, default=1)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(fn=cmd_maintain)

    sp = sub.add_parser("propose", help="run the skill proposer for an iter")
    add_ws(sp); sp.add_argument("--iter", type=int, default=1)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(fn=cmd_propose)

    sp = sub.add_parser("reset", help="clear raw/runs and roll skills back")
    add_ws(sp); sp.set_defaults(fn=cmd_reset)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
