#!/usr/bin/env python3
"""Aggregate the Go rounds into Markdown tables.

    python3 harness/go/aggregate.py flaky harness/go/results/flaky-r1
    python3 harness/go/aggregate.py skip  harness/go/results/skip-r1
"""

from __future__ import annotations

import collections
import glob
import gzip
import json
import os
import statistics
import sys


def pct(a, b):
    return f"{100.0 * a / b:.1f}%" if b else "n/a"


def flaky(d):
    rows = []
    tot = collections.Counter()
    slow = []
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        r = json.load(open(f))
        name = r["spec"]["name"]
        st = r.get("status")
        base = r.get("baseline", {})
        unstable = set(r.get("baseline_unstable", []))
        conf = r.get("confirm", {})
        documented = [k for k in conf if k.split("::")[1] in r["spec"]["tests"]]
        doc_seen = [k for k in documented if k in base]
        doc_flaky_base = [k for k in documented if k in unstable]
        rep_unstable = [k for k in unstable if conf.get(k, {}).get("reproduced")]
        rep_doc = [k for k in documented if conf.get(k, {}).get("reproduced")]
        cov = r.get("fingerprint_coverage", [0, 0])
        broken = r.get("broken", [])
        ntests = len(base)
        s = r.get("slowdown")
        if s is not None:
            slow.append(s)
        tot.update({"projects": 1, "ok": st == "done", "tests": ntests, "unstable": len(unstable),
                    "rep_unstable": len(rep_unstable), "documented": len(documented), "doc_seen": len(doc_seen),
                    "doc_flaky_base": len(doc_flaky_base), "rep_doc": len(rep_doc), "cov_same": cov[0],
                    "cov_total": cov[1], "broken": len(broken)})
        rows.append(f"| {name} | {st} | {r.get('go_version', '')} | {ntests} | {len(unstable)} | {len(rep_unstable)} | "
                    f"{len(doc_seen)}/{len(documented)} | {len(doc_flaky_base)} | {len(rep_doc)} | {len(broken)} | "
                    f"{pct(cov[0], cov[1])} | {'' if s is None else f'{100 * s:+.1f}%'} |")
    print("| project | status | go | tests | baseline-unstable | reproduced (of unstable) | documented test ran | "
          "documented flaky in baseline | documented reproduced | broken by --det | fingerprint coverage | slowdown |")
    print("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    print("\n".join(rows))
    print()
    print(f"projects {tot['projects']} (done {tot['ok']}); tests {tot['tests']}; baseline-unstable {tot['unstable']}, "
          f"reproduced {tot['rep_unstable']} = {pct(tot['rep_unstable'], tot['unstable'])}; documented tests "
          f"{tot['documented']} (ran {tot['doc_seen']}, flaky in baseline {tot['doc_flaky_base']}, reproduced "
          f"{tot['rep_doc']}); broken by --det {tot['broken']}; fingerprint coverage "
          f"{pct(tot['cov_same'], tot['cov_total'])}; median slowdown "
          f"{'n/a' if not slow else f'{100 * statistics.median(slow):+.1f}%'} over {len(slow)} projects")


def mm(v):
    return f"{100 * statistics.median(v):.0f}% / {100 * statistics.mean(v):.0f}%" if v else "n/a"


def skip(d):
    by = collections.defaultdict(list)
    own_rows = []
    for f in sorted(glob.glob(os.path.join(d, "*.json.gz"))):
        r = json.load(gzip.open(f, "rt"))
        by[r["spec"]["name"]].append(r)
    print("| repository | shards | commits walked (min over shards) | tests per commit | fenvix: share of test time "
          "reused with proof, median / mean | go test cache: share, median / mean | fenvix reuses verified | wrong | "
          "flaky | go cache reuses verified | wrong | flaky |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, shards in sorted(by.items()):
        # merge shards by commit index
        per = collections.defaultdict(lambda: {"all": 0.0, "fen": 0.0, "own": 0.0, "go": 0.0, "n": 0})
        ver = collections.Counter()
        walked = min(len([c for c in s["commits"] if c.get("status") == "ok"]) for s in shards)
        for s in shards:
            for c in s["commits"]:
                if c.get("status") != "ok" or c["i"] == 0:
                    continue
                p = per[c["i"]]
                for t in c["tests"]:
                    if t["fresh"] in ("", "skipped"):
                        continue
                    el = t["elapsed"] or 0.0
                    p["all"] += el
                    p["n"] += 1
                    if t["reuse"]:
                        p["fen"] += el
                        ver["fen"] += 1
                    if t.get("reuse_own"):
                        p["own"] += el
                        ver["own"] += 1
                    if t["go_cached"]:
                        p["go"] += el
                        ver["go"] += 1
                for ch in c.get("checks", []):
                    ver[f"{ch['rule']}-{ch['verdict']}"] += 1
        idx = [i for i in sorted(per) if i < walked]
        fen = [per[i]["fen"] / per[i]["all"] for i in idx if per[i]["all"] > 0]
        go = [per[i]["go"] / per[i]["all"] for i in idx if per[i]["all"] > 0]
        own = [per[i]["own"] / per[i]["all"] for i in idx if per[i]["all"] > 0]
        own_rows.append(f"| {name} | {mm(own) if ver['own'] else 'n/a'} | {ver['own']} | {ver['own-wrong']} | {ver['own-flaky']} |")
        ntests = statistics.median([per[i]["n"] for i in idx]) if idx else 0

        print(f"| {name} | {len(shards)} | {walked - 1 if walked else 0} transitions | {ntests:.0f} | {mm(fen)} | {mm(go)} | "
              f"{ver['fen']} | {ver['fenvix-wrong']} | {ver['fenvix-flaky']} | {ver['go']} | {ver['go-wrong']} | "
              f"{ver['go-flaky']} |")
    print()
    print("Measurement-only variant without the prefix rule (own inputs + package set-up):")
    print()
    print("| repository | share, median / mean | reuses verified | wrong | flaky |")
    print("|---|---:|---:|---:|---:|")
    print("\n".join(own_rows))
    # reasons for reruns
    print()
    reasons = collections.Counter()
    for shards in by.values():
        for s in shards:
            for c in s["commits"]:
                if c.get("status") != "ok" or c["i"] == 0:
                    continue
                for t in c["tests"]:
                    if not t["reuse"]:
                        reasons[(t["why"] or "").split(":")[0]] += 1
    print("rerun reasons (all repositories, test-transitions):", dict(reasons.most_common()))


if __name__ == "__main__":
    {"flaky": flaky, "skip": skip}[sys.argv[1]](sys.argv[2])
