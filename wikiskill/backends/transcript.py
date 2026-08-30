"""Transcript normalization for the Raw Layer.

Every backend's export_session() must write a NORMALIZED JSONL whose first
line carries ``tool_call_count`` and ``message_count`` — the gating layer's
launch-failure check reads exactly those fields (see gating._session_had_no_tool_calls).
Backends whose native transcripts already match (Hermes) pass through.
"""

from __future__ import annotations

import json
import shutil


def tool_call_count(path: str) -> int:
    """Read tool_call_count from a normalized transcript's first line."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            first = json.loads(f.readline())
    except (OSError, ValueError):
        return 0
    return int(first.get("tool_call_count") or 0)


def normalize_hermes(src: str, dest: str) -> str:
    """Hermes exports already carry tool_call_count on the first line."""
    shutil.copy2(src, dest)
    return dest


def normalize_claude_stream(src: str, dest: str) -> str:
    """Convert a `claude -p --output-format stream-json` transcript into the
    normalized shape: header object + one JSON object per raw event line.

    Counts tool calls from assistant messages' ``content[].type == tool_use``
    blocks (the stream-json schema for Claude Code v2.x).
    """
    tool_calls, messages = 0, 0
    kept = []
    with open(src, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue  # partial/corrupt stream line — keep going
            if not isinstance(ev, dict):
                continue  # tolerate non-object JSON events
            if ev.get("type") == "assistant":
                messages += 1
                msg = ev.get("message")
                for block in (msg.get("content") if isinstance(msg, dict) else []) or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_calls += 1
            elif ev.get("type") == "user":
                messages += 1
            elif ev.get("type") == "result":
                pass  # header carries result metadata below
            kept.append(ev)
    header = {
        "backend": "claude",
        "tool_call_count": tool_calls,
        "message_count": messages,
        "session_id": next((e.get("session_id") for e in kept
                            if e.get("type") == "result" and e.get("session_id")), None),
    }
    with open(dest, "w", encoding="utf-8") as out:
        out.write(json.dumps(header) + "\n")
        for ev in kept:
            out.write(json.dumps(ev) + "\n")
    return dest


def normalize(backend: str, src: str, dest: str) -> str:
    if backend == "claude":
        return normalize_claude_stream(src, dest)
    return normalize_hermes(src, dest)
