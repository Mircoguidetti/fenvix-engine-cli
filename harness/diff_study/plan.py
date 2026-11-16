#!/usr/bin/env python3
"""Reads harness/diff_study/run.json and prints GitHub Actions step outputs."""

import json
from pathlib import Path

cfg = json.loads((Path(__file__).resolve().parent / "run.json").read_text())
mut = []
m = cfg.get("mutants", {})
if m.get("enabled"):
    for r in m["repos"]:
        for s in range(1 if m.get("recheck") else r.get("shards", 1)):
            mut.append({"repo": r["name"], "url": r["url"], "ref": r["ref"], "install": json.dumps(r.get("install", [])),
                        "pytest_args": json.dumps(r.get("pytest_args", [])), "shard": s,
                        "per_shard": m.get("per_shard", 40), "recheck": m.get("recheck", ""),
                        "controls": m.get("controls", 0)})
prs = cfg.get("prs", {})
print(f"engine={cfg['engine_sha']}")
print(f"prs={'true' if prs.get('enabled') else 'false'}")
print(f"prs_args={prs.get('args', '')}")
print(f"prs_reuse={prs.get('reuse', '')}")
print(f"prs_indices={json.dumps(prs.get('indices', []))}")
print(f"mutants={'true' if mut else 'false'}")
print(f"mut_matrix={json.dumps(mut or [{'repo': 'none'}])}")
print(f"publish_run={cfg.get('publish_run_id', '')}")
