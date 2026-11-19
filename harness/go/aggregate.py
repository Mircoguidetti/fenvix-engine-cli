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


def slowdown_invalid(r):
    """Why a slowdown comparison is not valid (review R-025 N3), or ""."""
    tm = r.get("timing", {})
    timeout = float(str(r["spec"].get("timeout", "10m")).rstrip("m")) * 60
    plain_out = min(tm.get("plain", [0]) or [0]) >= timeout - 1
    det_out = min(tm.get("det", [0]) or [0]) >= timeout - 1
    if plain_out and det_out:
        return "both arms stopped by the go test timeout"
    if det_out:
        # R-025b N5: only the --det arm stopped; this is a break by --det
        return "the --det arm stopped by the go test timeout (broken by --det)"
    if plain_out:
        return "the plain arm stopped by the go test timeout"
    if len(r.get("det0", {})) < 0.5 * len(r.get("baseline", {})):
        return f"--det ran {len(r.get('det0', {}))} of {len(r.get('baseline', {}))} tests"
    return ""


def det_gaps(r):
    """Tests passing 10/10 plain with no --det seed-0 result, and those that do
    not pass 3/3 under --det (review R-025 N2)."""
    base, det = r.get("baseline", {}), r.get("det0", {})
    allpass = [k for k, v in base.items() if v and all(x == "passed" for x in v) and "::Example" not in k]
    missing = [k for k in allpass if k not in det]
    notall = [k for k in allpass if k in det and any((x or [None])[0] != "passed" for x in det[k])]
    return missing, notall


