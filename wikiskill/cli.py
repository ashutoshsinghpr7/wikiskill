"""wikiskill CLI — drive a WikiSkill evolution workspace."""

from __future__ import annotations

import argparse
import os
import sys

from . import agents, backends, bench, compare, gating, harness, tasks as tasks_mod, traces, transfer


def default_ws_root() -> str:
    """Domains live in `./workspaces/` next to wherever the CLI is run.

    Before 0.1.5 this was resolved relative to the *package directory*, so an
    installed wheel created workspaces inside `site-packages` and
    `wikiskill init demo` silently ignored the directory you ran it from
    (issue #29). Computed per call, not at import time, so it follows the cwd.
    """
    return os.path.join(os.getcwd(), "workspaces")


def legacy_ws_root() -> str:
    """The pre-0.1.5 default: `<parent of the package>/workspaces`.

    Read-only fallback in `resolve_ws` so a source checkout keeps finding
    workspaces it already has when the CLI is run from a subdirectory; we never
    create anything here.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "workspaces")


def resolve_ws(domain: str, ws: str | None) -> str:
    if ws:
        return os.path.abspath(ws)
    cwd_ws = os.path.join(default_ws_root(), domain)
    if not os.path.isdir(cwd_ws):
        legacy = os.path.join(legacy_ws_root(), domain)
        if os.path.isdir(legacy):
            print(f"[wikiskill] using the existing workspace at {legacy} "
                  f"(move it under ./workspaces/ or pass --ws to silence this)",
                  file=sys.stderr)
            return legacy
    return cwd_ws


def cmd_init(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    # Refuse only a workspace that is actually finished: a directory left behind
    # by an init that failed (e.g. a broken install, issue #29) is incomplete —
    # no tasks.json — and must be re-initializable rather than reported as
    # "already exists".
    if os.path.exists(tasks_mod.tasks_path(ws)):
        print(f"workspace already exists: {ws}")
        return 1
    if args.backend:
        backends.write_backend(ws, args.backend)
    harness.init_workspace(ws)
    tasks = bench.generate(args.seed)
    tasks_mod.save(ws, tasks)
    tasks_mod.materialize_all(ws, tasks)
    print(f"workspace initialized: {ws}")
    print(f"  tasks: {len(tasks)} ({sum(1 for t in tasks if t['split']=='train')} train, "
          f"{sum(1 for t in tasks if t['split']=='val')} val)")
    print("  next: `wikiskill status` or `wikiskill evolve --iters 3`")
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
          f"| wiki patterns: {len(patterns)} | backend: {agents.resolve(ws).name}")
    for h in state.get("history", []):
        print(f"  iter-{h['iter']:02d}: {h.get('proposal')} R_val={h.get('r_val')} "
              f"{'ACCEPT' if h.get('accepted') else 'reject'}")
    return 0


def cmd_evolve(args) -> int:
    ws = resolve_ws(args.domain, args.ws)
    if not os.path.exists(tasks_mod.tasks_path(ws)):
        print(f"no workspace at {ws} (run `wikiskill init <domain>`)")
        return 1
    if args.backend:
        backends.write_backend(ws, args.backend)
        print(f"[wikiskill] backend → {args.backend}")
        if not args.dry_run:
            # the switched-to backend needs its isolated profile (credentials,
            # config, skills dir) before any rollout — init created it for
            # fresh workspaces, but switching an existing one never did.
            agents.bootstrap_profile(ws)
    state = harness.evolve(ws, iters=args.iters, model=args.model,
                           provider=args.provider, dry_run=args.dry_run,
                           verbose=True, max_turns=args.max_turns,
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


def cmd_compare(args) -> int:
    root = default_ws_root()
    ws_a = args.ws_a if os.path.isdir(args.ws_a) else os.path.join(root, args.ws_a)
    ws_b = args.ws_b if os.path.isdir(args.ws_b) else os.path.join(root, args.ws_b)
    for p, name in ((ws_a, "ws_a"), (ws_b, "ws_b")):
        if not os.path.isdir(p):
            print(f"workspace not found: {name} -> {p}")
            return 1
    rep = compare.run_comparison(
        ws_a, ws_b, iters=args.iters, dry_run=args.dry_run,
        max_turns=args.max_turns)
    print(compare.format_report(rep))
    return 0


def cmd_transfer(args) -> int:
    root = default_ws_root()
    src = args.src if os.path.isdir(args.src) else os.path.join(root, args.src)
    dst = args.dst if os.path.isdir(args.dst) else os.path.join(root, args.dst)
    for p, name in ((src, "src"), (dst, "dst")):
        if not os.path.isdir(p):
            print(f"workspace not found: {name} -> {p}")
            return 1
    m = transfer.transfer_skills(src, dst, force=args.force)
    print(transfer.format_report(m))
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
        sp.add_argument("--ws", help="explicit workspace path (default: ./workspaces/<domain>)")

    sp = sub.add_parser("init", help="create a workspace with the demo bench")
    add_ws(sp); sp.add_argument("--seed", type=int, default=42)
    sp.add_argument("--backend", choices=sorted(backends.BACKENDS), default=None,
                    help="agent backend for this workspace (default: hermes)")
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
    sp.add_argument("--model", help="patch the isolated profile's default model "
                                    "(e.g. google/gemini-2.5-flash-lite)")
    sp.add_argument("--provider", help="provider for --model (e.g. openrouter)")
    sp.add_argument("--backend", choices=sorted(backends.BACKENDS), default=None,
                    help="switch this workspace's agent backend before evolving")
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

    sp = sub.add_parser("compare", help="paired statistical comparison of two workspaces")
    sp.add_argument("ws_a")
    sp.add_argument("ws_b")
    sp.add_argument("--iters", type=int, default=3,
                    help="runs per workspace (more = tighter test)")
    sp.add_argument("--max-turns", type=int, default=None)
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(fn=cmd_compare)

    sp = sub.add_parser("transfer", help="copy one workspace's active skills into another")
    sp.add_argument("src")
    sp.add_argument("dst")
    sp.add_argument("--force", action="store_true", help="overwrite same-named skills")
    sp.set_defaults(fn=cmd_transfer)

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
    try:
        return args.fn(args)
    except FileNotFoundError as e:
        # e.g. an install that ships no framework skills (issue #29) — one
        # actionable line, not a 20-line traceback
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
