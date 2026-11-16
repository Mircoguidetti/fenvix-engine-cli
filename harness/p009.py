"""P-009 helpers: order-only targets and analysis of the orderonly / baseline result sets.

    python harness/p009.py targets  [--results harness/results/mixed-after-fixes]
    python harness/p009.py orderonly harness/results/order-only
    python harness/p009.py baseline  harness/results/django-beam-baseline
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _tests_csvs(results: Path):
    for f in sorted(results.glob("*.csv")):
        if f.name.endswith("_runs.csv") or f.name in ("summary.csv", "not-reproduced-causes.csv"):
            continue
        rows = list(csv.DictReader(open(f)))
        if rows and "reproduced" in rows[0]:
            yield f.stem, rows


def targets(args) -> None:
    out: dict = {}
    for repo, rows in _tests_csvs(Path(args.results)):
        for r in rows:
            if r["reproduced"] == "True":
                out.setdefault(repo, {}).setdefault(r["repro_seed"], []).append(r["nodeid"])
    Path(args.out).write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    n = sum(len(v) for d in out.values() for v in d.values())
    print(f"{n} reproduced tests, {len(out)} repositories, "
          f"{sum(len(d) for d in out.values())} configurations -> {args.out}")


def orderonly(args) -> None:
    d = Path(args.dir)
    reasons = {}
    for repo, rows in _tests_csvs(Path(args.results)):
        for r in rows:
            if r["reproduced"] == "True":
                reasons[(repo, r["nodeid"])] = (r["pass_fail_reason"] or "-", r["idoft_category"] or "-")
    files = sorted(d.glob("*.orderonly.json"))
    tot = collections.Counter()
    by_reason = collections.defaultdict(collections.Counter)
    by_cat = collections.defaultdict(collections.Counter)
    rows = []
    for f in files:
        res = json.loads(f.read_text())
        for nid, t in res["tests"].items():
            k = "order alone" if t["order_alone"] else ("sometimes" if t["fails"] else "never")
            tot[k] += 1
            reason, cat = reasons.get((res["name"], nid), ("?", "?"))
            by_reason[reason][k] += 1
            by_cat[cat][k] += 1
            rows.append((res["name"], nid, t["config"], t["runs"], t["fails"], k, reason, cat))
    with open(d / "order-only.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["repo", "nodeid", "config", "runs", "fails", "verdict", "pass_fail_reason", "idoft_category"])
        w.writerows(rows)
    summary = {"tests": sum(tot.values()), "verdicts": dict(tot),
               "by_pass_fail_reason": {k: dict(v) for k, v in by_reason.items()},
               "by_idoft_category": {k: dict(v) for k, v in by_cat.items()},
               "per_repo": {}}
    for name, *_rest in rows:
        summary["per_repo"].setdefault(name, collections.Counter())
    for name, _nid, _c, _r, _f, k, *_x in rows:
        summary["per_repo"][name][k] += 1
    summary["per_repo"] = {k: dict(v) for k, v in summary["per_repo"].items()}
    (d / "order-only-summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def baseline(args) -> None:
    for f in sorted(Path(args.dir).glob("*.baseline.json")):
        res = json.loads(f.read_text())
        flaky = {k: v for k, v in res["known_flaky"].items() if any(len(c) > 1 for c in v.values())}
        print(f"{res['name']}: py{res['python']} xdist={res['xdist']} runs={res['runs']} tests={res['tests']} "
              f"unstable={len(res['unstable'])} known flaky unstable={len(flaky)}/{len(res['known_flaky'])} "
              f"cpu={res['runner'].get('cpu_model')} cpus={res['runner'].get('cpus')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("targets")
    t.add_argument("--results", default=str(HERE / "results" / "mixed-after-fixes"))
    t.add_argument("--out", default=str(HERE / "order_only_targets.json"))
    o = sub.add_parser("orderonly")
    o.add_argument("dir")
    o.add_argument("--results", default=str(HERE / "results" / "mixed-after-fixes"))
    b = sub.add_parser("baseline")
    b.add_argument("dir")
    args = ap.parse_args()
    {"targets": targets, "orderonly": orderonly, "baseline": baseline}[args.cmd](args)


if __name__ == "__main__":
    main()
