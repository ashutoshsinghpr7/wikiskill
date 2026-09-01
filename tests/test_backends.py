"""Backend protocol tests (issue #13): registry, per-backend command
construction, transcript normalization, and the agents.py facade dispatch."""

import json
import os
import subprocess

from wikiskill import agents, backends
from wikiskill.backends.claude import ClaudeBackend
from wikiskill.backends.hermes import HermesBackend
from wikiskill.backends import transcript


def _mkws(tmp_path, name="ws") -> str:
    ws = str(tmp_path / name)
    os.makedirs(ws, exist_ok=True)
    return ws


# ---------------------------------------------------------------- registry

def test_default_backend_is_hermes_for_legacy_workspaces(tmp_path):
    ws = _mkws(tmp_path)
    assert backends.read_backend(ws) == "hermes"
    assert backends.resolve(ws).name == "hermes"
    assert not os.path.exists(backends.workspace_file(ws))  # nothing written


def test_write_and_resolve_backend(tmp_path):
    ws = _mkws(tmp_path)
    backends.write_backend(ws, "claude")
    assert backends.read_backend(ws) == "claude"
    assert backends.resolve(ws).name == "claude"
    assert backends.workspace_file(ws).endswith("workspace.json")
    try:
        backends.write_backend(ws, "nope")
        assert False, "unknown backend must raise"
    except ValueError:
        pass


def test_write_backend_creates_missing_workspace_dir(tmp_path):
    """Regression: `wikiskill init --backend claude` writes workspace.json
    before init_workspace creates the dir — must not crash."""
    fresh = str(tmp_path / "not" / "created" / "yet")
    backends.write_backend(fresh, "claude")
    assert os.path.exists(backends.workspace_file(fresh))


def test_resolve_unknown_backend_raises_valueerror_not_keyerror(tmp_path):
    """Regression: a hand-edited workspace.json with a bogus backend must
    fail loudly (ValueError), not with an uncaught KeyError."""
    ws = _mkws(tmp_path)
    with open(backends.workspace_file(ws), "w", encoding="utf-8") as f:
        json.dump({"backend": "evil"}, f)
    try:
        backends.resolve(ws)
        assert False, "must raise"
    except ValueError as e:
        assert "evil" in str(e)


def test_read_backend_tolerates_non_dict_json(tmp_path):
    """Regression (adversarial review): valid JSON of the wrong type in
    workspace.json (null/[]/true/42/\"x\") must fall back to hermes, not crash
    with AttributeError on `.get`."""
    ws = _mkws(tmp_path)
    for payload in ("null", "[]", "true", "42", '"claude"'):
        with open(backends.workspace_file(ws), "w", encoding="utf-8") as f:
            f.write(payload)
        assert backends.read_backend(ws) == "hermes", payload
        assert backends.resolve(ws).name == "hermes", payload


# ---------------------------------------------------------------- hermes

def test_hermes_backend_dry_run_command(tmp_path):
    res = HermesBackend().run(_mkws(tmp_path), "hi", tag="t1", dry_run=True,
                              model="x/y", workdir="/sandbox", max_turns=8)
    assert res.dry_run and res.cmd[0] == "hermes"
    for flag in ("--query-file", "-Q", "--oneshot", "-t", "--max-turns",
                 "--run-budget", "-m", "--in"):
        assert flag in res.cmd
    assert res.cmd[res.cmd.index("--max-turns") + 1] == "8"
    assert res.cmd[res.cmd.index("-m") + 1] == "x/y"
    assert res.cmd[res.cmd.index("--in") + 1] == "/sandbox"


# ---------------------------------------------------------------- claude

def test_claude_backend_dry_run_command(tmp_path):
    res = ClaudeBackend().run(_mkws(tmp_path), "hi", tag="t1", dry_run=True,
                              model="sonnet", workdir="/sandbox", max_turns=8)
    assert res.dry_run and res.cmd[0] == "claude"
    for flag in ("-p", "--output-format", "stream-json", "--verbose",
                 "--max-turns", "--permission-mode", "acceptEdits",
                 "--allowedTools", "--model", "--max-budget-usd"):
        assert flag in res.cmd, flag
    assert res.cmd[res.cmd.index("--max-turns") + 1] == "8"
    assert res.cmd[res.cmd.index("--model") + 1] == "sonnet"
    # terminal,file,code_execution -> Bash,Read,Write,Edit (deduped)
    tools = res.cmd[res.cmd.index("--allowedTools") + 1]
    assert tools == "Bash,Read,Write,Edit"
    # run_budget 300 (hermes cents-ish) -> $3.00 max-budget-usd
    assert res.cmd[res.cmd.index("--max-budget-usd") + 1] == "3.00"