def flaky(d):
    rows = []
    tot = collections.Counter()
    slow = []
    invalid = {}
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        r = json.load(open(f))
        if "spec" not in r:
            continue
        name = r["spec"]["name"]
        st = r.get("status")
        base = r.get("baseline", {})
        unstable = set(r.get("baseline_unstable", []))
        conf = r.get("confirm", {})
        loc = r.get("located", {})
        tops = set(r["spec"]["tests"])
        for t, how in loc.items():
            if how.startswith("method (subtest of "):
                tops |= {x for x in how[len("method (subtest of "):-1].split(",") if x}
        documented = [k for k in conf if k.split("::")[1] in tops]
        doc_seen = [k for k in documented if k in base]
        doc_flaky_base = [k for k in documented if k in unstable]
        rep_unstable = [k for k in unstable if conf.get(k, {}).get("reproduced")]
        rep_doc = [k for k in documented if conf.get(k, {}).get("reproduced")]
        cov = r.get("fingerprint_coverage", [0, 0])
        broken = r.get("broken", [])
        ntests = len(base)
        s = r.get("slowdown")
        why_bad = slowdown_invalid(r) if s is not None else ""
        if s is not None and not why_bad:
            slow.append(s)
        elif s is not None:
            invalid[name] = why_bad
        missing, notall = det_gaps(r)
        tot.update({"projects": 1, "ok": st == "done", "tests": ntests, "unstable": len(unstable),
                    "rep_unstable": len(rep_unstable), "documented": len(documented), "doc_seen": len(doc_seen),
                    "doc_flaky_base": len(doc_flaky_base), "rep_doc": len(rep_doc), "cov_same": cov[0],
                    "cov_total": cov[1], "broken": len(broken), "missing": len(missing), "notall": len(notall)})
        rows.append(f"| {name} | {st} | {r.get('go_version', '')} | {ntests} | {len(unstable)} | {len(rep_unstable)} | "
                    f"{len(doc_seen)}/{len(documented)} | {len(doc_flaky_base)} | {len(rep_doc)} | {len(broken)} | "
                    f"{len(missing)} | {len(notall)} | {pct(cov[0], cov[1])} | "
                    f"{'' if s is None else (f'{100 * s:+.1f}%' + (f' (invalid: {why_bad})' if why_bad else ''))} |")
    print("| project | status | go | tests | baseline-unstable | reproduced (of unstable) | documented test ran | "
          "documented flaky in baseline | documented reproduced | broken by --det (fails 3/3) | "
          "10/10 plain, no --det result | 10/10 plain, not 3/3 --det | fingerprint coverage | slowdown |")
    print("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    print("\n".join(rows))
    print()
    print(f"projects {tot['projects']} (done {tot['ok']}); tests {tot['tests']}; baseline-unstable {tot['unstable']}, "
          f"reproduced {tot['rep_unstable']} = {pct(tot['rep_unstable'], tot['unstable'])}; documented tests "
          f"{tot['documented']} (ran {tot['doc_seen']}, flaky in baseline {tot['doc_flaky_base']}, reproduced "
          f"{tot['rep_doc']}); broken by --det {tot['broken']}; passing 10/10 plain with no --det result "
          f"{tot['missing']}, passing 10/10 plain but not 3/3 under --det {tot['notall']}; fingerprint coverage "
          f"{pct(tot['cov_same'], tot['cov_total'])} (of {tot['cov_total']} tests with a --det result); median slowdown "
          f"{'n/a' if not slow else f'{100 * statistics.median(slow):+.1f}%'} over {len(slow)} valid comparisons "
          f"(left out: {invalid})")


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
    # broken by skip mode (R-025b S1): the fresh fenvix run fails where the
    # plain go test run of the same commit passes; tests with 10 or more
    print()
    for name, shards in sorted(by.items()):
        bad = collections.Counter()
        for s in shards:
            for c in s["commits"]:
                if c.get("status") != "ok" or c["i"] == 0:
                    continue
                for t in c["tests"]:
                    if t["fresh"] in ("failed", "interrupted") and t.get("plain") == "passed":
                        bad[(t["pkg"], t["test"])] += 1
        many = {k: v for k, v in bad.items() if v >= 10}
        verdicts = collections.Counter(ch["verdict"] for s in shards for c in s["commits"] for ch in c.get("checks", []))
        print(f"{name}: broken by skip mode (fresh fenvix failed, plain go test passed, in >= 10 commits): "
              f"{len(many)} tests {sorted(many.items())[:8]}; rerun verdicts {dict(verdicts)}")
    # gap to go's cache by test time (review R-025 N1): the time of tests go's
    # cache reused and fenvix ran, by fenvix's first own reason
    print()
    print("Test time go's cache reused and fenvix ran, by fenvix's reason (points of all test time):")
    print()
    print("| repository | gap | " + " | ".join(GAP_CLASSES) + " |")
    print("|---|---:|" + "---:|" * len(GAP_CLASSES))
    for name, shards in sorted(by.items()):
        tot, gap = 0.0, collections.Counter()
        for s in shards:
            for c in s["commits"]:
                if c.get("status") != "ok" or c["i"] == 0:
                    continue
                for t in c["tests"]:
                    if t["fresh"] in ("", "skipped"):
                        continue
                    el = t.get("elapsed") or 0.0
                    tot += el
                    if t["go_cached"] and not t["reuse"]:
                        gap[gap_class(t.get("why_own") or t["why"])] += el
        if tot:
            print(f"| {name} | {100 * sum(gap.values()) / tot:.1f} | " +
                  " | ".join(f"{100 * gap[k] / tot:.1f}" for k in GAP_CLASSES) + " |")


GAP_CLASSES = ["code-or-config", "network", "local-service", "clock", "exec", "telemetry", "file", "meta", "listing",
               "env", "unkeyed", "other"]


def gap_class(why):
    if "/.config/go/telemetry/" in why:
        return "telemetry"
    head = why.split(":")[0]
    if head in ("appeared", "vanished"):
        return "meta"
    if head == "volatile":
        return "unkeyed"
    return head if head in GAP_CLASSES else "other"


if __name__ == "__main__":
    {"flaky": flaky, "skip": skip}[sys.argv[1]](sys.argv[2])
