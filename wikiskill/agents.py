"""Agent runner: executes Hermes agent turns in an isolated profile.

Faithful gating requires the inference agent to see *exactly* the active skill
set (paper: S_k). We achieve this with a dedicated HERMES_HOME per evolution
workspace whose skills/ dir contains only symlinks to the current active skills
(plus the framework skills when running maintainer/proposer turns). The
isolated profile has fresh sessions/ and memories/, so inference runs are
uncontaminated by the user's real profile memory, and every run's full
trajectory lands in a session JSONL we can copy into the Raw Layer.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time

PROFILE_DIR = ".hermes-home"
FRAMEWORK_SKILLS = ("wikiskill-maintainer", "wikiskill-proposer")
DEFAULT_TOOLSETS = "terminal,file,code_execution"
MAINTAINER_TOOLSETS = "file,terminal"
PROPOSER_TOOLSETS = "file,terminal"


def real_home() -> str:
    return os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")


def profile_dir(ws: str) -> str:
    return os.path.join(ws, PROFILE_DIR)


def hermes_env(ws: str) -> dict:
    env = dict(os.environ)
    env["HERMES_HOME"] = profile_dir(ws)
    return env


def bootstrap_profile(ws: str, real: str | None = None) -> str:
    """Create the isolated profile: copy secrets/config, empty sessions+memory,
    stop bundled-skill seeding so the skill set is exactly what we symlink."""
    real = real or real_home()
    prof = profile_dir(ws)
    for d in ("sessions", "skills", "memories", "logs"):
        os.makedirs(os.path.join(prof, d), exist_ok=True)
    for f in ("config.yaml", ".env", "auth.json"):
        src = os.path.join(real, f)
        dst = os.path.join(prof, f)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    # Isolated profile must not auto-seed the bundled skill catalog.
    subprocess.run(["hermes", "skills", "opt-out"],
                   env=hermes_env(ws), capture_output=True, text=True, check=False)
    return prof


def set_active_skills(ws: str, include_framework: bool = False) -> None:
    """Rebuild the isolated profile's skills/ as symlinks of the active set."""
    prof_skills = os.path.join(profile_dir(ws), "skills")
    os.makedirs(prof_skills, exist_ok=True)
    for name in os.listdir(prof_skills):
        p = os.path.join(prof_skills, name)
        if os.path.islink(p):
            os.unlink(p)
        elif os.path.isdir(p):
            shutil.rmtree(p)
    sources = []
    active = os.path.join(ws, "skills", "active")
    if os.path.isdir(active):
        for name in sorted(os.listdir(active)):
            sources.append(os.path.join(active, name))
    if include_framework:
        fw = os.path.join(ws, "skills", "framework")
        if os.path.isdir(fw):
            for name in sorted(os.listdir(fw)):
                sources.append(os.path.join(fw, name))
    for src in sources:
        os.symlink(src, os.path.join(prof_skills, os.path.basename(src)))


def newest_session(ws: str) -> str | None:
    """Deprecated helper — sessions live in state.db now; use export_session()."""
    sess = os.path.join(profile_dir(ws), "sessions")
    files = glob.glob(os.path.join(sess, "*.jsonl"))
    return max(files, key=os.path.getmtime) if files else None


def export_session(ws: str, dest: str, session_id: str | None = None) -> str | None:
    """Export the isolated profile's latest session to `dest` as JSONL.

    Prefer an explicit session_id (parsed from run stdout); otherwise fall back
    to the newest session from `hermes sessions list`.
    """
    env = hermes_env(ws)
    if session_id is None:
        p = subprocess.run(["hermes", "sessions", "list"], env=env,
                           capture_output=True, text=True)
        ids = []
        for line in p.stdout.splitlines():
            s = line.strip()
            if s and not s.startswith("Title") and "─" not in s:
                ids.append(s.split()[-1])
        if not ids:
            return None
        session_id = ids[0]  # list is newest-first
    assert session_id is not None
    q = subprocess.run(["hermes", "sessions", "export", "--format", "jsonl",
                        "--session-id", session_id, dest],
                       env=env, capture_output=True, text=True)
    if q.returncode != 0 or not os.path.exists(dest):
        return None
    return dest


def _session_id_from_stdout(stdout_path: str) -> str | None:
    try:
        with open(stdout_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    import re

    m = re.search(r"session_id[:\s]+([0-9a-zA-Z_]+)", text)
    return m.group(1) if m else None


def run_agent(ws: str, prompt: str, *, tag: str, toolsets: str = DEFAULT_TOOLSETS,
              model: str | None = None, max_turns: int = 15, run_budget: int = 300,
              workdir: str | None = None, include_framework: bool = False,
              dry_run: bool = False) -> dict:
    """Run one Hermes agent turn in the isolated profile. Returns a result dict
    with cmd/exit_code/duration/stdout_path/session_file. With dry_run=True it
    returns the constructed command without executing anything."""
    set_active_skills(ws, include_framework=include_framework)
    run_dir = os.path.join(ws, "runs", tag)
    os.makedirs(run_dir, exist_ok=True)
    qfile = os.path.join(run_dir, "query.txt")
    with open(qfile, "w", encoding="utf-8") as f:
        f.write(prompt)

    cmd = ["hermes", "chat", "--query-file", qfile, "-Q", "--oneshot",
           "-t", toolsets, "--max-turns", str(max_turns),
           "--run-budget", str(run_budget)]
    if model:
        cmd += ["-m", model]
    if workdir:
        cmd += ["--in", workdir]

    if dry_run:
        return {"cmd": cmd, "run_dir": run_dir, "qfile": qfile, "dry_run": True}

    t0 = time.time()
    out_path = os.path.join(run_dir, "stdout.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        p = subprocess.run(cmd, env=hermes_env(ws), stdout=f,
                           stderr=subprocess.STDOUT, text=True)
    dur = round(time.time() - t0, 1)
    session_file = export_session(ws, os.path.join(run_dir, "session.jsonl"),
                                  _session_id_from_stdout(out_path))
    return {"cmd": cmd, "exit_code": p.returncode, "duration_s": dur,
            "stdout_path": out_path, "session_file": session_file}
