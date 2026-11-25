#!/usr/bin/env python3
"""Workflow-route job (inside GitHub Actions, GITHUB_TOKEN via GH_TOKEN; read-only on other repositories).

Usage: wf_job.py --request requests/<n>.json

Request file: {"cmd": "probe"} | {"cmd": "list"} | {"cmd": "material", "start": int, "count": int}.
probe → probe/workflow-*.json; list → data/listing/*.jsonl.gz and data/listing_meta.json (the frame and the reading
order are built by the session from the committed listing); material → data/material/m<start>.jsonl.gz for reading
positions [start, start+count) of the committed data/order.json. Requests are logged to $ASC_REQLOG.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    req = json.loads(Path(ap.parse_args().request).read_text())
    if req["cmd"] == "probe":
        fetch.probe(route="workflow")
    elif req["cmd"] == "list":
        fetch.list_all(build=False)
    elif req["cmd"] == "material":
        fetch.material(int(req["start"]), int(req["count"]))
    else:
        sys.exit(f"unknown cmd {req['cmd']!r}")


if __name__ == "__main__":
    main()
