#!/usr/bin/env python3
"""Workflow entry point (GitHub Actions, GITHUB_TOKEN, GET only).

Usage: job.py --request requests/<n>.json
A request that finishes writes results/requests_done/<name>; the workflow runs every request file without one, so a
run cancelled while pending (one pending run per concurrency group) or stopped at its deadline is picked up by the
next push.
Request kinds: {"chunk": "probe", "probe": true} (§0.2 workflow route probe), {"chunk": n, "candidates": [...]} and
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    a = ap.parse_args()
    req = json.loads(Path(a.request).read_text())
    import chunk
    name = Path(a.request).name
    if req.get("probe"):
        rc = subprocess.call([sys.executable, str(HERE / "probe.py"), "workflow"])
        if rc == 0:
            chunk.mark_done(name, {"probe": True, "at": chunk.now()})
        return rc
    return chunk.run_chunk(req, name)


if __name__ == "__main__":
    sys.exit(main())
