#!/usr/bin/env python3
"""C5.3 step 2.11: the hand-check sample of qualifying job ids, and their excerpts for the session to read.

Usage: handcheck.py [--seed 4]   prints, for each sampled job, its excerpt path, detected runner and summary line.
The session writes handcheck.jsonl itself: {"job_id", "seen_runner", "agrees", "note"} per sampled job.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from collect import read_jsonl  # noqa: E402


def sample(rows: list[dict], seed: int, k: int = 10) -> list[int]:
    ids = sorted(r["job_id"] for r in rows if r["verdict"] == "qualifying")
    return ids if len(ids) <= k else random.Random(seed).sample(ids, k)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=4)
    a = ap.parse_args(argv[1:])
    rows = read_jsonl(HERE / "results" / "prs.jsonl.gz")
    by_job = {r["job_id"]: r for r in rows if r["verdict"] == "qualifying"}
    for j in sample(rows, a.seed):
        r = by_job[j]
        print(j, r["runner"], r["url"], HERE / "results" / "excerpts" / f"{j}.txt.gz")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
