"""Gating + agents + harness tests with a fake agent runner (no real LLM calls)."""

import json
import os

from wikiskill import agents, bench, gating, harness, tasks as tasks_mod


def build_ws(tmp_path, seed=7):
    ws = str(tmp_path / "ws")
    harness.init_workspace(ws)
    tasks = bench.generate(seed)
    tasks_mod.save(ws, tasks)
    tasks_mod.materialize_all(ws, tasks)
    return ws


def val_ids(ws):
    return [t["id"] for t in tasks_mod.load(ws) if t["split"] == "val"]


def train_ids(ws):
    return [t["id"] for t in tasks_mod.load(ws) if t["split"] == "train"]


class FakeRunner:
    """In-memory agent runner: writes deliverables (per configured pass sets)
    and proposal JSONs, records call order. No network, no hermes."""

    def __init__(self, val_pass=None, train_pass=None, proposals=None):
        self.val_pass = val_pass or {}
        self.train_pass = train_pass or {}
        self.proposals = proposals or {}
        self.calls = []

    def _pass_set(self, ws, tag):
        parts = tag.split("/")
        if len(parts) == 3 and parts[1] in ("train", "val"):
            it = int(parts[0].split("-")[1])
            return (self.val_pass if parts[1] == "val" else self.train_pass).get(it, set())
        return None

    def __call__(self, ws, prompt, *, tag, workdir=None, dry_run=False, **kw):
        self.calls.append(tag)
        if dry_run:
            return {"cmd": ["hermes", "chat"], "dry_run": True}
        wd = workdir or ws
        parts = tag.split("/")
        if len(parts) == 3 and parts[1] in ("train", "val"):
            tid = parts[2]
            task = next(t for t in tasks_mod.load(ws) if t["id"] == tid)
            g = task["grader"]
            ok = tid in self._pass_set(ws, tag)
            if g["type"] == "code_stdout":
                script = g.get("script", "solve.py")
                with open(os.path.join(wd, script), "w") as f:
                    f.write(f"print({g['expected']!r})" if ok else "print('WRONG')")
            else:
                p = os.path.join(wd, g["file"])
                os.makedirs(os.path.dirname(p) or wd, exist_ok=True)
                with open(p, "w") as f:
                    f.write(g["expected"] if ok else "WRONG CONTENT")
            sess = os.path.join(ws, ".hermes-home", "sessions", f"{tag.replace('/', '_')}.jsonl")
            os.makedirs(os.path.dirname(sess), exist_ok=True)
            with open(sess, "w") as f:
                f.write('{"id":"x","tool_call_count":3,"message_count":6}\n')
            return {"exit_code": 0, "duration_s": 1.0, "stdout_path": "/dev/null",
                    "session_file": sess}
        if tag.startswith("maintain-"):
            wiki_dir = os.path.join(ws, "wiki")
            with open(os.path.join(wiki_dir, "index.md"), "w") as f:
                f.write("# Pattern Index\n\n[test-pattern](wiki/patterns/test.md): x\n")
            os.makedirs(os.path.join(wiki_dir, "patterns"), exist_ok=True)
            with open(os.path.join(wiki_dir, "patterns", "test.md"), "w") as f:
                f.write("# test\n\nPROBLEM\nROOT CAUSE\nFIX\n")
            return {"exit_code": 0, "duration_s": 1.0, "stdout_path": "/dev/null",
                    "session_file": None}
        if tag.startswith("propose-"):
            k = int(tag.split("-")[1])
            os.makedirs(os.path.join(ws, "runs", "proposals"), exist_ok=True)
            with open(os.path.join(ws, "runs", "proposals", f"iter-{k:02d}.json"), "w") as f:
                json.dump(self.proposals.get(k, {"action": "no_action"}), f)
            return {"exit_code": 0, "duration_s": 1.0, "stdout_path": "/dev/null",
                    "session_file": None}
        return {"exit_code": 0, "duration_s": 1.0, "stdout_path": "/dev/null",
                "session_file": None}


def _proposal_create():
    return {
        "action": "create",
        "name": "spec_literal_transform",
        "skill_md": "---\nname: spec_literal_transform\ndescription: Follow the spec literally.\n---\n# Spec\n\nOne line per input record.\n",
        "purpose_md": "Origin: iter-01 failures.\nPatterns: spec-literal-execution.\n",
    }


def _proposal_patch():
    return {
        "action": "patch",
        "name": "spec_literal_transform",
        "edits": [{"op": "append", "content": "\n- Re-read the deliverable.\n"}],
    }


# ---------------------------------------------------------------- harness loop


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
    assert state["history"][0]["accepted"] is True
    assert state["r_best"] == round(4 / len(val), 4)
    active = os.path.join(ws, "skills", "active")
    assert "spec_literal_transform" in os.listdir(active)
    impact = open(os.path.join(ws, "wiki", "skill-impact.md")).read()
    assert "ACCEPTED" in impact
    # order per Algorithm 1: train → maintain → propose → gate
    joined = "|".join(runner.calls)
    assert joined.index("iter-01/train/") < joined.index("maintain-01")
    assert joined.index("maintain-01") < joined.index("propose-01")
    assert joined.index("propose-01") < joined.index("iter-01/val/")


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
    assert os.path.exists(os.path.join(ws, "wiki", "patterns", "test.md"))


