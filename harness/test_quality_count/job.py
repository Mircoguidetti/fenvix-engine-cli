#!/usr/bin/env python3
"""Workflow runner (GitHub Actions, GITHUB_TOKEN; GET only, read-only on every other repository).

Usage: job.py --request requests/<n>.json
Request kinds: {"chunk": n, "probe": true} (§0 probes from the workflow route), {"chunk": n, "candidates": [...]}
(§2-§4.3 rows), {"chunk": "debug-x", "debug": true, "repos": [...]} (pipeline check on repositories named in the
tests; results/debug/, not counted), {"chunk": n, "issues": true, "repos": [...]} (§4.3 on the workflow route).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    a = ap.parse_args()
    req = json.loads(Path(a.request).read_text())
    if req.get("probe"):
        import probe
        return probe.main(["workflow"])
    if req.get("issues"):
        import issues
        return issues.main(["--route", "workflow", "--chunk", str(req["chunk"])] +
                           sum((["--repo", r] for r in req.get("repos") or []), []))
    import chunk
    return chunk.run_chunk(req)


if __name__ == "__main__":
    sys.exit(main())
