#!/usr/bin/env python3
"""Aggregate cache-proof walk results (walk.py outputs) into per-project numbers.

    python harness/cache_proof/aggregate.py RESULTS_DIR [--md OUT.md] [--json OUT.json]

Per project (shards of one project are summed per commit):
* skipped share = test time of reused results / test time of all tests, per commit after the first (the first
  commit runs everything with an empty cache); median and mean over commits;
* verification: reused results compared with the full run (B) at the same commit; a mismatch confirmed by a
  second full run is a wrong reuse, otherwise flaky;
* cache-hit run time vs full run: wall time of A (pytest --det --det-cache) vs B (pytest --det), per commit;
* capture overhead: a run with an empty cache (everything recorded) vs the plain --det runs at the same commit;
* invalidating commits: commits where under 5% of the test time was reused, with the dominant miss reason.
"""

from __future__ import annotations

import argparse
import collections
import glob
import gzip
import json
import os
import statistics


def load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rb") as fh:
        return json.loads(fh.read())


def med(xs):
    return statistics.median(xs) if xs else None


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def secs(x):
    return "-" if x is None else f"{x:.1f}s"


def project_rows(files, from_i: int = 0):
    by_project = collections.defaultdict(list)
    for f in files:
        d = load(f)
        d["steps"] = [st for st in d["steps"] if st.get("i", 0) >= from_i]
        by_project[d["spec"]["name"]].append(d)
    out = {}
    for name, shards in sorted(by_project.items()):
        nsh = shards[0].get("nshards", 1)
        # per commit index: only commits every shard reached with status ok
        steps = collections.defaultdict(list)
        for d in shards:
            for st in d["steps"]:
                steps[st["i"]].append(st)
        commits = []
        for i in sorted(steps):
            sts = steps[i]
            if len(sts) < len(shards) or any(s.get("status") != "ok" for s in sts):
                continue
            c = {"i": i, "sha": sts[0]["sha"]}
            c["time_total"] = sum(s.get("time_total") or 0 for s in sts)
            c["time_reused"] = sum(s.get("time_reused") or 0 for s in sts)
            c["n_tests"] = sum(s.get("n_tests") or 0 for s in sts)
            c["n_reused"] = sum(s.get("n_reused") or 0 for s in sts)
            # shards run in parallel: the commit's wall time is the slowest shard
            c["a_wall"] = max(s["A"]["wall"] for s in sts)
            c["b_wall"] = max(s["B"]["wall"] for s in sts)
            c["a_wall_sum"] = sum(s["A"]["wall"] for s in sts)
            c["b_wall_sum"] = sum(s["B"]["wall"] for s in sts)
            c["checked"] = sum(s["verify"]["checked"] for s in sts)
            c["mm"] = [m for s in sts for m in s["verify"]["mismatches"]]
            c["ran_diff"] = sum((s.get("ran_diff") or {}).get("n", 0) for s in sts)
            mr = collections.Counter()
            nc = collections.Counter()
            for s in sts:
                mr.update(s["A"].get("miss_reasons") or {})
                nc.update(s["A"].get("not_cached") or {})
            c["miss"] = dict(mr)
            c["nc"] = dict(nc)
            ov = [s["overhead"] for s in sts if s.get("overhead")]
            if len(ov) == len(sts):
                c["cold"] = sum(o["cold_wall"] for o in ov)
                c["plain"] = sum(mean(o["plain_walls"]) for o in ov)
                c["record_s"] = sum(o.get("cold_record_s") or 0 for o in ov)
                if all(o.get("pytest_walls") for o in ov):
                    c["pytest"] = sum(mean(o["pytest_walls"]) for o in ov)
                    c["cold_max_ratio"] = max(o["cold_wall"] / mean(o["pytest_walls"]) for o in ov)
                    c["det_max_ratio"] = max(mean(o["plain_walls"]) / mean(o["pytest_walls"]) for o in ov)
            ed = [s["epoch_diff"] for s in sts if s.get("epoch_diff")]
            if ed:
                c["epoch_diff"] = sum(e["n"] for e in ed)
                c["epoch_diff_ids"] = [x for e in ed for x in e["ids"]][:10]
            c["n_reused_checked_possible"] = sum(s.get("n_reused_in_B") or 0 for s in sts)
            c["children"] = sum(s["A"].get("children") or 0 for s in sts)
            det = collections.Counter()
            for s in sts:
                det.update(s["A"].get("not_cached_detail") or {})
            c["nc_detail"] = dict(det)
            commits.append(c)
        first = min((c["i"] for c in commits), default=0)
        later = [c for c in commits if c["i"] > first and c["time_total"] > 0]
        shares = [c["time_reused"] / c["time_total"] for c in later]
        nshares = [c["n_reused"] / c["n_tests"] for c in later if c["n_tests"]]
        speed = [c["a_wall_sum"] / c["b_wall_sum"] for c in later if c["b_wall_sum"]]
        wrong = [m for c in commits for m in c["mm"] if m.get("verdict") == "wrong"]
        flaky = [m for c in commits for m in c["mm"] if m.get("verdict") == "flaky"]
        ovs = [c["cold"] / c["plain"] - 1 for c in commits if c.get("cold") and c.get("plain")]
        inval = []
        for c in later:
            if c["time_reused"] / c["time_total"] < 0.05:
                top = max(c["miss"].items(), key=lambda kv: kv[1])[0] if c["miss"] else "-"
                inval.append({"i": c["i"], "sha": c["sha"][:10], "top_miss": top, "miss": c["miss"]})
        nc_total = collections.Counter()
        miss_total = collections.Counter()
        detail_total = collections.Counter()
        for c in later:
            nc_total.update(c["nc"])
            miss_total.update(c["miss"])
            detail_total.update(c["nc_detail"])
        ov_pytest = [c["cold"] / c["pytest"] for c in commits if c.get("cold") and c.get("pytest")]
        det_pytest = [c["plain"] / c["pytest"] for c in commits if c.get("plain") and c.get("pytest")]
        out[name] = {
            "shards": nsh, "shards_found": len(shards), "commits_ok": len(commits), "transitions": len(later),
            "tests_median": med([c["n_tests"] for c in commits]),
            "skip_time_median": med(shares), "skip_time_mean": mean(shares),
            "skip_tests_median": med(nshares), "skip_tests_mean": mean(nshares),
            "verified": sum(c["checked"] for c in commits), "wrong": len(wrong), "flaky": len(flaky),
            "wrong_ids": [(m.get("nodeid"), m.get("cached"), m.get("fresh")) for m in wrong][:20],
            "ran_diff": sum(c["ran_diff"] for c in later),
            "a_wall_median": med([c["a_wall"] for c in later]), "b_wall_median": med([c["b_wall"] for c in later]),
            "a_wall_mean": mean([c["a_wall"] for c in later]), "b_wall_mean": mean([c["b_wall"] for c in later]),
            "hit_over_full_median": med(speed), "hit_over_full_mean": mean(speed),
            "capture_overhead_median": med(ovs), "capture_overhead_n": len(ovs),
            "cold_over_det": [round(c["cold"] / c["plain"], 3) for c in commits if c.get("cold") and c.get("plain")],
            "cold_over_pytest": [round(x, 3) for x in ov_pytest],
            "det_over_pytest": [round(x, 3) for x in det_pytest],
            "cold_over_pytest_worst_shard": [round(c["cold_max_ratio"], 3) for c in commits if c.get("cold_max_ratio")],
            "epoch_diff": sum(c.get("epoch_diff", 0) for c in commits),
            "epoch_diff_ids": [x for c in commits for x in c.get("epoch_diff_ids", [])][:20],
            "reused_total": sum(c["n_reused"] for c in later),
            "children_total": sum(c["children"] for c in commits),
            "not_cached_detail": dict(detail_total.most_common(25)),
            "invalidating": inval, "not_cached": dict(nc_total.most_common()), "miss": dict(miss_total.most_common()),
            "per_commit": [{k: c[k] for k in ("i", "sha", "time_total", "time_reused", "n_tests", "n_reused",
                                              "a_wall", "b_wall", "checked")} for c in commits],
            "stopped": [d.get("stopped") for d in shards if d.get("stopped")],
        }
    return out