def test_claude_patch_model_flows_into_run(tmp_path):
    """Regression: `evolve --backend claude --model X` must reach the CLI —
    the stored model is applied when the runner gets no explicit model."""
    ws = _mkws(tmp_path)
    ClaudeBackend().patch_model(ws, "claude-3-5-sonnet", "anthropic")
    res = ClaudeBackend().run(ws, "hi", tag="t1", dry_run=True)
    assert res.cmd[res.cmd.index("--model") + 1] == "claude-3-5-sonnet"
    # explicit --model at run time wins over the stored one
    res2 = ClaudeBackend().run(ws, "hi", tag="t2", dry_run=True, model="other")
    assert res2.cmd[res2.cmd.index("--model") + 1] == "other"
    # nothing stored -> no --model flag at all
    ws2 = _mkws(tmp_path, "ws2")
    res3 = ClaudeBackend().run(ws2, "hi", tag="t3", dry_run=True)
    assert "--model" not in res3.cmd


def test_claude_run_uses_isolated_config_and_pins_cwd(tmp_path, monkeypatch):
    ws = _mkws(tmp_path)
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        calls["env"] = kw.get("env")
        calls["cwd"] = kw.get("cwd")
        calls["input"] = kw.get("input")
        # emulate a tiny stream-json transcript: one user, one assistant w/ tool_use
        out = "\n".join([
            json.dumps({"type": "user", "message": {"role": "user"}}),
            json.dumps({"type": "assistant", "message": {
                "content": [{"type": "tool_use", "name": "Bash", "id": "t1"},
                            {"type": "text", "text": "done"}]}}),
            json.dumps({"type": "result", "subtype": "success",
                        "session_id": "abc123", "num_turns": 2}),
        ])
        open(kw["stdout"].name, "w", encoding="utf-8").write(out)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    res = ClaudeBackend().run(ws, "the prompt", tag="t1", workdir="/sandbox")
    assert calls["env"]["CLAUDE_CONFIG_DIR"] == os.path.join(ws, ".claude-home")
    assert calls["cwd"] == "/sandbox"
    assert calls["input"] == "the prompt"
    # transcript normalized with tool_call_count for the gating check
    assert res.session_file and os.path.exists(res.session_file)
    header = json.loads(open(res.session_file, encoding="utf-8").readline())
    assert header["tool_call_count"] == 1
    assert header["message_count"] == 2
    assert header["session_id"] == "abc123"


def test_claude_bootstrap_copies_config(tmp_path):
    real = tmp_path / "real-claude"
    real.mkdir()
    (real / "settings.json").write_text("{}")
    (real / ".credentials.json").write_text("{}")
    ws = _mkws(tmp_path)
    ClaudeBackend().bootstrap_profile(ws, real=str(real))
    prof = os.path.join(ws, ".claude-home")
    assert os.path.exists(os.path.join(prof, "settings.json"))
    assert os.path.exists(os.path.join(prof, ".credentials.json"))
    assert os.path.isdir(os.path.join(prof, "skills"))
    assert os.path.isdir(os.path.join(prof, "projects"))


# ---------------------------------------------------------------- transcript

def test_normalize_claude_stream_counts_tool_calls(tmp_path):
    src = tmp_path / "raw.jsonl"
    raw = [
        {"type": "user", "message": {"role": "user"}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "thinking"},
            {"type": "tool_use", "name": "Read", "id": "r1"}]}},
        {"type": "user", "message": {"role": "user"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "id": "b1"},
            {"type": "tool_use", "name": "Edit", "id": "e1"}]}},
        {"type": "result", "session_id": "sess-9"},
        "garbage line that is not json",
    ]
    src.write_text("\n".join(json.dumps(x) for x in raw))
    dest = str(tmp_path / "session.jsonl")
    transcript.normalize_claude_stream(str(src), dest)
    lines = open(dest, encoding="utf-8").read().splitlines()
    header = json.loads(lines[0])
    assert header["tool_call_count"] == 3
    assert header["message_count"] == 4
    assert header["session_id"] == "sess-9"
    # raw events preserved after the header; corrupt line skipped
    assert len(lines) == 6  # header + 5 events (garbage dropped)


def test_normalized_claude_transcript_fed_to_gating_check(tmp_path):
    from wikiskill import gating
    src = tmp_path / "raw.jsonl"
    src.write_text("\n".join([
        json.dumps({"type": "user", "message": {"role": "user"}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "no tools"}]}}),
    ]))
    dest = str(tmp_path / "session.jsonl")
    transcript.normalize_claude_stream(str(src), dest)
    assert gating._session_had_no_tool_calls(dest) is True  # launch failure
    src2 = tmp_path / "raw2.jsonl"
    src2.write_text("\n".join([
        json.dumps({"type": "user", "message": {"role": "user"}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "id": "b"}]}}),
    ]))
    dest2 = str(tmp_path / "session2.jsonl")
    transcript.normalize_claude_stream(str(src2), dest2)
    assert gating._session_had_no_tool_calls(dest2) is False


