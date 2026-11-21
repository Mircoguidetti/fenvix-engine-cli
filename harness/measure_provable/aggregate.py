"""Aggregate the per-test records into the report's tables and the raw CSV."""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

BUCKETS = ["PROVABLE", "NOT PROVEN, coverable", "NOT PROVEN, by nature"]
# a run that did not execute exactly one test, or whose sensors failed, is not classified
EXCLUDE_STATUS = {"error", "no-strace", "no-test-ran", "several-tests-ran", "no-engine-record"}
VIEWS = [("bucket_E", "causes_E", "Rule E, whole run (primary)"),
         ("bucket_testphase_E", "causes_testphase_E", "Rule E, test phase only"),
         ("bucket_S", "causes_S", "Rule S, whole run (sensitivity)")]


def excluded(r: dict) -> bool:
    return r.get("bucket") == "EXCLUDED" or r.get("status") in EXCLUDE_STATUS


def pct(n: int, d: int) -> str:
    return "—" if not d else f"{100.0 * n / d:.1f}%"


def table(recs: list, bkey: str) -> dict:
    by = collections.defaultdict(collections.Counter)
    for r in recs:
        if excluded(r):
            continue
        by[r["project"]][r[bkey]] += 1
        by["ALL"][r[bkey]] += 1
    return by


