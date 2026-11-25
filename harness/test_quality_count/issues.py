#!/usr/bin/env python3
"""§4.3 issues search on the route chosen by the §0.2c probe (gate note 3: the session runs it per chunk).

Usage: issues.py --route session|workflow --chunk N [--repo owner/name ...]
For every row of chunk N that is `running`, has no duration pain and has no issues result yet, runs the per-tool
queries (+ `mutation`) with the cap left after its history requests (300 in all). Appends results/issues.jsonl
({repo, chunk, route, at, ...}) and the raw responses to results/issues_raw/<chunk>.jsonl.gz (verify.py replays them).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import chunk as CH  # noqa: E402
import discover  # noqa: E402
import ghapi  # noqa: E402
import history  # noqa: E402
import pipeline  # noqa: E402

RES = HERE / "results"


def needs_issues(row: dict, have: set) -> bool:
    return (row.get("cls") == "running" and not (row.get("duration") or {}).get("pain")
            and row["repo"].lower() not in have and not (row.get("issues") or {}).get("done"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", default="session")
    ap.add_argument("--chunk", required=True)
    ap.add_argument("--repo", action="append", default=[])
    a = ap.parse_args(argv)
    discover.require_budget_free()
    have = {r["repo"].lower() for r in CH.read_jsonl(RES / "issues.jsonl") if r.get("done")}
    rows = [r for r in CH.read_jsonl(RES / "rows.jsonl") if str(r.get("chunk")) == str(a.chunk)]
    if a.repo:
        rows = [r for r in rows if r["repo"].lower() in {x.lower() for x in a.repo}]
    todo = [r for r in rows if needs_issues(r, have)]
    c = ghapi.Client(use_gh=True) if a.route == "session" else ghapi.from_env()
    (RES / "issues_raw").mkdir(parents=True, exist_ok=True)
    for r in todo:
        src = pipeline.LiveSource(c)
        left = 300 - ((r.get("history") or {}).get("requests") or 0)
        repo = (r.get("meta") or {}).get("full_name") or r["repo"]
        out = history.run_issues(src, repo, pipeline.row_tools(r), left)
        rec = {"repo": r["repo"], "query_repo": repo, "chunk": r.get("chunk"), "route": a.route,
               "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "cap_left": left,
               "tools": pipeline.row_tools(r), **out}
        with open(RES / "issues.jsonl", "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        with gzip.open(RES / "issues_raw" / f"{a.chunk}.jsonl.gz", "at") as f:
            f.write(json.dumps({"repo": r["repo"], "responses": src.responses}, sort_keys=True) + "\n")
        print(f"{r['repo']}: {len(out['queries'])} queries, {len(out['candidates'])} hits, "
              f"errors {len(out['errors'])}, capped {out['capped']}", flush=True)
    print(f"issues chunk {a.chunk}: {len(todo)} repositories, {c.n_search['issues']} issues searches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