# ---------------------------------------------------------------- facade

def test_facade_dispatches_to_workspace_backend(tmp_path):
    ws = _mkws(tmp_path)
    res = agents.run_agent(ws, "hi", tag="t1", dry_run=True)
    assert res["cmd"][0] == "hermes"  # legacy default
    backends.write_backend(ws, "claude")
    res = agents.run_agent(ws, "hi", tag="t1", dry_run=True)
    assert res["cmd"][0] == "claude"
    assert res["dry_run"] is True and "cmd" in res


def test_facade_run_agent_dict_shape_matches_gating_contract(tmp_path):
    ws = _mkws(tmp_path)
    res = agents.run_agent(ws, "hi", tag="t1", dry_run=True)
    for key in ("cmd", "exit_code", "duration_s", "stdout_path", "session_file"):
        assert key in res


def test_evolve_switch_backend_bootstraps_profile(tmp_path, monkeypatch):
    """Regression (adversarial review): `evolve --backend claude` on an
    existing workspace must bootstrap the claude profile (credentials,
    config, skills dir) — otherwise every rollout fails auth and scores 0.0."""
    from wikiskill import cli, harness, tasks as tasks_mod
    from wikiskill import bench as bench_mod
    ws = _mkws(tmp_path)
    harness.init_workspace(ws)
    tasks_mod.save(ws, bench_mod.generate(42))
    calls = []
    monkeypatch.setattr(cli.agents, "bootstrap_profile",
                        lambda *a, **k: calls.append("boot"))
    monkeypatch.setattr(cli.harness, "evolve",
                        lambda *a, **k: {"baseline": 1.0, "r_best": 1.0})
    rc = cli.main(["evolve", "dummy", "--ws", ws, "--backend", "claude", "--dry-run"])
    assert rc == 0 and calls == [], "dry-run must not bootstrap (side effects)"
    rc = cli.main(["evolve", "dummy", "--ws", ws, "--backend", "claude"])
    assert rc == 0 and calls == ["boot"], "real evolve must bootstrap the profile"


def test_normalize_tolerates_non_dict_message(tmp_path):
    """Regression: a stream event whose `message` is a string (corrupt/
    partial JSON) must not crash the parser."""
    src = tmp_path / "raw.jsonl"
    src.write_text("\n".join([
        json.dumps({"type": "assistant", "message": "interrupted"}),
        json.dumps({"type": "user", "message": {"role": "user"}}),
        json.dumps({"type": "result", "session_id": "s1"}),
    ]))
    dest = str(tmp_path / "session.jsonl")
    transcript.normalize_claude_stream(str(src), dest)
    header = json.loads(open(dest, encoding="utf-8").readline())
    assert header["tool_call_count"] == 0
    # the corrupted assistant event still counts as a message (content is
    # unparseable but the event itself is real) — no crash is the point
    assert header["message_count"] == 2


def test_claude_export_never_serves_stale_transcript(tmp_path):
    """Regression: an empty stdout (agent launch failure) must return None and
    REMOVE any session.jsonl left by an earlier run — gating must never grade
    a stale transcript as this run's result."""
    from wikiskill.backends.claude import export_session
    run_dir = str(tmp_path / "runs" / "iter-00" / "val" / "t1")
    os.makedirs(run_dir)
    dest = os.path.join(run_dir, "session.jsonl")
    with open(dest, "w", encoding="utf-8") as f:
        f.write('{"tool_call_count": 3}\n')
    with open(os.path.join(run_dir, "stdout.txt"), "w", encoding="utf-8"):
        pass  # empty stream
    assert export_session(str(tmp_path), run_dir) is None
    assert not os.path.exists(dest), "stale transcript must be removed"


# ---------------------------------------------------------------- codex (issue #15)

def test_codex_backend_dry_run_command(tmp_path):
    ws = _mkws(tmp_path)
    from wikiskill.backends.codex import CodexBackend
    r = CodexBackend().run(ws, "do it", tag="t1", max_turns=9, dry_run=True)
    assert r.cmd[:3] == ["codex", "exec", "--json"]
    assert "--full-auto" in r.cmd
    assert "--max-turns" in r.cmd and r.cmd[r.cmd.index("--max-turns") + 1] == "9"


def test_codex_run_uses_isolated_config(tmp_path):
    ws = _mkws(tmp_path)
    from wikiskill.backends.codex import CodexBackend
    b = CodexBackend()
    e = b.env(ws)
    assert e["CODEX_HOME"] == os.path.join(ws, ".codex-home")
    assert b.profile_dir_name == ".codex-home"


