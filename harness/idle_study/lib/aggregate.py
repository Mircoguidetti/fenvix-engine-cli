#!/usr/bin/env python3
"""Aggregate results/*.json into the report tables (markdown on stdout) and results/flaky.json.

usage: aggregate.py [RESULTS_DIR]

Per repository (median over its runs):
  idle_raw       1 - B/W           B = CPU-busy seconds summed over all CPUs, W = wall seconds of the test command
  idle_clamped   max(0, idle_raw)  upper bound of compression if the box ran everything on one core
  interval_bound sum over 0.5 s intervals of max(0, 1 - busy cores) / W:
                 a lower bound of the time in which no CPU ran at all (every process blocked),
                 i.e. what a multi-core virtual clock could skip without serialising anything.
                 Results produced before this metric existed carry only run 1 at 1 s resolution;
                 the bound is computed from that (coarser buckets only lower it).
"""
import glob
import json
import os
import statistics as stx
import sys

here = os.path.dirname(os.path.abspath(__file__))
rdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "results")
repos = json.load(open(os.path.join(here, "..", "repos.json")))
res = {}
for p in sorted(glob.glob(os.path.join(rdir, "*.json"))):
    if os.path.basename(p) in ("flaky.json", "summary.json"):
        continue
    d = json.load(open(p))
    res[d.get("name") or os.path.basename(p)[:-5]] = d


def pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


def interval_bound(series, dt):
    if not series:
        return None
    return sum(dt * max(0.0, 1.0 - b) for b in series) / (dt * len(series))


summary = {}
rows = []
for name, cfg in repos.items():
    d = res.get(name)
    if not d or d.get("status") != "ok" or not d.get("n_runs"):
        rows.append(f"| {name} | {cfg['app']} | {cfg['suite']} | 0 | - | - | - | - | - | {d.get('status') if d else 'not run'} | - | - |")
        continue
    runs = d["runs"]
    raw = [1 - r["busy_cpu_s"] / r["wall_s"] for r in runs]
    ib = [r["idle_interval_bound"] for r in runs if r.get("idle_interval_bound") is not None]
    ib_note = "0.5 s, all runs"
    if not ib:
        ib = [interval_bound(runs[0].get("series_1s"), 1.0)]
        ib_note = "1 s, run 1"
    s = {
        "app": cfg["app"],
        "kind": cfg["suite"].split(":")[0],
        "runs": len(runs),
        "wall_s": stx.median(r["wall_s"] for r in runs),
        "busy_s": stx.median(r["busy_cpu_s"] for r in runs),
        "cores": stx.median(r["busy_cpu_s"] / r["wall_s"] for r in runs),
        "idle_raw": stx.median(raw),
        "idle_clamped": max(0.0, stx.median(raw)),
        "interval_bound": stx.median(ib),
        "interval_note": ib_note,
        "tests": d["tests"]["n_distinct"],
        "flaky": d["tests"]["n_flaky"],
        "always_fail": d["tests"]["n_consistent_fail"],
        "baseline_cores": d.get("baseline_cores"),
        "runner": d.get("runner"),
    }
    summary[name] = s
    rows.append(f"| {name} | {s['app']} | {cfg['suite']} | {s['runs']} | {s['wall_s']:.0f} | {s['busy_s']:.0f} | {s['cores']:.2f} | "
                f"{100 * s['idle_raw']:.0f}% | {pct(s['interval_bound'])} | {s['tests']} | {s['flaky']} | {s['always_fail']} |")

print("| Repository | App | Suite | Runs | Wall (s) | CPU-busy (s) | Mean busy cores | Idle share 1 - B/W | All-blocked share (lower bound) | Tests | Flaky | Always failing |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
print("\n".join(rows))
print()
if summary:
    v = list(summary.values())
    def line(label, xs):
        xs = sorted(xs)
        print(f"- {label}: median {pct(stx.median(xs))}, quartiles {pct(xs[len(xs)//4])} / {pct(xs[(3*len(xs))//4])}, min {pct(xs[0])}, max {pct(xs[-1])}")
    print(f"repositories measured: {len(v)}")
    line("idle share 1 - B/W, clamped at 0", [s["idle_clamped"] for s in v])
    line("all-blocked share (lower bound)", [s["interval_bound"] for s in v])
    for k in ("e2e", "integration"):
        sub = [s for s in v if s["kind"] == k]
        if sub:
            line(f"  {k} ({len(sub)}): idle clamped", [s["idle_clamped"] for s in sub])
            line(f"  {k} ({len(sub)}): all-blocked", [s["interval_bound"] for s in sub])
    for k in ("python", "node"):
        sub = [s for s in v if s["app"] == k]
        if sub:
            line(f"  {k} apps ({len(sub)}): idle clamped", [s["idle_clamped"] for s in sub])
    print(f"- median mean-busy-cores: {stx.median(s['cores'] for s in v):.2f}")
    print(f"- test executions: {sum(s['tests'] * s['runs'] for s in v)}; distinct tests {sum(s['tests'] for s in v)}; flaky {sum(s['flaky'] for s in v)}")

flaky = []
for name, d in res.items():
    for f in (d.get("tests") or {}).get("flaky", []):
        flaky.append({"repo": name, **f})
json.dump(flaky, open(os.path.join(rdir, "flaky.json"), "w"), indent=1)
json.dump(summary, open(os.path.join(rdir, "summary.json"), "w"), indent=1)
print(f"\nflaky tests total: {len(flaky)} in {len({f['repo'] for f in flaky})} repositories")
