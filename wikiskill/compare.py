"""Paired run comparison: did the skill (or model) actually help?

Runs both workspaces' val sets N times with the same tasks and reports a
per-task win/loss/tie table plus a paired significance test (two-sided exact
binomial on discordant pairs — the paired-sample analogue of McNemar's test,
computable without any external statistics dependency).

Verdict semantics:
  - per-task pass = grade == 1.0 (graders are deterministic per run)
  - discordant pair = A passed the run while B failed it (or vice versa)
  - p-value = P(|B - C| >= |b - c|) under B ~ Binomial(b + c, 0.5)
  - "A better" requires pA > pB AND p <= 0.05 (two-sided); else tie.
"""

from __future__ import annotations

import math

from . import gating, tasks as tasks_mod


def _pass(score: float) -> bool:
    return score >= 0.5  # all bundled graders return 0.0 or 1.0


def _two_sided_binomial_p(b: int, c: int) -> float:
    """Two-sided exact p-value for the McNemar-style discordant-pair test."""
    n = b + c
    if n == 0:
        return 1.0
    obs = abs(b - c)
    # sum P(X=k) over all k with |2k - n| >= obs
    p = 0.0
    for k in range(n + 1):
        if abs(2 * k - n) >= obs:
            p += math.comb(n, k) * (0.5 ** n)
    return min(p, 1.0)


def run_comparison(ws_a: str, ws_b: str, iters: int = 3, *,
                   runner=gating.run_task, dry_run: bool = False,
                   max_turns: int | None = None) -> dict:
    """Run the val sets of both workspaces `iters` times each; return stats."""
    ta = tasks_mod.load(ws_a)
    tb = tasks_mod.load(ws_b)
    ids_a = [t["id"] for t in ta if t["split"] == "val"]
    ids_b = [t["id"] for t in tb if t["split"] == "val"]
    if set(ids_a) != set(ids_b):
        raise ValueError(
            f"workspaces have different val task sets "
            f"(A has {len(ids_a)}, B has {len(ids_b)}); compare needs identical tasks")
    ids = sorted(ids_a)

    # Per (task, run) outcome for each workspace.
    scores = {"A": {}, "B": {}}
    for tag, ws in (("A", ws_a), ("B", ws_b)):
        for tid in ids:
            task = next(t for t in (ta if tag == "A" else tb) if t["id"] == tid)
            per_run = []
            for k in range(iters):
                res = runner(ws, task, k, dry_run=dry_run,
                             overwrite=True, max_turns=max_turns)
                per_run.append(1.0 if _pass(res["score"]) else 0.0)
            scores[tag][tid] = per_run

    rows = []
    b_discord_a, b_discord_b = 0, 0  # A-pass/B-fail, B-pass/A-fail
    for tid in ids:
        a_ok = sum(scores["A"][tid])
        b_ok = sum(scores["B"][tid])
        for x, y in zip(scores["A"][tid], scores["B"][tid]):
            if x == 1 and y == 0:
                b_discord_a += 1
            elif x == 0 and y == 1:
                b_discord_b += 1
        rows.append({
            "task": tid,
            "A": round(a_ok / iters, 3),
            "B": round(b_ok / iters, 3),
            "outcome": ("A" if a_ok > b_ok else ("B" if b_ok > a_ok else "tie")),
        })

    p_a = (sum(r["A"] for r in rows) / len(rows)) if rows else 0.0
    p_b = (sum(r["B"] for r in rows) / len(rows)) if rows else 0.0
    p_value = _two_sided_binomial_p(b_discord_a, b_discord_b)
    if p_a > p_b and p_value <= 0.05:
        verdict = "A better"
    elif p_b > p_a and p_value <= 0.05:
        verdict = "B better"
    else:
        verdict = "no significant difference"
    return {
        "iters": iters,
        "tasks": rows,
        "pass_rate": {"A": round(p_a, 4), "B": round(p_b, 4)},
        "discordant_pairs": {"A_pass_B_fail": b_discord_a, "B_pass_A_fail": b_discord_b},
        "p_value": round(p_value, 4),
        "verdict": verdict,
    }


def format_report(r: dict) -> str:
    lines = [
        f"compare: {r['iters']} run(s) per workspace, val-only",
        "",
        f"{'task':<22s} {'A':>6s} {'B':>6s}  winner",
        "-" * 42,
    ]
    for row in r["tasks"]:
        lines.append(f"{row['task']:<22s} {row['A']:>6.3f} {row['B']:>6.3f}  {row['outcome']}")
    lines += [
        "-" * 42,
        f"pass rate: A={r['pass_rate']['A']:.3f}  B={r['pass_rate']['B']:.3f}",
        f"discordant pairs: A-pass/B-fail={r['discordant_pairs']['A_pass_B_fail']}  "
        f"B-pass/A-fail={r['discordant_pairs']['B_pass_A_fail']}",
        f"paired exact binomial p={r['p_value']:.4f} (two-sided, discordant pairs only)",
        f"verdict: {r['verdict']}",
    ]
    return "\n".join(lines)


def permutation_verdict(r: dict) -> str:
    """Machine-readable verdict (for tests/automation)."""
    return r["verdict"]
