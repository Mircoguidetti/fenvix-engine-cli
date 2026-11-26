#!/usr/bin/env python3
"""Per-hour search 429s, search requests, nodes and queries done per family, from the checkpoint history of this
branch (git log of results/discovery_state_<family>.json and prepass_code.json). Session tool, no network.

The 429 and request counters in a state file are per process (they restart with each run and each request), so
the per-checkpoint increase is taken within a process and a drop starts a new process. Hours are UTC.
Usage: ratelog.py [--ref origin/claude/agent-determinism-count]   (writes results/ratelog.json)
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REL = "harness/agent_determinism_count/results"


def git(*a) -> str:
    return subprocess.run(["git", *a], capture_output=True, text=True, cwd=HERE).stdout


def history(ref: str, f: str) -> list[tuple[str, str, dict]]:
    out = []
    for ln in git("log", "--reverse", "--format=%H %cI %s", ref, "--", f":(top){REL}/{f}").splitlines():
        h, t, subj = ln.split(" ", 2)
        try:
            d = json.loads(git("show", f"{h}:{REL}/{f}") or "null")
        except json.JSONDecodeError:
            continue
        if d:
            out.append((t, subj, d))
    return out


def series(ref: str, family: str) -> dict:
    hours = collections.defaultdict(lambda: {"429": 0, "search_requests": 0, "nodes": 0, "queries_done": 0,
                                             "checkpoints": 0})
    prev = None
    for t, subj, st in history(ref, f"discovery_state_{family}.json"):
        q = st.get("queries") or {}
        cur = {"429": (st.get("search_stats") or {}).get("429") or 0,
               "req": sum((st.get("search_requests") or {}).values()),
               "nodes": sum(v.get("nodes", 0) for v in q.values()),
               "done": sum(1 for v in q.values() if v.get("done"))}
        h = hours[t[:13] + ":00Z"]
        h["checkpoints"] += 1
        if prev:
            new_proc = cur["req"] < prev["req"] or cur["429"] < prev["429"]
            h["429"] += cur["429"] if new_proc else cur["429"] - prev["429"]
            h["search_requests"] += cur["req"] if new_proc else cur["req"] - prev["req"]
            h["nodes"] += max(0, cur["nodes"] - prev["nodes"])
            h["queries_done"] += max(0, cur["done"] - prev["done"])
        prev = cur
    return dict(sorted(hours.items()))


def prepass_series(ref: str) -> dict:
    """S1 pre-pass answers per hour (each answer carries its time and the process's 429 count)."""
    hours = collections.defaultdict(lambda: {"prepass_answers": 0, "429_max": 0})
    hist = history(ref, "prepass_code.json")
    if hist:
        for v in hist[-1][2].values():
            h = hours[(v.get("at") or "")[:13] + ":00Z"]
            h["prepass_answers"] += 1
            h["429_max"] = max(h["429_max"], v.get("search_429") or 0)
    return dict(sorted(hours.items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="origin/claude/agent-determinism-count")
    a = ap.parse_args(argv)
    out = {"note": __doc__.split("\n\n")[1].replace("\n", " "), "ref": git("rev-parse", "--short", a.ref).strip(),
           "text": series(a.ref, "text"), "code": series(a.ref, "code"), "code_prepass": prepass_series(a.ref)}
    (HERE / "results" / "ratelog.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    for fam in ("text", "code", "code_prepass"):
        print(fam)
        for h, v in out[fam].items():
            print(" ", h, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
