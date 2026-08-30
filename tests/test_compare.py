"""Paired comparison tests (issue #3): honest 'did the skill help?' statistics."""

import os

import pytest

from wikiskill import bench, compare, tasks as tasks_mod


def build_ws(root: str) -> str:
    os.makedirs(root, exist_ok=True)
    tasks = bench.generate(42)
    tasks_mod.save(root, tasks)
    # minimal workspace: active-skills dir + git (run_task doesn't need more
    # when handed a fake runner)
    os.makedirs(os.path.join(root, "skills", "active"), exist_ok=True)
    return root


def val_ids(ws: str) -> list[str]:
    return sorted(t["id"] for t in tasks_mod.load(ws) if t["split"] == "val")


def _fake_runner(b_fail: set[str]):
    """Returns a run_task-compatible fake: A passes everything, B fails
    the tasks in `b_fail` (per workspace, detected by path basename)."""
    def runner(ws, task, k, **kw):
        is_b = os.path.basename(ws.rstrip("/")).startswith("b")
        score = 0.0 if (is_b and task["id"] in b_fail) else 1.0
        return {"score": score}
    return runner


def test_binomial_p_known_values():
    assert compare._two_sided_binomial_p(0, 0) == 1.0
    assert compare._two_sided_binomial_p(10, 0) == pytest.approx(2 / 2 ** 10)
    assert compare._two_sided_binomial_p(5, 5) == 1.0
    p = compare._two_sided_binomial_p(4, 0)
    assert p == pytest.approx(2 / 2 ** 4)  # 0.125


def test_compare_detects_significant_win(tmp_path):
    ws_a = build_ws(str(tmp_path / "a-ws"))
    ws_b = build_ws(str(tmp_path / "b-ws"))
    fail_two = sorted(val_ids(ws_b))[:2]
    rep = compare.run_comparison(ws_a, ws_b, iters=4,
                                 runner=_fake_runner(set(fail_two)))
    assert rep["verdict"] == "A better"
    assert rep["pass_rate"]["A"] == 1.0
    assert rep["p_value"] <= 0.05
    # every task the fake failed shows in the table as an A win
    a_wins = [r for r in rep["tasks"] if r["outcome"] == "A"]
    assert {r["task"] for r in a_wins} == set(fail_two)


def test_compare_tie_when_no_difference(tmp_path):
    ws_a = build_ws(str(tmp_path / "a-ws"))
    ws_b = build_ws(str(tmp_path / "b-ws"))
    rep = compare.run_comparison(ws_a, ws_b, iters=3,
                                 runner=_fake_runner(set()))
    assert rep["verdict"] == "no significant difference"
    assert rep["pass_rate"]["A"] == rep["pass_rate"]["B"] == 1.0


def test_compare_rejects_mismatched_task_sets(tmp_path):
    ws_a = build_ws(str(tmp_path / "a-ws"))
    ws_b = build_ws(str(tmp_path / "b-ws"))
    # move one VAL task out of val so the task sets differ
    tasks_b = tasks_mod.load(ws_b)
    for t in tasks_b:
        if t["split"] == "val":
            t["split"] = "train"
            break
    tasks_mod.save(ws_b, tasks_b)
    with pytest.raises(ValueError, match="different val task sets"):
        compare.run_comparison(ws_a, ws_b, iters=1, runner=_fake_runner(set()))


def test_report_contains_verdict_and_table():
    rep = {
        "iters": 2,
        "tasks": [{"task": "t1", "A": 1.0, "B": 0.0, "outcome": "A"}],
        "pass_rate": {"A": 1.0, "B": 0.0},
        "discordant_pairs": {"A_pass_B_fail": 2, "B_pass_A_fail": 0},
        "p_value": 0.25,
        "verdict": "A better",
    }
    out = compare.format_report(rep)
    assert "t1" in out and "A better" in out and "p=0.25" in out