def markdown(rows) -> str:
    lines = ["| project | transitions | tests | time skipped median / mean | tests skipped median / mean | "
             "cache run vs full run, median (A / B) | capture overhead (median, n) | cold / plain pytest (median) | "
             "verified reuses (wrong, flaky) | invalidate-all commits |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for name, r in rows.items():
        o = r["capture_overhead_median"]
        ov = "-" if o is None else f"{100 * o:+.0f}%"
        lines.append(
            f"| {name} | {r['transitions']} | {r['tests_median']} | {pct(r['skip_time_median'])} / "
            f"{pct(r['skip_time_mean'])} | {pct(r['skip_tests_median'])} / {pct(r['skip_tests_mean'])} | "
            f"{pct(r['hit_over_full_median'])} ({secs(r['a_wall_median'])} / {secs(r['b_wall_median'])}) | "
            f"{ov} "
            f"({r['capture_overhead_n']}) | "
            f"{'-' if not r['cold_over_pytest'] else format(med(r['cold_over_pytest']), '.2f') + 'x'} | "
            f"{r['verified']} ({r['wrong']}, {r['flaky']}) | "
            f"{len(r['invalidating'])}/{r['transitions']} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--md")
    ap.add_argument("--json")
    ap.add_argument("--from-i", type=int, default=0, help="drop commits before this index (e.g. r5's window)")
    a = ap.parse_args(argv)
    files = sorted(glob.glob(os.path.join(a.results, "*.json*")))
    rows = project_rows(files, a.from_i)
    md = markdown(rows)
    print(md)
    if a.md:
        with open(a.md, "w") as fh:
            fh.write(md)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rows, fh, indent=1)


if __name__ == "__main__":
    main()
