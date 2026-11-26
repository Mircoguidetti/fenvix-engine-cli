#!/usr/bin/env python3
"""Work-session driver for Part 1 reading (§1.4): pushes requests/<n>.json ({"kind": "pairs"}), waits for the
workflow to commit results, repeats until 200 complete pairs, the frame end, or the reading deadline.

Usage: driver.py --start-n N --deadline <ISO UTC>
Before the first request it gzips discovery/candidates.jsonl -> discovery/candidates.jsonl.gz and commits it.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
BR = "claude/market-direction-check"
TRAILER = ("\n\nClaude-Session: https://claude.ai/code/session_01YAF6DkSUDXwQikH19ZCnEu")


def sh(*a, check=True):
    r = subprocess.run(a, cwd=ROOT, text=True, capture_output=True)
    print("$", " ".join(a), "->", r.returncode, (r.stdout + r.stderr).strip()[-400:], flush=True)
    if check and r.returncode:
        raise SystemExit(f"failed: {a}")
    return r


def push(paths, msg):
    for i in range(5):
        sh("git", "add", *paths)
        sh("git", "commit", "-q", "-m", msg + TRAILER, check=False)
        sh("git", "pull", "-q", "--no-rebase", "--no-edit", "origin", BR, check=False)
        if sh("git", "push", "-q", "origin", BR, check=False).returncode == 0:
            return
        time.sleep(5 * (i + 1))
    raise SystemExit("push failed")


def chunks() -> list[dict]:
    p = HERE / "results" / "chunks.jsonl"
    return [json.loads(x) for x in open(p)] if p.exists() else []


def wait_for(n: int, limit_s: float = 6 * 3600) -> dict:
    t0 = time.time()
    while time.time() - t0 < limit_s:
        sh("git", "pull", "-q", "--no-rebase", "--no-edit", "origin", BR, check=False)
        for c in chunks():
            if c.get("n") == n:
                return c
        time.sleep(60)
    raise SystemExit(f"timed out waiting for chunk {n}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-n", type=int, required=True)
    ap.add_argument("--deadline", required=True)
    a = ap.parse_args()
    gz = HERE / "discovery" / "candidates.jsonl.gz"
    if not gz.exists():
        with open(HERE / "discovery" / "candidates.jsonl", "rb") as f, gzip.open(gz, "wb") as g:
            shutil.copyfileobj(f, g)
        push(["harness/market_direction/discovery"], "market-direction: frame (candidates.jsonl.gz) for reading")
    n = a.start_n
    while True:
        req = {"kind": "pairs", "n": n, "max_minutes": 280, "deadline": a.deadline}
        (HERE / "requests" / f"{n}.json").write_text(json.dumps(req) + "\n")
        push([f"harness/market_direction/requests/{n}.json"], f"market-direction: request {n} (pairs)")
        c = wait_for(n)
        print(json.dumps(c), flush=True)
        if c["stopped"] in ("200 pairs", "reading deadline", "frame end"):
            return 0
        n += 1


if __name__ == "__main__":
    sys.exit(main())
