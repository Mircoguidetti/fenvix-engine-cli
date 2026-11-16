#!/usr/bin/env python3
"""Aggregate results/*.json into tables (markdown on stdout) and flaky.json (for classification).

usage: aggregate.py [RESULTS_DIR]
"""
import glob
import json
import os
import re
import statistics as stx
import sys

rdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "results")
repos = json.load(open(os.path.join(os.path.dirname(__file__), "..", "repos.json")))
res = {}
for p in sorted(glob.glob(os.path.join(rdir, "*.json"))):
    if os.path.basename(p) in ("flaky.json", "classification.json"):
        continue
    d = json.load(open(p))
    res[d.get("name") or os.path.basename(p)[:-5]] = d


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


rows, idle_vals, idle_net, quiet_vals = [], [], [], []
print("| Repository | App | Suite | Runs | Median wall (s) | Median CPU-busy (s) | Mean cores | Idle share (raw) | Idle share (net of baseline) | All-blocked share | Tests | Flaky | Always failing |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for name, cfg in repos.items():
    d = res.get(name)
    if not d or d.get("status") != "ok" or not d.get("n_runs"):
        st = d.get("status") if d else "not run"
        print(f"| {name} | {cfg['app']} | {cfg['suite']} | 0 | - | - | - | - | - | - | - | - | {st} |")
        continue
    i, t = d["idle"], d["tests"]
    idle_vals.append(i["median_idle_share_raw"])
    idle_net.append(i["median_idle_share_net"])
    quiet_vals.append(i["median_quiet_share"])
    print(f"| {name} | {cfg['app']} | {cfg['suite']} | {d['n_runs']} | {i['median_wall_s']:.0f} | {i['median_busy_cpu_s']:.0f} | "
          f"{i['median_cores_mean']:.2f} | {pct(i['median_idle_share_raw'])} | {pct(i['median_idle_share_net'])} | "
          f"{pct(i['median_quiet_share'])} | {t['n_distinct']} | {t['n_flaky']} | {t['n_consistent_fail']} |")
print()
if idle_vals:
    print(f"repositories measured: {len(idle_vals)}")
    print(f"median idle share raw: {pct(stx.median(idle_vals))}  (min {pct(min(idle_vals))}, max {pct(max(idle_vals))})")
    print(f"median idle share net: {pct(stx.median(idle_net))}")
    print(f"median all-blocked share: {pct(stx.median(quiet_vals))}")
    q = sorted(idle_vals)
    print(f"quartiles raw: {pct(q[len(q)//4])} / {pct(stx.median(q))} / {pct(q[(3*len(q))//4])}")

flaky = []
for name, d in res.items():
    for f in (d.get("tests") or {}).get("flaky", []):
        flaky.append({"repo": name, **f})
json.dump(flaky, open(os.path.join(rdir, "flaky.json"), "w"), indent=1)
print(f"\nflaky tests total: {len(flaky)} in {len({f['repo'] for f in flaky})} repositories")