def causes(recs: list, ckey: str, bkey: str, project: str | None = None) -> list:
    c = collections.Counter()
    n = 0
    for r in recs:
        if excluded(r) or (project and r["project"] != project):
            continue
        n += 1
        if r[bkey] == "PROVABLE":
            continue
        for cause in set(r[ckey]):
            c[cause] += 1
    return [(cause, k, pct(k, n)) for cause, k in c.most_common()], n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/home/user/measure/out")
    ap.add_argument("--projects", nargs="+", required=True)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    recs: list = []
    for p in a.projects:
        f = Path(a.out) / f"{p}.jsonl"
        if not f.exists():
            print(f"(missing {f})")
            continue
        recs += [json.loads(ln) for ln in f.open() if ln.strip()]
    print(f"records: {len(recs)}  excluded (not exactly one test, or sensor failed): "
          f"{sum(1 for r in recs if excluded(r))}")
    print(f"status: {dict(collections.Counter(r.get('status') for r in recs))}")
    print(f"engine outcome: {dict(collections.Counter(r.get('engine_outcome') for r in recs))}")

    summary: dict = {"views": {}, "n": len(recs)}
    for bkey, ckey, title in VIEWS:
        print(f"\n=== {title} ===")
        by = table(recs, bkey)
        hdr = f"{'project':14s} {'n':>5s} " + " ".join(f"{b:>24s}" for b in BUCKETS)
        print(hdr)
        rows = {}
        for proj in [*a.projects, "ALL"]:
            if proj not in by:
                continue
            cnt = by[proj]
            tot = sum(cnt.values())
            cells = " ".join(f"{str(cnt[b]) + ' (' + pct(cnt[b], tot) + ')':>24s}" for b in BUCKETS)
            print(f"{proj:14s} {tot:5d} {cells}")
            rows[proj] = {b: [cnt[b], pct(cnt[b], tot)] for b in BUCKETS} | {"n": tot}
        summary["views"][title] = rows
        cs, n = causes(recs, ckey, bkey)
        print(f"\n  top causes of NOT PROVEN (share of all {n} classified tests):")
        for cause, k, s in cs[:10]:
            print(f"    {s:>7s}  {k:5d}  {cause}")
        summary["views"][title + " :: causes"] = cs[:10]

    # per project cause ranking for the primary view
    for proj in a.projects:
        cs, n = causes(recs, "causes_E", "bucket_E", proj)
        if not n:
            continue
        summary[f"causes_E_{proj}"] = cs[:10]
        cs2, n2 = causes(recs, "causes_testphase_E", "bucket_testphase_E", proj)
        summary[f"causes_testphase_{proj}"] = cs2[:10]

    # what coverage buys: remove one cause family at a time from the test-phase view
    print("\n=== what recording one more channel would buy (test-phase view) ===")
    fams = collections.Counter()
    for r in recs:
        if excluded(r):
            continue
        for c in set(r["causes_testphase_E"]):
            fams[c] += 1
    base = sum(1 for r in recs if not excluded(r)
               and r["bucket_testphase_E"] == "PROVABLE")
    tot = sum(1 for r in recs if not excluded(r))
    print(f"  baseline PROVABLE (test phase): {base}/{tot} = {pct(base, tot)}")
    cum: list = []
    covered: set = set()
    order = [c for c, _ in fams.most_common()]
    for c in order:
        covered.add(c)
        now = sum(1 for r in recs if not excluded(r)
                  and not (set(r["causes_testphase_E"]) - covered))
        cum.append((c, now, pct(now, tot)))
        print(f"  + {c[:62]:62s} -> {now:5d} {pct(now, tot):>7s}")
    summary["cumulative_testphase"] = cum

    # What the engine already refuses today vs what the rule would add.
    # A test with a non-empty `uncontrolled` list is already never reported identical.
    print("\n=== already refused today (uncontrolled.* mark) vs the rule's verdict ===")
    print(f"{'project':14s} {'n':>5s} {'marked today':>13s} {'by nature':>10s} "
          f"{'by nature, not marked':>22s} {'coverable':>10s}")
    xtab = {}
    for proj in [*a.projects, "ALL"]:
        rs = [r for r in recs if not excluded(r)
              and (proj == "ALL" or r["project"] == proj)]
        if not rs:
            continue
        n = len(rs)
        marked = sum(1 for r in rs if r.get("engine_uncontrolled"))
        nat = sum(1 for r in rs if r["bucket_E"] == "NOT PROVEN, by nature")
        nat_unmarked = sum(1 for r in rs if r["bucket_E"] == "NOT PROVEN, by nature"
                           and not r.get("engine_uncontrolled"))
        cov = sum(1 for r in rs if r["bucket_E"] == "NOT PROVEN, coverable")
        print(f"{proj:14s} {n:5d} {str(marked) + ' (' + pct(marked, n) + ')':>13s} "
              f"{str(nat) + ' (' + pct(nat, n) + ')':>10s} "
              f"{str(nat_unmarked) + ' (' + pct(nat_unmarked, n) + ')':>22s} "
              f"{str(cov) + ' (' + pct(cov, n) + ')':>10s}")
        xtab[proj] = {"n": n, "marked_today": marked, "by_nature": nat,
                      "by_nature_not_marked": nat_unmarked, "coverable": cov}
    summary["already_refused"] = xtab

    # per-project cause rankings, printed
    for proj in a.projects:
        cs, n = causes(recs, "causes_testphase_E", "bucket_testphase_E", proj)
        if not n:
            continue
        print(f"\n=== {proj}: top causes, test-phase view (n={n}) ===")
        for cause, k, sh in cs[:10]:
            print(f"    {sh:>7s}  {k:5d}  {cause}")

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["project", "nodeid", "engine_outcome", "engine_sources",
                        "engine_uncontrolled", "engine_n_events",
                        "bucket_rule_E_whole_run", "causes_rule_E_whole_run",
                        "bucket_rule_E_test_phase", "causes_rule_E_test_phase",
                        "bucket_rule_S_whole_run", "causes_rule_S_whole_run",
                        "n_native_reads_test", "wall_s", "exit", "status",
                        "channels_test", "channels_whole_run"])
            for r in sorted(recs, key=lambda x: (x["project"], x["nodeid"])):
                w.writerow([
                    r.get("project"), r.get("nodeid"), r.get("engine_outcome"),
                    json.dumps(r.get("engine_sources"), sort_keys=True),
                    ";".join(r.get("engine_uncontrolled") or []), r.get("engine_n_events"),
                    r.get("bucket_E"), " | ".join(r.get("causes_E") or []),
                    r.get("bucket_testphase_E"), " | ".join(r.get("causes_testphase_E") or []),
                    r.get("bucket_S"), " | ".join(r.get("causes_S") or []),
                    r.get("n_native_reads_test"), r.get("wall_s"), r.get("exit"), r.get("status"),
                    json.dumps(r.get("channels_test"), sort_keys=True),
                    json.dumps(r.get("channels_all"), sort_keys=True)])
        print(f"\nCSV -> {a.csv}")
    if a.json:
        Path(a.json).write_text(json.dumps(summary, indent=1))
        print(f"summary -> {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
