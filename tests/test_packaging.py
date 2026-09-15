"""Packaging regressions (issue #29) — the non-editable install path.

`skills/` sits at the repo root because this repo doubles as a Hermes skills tap,
whose discovery requires `skills/<name>/SKILL.md`. setuptools ships nothing
outside the `wikiskill` package, so before 0.1.5 every non-editable install
(pip / `uv tool install`) got an empty `workspaces/<domain>/skills/framework/`
and ran the maintainer and proposer turns with no skill loaded — silently, with
well-formed scores. CI only ever exercised `pip install -e .`, which resolves the
skills from the checkout, so nothing caught it.

These tests pin the whole chain: the built WHEEL and SDIST carry the framework
skills (setup.py's build_py hook + MANIFEST.in), `init_workspace` stages them, a
workspace left empty (or half-staged, or wrongly typed) by a broken install is
repaired, they reach the agent's isolated profile, and a missing skill fails
loudly instead of degrading.
"""

import glob
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest

from wikiskill import harness

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Everything setuptools needs to build the distribution.
BUILD_INPUTS = ("pyproject.toml", "setup.py", "MANIFEST.in", "README.md",
                "LICENSE", "wikiskill", "skills")


def skill_md(ws: str, name: str) -> str:
    return os.path.join(ws, "skills", "framework", name, "SKILL.md")


def _require_build_tooling():
    """`build`/`setuptools` are needed to test the artifact, not to run wikiskill.

    Skipping is fine locally, but in CI this test is *the* guard for issue #29 —
    a silent skip there is exactly how the bug shipped, so it fails instead.
    """
    import importlib.util
    missing = [m for m in ("build", "setuptools")
               if importlib.util.find_spec(m) is None]
    if missing:
        if os.environ.get("CI"):
            pytest.fail(f"{missing} must be installed in CI — this test guards issue #29")
        pytest.skip(f"{missing} not installed")


def _source_copy(tmp_path) -> str:
    """A throwaway copy of the packaging inputs, so builds leave no residue."""
    src = tmp_path / "src"
    src.mkdir()
    for name in BUILD_INPUTS:
        s, d = os.path.join(REPO_ROOT, name), str(src / name)
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(s, d)
    return str(src)


def test_init_stages_framework_skills_in_the_workspace(tmp_path):
    ws = str(tmp_path / "ws")
    harness.init_workspace(ws)
    for name in harness.FRAMEWORK_SKILLS:
        assert os.path.isfile(skill_md(ws, name)), f"{name} was not staged"
        # the maintainer/proposer prompt loads the skill BY NAME
        with open(skill_md(ws, name), encoding="utf-8") as f:
            assert f"name: {name}" in f.read()


@pytest.mark.parametrize("damage", ["missing", "empty", "junk-only", "plain-file"])
def test_init_repairs_a_wrong_or_half_staged_framework_dir(tmp_path, damage):
    """0.1.2–0.1.4 workspaces have an empty skills/framework/ — and an
    interrupted copy can leave worse. All of it must be repaired, never treated
    as staged (a non-empty dir without SKILL.md is the silent case)."""
    ws = str(tmp_path / "ws")
    harness.init_workspace(ws)
    name = harness.FRAMEWORK_SKILLS[0]
    dst = os.path.join(ws, "skills", "framework", name)
    shutil.rmtree(dst)
    if damage == "empty":
        os.makedirs(dst)
    elif damage == "junk-only":
        os.makedirs(dst)
        with open(os.path.join(dst, "notes.txt"), "w", encoding="utf-8") as f:
            f.write("half-staged by an interrupted copy\n")
    elif damage == "plain-file":
        with open(dst, "w", encoding="utf-8") as f:
            f.write("not a directory\n")

    harness.ensure_framework_skills(ws)
    assert os.path.isfile(skill_md(ws, name))
    assert not os.path.exists(os.path.join(dst, "notes.txt"))


