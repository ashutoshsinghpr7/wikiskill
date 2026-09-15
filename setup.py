"""Build hook: ship the framework skills inside the wheel.

The framework skills (`wikiskill-maintainer`, `wikiskill-proposer`) live at the
repo root under `skills/` because this repo doubles as a Hermes skills tap, and
tap discovery requires `skills/<name>/SKILL.md`. That directory sits *outside*
the `wikiskill` package, so setuptools ships none of it by default — which is
exactly issue #29: every non-editable install (pip / `uv tool`) got an empty
`workspaces/<domain>/skills/framework/` and ran the maintainer and proposer
turns with no skill loaded, silently (CI only ever tested `pip install -e .`).

This hook copies the framework skills into the build tree as
`wikiskill/framework_skills/<name>/` so the wheel carries them and
`wikiskill.harness.repo_skills_dir()` finds them inside the package. The
repo-root layout stays authoritative — there is exactly one copy in git.
"""

from __future__ import annotations

import os
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

HERE = os.path.dirname(os.path.abspath(__file__))

# Keep in sync with wikiskill.backends.base.FRAMEWORK_SKILLS — tests/test_packaging.py
# asserts both names (with SKILL.md) are present in the built wheel.
FRAMEWORK_SKILLS = ("wikiskill-maintainer", "wikiskill-proposer")


class build_py(_build_py):
    """build_py + the repo-root framework skills."""

    def run(self) -> None:
        super().run()
        staged = [os.path.join(HERE, "skills", name) for name in FRAMEWORK_SKILLS]
        for src in staged:
            if not os.path.isfile(os.path.join(src, "SKILL.md")):
                # A wheel without these silently degrades every evolution run
                # (issue #29) — fail the build instead of shipping it.
                raise SystemExit(
                    f"build aborted: framework skill {os.path.basename(src)!r} "
                    f"has no SKILL.md at {src!r}"
                )
        # Clear the whole directory, not just the names we are about to write:
        # a stale build/lib would otherwise keep shipping a renamed or removed
        # framework skill.
        dst_root = os.path.join(self.build_lib, "wikiskill", "framework_skills")
        shutil.rmtree(dst_root, ignore_errors=True)
        for src in staged:
            shutil.copytree(src, os.path.join(dst_root, os.path.basename(src)))


setup(cmdclass={"build_py": build_py})
