#!/usr/bin/env python3
"""Workflow chunk runner (GitHub Actions, GITHUB_TOKEN; read-only on every other repository).

Usage: job.py --request requests/<n>.json
Request kinds: {"chunk": n, "probe": true} (§0 route probe), {"chunk": n, "discovery": true} (§1, resumed from
discovery_state.json), {"chunk": n, "candidates": [...]} (§2-§3 rows),
{"chunk": n, "perworker": true} (§4 file reads for results/perworker_search.jsonl), {"chunk": "debug-x", "debug": true,
"repos": [...]} (pipeline check on named repositories, kept in results/debug/, not counted).
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
    if req.get("probe"):
        return subprocess.call([sys.executable, str(HERE / "probe.py"), "workflow"])
    if req.get("discovery"):
        import discover
        return discover.main(["--route", "workflow", "--max-minutes", str(req.get("max_minutes", 320))])
    if req.get("perworker"):
        import perworker
        return perworker.fetch_eval()
    import chunk
    return chunk.run_chunk(req)


if __name__ == "__main__":
    sys.exit(main())
