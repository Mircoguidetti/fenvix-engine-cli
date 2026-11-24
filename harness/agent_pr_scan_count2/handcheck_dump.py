#!/usr/bin/env python3
"""Print the hand-check sample (random.Random(2).sample(sorted(urls_with_failed_check), 20)) with the committed raw
responses a reader needs: the head check runs / statuses, the head workflow run, the base listing entries of the
identity's workflow and the base jobs / commit checks that were read. Usage: handcheck_dump.py [index]
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import rules as R  # noqa: E402


def sample(rows):
    return random.Random(2).sample(sorted(r["url"] for r in rows if r["verdict"] in R.PR_ORDER), 20)


def main():
    res = HERE / "results"
    rows = {r["url"]: r for r in J.read_jsonl(res / "rows.jsonl")}
    raws = {x["url"]: x for x in J.raw_records(res)}
    urls = sample(rows.values())
    pick = [int(sys.argv[1])] if len(sys.argv) > 1 else range(len(urls))
    for i in pick:
        u = urls[i]
        row, raw = rows[u], raws[u]
        print(f"===== [{i}] {u}  auto={row['verdict']}  window={row.get('window')}")
        for path, rec in raw["responses"].items():
            d = rec.get("data", rec.get("error"))
            if "/check-runs" in path and isinstance(d, dict):
                d = [(c["id"], c["name"], c["app"], c["status"], c["conclusion"], c["started_at"], c["check_suite_id"])
                     for c in d["check_runs"]]
            elif path.endswith("/status") and isinstance(d, dict):
                d = [(s["context"], s["state"], s["created_at"]) for s in d["statuses"]]
            elif "/jobs" in path and isinstance(d, dict):
                d = [(j["id"], j["name"], j["status"], j["conclusion"], j["started_at"]) for j in d["jobs"]]
            elif "actions/runs?" in path and isinstance(d, dict):
                d = [(r["id"], r["name"], r["event"], r["head_branch"], r["head_repo"], r["conclusion"],
                      r["run_started_at"], r["check_suite_id"]) for r in d["workflow_runs"]]
            print(f"-- {path} [{rec['status']}]")
            if isinstance(d, list):
                for x in d[:60]:
                    print("   ", x)
                if len(d) > 60:
                    print(f"    ... {len(d) - 60} more")
            else:
                print("   ", json.dumps(d)[:600])
        for f in row.get("failed_checks", []):
            print("  FAILED", json.dumps({k: f.get(k) for k in ("kind", "identity", "S", "conclusion", "verdict",
                                                                 "reason", "base", "secondary", "job_confirmed")}))


if __name__ == "__main__":
    main()
