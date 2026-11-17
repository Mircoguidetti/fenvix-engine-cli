#!/usr/bin/env python3
"""The founder's sentence from the head-to-head runs: time skipped in the fixed environment (arm ``main``: real commit
history) and wrong skips over every arm (fixed environment, environment changed, realistic CI changes).

    python3 harness/skip_study2/headtohead/headline.py h1 h2 h3 h4 h5 l1 [--json out.json]

* time skipped: per project, the mean over its commits of the share of test time the rule does not rerun; then the
  mean over projects (each project weighs the same). Also the pooled mean (each commit of every project weighs the
  same) and the per-project table.
* wrong: confirmed stale passes (a unit the rule skipped, whose fresh run fails twice at the head while its reused
  record passes twice at the cached commit), counted as (test file x commit) and as distinct test files, per arm.
"""

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = ("A", "Ae", "Af", "B", "B+", "C")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("run_ids", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    with tempfile.NamedTemporaryFile(suffix=".json") as tf:
        subprocess.run([sys.executable, str(HERE / "h2h_aggregate.py"), *a.run_ids, "--json", tf.name], check=True,
                       capture_output=True)
        res = json.loads(Path(tf.name).read_text())
    main_arm = {n: s for n, s in res.get("main", {}).items() if not n.startswith("_")}
    out = {"projects": sorted(main_arm), "time": {}, "wrong": {}}
    for r in RULES:
        ms = [s[r]["time"]["mean"] for s in main_arm.values() if r in s.get("rules", []) and s[r]["time"]["mean"] is not None]
        pooled = [x for s in main_arm.values() if r in s.get("rules", []) for x in s[r]["share_series"] if x is not None]
        out["time"][r] = {"projects": len(ms), "mean_of_project_means": statistics.fmean(ms) if ms else None,
                          "pooled_mean": statistics.fmean(pooled) if pooled else None,
                          "pooled_median": statistics.median(pooled) if pooled else None}
    for arm, sums in res.items():
        for n, s in sums.items():
            if n.startswith("_"):
                continue
            for r in s.get("rules", []):
                w = out["wrong"].setdefault(r, {"total": 0, "files": 0, "by_arm": {}})
                x = s[r]
                if x["wrong"]:
                    w["total"] += x["wrong"]
                    w["files"] += x["wrong_units"]
                    b = w["by_arm"].setdefault(arm, {"wrong": 0, "files": 0, "projects": []})
                    b["wrong"] += x["wrong"]
                    b["files"] += x["wrong_units"]
                    b["projects"].append(n)
                w.setdefault("checked", 0)
                w["checked"] += x["checked"]
    pct = lambda v: "-" if v is None else f"{100 * v:.0f}%"
    for r in RULES:
        t, w = out["time"][r], out["wrong"].get(r, {})
        print(f"{r:3} time skipped (fixed env, {t['projects']} projects): mean of project means "
              f"{pct(t['mean_of_project_means'])}, pooled mean {pct(t['pooled_mean'])}, pooled median "
              f"{pct(t['pooled_median'])} | wrong over all arms: {w.get('total', 0)} (test file x commit), "
              f"{w.get('files', 0)} test files, of {w.get('checked', 0)} verified skips | by arm: "
              + "; ".join(f"{k} {v['wrong']} ({v['files']} files: {', '.join(v['projects'])})"
                          for k, v in sorted(w.get("by_arm", {}).items())))
    A, C = out["time"]["A"], out["time"]["C"]
    print(f"\nSentence: Competitor-style method (coverage, file level): {pct(A['mean_of_project_means'])} of test time "
          f"skipped, {out['wrong']['A']['total']} wrong. fenvix proof rule: {pct(C['mean_of_project_means'])}, "
          f"{out['wrong']['C']['total']} wrong.")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
