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

## Run 4 — gemma-3-4b (free, OpenRouter), 8 turns — *a cautionary tale*

We tried the paper's headline scenario with a genuinely small free model.
**The run was invalid and was thrown out** — and the Wiki Maintainer agent
caught the problem itself:

| Symptom | Root cause |
|---|---|
| All sessions `tool_call_count=0`, `message_count=1` | **`-m` model routing is broken for unconfigured providers** — the request fell through to a `fallback_providers: [{provider: moa, model: default}]` entry, surfacing as `HTTP 400: default is not a valid model ID` |
| Scores still looked plausible (R = 0.8889) | **Phantom grading**: `reset` clears `raw/` but not sandboxes, so dead agent runs were graded against *stale deliverables* left by earlier experiments |

The maintainer's fifth pattern page (`trace-harness-launch-failure`) described
the zero-step sessions and the stale-grading trap — the framework diagnosed
its own bug through the mechanism it was built to run.

**Fixes (committed):**
1. `--model`/`--provider` now **patch the isolated profile's default model**
   (and strip the broken `moa` fallback) instead of relying on `-m` — the
   default-model path is the one that's proven to work for any provider.
2. **Fresh sandbox per rollout**: `materialize(force=True)` now deletes
   anything not in the task spec, so stale deliverables can never be graded.
3. Zero-tool-call sessions emit an explicit ⚠ warning.

Regression tests added for all three.

## Run 5 — gemini-2.5-flash-lite (free, OpenRouter), 8 turns — *the acceptance run*

The paper's headline scenario, done right this time: a small model that
fails at S₀. Tool use verified working before launch (`echo TOOL-OK` through
the isolated profile). All sessions real (verified tool calls, no phantom
grading).

| Phase | Result |
|---|---|
| Baseline gate (9 val, S₀=∅) | **R = 0.6667** — `spec-format1-2`, `spec-format2-2`, `spec-format3-2` all fail (a genuinely weak model at S₀) |
| Train rollouts (13 tasks) | **0.5385** (7/13) — real failure material for the maintainer |
| Wiki maintenance | sampled 8 traces → patterns distilled; wiki grew to **5 pattern pages** (4 from the deepseek era + `trace-harness-launch-failure`) |
| Skill proposal | `create find-secret` — derived from the `search-miss-binary` pattern (grep for a literal secret string, use `grep -a`) |
| Validation gate (9 val, +skill) | **R = 0.4444** → **REJECTED** |

**Why it was rejected — the money shot:** the skill *hurt*. Two val tasks
regressed with it loaded: `extract-longest` 1.0 → 0.0 and `find-biggest`
1.0 → 0.0 (its "search for the exact string" guidance misdirected the agent
on tasks that need *comparing* files). The strict `R_val > R_best` gate
caught a harmful proposal live, rolled the skill back, and the wiki (now with
5 patterns + audit-trail commits) was retained.

Cost: **$0.086** for the full iteration (31 real sessions).

**Acceptance remains test-proven, not live-proven** — every live gate so far
was a rejection (neutral, harmful, harmful). Getting a live *acceptance*
likely needs a multi-iteration run where the proposer builds on the wiki's
accumulated patterns (the paper's key ablation) or a task set with headroom
for a small model to grow into. That's the roadmap.

## Run 6 — compounding experiment (issue #5): 3 iterations, gemini-2.5-flash-lite — *an honest negative result*

The multi-iteration accumulation run: 3 full Algorithm-1 iterations on a
genuinely weak free-tier model (baseline 0.4444) to test whether the wiki
grows and skills compound.

| Phase | Result |
|---|---|
| Baseline gate (9 val, S₀=∅) | **R = 0.4444** (5/9) — weakest S₀ yet |
| Train rollouts (13 tasks × 3 iters) | iter-03 train **0.2308**; **6/48 sessions launch-failed** (0 tool calls — detected, scored 0.0 from fresh sandbox) |
| Wiki maintenance (8 traces sampled / iter) | only iter-03 distilled a pattern: `successful-empty-search` (sampled traces showed correct empty-search behavior, not failures) |
| Skill proposal | iter-03: **`no_action`** — proposer declined; nothing to gate |
| Validation gates | none ran (no candidate skill) |
| Final state | r_best = **0.4444** = baseline — zero skills accepted, zero admitted |

**Why nothing happened:** with ~12% launch failures and weak reasoning, the
raw layer starves the wiki — most sampled traces were empty/failed or
successful-but-trivial, so the maintainer found no failure pattern to distill
and the proposer correctly declined (`no_action`). The mechanism worked as
designed — no hallucinated skills, no harmful admissions, clean state — but
accumulation clearly needs a stronger model or healthier sessions.

Cost: 48 sessions, ~$0.25 at gemini-lite rates.

**Status of the acceptance question:** still open. Every live gate across
Runs 5–6 was a rejection or a no-op. The paper's accumulation claim is
documented as not-yet-demonstrated on free-tier models; the next candidate is
a stronger model or the claude/codex backends (issue #13).

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
6. **Phantom grading (the big one)** — dead agent runs were scored against
   stale sandbox deliverables from earlier experiments. Fixed with fresh
   sandboxes per rollout + explicit zero-tool-call warnings (see Run 4).
7. **Broken `-m` routing for unconfigured providers** — replaced with
   isolated-profile default-model patching (see Run 4).

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
