#!/usr/bin/env python3
"""Workflow entry point (GitHub Actions, GITHUB_TOKEN, GET only).

Usage: job.py --request requests/<n>.json
A request that finishes writes results/requests_done/<name>; the workflow runs every request file without one, so a
run cancelled while pending (one pending run per concurrency group) or stopped at its deadline is picked up by the
next push.
Request kinds: {"chunk": "probe", "probe": true} (§0.2 workflow route probe), {"probe_text": true} (§0.2c/d: the
issues/commits probes and the registry pages, workflow route), {"discovery": "text"} (§1 S2/S3 pre-pass and bisection
in the workflow, resumable; one request per job run), {"chunk": n, "candidates": [...]} and
{"chunk": "<n>c", "comments": n} and {"chunk": "debug-x", "debug": true, "repos": [...]} (chunk.py).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def paused(family: str) -> bool:
    """A coordinator pause (results/pause_<family>.json with ``start`` and no ``end``) stops discovery requests."""
    p = HERE / "results" / f"pause_{family}.json"
    if not p.exists():
        return False
    d = json.loads(p.read_text())
    return bool(d.get("start")) and not d.get("end")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    a = ap.parse_args()
    req = json.loads(Path(a.request).read_text())
    import chunk
    name = Path(a.request).name
    if req.get("noop"):  # a push that only starts a run (pending requests without a marker run before it)
        chunk.mark_done(name, {"noop": True, "at": chunk.now()})
        return 0
    if req.get("probe_text"):
        rc = subprocess.call([sys.executable, str(HERE / "probe.py"), "workflow-text"])
        if rc == 0:
            chunk.mark_done(name, {"probe_text": True, "at": chunk.now()})
        return rc
    if req.get("discovery"):  # {"discovery": "text", "max_minutes": 300}: pre-pass, then bisection (resumable)
        if paused(req["discovery"]):
            print(f"discovery {req['discovery']} paused (results/pause_{req['discovery']}.json): request left pending")
            return 0
        import discover
        import parts
        fam = req["discovery"]
        if parts.restore(fam) != 0:  # state of an earlier run kept in its artifact (results/discovery/restore_*.json)
            print("restore failed: discovery not run; the request stays pending")
            return 1
        import ghapi
        try:
            rc = discover.prepass(fam, "workflow")
            if rc == 0:
                rc = discover.run(fam, "workflow", float(req.get("max_minutes", 300)), None)
        except ghapi.DeadlineReached as e:  # state is saved after every node: the request stays pending and resumes
            print(f"job deadline: {e}; discovery {fam} resumes in the next run")
            return 0
        chunk.mark_done(name, {"discovery": fam, "rc": rc, "at": chunk.now()})  # the next request resumes
        return 0
    if req.get("probe"):
        rc = subprocess.call([sys.executable, str(HERE / "probe.py"), "workflow"])
        if rc == 0:
            chunk.mark_done(name, {"probe": True, "at": chunk.now()})
        return rc
    return chunk.run_chunk(req, name)


if __name__ == "__main__":
    sys.exit(main())
