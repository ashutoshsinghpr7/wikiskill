# 🧠 WikiSkill

**Compile agent experience into a persistent wiki — and let skills evolve themselves.**

> 📚 **Docs site**: [ashutoshsinghpr7.github.io/wikiskill](https://ashutoshsinghpr7.github.io/wikiskill) · **arXiv**: [2608.27454](https://arxiv.org/abs/2608.27454)

A faithful, production-minded implementation of **[WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution](https://arxiv.org/abs/2608.27454)** (arXiv:2608.27454, Google Research). The loop is **agent-agnostic** — **Hermes Agent** is the reference backend (built natively), **Claude Code** ships in the box, and Codex/OpenCode are on the roadmap ([issue #13](https://github.com/ashutoshsinghpr7/wikiskill/issues/13)). Your agent becomes both the *student* and the *teacher*.

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/wikiskill?color=orange)](https://pypi.org/project/wikiskill/)
[![CI](https://img.shields.io/github/actions/workflow/status/ashutoshsinghpr7/wikiskill/ci.yml?label=CI)](https://github.com/ashutoshsinghpr7/wikiskill/actions)
[![arXiv](https://img.shields.io/badge/arXiv-2608.27454-red.svg)](https://arxiv.org/abs/2608.27454)

---

## What this is

Agents fail. They also *learn* — but the lessons usually die with the session. WikiSkill fixes that by keeping a **persistent knowledge wiki** alongside the skill set, and running a closed evolution loop:

1. The agent runs **training tasks** with its current skills → raw execution traces
2. A **Wiki Maintainer** agent distills the traces into pattern pages (root causes, fixes)
3. A **Skill Proposer** agent reads the wiki + traces and proposes one skill change (create or patch)
4. **Gating**: the change is validated on held-out tasks — **strictly better** than the best score so far → kept; otherwise rolled back. **The wiki is never rolled back.**

Over iterations, knowledge compounds in the wiki while only *proven* improvements touch the skills.

```
                ┌──────────────────────────────────────────────────────┐
                │              EVOLUTION LOOP (Algorithm 1)            │
                │                                                      │
   tasks ─────► │  Inference Agent ──► raw/traces/ (immutable)         │
                │        │                                            │
                │        ▼                                            │
                │  Wiki Maintainer ──► wiki/patterns/, index, log     │
                │        │                                            │
                │        ▼                                            │
                │  Skill Proposer ──► proposal (create/patch skill)   │
                │        │                                            │
                │        ▼                                            │
                │  GATE: val score > R_best? ──yes──► keep, R_best=R  │
                │        │ no                                         │
                │        ▼                                            │
                │  rollback skills; wiki retained forever             │
                └──────────────────────────────────────────────────────┘
```

## Why Hermes?

This is not a toy simulator. Every component is a **real Hermes agent turn**:

| WikiSkill (paper) | This repo |
|---|---|
| Inference Agent | `hermes chat --oneshot` in an **isolated `HERMES_HOME` profile** |
| Raw Layer | Full session JSONL transcripts, exported via `hermes sessions export` |
| Wiki Layer | `wiki/` — git-tracked, maintained by a real agent, never rolled back |
| Skill Layer | Real `SKILL.md` packages (frontmatter + instructions), git-managed |
| Wiki Maintainer | Agent turn with the paper's **Appendix E.2 prompt** (extracted verbatim) |
| Skill Proposer | Agent turn with the paper's **Appendix E.3 ReAct prompt** |
| Gating | Strict `R_val > R_best`; `git reset --hard` on reject |

**Why the isolated profile matters:** gating is only meaningful if the agent sees *exactly* the candidate skill set. Each evolution workspace gets its own `HERMES_HOME` (bundled skills opted out, empty memory, skills symlinked per stage) — your real profile is never touched.

## Quickstart (60 seconds)

```bash
pip install wikiskill        # from PyPI (wheel + sdist, Python ≥3.10)
wikiskill init demo           # workspace + 22-task auto-graded bench (13 train / 9 val)
wikiskill status
wikiskill evolve --iters 3    # full Algorithm 1 loop with your default model
```

Or from source: `pip install -e .` (installs the same `wikiskill` CLI).

That's it. Each evolution workspace lives at `workspaces/<domain>/`:

```
workspaces/demo/
├── raw/traces/iter-01/{train,val}/<task>.jsonl   # immutable execution traces
├── wiki/                                          # persistent knowledge (never rolled back)
│   ├── index.md  ·  log.md  ·  skill-impact.md  ·  patterns/*.md
├── skills/active/                                 # git-managed evolving skill set (S₀ = ∅)
├── skills/framework/                              # maintainer + proposer agent skills
├── bench/tasks/<id>/                              # task sandboxes (inputs + grader)
└── runs/                                          # per-run stdout, proposals, state
```

## CLI

| Command | What it does |
|---|---|
| `wikiskill init <domain> [--backend claude]` | Create workspace + demo bench (pins the agent backend) |
| `wikiskill bench --reset` | Regenerate tasks (deterministic, seed=42) |
| `wikiskill status` | Workspace state: scores, skills, wiki, history |
| `wikiskill evolve --iters N [--model M] [--provider P] [--max-turns N] [--no-early-stop]` | The full loop (`--model`/`--provider` patch the isolated profile's default model, e.g. `google/gemini-2.5-flash-lite` + `openrouter`) |
| `wikiskill run-task <id>` | Single inference rollout (debug) |
| `wikiskill compare <wsA> <wsB> [--iters N]` | Paired statistical comparison: per-task win/loss/tie + two-sided exact-binomial p-value (answers "did the skill actually help?" — see [docs/COMPARING.md](docs/COMPARING.md)) |

## Bring your own tasks

Tasks are plain JSON (`tasks.json`); anything auto-gradable works:

```json
{
  "id": "spec-format1-1", "split": "train",
  "title": "Format products according to spec",
  "prompt": "Read spec.md and products.json...",
  "sandbox": {"spec.md": "...", "products.json": "..."},
  "grader": {"type": "exact", "file": "output.txt", "expected": "alpha|35|active\n..."}
}
```

Graders: `exact`, `contains`, `json_field`, `code_stdout` (runs the produced script). Missing deliverables score **0**, never crash.

## Live results so far

Honest numbers from real agent runs on the bundled bench:

| Setup | Baseline (S₀) | What happened |
|---|---|---|
| deepseek-v4-flash, 15 turns | **1.0** | Algorithm 1 **early-stop** — nothing to evolve |
| deepseek-v4-flash, 8 turns | **1.0** | same |
| deepseek-v4-flash, forced | 1.0 | proposer created `spec_literal_transform` → R_val=1.0, not > R_best → **rejected** |
| deepseek-v4-flash, forced | 1.0 | maintainer distilled **4 pattern pages** (incl. `execute_code` blocked in sandbox, ripgrep binary misses); proposer created `exact-match-sandbox-task` → R_val=0.8889 (skill *hurt*) → **rejected** |
| gemma-3-4b (free, OpenRouter) | — | **invalid run, thrown out** — dead agent sessions were phantom-graded against stale sandboxes. The maintainer's pattern page caught the framework's own bug; fixed + regression-tested (see [docs/RUNS.md](docs/RUNS.md) Run 4) |
| **gemini-2.5-flash-lite (free, OpenRouter), 8 turns** | **0.6667** (real) | small model fails at S₀ → maintainer distilled 5 patterns → proposer created `find-secret` → **R_val=0.4444, the skill hurt (2 regressions) → rejected**. Full loop live on a genuinely weak model, ~$0.09/iteration |
| gemini-2.5-flash-lite, 3 iterations (issue #5) | **0.4444** (real) | compounding run: train as low as 0.2308, 6/48 launch failures (detected + honest 0.0s), maintainer distilled 1 pattern, proposer **declined (`no_action`)** — nothing to gate, r_best preserved. Honest negative: accumulation needs a stronger model (see [docs/RUNS.md](docs/RUNS.md) Run 6) |

The gating mechanism has caught both a neutral and a *harmful* proposal live. Full logs in [docs/RUNS.md](docs/RUNS.md).

## Design decisions worth knowing

- **`--in` doesn't pin the agent's CWD** in single-query runs → every inference prompt embeds an absolute `WORKING DIRECTORY` and forbids exploring outside it.
- **Sessions live in `state.db`**, not loose files → transcripts are materialized via `hermes sessions export --format jsonl`.
- **Rejected proposals are never lost** — their full content is embedded in `wiki/skill-impact.md` so future proposers don't repeat them (per Appendix E.3).
- **The demo bench has traps**: subtle-spec tasks and multi-bug debug scripts whose bugs *don't* compensate (verified at generation time).

## How this compares to other community implementations

We audited the three repos that appeared alongside the paper (see [docs/RUNS.md](docs/RUNS.md)). This is the only one that: runs on a real agent stack (Hermes), gates skills through a fully isolated profile, ships verbatim Appendix E prompts, and has a live-verified end-to-end loop (maintainer → proposer → gate → rollback).

## Agent backends

The loop runs on any supported agent CLI — the raw/wiki/skill layers are
backend-agnostic ([issue #13](https://github.com/ashutoshsinghpr7/wikiskill/issues/13)).

| Backend | Pin a workspace | Notes |
|---|---|---|
| `hermes` (default) | `wikiskill init demo --backend hermes` | reference implementation; isolated `HERMES_HOME` per workspace |
| `claude` | `wikiskill init demo --backend claude` | Claude Code 2.x (`claude -p`), isolated `CLAUDE_CONFIG_DIR`, transcripts normalized from the stream-json output; `claude auth login` required once |

Each workspace pins its backend in `workspaces/<domain>/workspace.json`; switch
anytime with `wikiskill evolve <domain> --backend claude`. Skills evolved on
one backend transfer to another via `wikiskill transfer` (same SKILL.md format).

## Skills tap — install the distilled patterns in Hermes

This repo doubles as a [Hermes skills tap](https://agentskills.io/specification) —
the patterns distilled from live evolution runs, installable in Hermes:

```bash
hermes skills tap add ashutoshsinghpr7/wikiskill
hermes skills install ashutoshsinghpr7/wikiskill/skills/wikiskill-evolve
hermes skills install ashutoshsinghpr7/wikiskill/skills/search-miss-binary
# ...one `install` per skill you want
```

| Skill | What it teaches | Paper layer |
|---|---|---|
| `wikiskill-evolve` | Run the full evolution loop from inside Hermes | framework meta-skill (tooling doc, not a paper artifact) |
| `search-miss-binary` | ripgrep silently skips binary files — verify empty results | maintainer wiki pattern (distilled from live run) |
| `script-exec-blocked` | Sandbox approval policy: use file tools, not `python3 -c` | maintainer wiki pattern |
| `spec-literal-execution` | Apply only the spec's literal clauses — no hidden transforms | maintainer wiki pattern |
| `trace-harness-launch-failure` | Empty traces = launch failure, not agent behavior | maintainer wiki pattern |
| `verify-output-readback` | Re-read the deliverable before finishing | maintainer wiki pattern |

**Paper alignment, stated honestly:** the five operational skills are the
*maintainer's* distilled patterns from real graded runs (`docs/RUNS.md`) — the
paper's wiki layer. None has been *accepted* by the validation gate yet (every
live gate so far was a rejection or `no_action`), so treat them as
well-evidenced raw material for the proposer/gate pipeline, not as
gate-approved skills. All ship as standard SKILL.md (agentskills.io-compatible).

## Roadmap

**Done:**
- [x] `compare` command — paired exact-binomial run comparison ([#6](https://github.com/ashutoshsinghpr7/wikiskill/pull/6))
- [x] Skill *transfer* across workspaces/models ([#7](https://github.com/ashutoshsinghpr7/wikiskill/pull/7))
- [x] Cron-driven overnight evolution (`hermes cron`, 01:00 IST nightly) + docs/CRON.md
- [x] Multi-agent backends: Hermes (reference) + **Claude Code**, protocol ready for more ([#13](https://github.com/ashutoshsinghpr7/wikiskill/issues/13))
- [x] GitHub Pages — custom animated docs site ([#18](https://github.com/ashutoshsinghpr7/wikiskill/pull/18))
- [x] PyPI package `wikiskill` via **tokenless trusted publishing** ([#20](https://github.com/ashutoshsinghpr7/wikiskill/pull/20))
- [x] Multi-iteration compounding run — honest negative documented (Run 6)

**Planned:**
- [ ] Codex backend ([#15](https://github.com/ashutoshsinghpr7/wikiskill/issues/15))
- [ ] OpenCode backend ([#16](https://github.com/ashutoshsinghpr7/wikiskill/issues/16))
- [ ] Cross-agent transfer demo — evolve on one agent, gate on another ([#17](https://github.com/ashutoshsinghpr7/wikiskill/issues/17))
- [ ] A live *acceptance* gate (proposal beats baseline on a real model) — still the open scientific question (see Run 6)
- [ ] Real-task domains — your recurring workflows as graded task packs ([#2](https://github.com/ashutoshsinghpr7/wikiskill/issues/2))

## License

MIT — see [LICENSE](LICENSE). Based on arXiv:2608.27454 (Google Research); all prompts in `skills/` are adapted from the paper's Appendix E. Inspired by [Karpathy's LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
