"""Prompts for the three agent roles.

The Wiki Maintainer and Skill Proposer system prompts are adapted from the
paper's Appendix E (extracted verbatim from the arXiv HTML). The inference
prompt follows the paper's per-benchmark "You are an agent solving X" style.
"""

from __future__ import annotations

import json
import os

INFERENCE_PREFIX = (
    "You are an agent completing a task in a sandbox directory. "
    "Follow the instructions precisely. Use your tools to inspect files and "
    "verify your work before finishing. Write every deliverable file exactly "
    "as specified. Your final message should briefly state what you did.\n\n"
)


def inference_prompt(task: dict, sandbox: str | None = None) -> str:
    anchor = ""
    if sandbox:
        anchor = (
            f"\n\nWORKING DIRECTORY: {sandbox}\n"
            "Read input files from and write ALL deliverables into the WORKING "
            "DIRECTORY above. Use absolute paths (prefix every path with it). "
            "Do not guess the directory — it is given. Do NOT explore, read, or "
            "modify anything outside the WORKING DIRECTORY (ignore git state and "
            "files above it). Verify the final file exists at its absolute path "
            "before finishing.\n"
        )
    return INFERENCE_PREFIX + f"TASK: {task['title']}\n\n{task['prompt']}" + anchor


def _trace_manifest(traces: list[dict]) -> str:
    lines = []
    for t in traces:
        meta = t["meta"]
        lines.append(
            f"- {meta['task_id']} (split={t['split']}, iter={t['it']}, "
            f"score={meta.get('score')}): {meta.get('title', '')}\n"
            f"  trace: {t['path']}"
        )
    return "\n".join(lines)


def maintainer_prompt(ws: str, it: int, sampled_traces: list[dict]) -> str:
    wiki = os.path.join(ws, "wiki")
    manifest = "\n".join(f"- {t['path']}" for t in sampled_traces)
    return f"""You are the Wiki Maintainer in a WikiSkill evolution loop (iteration {it}).

Load the `wikiskill-maintainer` skill and follow it exactly.

WORKSPACE: {ws}
- Wiki (read + edit): {wiki}/  (index.md, log.md, skill-impact.md, patterns/)
- Raw traces to analyze this iteration (read only, immutable):

{manifest}

Procedure:
1. Read the trace JSONL files above (the agent's full step-by-step execution:
   reasoning, tool calls, outputs, final answer). Focus on the low-scoring
   traces for root-cause analysis; also read passing traces to preserve
   effective behavior.
   IMPORTANT — traces can be very long. Do NOT read every line of every trace.
   Use search_files to locate failures/errors, read the last few messages of a
   failed run, and skip tool outputs you don't need. Reading selectively leaves
   budget for writing.
2. Perform deep trace analysis: compare successful vs failed tasks, identify
   ACTION patterns (not just error messages), check whether any active skill
   guidance was helpful.
3. Update the wiki incrementally — WRITE EARLY, edit later. Create/update
   pattern pages under wiki/patterns/, rewrite wiki/index.md (complete content,
   one line per pattern: [name](wiki/patterns/name.md): PROBLEM + ROOT CAUSE +
   FIX in one or two sentences), append your findings to wiki/log.md.
   Finish writing before you run out of turns.
4. Keep pattern pages 10-30 lines, concise, no duplicates.
"""


def proposer_prompt(ws: str, it: int, train_results: list[dict]) -> str:
    wiki = os.path.join(ws, "wiki")
    rows = []
    for r in sorted(train_results, key=lambda x: (x.get("score") or 0, x["id"])):
        rows.append(f"- {r['id']} [{r['split']}] score={r.get('score')}: {r['title']}")
    table = "\n".join(rows)
    return f"""You are the Skill Proposer in a WikiSkill evolution loop (iteration {it}).

Load the `wikiskill-proposer` skill and follow it exactly.

WORKSPACE: {ws}
- Wiki: {wiki}/ (index.md, skill-impact.md, patterns/, log.md)
- Raw traces: {os.path.join(ws, 'raw', 'traces', f'iter-{it:02d}')}/ (full execution logs,
  read any trace you need via read_file)
- Active skills: {os.path.join(ws, 'skills', 'active')}/

Training rollout summary this iteration:
{table}

Rules (from the paper's Appendix E.3):
1. Read wiki/index.md FIRST, then wiki/skill-impact.md (contains full content of
   rejected proposals — DO NOT repeat rejected approaches).
2. Read relevant pattern pages, then read at least 4 execution traces for failed
   tasks to diagnose root causes. Traces can be long — read selectively
   (search_files for errors, read tails); do not read every line.
3. Decide: create (new skill), patch (existing skill), or no_action.
4. Write your proposal JSON to: {os.path.join(ws, 'runs', 'proposals', f'iter-{it:02d}.json')}
   Create/patch skills under {os.path.join(ws, 'skills', 'active')} ONLY via the proposal file;
   the harness applies it. The harness applies the proposal, validates it on the
   validation split, and records the outcome in skill-impact.md.
   WRITE EARLY — leave enough turns to finish the file before the cap.

Proposal JSON schema (write the file with write_file):
{{"action": "create", "name": "snake_case", "skill_md": "full SKILL.md with YAML frontmatter + When to Apply + When NOT to Apply + Instructions", "purpose_md": "Origin + Patterns Addressed + Evolution History"}}
{{"action": "patch", "name": "existing-skill", "edits": [{{"op": "append"|"replace"|"insert_after", "target": "exact text", "content": "..."}}]}}
{{"action": "no_action"}}
Prefer patching over creating when a skill is partially correct. Keep skills
concise and actionable. If no change is warranted, write {{"action": "no_action"}}.
"""


def gate_outcome_entry(ws: str, it: int, proposal: dict, r_val: float | None,
                       accepted: bool, diff: str, baseline_r: float | None) -> str:
    prop_path = os.path.join(ws, "runs", "proposals", f"iter-{it:02d}.json")
    head = (f"### iter-{it:02d} — {'ACCEPTED' if accepted else 'REJECTED'} "
            f"(R_val={r_val}, R_best={'—' if baseline_r is None else baseline_r})")
    if proposal.get("action") == "no_action":
        return f"{head}\n\nProposal: no_action (no validation run performed).\n"
    name = proposal.get("name", "?")
    action = proposal.get("action", "?")
    body = [head, "", f"Proposal: {action} `{name}`",
            f"Proposal file: `{prop_path}` (re-run collisions possible — full content embedded below)"]
    if diff.strip():
        body += ["", "```diff", diff.strip(), "```"]
    body += ["", "Full proposal content (paper: rejected proposals must remain visible to future proposers):",
             "", "```json", json.dumps(proposal, indent=2), "```"]
    if accepted:
        body += ["", f"Validation: {r_val} > R_best → accepted, skills committed."]
    else:
        body += ["", f"Validation: {r_val} ≤ R_best → skills rolled back; wiki retained."]
    return "\n".join(body)