def test_codex_bootstrap_copies_auth(tmp_path):
    real = str(tmp_path / "real")
    os.makedirs(real, exist_ok=True)
    with open(os.path.join(real, "auth.json"), "w") as f:
        f.write("{}")
    with open(os.path.join(real, "config.toml"), "w") as f:
        f.write("model = 'x'")
    ws = _mkws(tmp_path, "ws2")
    from wikiskill.backends.codex import CodexBackend
    CodexBackend().bootstrap_profile(ws, real=real)
    assert os.path.exists(os.path.join(ws, ".codex-home", "auth.json"))
    assert os.path.exists(os.path.join(ws, ".codex-home", "config.toml"))


def test_codex_export_session_counts_messages_and_tool_calls(tmp_path):
    ws = _mkws(tmp_path)
    sess = os.path.join(ws, ".codex-home", "sessions")
    os.makedirs(sess, exist_ok=True)
    with open(os.path.join(sess, "s1.jsonl"), "w") as f:
        f.write('{"type": "message", "content": "hello"}\n')
        f.write('{"type": "message", "content": [{"type": "tool_use", "name": "shell"}]}\n')
        f.write('{"type": "message", "content": "done"}\n')
    run_dir = os.path.join(ws, "runs", "t1")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "stdout.txt"), "w") as f:
        f.write("out")
    from wikiskill.backends.codex import CodexBackend
    dest = CodexBackend().export_session(ws, run_dir)
    assert dest and os.path.exists(dest)
    with open(dest) as f:
        header = json.loads(f.readline())
    assert header["tool_call_count"] == 1
    assert header["message_count"] == 3
    assert transcript.tool_call_count(dest) == 1


# ---------------------------------------------------------------- copilot (issue #24)

def test_copilot_backend_dry_run_command(tmp_path):
    ws = _mkws(tmp_path)
    from wikiskill.backends.copilot import CopilotBackend
    r = CopilotBackend().run(ws, "do it", tag="t1", workdir=str(tmp_path / "sb"),
                             model="gpt-5.4", dry_run=True)
    assert r.cmd[0] == "copilot" and "-p" in r.cmd and "-s" in r.cmd
    assert "--allow-all-tools" in r.cmd and "--allow-all-paths" in r.cmd
    assert "--no-ask-user" in r.cmd
    assert r.cmd[r.cmd.index("--add-dir") + 1] == str(tmp_path / "sb")
    assert r.cmd[r.cmd.index("--model") + 1] == "gpt-5.4"


def test_copilot_env_isolation(tmp_path):
    ws = _mkws(tmp_path)
    from wikiskill.backends.copilot import CopilotBackend
    assert CopilotBackend().env(ws)["COPILOT_HOME"] == os.path.join(ws, ".copilot-home")


def test_copilot_bootstrap_copies_config(tmp_path):
    real = str(tmp_path / "real")
    os.makedirs(real, exist_ok=True)
    with open(os.path.join(real, "config.json"), "w") as f:
        f.write("{}")
    ws = _mkws(tmp_path, "ws2")
    from wikiskill.backends.copilot import CopilotBackend
    CopilotBackend().bootstrap_profile(ws, real=real)
    assert os.path.exists(os.path.join(ws, ".copilot-home", "config.json"))


def test_copilot_set_active_skills_symlinks_into_sandbox(tmp_path):
    ws = _mkws(tmp_path)
    active = os.path.join(ws, "skills", "active", "s1")
    os.makedirs(active, exist_ok=True)
    with open(os.path.join(active, "SKILL.md"), "w") as f:
        f.write("---\nname: s1\n---")
    sb = str(tmp_path / "sb")
    os.makedirs(sb, exist_ok=True)
    from wikiskill.backends.copilot import CopilotBackend
    CopilotBackend().set_active_skills(ws, workdir=sb)
    assert os.path.islink(os.path.join(sb, ".github", "skills", "s1"))


def test_copilot_export_session_from_events_jsonl(tmp_path):
    ws = _mkws(tmp_path)
    evdir = os.path.join(ws, ".copilot-home", "session-state", "abc123")
    os.makedirs(evdir, exist_ok=True)
    with open(os.path.join(evdir, "events.jsonl"), "w") as f:
        f.write('{"type": "message", "content": "hi"}\n')
        f.write('{"type": "message", "content": [{"type": "tool_use"}]}\n')
    run_dir = os.path.join(ws, "runs", "t1")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "stdout.txt"), "w") as f:
        f.write("out")
    from wikiskill.backends.copilot import CopilotBackend
    dest = CopilotBackend().export_session(ws, run_dir)
    with open(dest) as f:
        header = json.loads(f.readline())
    assert header["tool_call_count"] == 1
    assert header["message_count"] == 2


def test_registry_has_codex_and_copilot(tmp_path):
    ws = _mkws(tmp_path)
    for name in ("codex", "copilot"):
        backends.write_backend(ws, name)
        assert backends.resolve(ws).name == name
