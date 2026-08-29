# Run Log — documented inference & evolution runs

Every entry below is a **real agent run** on the bundled demo bench
(`workspaces/demo/`, 22 tasks, seed 42). Costs are per-run USD as reported in
the session metadata. No fabricated numbers — each row corresponds to
`runs/` + `raw/traces/` artifacts in the workspace.

## Environment

- Host: macOS (Apple M2), Hermes Agent desktop
- Providers: DeepSeek (default), OpenRouter (free small models)
- Bench: 22 tasks — spec formatting, extraction, coding, CSV, file-finding,
  plus `trap` tasks (subtle-spec + multi-bug debug scripts with
  generation-time-verified non-compensating bugs)

## Run 1 — deepseek-v4-flash, 15 turns, original 18-task bench

| Phase | Result |
|---|---|
| Baseline gate (6 val, S₀=∅) | **R = 1.0** (all tasks passed, 13–24s each) |
| Algorithm 1 | `R_best == 1.0` → **early stop** — correct per the paper |

Cost: ~$0.0003–0.0009 per inference run. Lesson: a strong model saturates an
easy synthetic bench at S₀ — exactly the case where the paper's early-stop
fires. To exercise the loop we either force it or use a weaker model.

## Run 2 — deepseek-v4-flash, 8 turns, 22-task bench (traps added)

| Phase | Result |
|---|---|
| Baseline gate (9 val, S₀=∅) | **R = 1.0** → early stop again |
| Forced iteration (training) | 13 train tasks, several failures: `spec-format2-*` misread "one line per product" as aggregate-by-name → 0.0 |
| Wiki Maintainer | **Turn-cap bug found**: analysis excellent, writes never happened (25-turn budget) → raised to 60 turns, added selective trace reading |
| Skill Proposer | Proposed `create spec_literal_transform` — valid SKILL.md with When to Apply |
| Gate | R_val = 1.0, not > R_best → **REJECTED, rolled back**; wiki retained |

## Run 3 — deepseek-v4-flash, 8 turns, fixed budgets (60-turn agents)

| Phase | Result |
|---|---|
| Baseline gate (9 val) | **R = 1.0** → forced iteration |
| Wiki Maintainer | Wrote **4 pattern pages** + index + log, distilled from real traces: |
| | `spec-literal-execution` — literal spec execution failure mode |
| | `script-exec-blocked` — **`execute_code` is blocked in single-query sandbox runs** (a Hermes-specific discovery) |
| | `search-miss-binary` — ripgrep returns 0 matches on binary-ish files → fall back to `grep -a` |
| | `verify-output-readback` — passing traces re-read deliverables |
| Skill Proposer (wiki-informed) | Proposed `create exact-match-sandbox-task` |
| Gate | R_val = **0.8889 < R_best** — the skill *hurt* one val task → **REJECTED, rolled back** |

This is the gating mechanism working as designed: it caught a **harmful**
proposal live. Both rejected proposals' full content remain in
`wiki/skill-impact.md`.

## Run 4 — gemma-3-4b (free, OpenRouter), 8 turns — *the acceptance run*

The paper's headline scenario: a small model that fails at S₀ and should
benefit from evolved skills.

| Phase | Result |
|---|---|
| Probes | `debug-boundary` 1.0, `csv-north-count` 1.0, **`spec-format2-2` 0.0** |
| Baseline gate (9 val, S₀=∅) | **R = 0.8889** → no early stop, iteration 1 runs |
| Iteration 1 | train rollouts → maintainer → proposer → gate (in progress at time of writing) |

Cost: **$0.00** (OpenRouter free-tier model).

## Bugs found & fixed during these runs

1. **`--in` doesn't pin the agent's CWD** — inference agents guessed the wrong
   sandbox (one wrote into another task's directory). Fix: every prompt embeds
   the absolute `WORKING DIRECTORY` and forbids exploring outside it.
2. **Sessions live in `state.db`**, not loose `.jsonl` files — transcript
   capture now exports via `hermes sessions export --format jsonl`.
3. **Compensating trap bugs** — a two-bug script whose bugs cancelled out
   (printed the right answer for the chosen input). Fix: re-chosen input +
   generation-time `assert` that the buggy output differs from expected.
4. **Maintainer/proposer turn caps** — 25/30 turns was enough to analyze but
   not to write. Now 60 turns with "write early" guidance.
5. **CI-readiness** — `bootstrap_profile` now skips `hermes skills opt-out`
   when the hermes binary is absent (test suite runs in plain CI).

## How we compare to other implementations

Audited 2026-08-30 (all three appeared within 2 days of the paper):

| Repo | Verdict |
|---|---|
| `srlabs/skillforge` | Solid full-loop reimplementation (Claude Code), fake-runner smoke tests, `compare` cmd — but no live end-to-end evidence, no isolated skill-set gating |
| `phin-tech/wiki-garden` | Personal memory system "adapted from WikiSkill" — wiki half only, no evolution loop |
| `IvanLukianenko/WikiSkill` | Claude/OpenCode plugin adaptation — no benchmark, no loop |

Independent design convergence: SkillForge and this repo both chose strict
`>` gating, wiki-always-persists, and fake-runner loop tests — good evidence
both read Algorithm 1 correctly.
