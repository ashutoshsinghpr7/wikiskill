"""Gating + agents + harness tests with a fake agent runner (no real LLM calls)."""

import json
import os
import subprocess

import pytest

from wikiskill import agents, bench, gating, harness, prompts, tasks as tasks_mod, wiki


def build_ws(tmp_path, seed=7):
    ws = str(tmp_path / "ws")
    harness.init_workspace(ws)
    tasks = bench.generate(seed=seed)
    tasks_mod.save(ws, tasks)
    tasks_mod.materialize_all(ws, tasks)
    return ws


class FakeRunner:
    """Pretends to run Hermes turns. Writes deliverable files so grading is real.

    - inference runs (tag iter-NN/{split}/{id}): writes the grader's deliverable
      with expected content iff the task id is in the pass set for that phase,
      else wrong content; emits a fake session jsonl as the transcript.
    - maintain runs: writes a pattern page + index.
    - propose runs: writes the configured proposal JSON for that iter.
    """

    def __init__(self, train_pass=None, val_pass=None, proposals=None):
        self.train_pass = train_pass or set()
        self.val_pass = {0: set(), 1: set(), 2: set()}
        if val_pass:
            self.val_pass.update(val_pass)
        self.proposals = proposals or {}
        self.calls = []

    def __call__(self, ws, prompt, *, tag, toolsets=None, model=None, dry_run=False,
                 max_turns=15, run_budget=300, workdir=None, include_framework=False,
                 **kw):
        self.calls.append(tag)
        if dry_run:
            return {"cmd": ["hermes", "chat"], "dry_run": True}
        wd = workdir or ws
        parts = tag.split("/")
        if len(parts) == 3 and parts[1] in ("train", "val"):
            tid = parts[2]
            k = int(parts[0].split("-")[1])
            t = next(x for x in tasks_mod.load(ws) if x["id"] == tid)
            pass_set = self.train_pass if parts[1] == "train" else self.val_pass.get(k, self.val_pass[0])
            g = t["grader"]
            ok = tid in pass_set
            if g["type"] == "code_stdout":
                script = g.get("script", "solve.py")
                with open(os.path.join(wd, script), "w") as f:
                    f.write(f"print({g['expected']!r})" if ok else "print('WRONG')")
            else:
                p = os.path.join(wd, g["file"])
                os.makedirs(os.path.dirname(p) or wd, exist_ok=True)
                with open(p, "w") as f:
                    f.write(g["expected"] if ok else "WRONG CONTENT")
        elif tag.startswith("maintain-"):
            w = os.path.join(ws, "wiki")
            with open(os.path.join(w, "patterns", "test-pattern.md"), "w") as f:
                f.write("# test-pattern\n\nPROBLEM: outputs malformed\nROOT CAUSE: ignored spec\nFIX: read spec first\n")
            with open(os.path.join(w, "index.md"), "w") as f:
                f.write("# Pattern Index\n\n[test-pattern](wiki/patterns/test-pattern.md): read spec before writing output\n")
        elif tag.startswith("propose-"):
            k = int(tag.split("-")[1])
            os.makedirs(os.path.join(ws, "runs", "proposals"), exist_ok=True)
            with open(os.path.join(ws, "runs", "proposals", f"iter-{k:02d}.json"), "w") as f:
                json.dump(self.proposals.get(k, {"action": "no_action"}), f)
        # fake transcript
        sess_dir = os.path.join(ws, ".hermes-home", "sessions")
        os.makedirs(sess_dir, exist_ok=True)
        sess = os.path.join(sess_dir, tag.replace("/", "_") + ".jsonl")
        with open(sess, "w") as f:
            f.write('{"role":"user","content":"q"}\n{"role":"assistant","content":"fake"}\n')
        return {"exit_code": 0, "duration_s": 1.0, "stdout_path": "/dev/null",
                "session_file": sess}


def val_ids(ws):
    return [t["id"] for t in tasks_mod.splits(ws)["val"]]


def train_ids(ws):
    return [t["id"] for t in tasks_mod.splits(ws)["train"]]


# ---------------------------------------------------------------- gating

def test_gate_scoring_and_traces(tmp_path):
    ws = build_ws(tmp_path)
    val = tasks_mod.splits(ws)["val"]
    runner = FakeRunner(val_pass={0: {val[0]["id"]}})
    g = gating.run_gate(ws, val, 0, runner=runner)
    assert g["mean"] == round(1 / len(val), 4)
    assert len(gating.load_state(ws)["history"]) == 0
    assert len(__import__("wikiskill.traces", fromlist=["list_traces"]).list_traces(ws, it=0, split="val")) == len(val)


def test_apply_patch_and_rollback(tmp_path):
    ws = build_ws(tmp_path)
    # seed an existing skill
    gating.apply_proposal(ws, {
        "action": "create", "name": "spec-first",
        "skill_md": "---\nname: spec-first\n---\n# read the spec\n",
        "purpose_md": "origin",
    })
    gating.commit_base(ws, 0)
    gating.apply_proposal(ws, {
        "action": "patch", "name": "spec-first",
        "edits": [{"op": "append", "content": "\nALSO verify output."}],
    })
    p = os.path.join(gating.active_dir(ws), "spec-first", "SKILL.md")
    assert "ALSO verify output" in open(p).read()
    gating.rollback(ws)  # reject case
    assert "ALSO verify output" not in open(p).read()
    with pytest.raises(ValueError):  # replace target not found
        gating.apply_proposal(ws, {
            "action": "patch", "name": "spec-first",
            "edits": [{"op": "replace", "target": "NO SUCH TEXT", "content": "x"}],
        })


