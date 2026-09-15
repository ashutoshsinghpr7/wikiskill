# Contributing

WikiSkill for Hermes is a small, sharp project. Contributions that move the
needle:

## High-value contributions

- **Task packs for real domains** — your recurring workflows, expressed as
  graded `tasks.json` sets (see README). The framework is only as good as its
  tasks.
- **Multi-iteration compounding runs** — run `evolve --iters 3+` on a domain
  with real baseline failures and publish the wiki/skill trajectory.
- **Skill transfer experiments** — evolve with one model, gate with another
  (the paper shows cross-model transfer).
- **Bug reports with traces** — if an inference run misbehaves, include the
  `raw/traces/` path and the `runs/` tag.

## Standards

- Python 3.10+, stdlib only (no new dependencies without discussion).
- `python3 -m pyflakes wikiskill/ tests/` must be clean.
- `python3 -m pytest tests/ -q` must pass — the fake-runner harness tests are
  mandatory for loop changes (they cover accept / reject / no_action /
  early-stop / crash-resume).
- No secrets, no PII: the repo is public. `workspaces/` is gitignored for a
  reason — never commit traces, `.hermes-home/`, or `runs/`.
- Every CLI change needs a test or an updated dry-run snapshot.
- `python3 -m pyflakes wikiskill/ tests/ setup.py` must be clean (CI lints
  `setup.py` too — it holds real build logic now).
- **`skills/` is load-bearing twice.** The framework skills (`wikiskill-maintainer`,
  `wikiskill-proposer`) live at the repo root because the repo doubles as a Hermes
  skills tap, whose discovery requires `skills/<name>/SKILL.md` — and they must
  also reach installed wheels, which setuptools does not ship from outside the
  package. `setup.py`'s `build_py` hook copies them into the wheel as
  `wikiskill/framework_skills/`; `wikiskill.harness.repo_skills_dir()` prefers
  that copy and falls back to `<repo>/skills`. If you touch packaging, run the
  `wheel` CI job's steps locally (`python -m build --wheel`, install in a clean
  venv, `wikiskill init demo`, check `skills/framework/*/SKILL.md`) — issue #29
  was invisible for exactly three releases because `pip install -e .` hides it.

## Process

1. Fork, branch, PR.
2. Describe what changed and *why* (algorithm fidelity matters more than code
   churn — when in doubt, re-read Appendix E of the paper).
3. CI runs pytest on every push.
