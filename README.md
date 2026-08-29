# WikiSkill for Hermes

A faithful implementation of **arXiv:2608.27454 — WikiSkill: Compiling Agent
Experience into Persistent Knowledge for Skill Evolution** (Google Research),
built natively on Hermes Agent.

WikiSkill co-evolves agent skills with a **persistent wiki**: raw execution
traces are consolidated into structured knowledge, which drives skill
proposals that are gated on a validation split — accepted skills are kept,
rejected ones are rolled back, and the wiki always persists.

## Paper → Hermes mapping

| Paper component | Hermes equivalent |
|---|---|
| Inference Agent | `hermes chat --query-file <p> -Q --oneshot` in an isolated profile |
| Raw Layer (`raw/`) | copied session JSONLs under `raw/traces/iter-NN/` |
| Wiki Layer (`wiki/`) | `wiki/{index.md, log.md, skill-impact.md, patterns/}` (git-tracked) |
| Skill Layer (`skills/`) | git-managed `skills/active/` (SKILL.md dirs) |
| Wiki Maintainer | agent turn with the `wikiskill-maintainer` skill (paper App. E.2) |
| Skill Proposer (ReAct) | agent turn with the `wikiskill-proposer` skill (paper App. E.3) |
| Gating & rollback | strict `R_val > R_best`; `git reset --hard` on reject; wiki never rolled back |
| Isolated skill sets | dedicated `HERMES_HOME` per workspace; `skills/` is symlinked per phase |

## Quickstart

```bash
pip install -e .            # installs the `wikiskill` CLI
wikiskill init demo         # workspace + 22-task auto-graded demo bench (15 train / 7 val)
wikiskill status
wikiskill evolve --iters 3  # full Algorithm 1 loop (real Hermes agent runs)
```

Each evolution iteration costs ~(train tasks + val tasks) inference runs plus
one maintainer and one proposer turn. With small task sets and a cheap model
(e.g. deepseek) a 3-iteration demo runs in well under an hour.

## Workspace layout

```
workspaces/<domain>/
├── tasks.json                 # task registry (prompt, sandbox files, grader)
├── bench/tasks/<id>/          # per-task sandboxes (agent workdirs)
├── raw/traces/iter-NN/        # immutable execution traces (Raw Layer)
│   ├── train/<id>.jsonl       #   full session transcript
│   └── train/<id>.meta.json   #   score + run metadata
├── wiki/                      # persistent knowledge base (Wiki Layer)
│   ├── index.md  log.md  skill-impact.md  patterns/
├── skills/
│   ├── active/                # the evolving skill set (git repo; S0 = ∅)
│   └── framework/             # maintainer/proposer skills (never gated)
├── runs/                      # queries, stdout, proposals, state.json
└── .hermes-home/              # isolated profile (HERMES_HOME per workspace)
```

## Algorithm (paper Algorithm 1)

```
baseline: R_best ← R(val, S0 = ∅)
for k = 1..K:
    if R_best == 1.0: break
    train rollouts with S_{k-1}                    → raw/traces/
    sample ≤5 failing + ≤3 passing traces (stratified)
    wiki maintenance: consolidate traces into wiki  (never rolled back)
    skill proposal: explore wiki + traces → proposal JSON
    if no_action: log, continue
    apply proposal → S'_k ; gate on validation split
    if R_val > R_best: accept, commit              (S_k ← S'_k, R_best ← R_val)
    else: roll back skills only; wiki retained
    append outcome + full proposal to skill-impact.md
```

## Adding your own task domain

`tasks.json` is just a list of `{id, split, prompt, sandbox, grader}`. Graders:
`exact`, `contains`, `json_field`, `code_stdout` (see `wikiskill/scoring.py`).
Your real recurring workflows can be plugged in as a task set; for honest
gating, prefer auto-gradable tasks (file/answer-based deliverables).
