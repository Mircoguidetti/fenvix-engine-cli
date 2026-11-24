#!/usr/bin/env python3
"""Work-session driver for one reading chunk (§5 execution).

Usage: driver.py <n>
  1. writes requests/<n>.json (next 150 unread candidates in §1 order), commits, pushes (starts the workflow);
  2. waits until the workflow commits results, pulls;
  3. runs the §4 code searches for new rows with median >= 10.0; if any file must be read, pushes
     requests/<n>-pw.json ({"perworker": true}) and waits again;
  4. prints status.py (counts, U, DROP check).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BR = "claude/db-serial-count"
TRAILER = ("\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
           "Claude-Session: https://claude.ai/code/session_01YAF6DiUQF2cbSxKe6sfT9m")


def sh(*a, check=True):
    print("$", " ".join(a), flush=True)
    r = subprocess.run(a, cwd=ROOT, text=True, capture_output=True)
    if r.stdout.strip():
        print(r.stdout.strip()[-2000:], flush=True)
    if r.stderr.strip():
        print(r.stderr.strip()[-2000:], file=sys.stderr, flush=True)
    if check and r.returncode:
        raise SystemExit(f"failed: {a}")
    return r


def head():
    sh("git", "fetch", "-q", "origin", BR)
    return subprocess.run(["git", "rev-parse", f"origin/{BR}"], cwd=ROOT, text=True, capture_output=True).stdout.strip()


def push(paths: list[str], msg: str) -> str:
    for i in range(4):
        sh("git", "add", *paths)
        sh("git", "commit", "-q", "-m", msg + TRAILER, check=False)
        r = sh("git", "push", "-q", "origin", BR, check=False)
        if r.returncode == 0:
            return head()
        sh("git", "pull", "-q", "--no-rebase", "--no-edit", "origin", BR)
        time.sleep(5 * (i + 1))
    raise SystemExit("push failed")


def wait_results(after: str, limit_s: float = 6.5 * 3600):
    t0 = time.time()
    while time.time() - t0 < limit_s:
        h = head()
        log = subprocess.run(["git", "log", "--format=%s", f"{after}..origin/{BR}"], cwd=ROOT, text=True,
                             capture_output=True).stdout
        if "results (run" in log:
            sh("git", "pull", "-q", "--no-rebase", "--no-edit", "origin", BR)
            return h
        time.sleep(30)
    raise SystemExit("timed out waiting for results")


def main() -> int:
    n = sys.argv[1]
    sh(sys.executable, str(HERE / "status.py"), "--next", n)
    after = push([f"harness/db_serial_count/requests/{n}.json"], f"db-serial-count: request {n} (chunk {n})")
    wait_results(after)
    before = len((HERE / "results" / "perworker_search.jsonl").read_text().splitlines()) \
        if (HERE / "results" / "perworker_search.jsonl").exists() else 0
    sh(sys.executable, str(HERE / "perworker.py"), "search")
    lines = (HERE / "results" / "perworker_search.jsonl").read_text().splitlines() \
        if (HERE / "results" / "perworker_search.jsonl").exists() else []
    new = [json.loads(x) for x in lines[before:]]
    if new:
        req = HERE / "requests" / f"{n}-pw.json"
        req.write_text(json.dumps({"chunk": f"{n}-pw", "perworker": True}) + "\n")
        after = push(["harness/db_serial_count/requests", "harness/db_serial_count/results/perworker_search.jsonl"],
                     f"db-serial-count: §4 searches after chunk {n}; request {n}-pw (file reads)")
        if any(x["fetch"] for x in new):
            wait_results(after)
    sh(sys.executable, str(HERE / "status.py"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