def test_evolve_no_action_skips_gate(tmp_path):
    ws = build_ws(tmp_path)
    runner = FakeRunner(
        val_pass={0: set(val_ids(ws)[:1])},
        proposals={1: {"action": "no_action"}},
    )
    state = harness.evolve(ws, iters=1, runner=runner, verbose=False)
    assert state["next_iter"] == 2
    assert not any("iter-01/val/" in c for c in runner.calls)  # gate skipped


def test_evolve_early_stop_at_perfect(tmp_path):
    ws = build_ws(tmp_path)
    val = val_ids(ws)
    runner = FakeRunner(val_pass={0: set(val)})
    state = harness.evolve(ws, iters=5, runner=runner, verbose=False)
    assert state["r_best"] == 1.0
    assert len(state["history"]) == 0  # never got to iter 1


def test_evolve_no_early_stop_flag(tmp_path):
    ws = build_ws(tmp_path)
    val = val_ids(ws)
    runner = FakeRunner(
        val_pass={0: set(val), 1: set(val)},
        proposals={1: _proposal_create()},
    )
    state = harness.evolve(ws, iters=1, runner=runner, verbose=False,
                           no_early_stop=True)
    assert len(state["history"]) == 1  # ran despite R_best == 1.0


# ---------------------------------------------------------------- agents / gating


def test_bootstrap_and_dry_run(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    (real / "config.yaml").write_text("model:\n  default: x\n")
    (real / ".env").write_text("KEY=abc\n")
    ws = str(tmp_path / "ws")
    agents.bootstrap_profile(ws, real=str(real))
    prof = os.path.join(ws, ".hermes-home")
    assert os.path.exists(os.path.join(prof, "config.yaml"))
    assert os.path.exists(os.path.join(prof, ".env"))
    assert "sessions" in os.listdir(prof)

    os.makedirs(os.path.join(ws, "skills", "active"))
    res = agents.run_agent(ws, "hi", tag="t1", dry_run=True, workdir="/tmp")
    assert res["cmd"][0] == "hermes"
    assert "--query-file" in res["cmd"]
    assert "-Q" in res["cmd"]
    assert "--in" in res["cmd"]


def test_patch_profile_model_rewrites_config(tmp_path):
    """Profile model patching: default model + provider replaced, broken moa
    fallback stripped (it carries the literal 'model: default' placeholder)."""
    prof = tmp_path / ".hermes-home"
    (prof / "sessions").mkdir(parents=True)
    cfg = prof / "config.yaml"
    cfg.write_text(
        "model:\n"
        "  default: deepseek-v4-flash\n"
        "  provider: deepseek\n"
        "  base_url: https://api.deepseek.com/v1\n"
        "fallback_providers:\n"
        "  - provider: moa\n"
        "    model: default\n"
        "agent:\n"
        "  max_turns: 500\n"
    )
    agents.patch_profile_model(str(tmp_path), "google/gemini-2.5-flash-lite", "openrouter")
    text = cfg.read_text()
    assert "default: google/gemini-2.5-flash-lite" in text
    assert "provider: openrouter" in text
    assert "fallback_providers" not in text
    assert "max_turns: 500" in text  # unrelated config preserved


def test_fresh_sandbox_prevents_stale_scores(tmp_path):
    """A dead agent run must score 0.0, never a stale deliverable from a
    previous experiment (the regression that phantom-graded the gemma run)."""
    ws = build_ws(tmp_path, seed=7)
    task = [t for t in tasks_mod.load(ws) if t["id"] == "csv-north-count"][0]
    sandbox = tasks_mod.sandbox_dir(ws, task["id"])
    # Simulate a prior experiment leaving a correct-looking deliverable.
    with open(os.path.join(sandbox, "answer.txt"), "w") as f:
        f.write(task["grader"]["expected"])
    assert scoring_grade(task, sandbox) == 1.0  # stale file would pass

    def dead_runner(*a, **k):
        return {"exit_code": 0, "session_file": None, "stdout_path": None}

    res = gating.run_task(ws, task, 1, runner=dead_runner)
    assert res["score"] == 0.0  # fresh sandbox → no deliverable → honest 0


def scoring_grade(task, sandbox):
    from wikiskill import scoring
    return scoring.grade(task, sandbox)


def test_zero_tool_call_session_detected(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"id":"x","tool_call_count":0,"message_count":1}\n')
    assert gating._session_had_no_tool_calls(str(p)) is True
    p.write_text('{"id":"x","tool_call_count":9,"message_count":18}\n')
    assert gating._session_had_no_tool_calls(str(p)) is False
    p.write_text('{"role":"user","content":"x"}\n')  # legacy/fake format
    assert gating._session_had_no_tool_calls(str(p)) is False


def test_evolve_accepts_provider_kwarg():
    import inspect
    sig = inspect.signature(harness.evolve)
    assert "provider" in sig.parameters
    assert sig.parameters["provider"].default is None
