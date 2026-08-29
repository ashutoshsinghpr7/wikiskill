"""Raw Layer: immutable execution traces.

Each trace is a <task_id>.json metadata file plus a <task_id>.jsonl transcript
copy (the isolated profile's session file for that run). The raw layer is
immutable: saving a trace for an existing (iter, split, task) raises unless
overwrite=True.
"""

from __future__ import annotations

import json
import os


def trace_dir(ws: str, it: int, split: str) -> str:
    return os.path.join(ws, "raw", "traces", f"iter-{it:02d}", split)


def meta_path(ws: str, it: int, split: str, tid: str) -> str:
    return os.path.join(trace_dir(ws, it, split), f"{tid}.meta.json")


def transcript_path(ws: str, it: int, split: str, tid: str) -> str:
    return os.path.join(trace_dir(ws, it, split), f"{tid}.jsonl")


def save_trace(ws: str, it: int, split: str, tid: str, meta: dict,
               transcript_src: str | None = None, overwrite: bool = False) -> dict:
    p = meta_path(ws, it, split, tid)
    if os.path.exists(p) and not overwrite:
        raise FileExistsError(f"trace already exists: {p}")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if transcript_src and os.path.exists(transcript_src):
        tp = transcript_path(ws, it, split, tid)
        with open(transcript_src, encoding="utf-8", errors="replace") as src, \
             open(tp, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        meta = {**meta, "transcript": os.path.relpath(tp, ws)}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)
    return meta


def load_trace(ws: str, it: int, split: str, tid: str) -> dict:
    with open(meta_path(ws, it, split, tid), encoding="utf-8") as f:
        return json.load(f)


def list_traces(ws: str, it: int | None = None, split: str | None = None) -> list[dict]:
    """Return [{"it": n, "split": s, "task_id": id, "path": meta, "meta": {...}}]."""
    out = []
    root = os.path.join(ws, "raw", "traces")
    if not os.path.isdir(root):
        return out
    for d in sorted(os.listdir(root)):
        if not d.startswith("iter-"):
            continue
        n = int(d.split("-")[1])
        if it is not None and n != it:
            continue
        for s in sorted(os.listdir(os.path.join(root, d))):
            if split is not None and s != split:
                continue
            for f in sorted(os.listdir(os.path.join(root, d, s))):
                if not f.endswith(".meta.json"):
                    continue
                tid = f[: -len(".meta.json")]
                p = os.path.join(root, d, s, f)
                with open(p, encoding="utf-8") as fh:
                    meta = json.load(fh)
                out.append({"it": n, "split": s, "task_id": tid, "path": p, "meta": meta})
    return out
