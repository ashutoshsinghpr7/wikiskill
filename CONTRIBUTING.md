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

## Process

1. Fork, branch, PR.
2. Describe what changed and *why* (algorithm fidelity matters more than code
   churn — when in doubt, re-read Appendix E of the paper).
3. CI runs pytest on every push.
