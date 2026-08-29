"""Graders + task registry + trace store unit tests."""

import json
import os
import pytest

from wikiskill import bench, scoring, tasks as tasks_mod, traces


def make_task(**over):
    t = {
        "id": "t1", "split": "train", "title": "T",
        "prompt": "write output.txt",
        "sandbox": {"data.txt": "a\nb\n"},
        "grader": {"type": "exact", "file": "output.txt", "expected": "hello world"},
    }
    t.update(over)
    return t


# ---------------------------------------------------------------- scoring

def test_grade_exact_normalizes_whitespace(tmp_path):
    (tmp_path / "output.txt").write_text("hello\n  world\n")
    assert scoring.grade(make_task(), str(tmp_path)) == 1.0
    (tmp_path / "output.txt").write_text("hello wrld")
    assert scoring.grade(make_task(), str(tmp_path)) == 0.0


def test_grade_contains(tmp_path):
    (tmp_path / "output.txt").write_text("prefix secret suffix")
    assert scoring.grade(make_task(grader={"type": "contains", "file": "output.txt",
                                          "needle": "secret"}), str(tmp_path)) == 1.0


def test_grade_json_field(tmp_path):
    (tmp_path / "out.json").write_text('{"a": {"b": "42"}}')
    g = {"type": "json_field", "file": "out.json", "path": ["a", "b"], "expected": "42"}
    assert scoring.grade(make_task(grader=g), str(tmp_path)) == 1.0


def test_grade_code_stdout(tmp_path):
    (tmp_path / "solve.py").write_text("print(21 * 2)")
    g = {"type": "code_stdout", "script": "solve.py", "expected": "42"}
    assert scoring.grade(make_task(grader=g), str(tmp_path)) == 1.0


# ---------------------------------------------------------------- tasks

def test_registry_roundtrip_and_validation(tmp_path):
    ws = str(tmp_path)
    t = make_task()
    tasks_mod.save(ws, [t])
    loaded = tasks_mod.load(ws)
    assert loaded == [t]
    assert tasks_mod.splits(ws) == {"train": [t], "val": []}
    with pytest.raises(ValueError):
        tasks_mod.save(ws, [make_task(id="bad id!")])
    with pytest.raises(ValueError):
        tasks_mod.save(ws, [make_task(grader={"type": "nope"})])


def test_materialize(tmp_path):
    ws = str(tmp_path)
    t = make_task()
    d = tasks_mod.materialize(ws, t)
    assert os.path.isfile(os.path.join(d, "data.txt"))
    # idempotent, does not clobber agent-created files
    out = os.path.join(d, "output.txt")
    with open(out, "w") as f:
        f.write("agent wrote this")
    tasks_mod.materialize(ws, t)
    assert open(out).read() == "agent wrote this"


# ---------------------------------------------------------------- traces

def test_trace_store_immutable(tmp_path):
    ws = str(tmp_path)
    meta = {"task_id": "t1", "score": 1.0}
    traces.save_trace(ws, 1, "train", "t1", meta)
    with pytest.raises(FileExistsError):
        traces.save_trace(ws, 1, "train", "t1", meta)
    traces.save_trace(ws, 1, "train", "t1", meta, overwrite=True)  # explicit
    found = traces.list_traces(ws, it=1, split="train")
    assert len(found) == 1 and found[0]["meta"]["score"] == 1.0


# ---------------------------------------------------------------- bench

def test_bench_generates_valid_tasks():
    tasks = bench.generate(seed=42)
    tasks_mod.validate(tasks)
    assert len(tasks) == 22
    assert sum(1 for t in tasks if t["split"] == "train") == 13
    assert sum(1 for t in tasks if t["split"] == "val") == 9
    # deterministic
    assert bench.generate(seed=42) == tasks


def test_bench_graders_self_consistent(tmp_path):
    """Every bench task's grader must pass on the generated sandbox+expected."""
    ws = str(tmp_path)
    tasks = bench.generate(seed=42)
    tasks_mod.save(ws, tasks)
    tasks_mod.materialize_all(ws, tasks)
    for t in tasks:
        d = tasks_mod.sandbox_dir(ws, t["id"])
        g = t["grader"]
        if g["type"] == "exact":
            with open(os.path.join(d, g["file"]), "w") as f:
                f.write(g["expected"])
        elif g["type"] == "code_stdout":
            with open(os.path.join(d, g.get("script", "solve.py")), "w") as f:
                f.write(f"print({g['expected']!r})")
        assert scoring.grade(t, d) == 1.0, f"grader inconsistent for {t['id']}"