# ---------------------------------------------------------------- agents

def test_bootstrap_and_dry_run(tmp_path):
    real = tmp_path / "real"
    (real / "sessions").mkdir(parents=True)
    (real / "config.yaml").write_text("model: test\n")
    (real / ".env").write_text("KEY=x\n")
    ws = str(tmp_path / "ws")
    os.makedirs(ws)
    prof = agents.bootstrap_profile(ws, real=str(real))
    assert os.path.isfile(os.path.join(prof, "config.yaml"))
    assert os.path.isfile(os.path.join(prof, ".env"))

    os.makedirs(os.path.join(ws, "skills", "active"))
    os.makedirs(os.path.join(ws, "skills", "framework", "wikiskill-maintainer"))
    (tmp_path / "ws" / "skills" / "framework" / "wikiskill-maintainer" / "SKILL.md").write_text("x")
    agents.set_active_skills(ws, include_framework=False)
    assert os.listdir(os.path.join(prof, "skills")) == []
    agents.set_active_skills(ws, include_framework=True)
    assert "wikiskill-maintainer" in os.listdir(os.path.join(prof, "skills"))

    r = agents.run_agent(ws, "hello", tag="probe", dry_run=True)
    cmd = r["cmd"]
    assert "--query-file" in cmd and "-Q" in cmd and "--oneshot" in cmd
    assert "-t" in cmd and "--in" not in cmd  # no workdir given


# ---------------------------------------------------------------- harness

def _proposal_create(name="spec-first"):
    return {
        "action": "create", "name": name,
        "skill_md": f"---\nname: {name}\ndescription: read the spec first\n---\n# When to Apply\nWhen producing a formatted output file.\n# Instructions\nRead the spec file fully before writing any output.\n",
        "purpose_md": "Origin: iter-1 failures\nPatterns: malformed outputs\n",
    }


def test_evolve_accept_path(tmp_path):
    ws = build_ws(tmp_path)
    val = val_ids(ws)
    baseline_pass = set(val[:2])           # R0 = 2/6
    iter1_pass = set(val[:4])              # R1 = 4/6 > R0 → accept
    runner = FakeRunner(
        val_pass={0: baseline_pass, 1: iter1_pass},
        proposals={1: _proposal_create()},
    )
    state = harness.evolve(ws, iters=1, runner=runner, verbose=False)
    assert state["baseline"] == round(2 / len(val), 4)
    assert state["r_best"] == round(4 / len(val), 4)
    assert state["history"][0]["accepted"] is True
    # skill persisted
    assert os.path.isfile(os.path.join(gating.active_dir(ws), "spec-first", "SKILL.md"))
    # wiki retained + impact logged
    assert "ACCEPTED" in open(os.path.join(ws, "wiki", "skill-impact.md")).read()
    # order: train runs → maintain → propose → val gate
    idx = {c: i for i, c in enumerate(runner.calls)}
    first_train = min(idx[c] for c in runner.calls if c.startswith("iter-01/train/"))
    assert idx["maintain-01"] > first_train
    assert idx["propose-01"] > idx["maintain-01"]
    assert all(idx[f"iter-01/val/{v}"] > idx["propose-01"] for v in val)
    # git log has accept commit
    log = gating.git_active(ws, "log", "--oneline").stdout
    assert "accept iter-1" in log


def test_evolve_reject_rolls_back_skills_keeps_wiki(tmp_path):
    ws = build_ws(tmp_path)
    val = val_ids(ws)
    baseline_pass = set(val[:3])           # R0 = 3/6
    runner = FakeRunner(
        val_pass={0: baseline_pass, 1: baseline_pass},  # no improvement
        proposals={1: _proposal_create()},
    )
    state = harness.evolve(ws, iters=1, runner=runner, verbose=False)
    assert state["r_best"] == round(3 / len(val), 4)
    assert state["history"][0]["accepted"] is False
    # skills rolled back to S0 (empty — only .git remains)
    assert [d for d in os.listdir(gating.active_dir(ws)) if not d.startswith(".")] == []
    # wiki retained even though rejected
    impact = open(os.path.join(ws, "wiki", "skill-impact.md")).read()
    assert "REJECTED" in impact
    assert "spec-first" in impact  # full proposal kept for the next proposer


def test_evolve_no_action_skips_gate(tmp_path):
    ws = build_ws(tmp_path)
    runner = FakeRunner(
        val_pass={0: set(val_ids(ws)[:1])},
        proposals={1: {"action": "no_action"}},
    )
    state = harness.evolve(ws, iters=1, runner=runner, verbose=False)
    assert state["next_iter"] == 2
    assert not any(c.startswith("iter-01/val/") for c in runner.calls)
    assert "no_action" in open(os.path.join(ws, "wiki", "skill-impact.md")).read()


def test_evolve_early_stop_at_perfect(tmp_path):
    ws = build_ws(tmp_path)
    val = val_ids(ws)
    runner = FakeRunner(val_pass={0: set(val)})
    state = harness.evolve(ws, iters=5, runner=runner, verbose=False)
    assert state["r_best"] == 1.0
    assert len(state["history"]) == 0  # never got to iter 1
