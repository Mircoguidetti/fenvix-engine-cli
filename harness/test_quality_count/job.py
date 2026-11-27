#!/usr/bin/env python3
"""Workflow runner (GitHub Actions, GITHUB_TOKEN; GET only, read-only on every other repository).

Usage: job.py --request requests/<n>.json
Request kinds: {"chunk": n, "probe": true} (§0 probes from the workflow route), {"chunk": n, "candidates": [...]}
(§2-§4.3 rows), {"chunk": "debug-x", "debug": true, "repos": [...]} (pipeline check on repositories named in the
tests; results/debug/, not counted), {"chunk": n, "issues": true, "repos": [...]} (§4.3 on the workflow route),
{"chunk": "ac4", "ac4": true} (AC4 evidence fetch, CHANGES.md 20).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def done(req: dict) -> bool:
    res = HERE / "results"
    if req.get("probe"):
        return (res / "probe_workflow.json").exists()
    if req.get("ac4"):
        return (res / "ac4_wf" / "done.json").exists()
    if req.get("issues"):
        return False  # issues.py skips repositories already searched
    p = res / ("debug" if req.get("debug") else "") / "chunks.jsonl"
    if not p.exists():
        return False
    chunks = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return any(str(c.get("chunk")) == str(req.get("chunk")) and not c.get("stopped") for c in chunks)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    ap.add_argument("--skip-done", action="store_true", help="skip a request whose chunk is already recorded")
    a = ap.parse_args()
    req = json.loads(Path(a.request).read_text())
    if a.skip_done and done(req):
        print(f"request {a.request}: already done, skipped")
        return 0
    if req.get("probe"):
        import probe
        return probe.main(["workflow"])
    if req.get("ac4"):
        import ac4fetch
        return ac4fetch.main(req)
    if req.get("issues"):
        import issues
        return issues.main(["--route", "workflow", "--chunk", str(req["chunk"])] +
                           sum((["--repo", r] for r in req.get("repos") or []), []))
    import chunk
    return chunk.run_chunk(req)


if __name__ == "__main__":
    sys.exit(main())
