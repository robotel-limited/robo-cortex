#!/usr/bin/env python3
"""HAIKU-0 benchmark runner: baseline vs. assisted, Haiku subject sessions.

Usage:
    python3 run.py --task a1 --arm baseline --run 1          # one session
    python3 run.py --battery                                  # full battery
    python3 run.py --battery --runs 5                         # 5 runs/arm/task

Each session:
  1. clones the repo into bench-work/runs/<task>-<arm>-<n>/clone
  2. applies the bug patch and commits it (clean working tree for the agent)
  3. invokes `claude -p` with the task prompt, subject model, JSON output
  4. re-runs the acceptance tests itself (never trusts the agent's claim)
  5. stores result.json (harness usage + acceptance verdict + git diff)

The subject's pytest runs are kept honest via PYTHONPATH=<clone>/src in the
session environment, so tests exercise the clone's (buggy/fixed) code, not
the machine-wide installed robo-cortex.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
WORK = REPO / "bench-work" / "runs"
TASKS = json.loads((HERE / "tasks" / "tasks.json").read_text())
PACKS_DIR = HERE / "tasks" / "packs"
SUBJECT_MODEL = "claude-haiku-4-5"
ACCEPT_DESELECT = "tests/test_smoke.py::test_version_is_set"

PROMPT_TEMPLATE = """You are working in the robo-cortex repository: a git-aware, \
evidence-based memory store for AI coding agents (pure Python, stdlib + SQLite, no \
external deps). Source in src/robo_cortex/, tests in tests/, design docs in \
ARCHITECTURE.md.

{bug_report}

The test suite currently has failing tests related to this bug. Reproduce with:

    python3 -m pytest tests/ -q --deselect {deselect}

Find the root cause and fix it in the source code. Do NOT modify anything under \
tests/. You are done when the full command above passes with 0 failures.
{pack_section}"""

PACK_SECTION = """
Prior institutional knowledge retrieved from this project's memory store \
(robo-cortex retrieve_context output) — it may or may not be relevant:

```json
{pack}
```
"""


def sh(cmd, cwd=None, env=None, timeout=None):
    return subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                          capture_output=True, text=True)


def build_clone(task_id: str, run_dir: Path) -> Path:
    clone = run_dir / "clone"
    if clone.exists():
        sh(["rm", "-rf", str(clone)])
    r = sh(["git", "clone", "-q", str(REPO), str(clone)])
    assert r.returncode == 0, r.stderr
    patch = HERE / "tasks" / TASKS[task_id]["patch"]
    r = sh(["git", "apply", str(patch)], cwd=clone)
    assert r.returncode == 0, f"patch failed: {r.stderr}"
    sh(["git", "commit", "-aqm", "wip"], cwd=clone)
    # the benchmark scripts and bug patches must not be visible to the subject
    sh(["rm", "-rf", str(clone / "scripts" / "benchmark"), str(clone / "bench-work")])
    sh(["git", "commit", "-aqm", "wip2"], cwd=clone)
    return clone


def acceptance(clone: Path) -> dict:
    env = dict(os.environ, PYTHONPATH=str(clone / "src"))
    r = sh(["python3", "-m", "pytest", "tests/", "-q", "--deselect", ACCEPT_DESELECT],
           cwd=clone, env=env, timeout=600)
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    return {"returncode": r.returncode, "summary": tail[0]}


def run_session(task_id: str, arm: str, run_idx: int) -> dict:
    task = TASKS[task_id]
    run_dir = WORK / f"{task_id}-{arm}-{run_idx}"
    run_dir.mkdir(parents=True, exist_ok=True)
    clone = build_clone(task_id, run_dir)

    pack_section = ""
    if arm == "assisted":
        pack = (PACKS_DIR / f"{task_id}-pack.json").read_text().strip()
        pack_section = PACK_SECTION.format(pack=pack)
    prompt = PROMPT_TEMPLATE.format(bug_report=task["bug_report"],
                                    deselect=ACCEPT_DESELECT,
                                    pack_section=pack_section)
    (run_dir / "prompt.txt").write_text(prompt)

    env = dict(os.environ, PYTHONPATH=str(clone / "src"))
    t0 = time.monotonic()
    r = sh(["claude", "-p", prompt, "--model", SUBJECT_MODEL,
            "--output-format", "json", "--dangerously-skip-permissions"],
           cwd=clone, env=env, timeout=1800)
    wall = time.monotonic() - t0

    (run_dir / "claude-stdout.json").write_text(r.stdout or "")
    (run_dir / "claude-stderr.txt").write_text(r.stderr or "")
    try:
        cj = json.loads(r.stdout)
    except (json.JSONDecodeError, TypeError):
        cj = {"parse_error": True}

    accept = acceptance(clone)
    diff = sh(["git", "diff"], cwd=clone).stdout

    result = {
        "task": task_id, "arm": arm, "run": run_idx,
        "wall_clock_s": round(wall, 1),
        "acceptance_pass": accept["returncode"] == 0,
        "acceptance_summary": accept["summary"],
        "claude": {k: cj.get(k) for k in
                   ("duration_ms", "duration_api_ms", "num_turns",
                    "total_cost_usd", "usage", "modelUsage", "is_error",
                    "subtype", "terminal_reason")},
        "diff_stat": sh(["git", "diff", "--stat"], cwd=clone).stdout,
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2))
    (run_dir / "fix.diff").write_text(diff)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task"), ap.add_argument("--arm")
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--battery", action="store_true")
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args()

    if a.battery:
        # interleave arms within each task: b1 a1 b2 a2 ... per plan §4
        for task_id in TASKS:
            for i in range(1, a.runs + 1):
                for arm in ("baseline", "assisted"):
                    marker = WORK / f"{task_id}-{arm}-{i}" / "result.json"
                    if marker.exists():
                        print(f"skip {task_id}-{arm}-{i} (done)", flush=True)
                        continue
                    res = run_session(task_id, arm, i)
                    print(f"{task_id}-{arm}-{i}: pass={res['acceptance_pass']} "
                          f"wall={res['wall_clock_s']}s "
                          f"turns={res['claude'].get('num_turns')}", flush=True)
    else:
        res = run_session(a.task, a.arm, a.run)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
