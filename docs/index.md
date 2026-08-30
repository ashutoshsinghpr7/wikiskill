# WikiSkill for Hermes

**Compile agent experience into a persistent wiki — and let skills evolve themselves.**

WikiSkill is a Google Research framework (arXiv:2608.27454) that co-evolves
agent skills with a persistent knowledge base. This repository is a faithful
implementation for **Hermes Agent**, with a live, documented run log on real
models.

## The loop

```
raw experience ──► persistent wiki ──► skill proposals ──► gated rollout
(session traces)   (pattern pages)      (SKILL.md)         R_val > R_best ?
```

1. **Raw layer** — agents execute tasks; full transcripts are captured.
2. **Wiki maintainer** — distills low-scoring traces into pattern pages in a
   persistent wiki (never rolled back — knowledge accumulates).
3. **Skill proposer** — proposes new skills from wiki patterns + trace
   evidence, with full rejected proposals kept visible (anti-repetition).
4. **Gating** — the candidate skill is rolled out on held-out tasks; accepted
   iff `R_val > R_best`, otherwise git-rolled-back. The wiki is always kept.

## Why this repo

- **The full loop, live** — every phase runs on a real agent (Hermes) with
  isolated per-workspace profiles; see the [Run Log](RUNS.md).
- **Small-model story proven** — a free-tier model failed at baseline (0.67),
  and gating caught a *harmful* proposed skill live (R dropped to 0.44) and
  rolled it back.
- **Honest by construction** — fresh sandboxes per rollout (no stale grading),
  zero-tool-call launch-failure detection, paired statistical comparison
  ([Comparing runs](COMPARING.md)), and a documented list of bugs found and
  fixed during development.

## Quickstart

```bash
pip install -e .
wikiskill init demo
wikiskill evolve demo --iters 1 --model google/gemini-2.5-flash-lite --provider openrouter
wikiskill status demo
```

Runs cost ≈ $0.09/iteration on free-tier models. See the [full README](https://github.com/ashutoshsinghpr7/wikiskill-hermes#readme) for the complete guide, CLI reference, and design decisions.
