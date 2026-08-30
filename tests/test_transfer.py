"""Skill transfer tests (issue #1): cross-model/workspace skill export/import."""

import os
import subprocess

import pytest

from wikiskill import transfer


def make_ws(root: str, with_skill: str | None = None) -> str:
    d = os.path.join(root, "skills", "active")
    os.makedirs(d, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=d, check=False)
    if with_skill:
        s = os.path.join(d, with_skill)
        os.makedirs(s, exist_ok=True)
        with open(os.path.join(s, "SKILL.md"), "w") as f:
            f.write(f"---\nname: {with_skill}\n---\nbody")
        subprocess.run(["git", "add", "-A"], cwd=d, check=False)
        subprocess.run(["git", "-c", "user.email=wikiskill@local",
                        "-c", "user.name=wikiskill", "commit", "-q",
                        "-m", f"add {with_skill}"], cwd=d, check=False)
    return root


def test_transfer_copies_skills(tmp_path):
    src = make_ws(str(tmp_path / "src"), with_skill="keep-calm")
    dst = make_ws(str(tmp_path / "dst"))
    m = transfer.transfer_skills(src, dst)
    assert m["transferred"] == ["keep-calm"]
    assert os.path.isfile(os.path.join(dst, "skills", "active", "keep-calm", "SKILL.md"))
    # source untouched
    assert transfer.active_skills(src) == ["keep-calm"]
    # destination git history records the transfer (rollback available)
    log = subprocess.run(["git", "-C", os.path.join(dst, "skills", "active"),
                          "log", "--oneline"], capture_output=True, text=True).stdout
    assert "transfer from src" in log


def test_transfer_skips_duplicate_without_force(tmp_path):
    src = make_ws(str(tmp_path / "src"), with_skill="same-skill")
    dst = make_ws(str(tmp_path / "dst"), with_skill="same-skill")
    m = transfer.transfer_skills(src, dst)
    assert m["transferred"] == [] and m["skipped"] == ["same-skill"]
    m2 = transfer.transfer_skills(src, dst, force=True)
    assert m2["transferred"] == ["same-skill"]


def test_transfer_requires_active_skills(tmp_path):
    src = make_ws(str(tmp_path / "src"))
    dst = make_ws(str(tmp_path / "dst"))
    with pytest.raises(ValueError, match="no active skills"):
        transfer.transfer_skills(src, dst)


def test_transfer_skips_dirs_without_skillmd(tmp_path):
    src = make_ws(str(tmp_path / "src"), with_skill="good")
    os.makedirs(os.path.join(src, "skills", "active", "no-skill-md"), exist_ok=True)
    dst = make_ws(str(tmp_path / "dst"))
    m = transfer.transfer_skills(src, dst)
    assert m["transferred"] == ["good"]
    assert "no-skill-md" in m["skipped"]