def test_a_symlinked_framework_dir_is_repaired_not_crashed(tmp_path):
    """Regression: 0.1.4 skipped a symlinked dst; the first cut of the repair
    called shutil.rmtree on it, and rmtree refuses to unlink a symlink."""
    ws = str(tmp_path / "ws")
    harness.init_workspace(ws)
    name = harness.FRAMEWORK_SKILLS[0]
    dst = os.path.join(ws, "skills", "framework", name)
    shutil.rmtree(dst)
    os.symlink(str(tmp_path / "elsewhere-empty"), dst)
    harness.ensure_framework_skills(ws)
    assert not os.path.islink(dst) and os.path.isfile(skill_md(ws, name))


def test_a_complete_staged_copy_is_left_alone(tmp_path):
    """Local edits to a staged skill must survive (the repair is not a reset)."""
    ws = str(tmp_path / "ws")
    harness.init_workspace(ws)
    name = harness.FRAMEWORK_SKILLS[0]
    with open(skill_md(ws, name), "a", encoding="utf-8") as f:
        f.write("\n<!-- local note -->\n")
    harness.ensure_framework_skills(ws)
    with open(skill_md(ws, name), encoding="utf-8") as f:
        assert "local note" in f.read()


def test_missing_framework_skills_fail_loudly(tmp_path, monkeypatch):
    """No silent skip: an install without the skills must abort the turn — and
    must abort it *before* creating a half-built workspace."""
    ws = str(tmp_path / "ws")
    monkeypatch.setattr(harness, "repo_skills_dir", lambda: str(tmp_path / "nope"))
    with pytest.raises(FileNotFoundError) as exc:
        harness.init_workspace(ws)
    msg = str(exc.value)
    assert "wikiskill-maintainer" in msg and "0.1.5" in msg
    assert not os.path.exists(ws), "a broken install must not leave debris behind"


def test_cli_reports_a_broken_install_as_one_line(tmp_path, monkeypatch, capsys):
    """The CLI's other error paths print a line and return 1 — not a traceback."""
    from wikiskill import cli
    monkeypatch.setattr(harness, "repo_skills_dir", lambda: str(tmp_path / "nope"))
    rc = cli.main(["init", "demo", "--ws", str(tmp_path / "ws")])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err.startswith("error: ") and "0.1.5" in captured.err


def test_init_is_rerunnable_after_a_failed_init(tmp_path):
    """A dir left behind by a failed init has no tasks.json — `init` must
    finish the job rather than report 'workspace already exists'."""
    from wikiskill import cli
    ws = str(tmp_path / "ws")
    os.makedirs(os.path.join(ws, ".hermes-home"))  # debris from the failed run
    assert cli.main(["init", "demo", "--ws", ws]) == 0
    assert os.path.isfile(os.path.join(ws, "tasks.json"))
    assert cli.main(["init", "demo", "--ws", ws]) == 1  # finished now


def test_maintain_step_repairs_before_running_the_agent(tmp_path):
    """The guarantee sits at the point of use, not only inside `init`."""
    ws = str(tmp_path / "ws")
    harness.init_workspace(ws)
    for name in harness.FRAMEWORK_SKILLS:
        shutil.rmtree(os.path.join(ws, "skills", "framework", name))
    calls = []

    def runner(ws_, prompt, **kw):
        calls.append(kw.get("tag"))
        return {"exit_code": 0}

    harness.maintain_step(ws, 1, [], runner=runner, dry_run=True)
    assert calls == ["maintain-01"], "the framework turn must still run once repaired"
    for name in harness.FRAMEWORK_SKILLS:
        assert os.path.isfile(skill_md(ws, name))


def test_repo_skills_dir_prefers_the_packaged_copy(tmp_path):
    """Wheel installs resolve inside the package; checkouts fall back to the
    repo root (where the Hermes tap needs them to stay)."""
    fake = tmp_path / "site-packages" / "wikiskill"
    fake.mkdir(parents=True)
    assert harness.repo_skills_dir(str(fake)) == os.path.join(
        str(tmp_path / "site-packages"), "skills")  # no packaged copy -> source layout
    (fake / "framework_skills").mkdir()
    assert harness.repo_skills_dir(str(fake)) == str(fake / "framework_skills")


