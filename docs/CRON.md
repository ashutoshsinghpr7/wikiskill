# Overnight evolution (cron)

Evolution runs are **slow** (a full iteration is ~1–2 hours on a free-tier
small model) and **cheap** (~$0.09/iteration). That's the ideal overnight
workload: the machine works while you sleep, and the morning report tells
you whether the wiki grew and whether any proposal was accepted.

## The built-in job

This repo ships with a hermes cron job, `wikiskill-overnight-evolution`,
which every night at 01:00 (local time):

1. runs `wikiskill evolve nightly --iters 1 --max-turns 8
   --model google/gemini-2.5-flash-lite --provider openrouter` on a
   dedicated `workspaces/nightly/` (its own isolated profile — your real
   Hermes setup is never touched),
2. waits for it,
3. reports: baseline R, wiki growth, proposal, and the gate verdict —
   honestly, including rate-limit or launch failures if they happen.

Manage it from Hermes: `cronjob(action='list')` / `pause` / `run`.

## Setting it up yourself (non-Hermes schedulers)

```bash
# macOS: crontab -e
0 1 * * * cd /path/to/wikiskill-hermes && \
  wikiskill evolve nightly --iters 1 --max-turns 8 \
    --model google/gemini-2.5-flash-lite --provider openrouter \
    >> workspaces/nightly/cron.log 2>&1
```

## What to check in the morning

- `wikiskill status nightly` → baseline / r_best / iteration history
- `workspaces/nightly/wiki/log.md` → per-iteration proposal + verdict
- `workspaces/nightly/wiki/patterns/` → what the maintainer distilled
- the gate verdict: `ACCEPT` means the skill beat the previous best
  (`R_val > R_best`) and is now the workspace's active skill set.

## Guard rails

- The cron prompt refuses to run if an evolve is already in flight
  (concurrent runs would corrupt `runs/state.json`).
- Launch failures (HTTP 400, rate limits) are detected and reported — a
  dead run scores 0.0 on fresh sandboxes, never phantom grades.
