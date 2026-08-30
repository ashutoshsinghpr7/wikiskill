# Comparing runs honestly

`wikiskill compare` answers the question every skill-evolution project eventually
asks: **"did the skill (or the new model, or the new prompt) actually help —
or was that single run just luck?"**

## Why single runs lie

Agent runs are stochastic. One gate showing 0.89 > 0.67 can be noise. The
paper's gating (`R_val > R_best`) is deliberately conservative to survive
this; `compare` is the tool for *post-hoc* questions like "does the accepted
skill generalize?" or "is model X better than model Y on this task set?"

## Usage

```bash
wikiskill compare demo skill-enabled --iters 8
```

Runs both workspaces' **val sets** N times each (fresh sandbox per run), then:

| Output | Meaning |
|---|---|
| per-task `A` / `B` | pass rate across the N runs (0.0–1.0) |
| per-task winner | A / B / tie by pass rate |
| discordant pairs | runs where exactly one side passed (the only informative ones) |
| `p` (two-sided exact binomial) | probability of seeing this imbalance by chance, on discordant pairs only |
| verdict | `A better` / `B better` / `no significant difference` (requires p ≤ 0.05 **and** the right direction) |

## Interpreting `p`

- p ≤ 0.05 + A's pass rate higher → **A better** (evidence, not proof).
- p > 0.05 → not enough discordant runs. **Bump `--iters`** — with a clean
  effect, 8 runs usually suffices; with a small effect, you need more.
- Discordant-pair-only testing ignores the tasks both sides pass or fail —
  those carry no signal, and including them would inflate significance.

## Requirements

Both workspaces must have the **same val task set** (compare validates this
and refuses to run otherwise). The bundled demo bench is deterministic
(seed 42), so two workspaces created from `wikiskill init` are directly
comparable.