def test_framework_skills_reach_the_agent_profile(tmp_path):
    """End of the chain: staged skills are symlinked into the isolated profile
    the agent actually runs in."""
    from wikiskill.backends import hermes
    ws = str(tmp_path / "ws")
    harness.init_workspace(ws)
    try:
        hermes.set_active_skills(ws, include_framework=True)
    except (OSError, NotImplementedError) as e:  # Windows without developer mode
        pytest.skip(f"cannot create symlinks here: {e}")
    prof = os.path.join(hermes.profile_dir(ws), "skills")
    for name in harness.FRAMEWORK_SKILLS:
        link = os.path.join(prof, name)
        assert os.path.islink(link), f"{name} not symlinked into the agent profile"
        assert os.path.isfile(os.path.join(os.path.realpath(link), "SKILL.md"))


def test_lookup_falls_back_to_the_pre_0_1_5_workspace_root(tmp_path, monkeypatch, capsys):
    """The cwd-relative default must not strand workspaces an older version
    created, when the CLI is run from a subdirectory."""
    from wikiskill import cli
    legacy = tmp_path / "legacy" / "workspaces"
    (legacy / "nightly").mkdir(parents=True)
    monkeypatch.setattr(cli, "legacy_ws_root", lambda: str(legacy))
    monkeypatch.chdir(tmp_path)
    assert cli.resolve_ws("nightly", None) == str(legacy / "nightly")
    assert "using the existing workspace" in capsys.readouterr().err
    # an unknown domain is still created relative to the cwd
    assert cli.resolve_ws("fresh", None) == os.path.join(str(tmp_path), "workspaces", "fresh")


def test_facade_warns_when_a_framework_turn_has_no_skill(tmp_path, capsys):
    """Last-resort tripwire (stderr, so it survives `>log 2>&1` habits)."""
    from wikiskill import agents
    ws = str(tmp_path / "ws")
    harness.init_workspace(ws)
    shutil.rmtree(os.path.join(ws, "skills", "framework", harness.FRAMEWORK_SKILLS[0]))
    agents.run_agent(ws, "hi", tag="t", include_framework=True, dry_run=True)
    assert "NO framework skill loaded" in capsys.readouterr().err


def test_built_distribution_ships_the_framework_skills(tmp_path):
    """The bug was invisible because CI only tested an editable install.

    Builds sdist + wheel from a throwaway copy of the packaging inputs, then
    asserts the wheel carries the skills (so a non-editable install works) and
    the sdist does too (so a wheel built from the sdist still works).
    """
    _require_build_tooling()
    src = _source_copy(tmp_path)
    out = tmp_path / "dist"
    subprocess.run([sys.executable, "-m", "build", "--no-isolation",
                    "--outdir", str(out), src], check=True, capture_output=True)

    names = zipfile.ZipFile(glob.glob(str(out / "*.whl"))[0]).namelist()
    for name in harness.FRAMEWORK_SKILLS:
        assert f"wikiskill/framework_skills/{name}/SKILL.md" in names, (
            f"{name} missing from the wheel — a non-editable install would run "
            f"the maintainer/proposer turns with no skill loaded (issue #29)"
        )
    # the tap layout must not leak into site-packages as a top-level package
    assert not [n for n in names if n.startswith("skills/")]

    with tarfile.open(glob.glob(str(out / "*.tar.gz"))[0]) as tf:
        sdist = tf.getnames()
    for name in harness.FRAMEWORK_SKILLS:
        assert any(n.endswith(f"/skills/{name}/SKILL.md") for n in sdist), (
            f"{name} missing from the sdist — a wheel built from it would ship "
            f"no framework skills (MANIFEST.in)"
        )
    # and the hook must never materialize a copy in the source tree, where it
    # would shadow the repo-root skills for editable installs
    assert not os.path.exists(os.path.join(src, "wikiskill", "framework_skills"))
