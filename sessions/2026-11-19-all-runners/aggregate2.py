#!/usr/bin/env python3
"""claude/all-runners-2 walks (REPORT-2): per repository, from the committed raw files, counting TESTS (review R-032
F8: never file entries).

Python (tracks/all-runners-python/results/ar2-py-*): run B = the runner under --det without cache, a separate fresh
run of the same commit; verified = reused tests compared with B (verify.checked); wrong = a mismatch whose recheck
(B') confirms it (verdict "wrong").
Node (harness/node_cache/results/ar2-node-*): two checks per transition, both per test:
  fresh  = the skip run's reused tests compared with a SEPARATE fresh run `detjs <runner> --det` without cache
           (compare.checked; a mismatch is rechecked by two more fresh runs, confirmed when all disagree);
  engine = the engine's own --det-cache-verify run (summary.verified_tests, verify_mismatches_tests).
Reuse share = reused tests / tests of the transition (median / mean over transitions); Python also by test time.
Usage: python3 aggregate2.py [--json]
"""
import glob
import gzip
import json
import os
import statistics
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def load(p):
    with gzip.open(p) as f:
        return json.load(f)


def med_mean(xs):
    return (round(100 * statistics.median(xs)), round(100 * statistics.mean(xs))) if xs else (None, None)


rows = []
for p in sorted(glob.glob(f"{ROOT}/tracks/all-runners-python/results/ar2-py-*/*.json.gz")):
    d = load(p)
    name = os.path.basename(p).rsplit("-", 1)[0]
    r = next((x for x in rows if x["repo"] == name), None)
    if r is None:
        r = {"lang": "python", "repo": name, "runs": set(), "files": [], "engine": set(), "transitions": 0,
             "verified": 0, "mismatches": 0, "wrong": 0, "share_tests": [], "share_time": []}
        rows.append(r)
    r["runs"].add(os.path.basename(os.path.dirname(p)))
    r["files"].append(os.path.relpath(p, ROOT))
    r["engine"].add((d.get("engine") or "")[:8])
    for s in d.get("steps", [])[1:]:  # the shard's first commit records only
        r["transitions"] += 1
        v = s.get("verify") or {}
        r["verified"] += v.get("checked", 0) or 0
        mm = v.get("mismatches") or []
        r["mismatches"] += len(mm)
        r["wrong"] += sum(1 for m in mm if m.get("verdict") == "wrong")
        if s.get("n_tests"):
            r["share_tests"].append((s.get("n_reused") or 0) / s["n_tests"])
        if s.get("time_total"):
            r["share_time"].append((s.get("time_reused") or 0) / s["time_total"])

for p in sorted(glob.glob(f"{ROOT}/harness/node_cache/results/ar2-node-*/*.json.gz")):
    d = load(p)
    name = os.path.basename(p).rsplit("-", 1)[0].removesuffix(".json")
    r = next((x for x in rows if x["repo"] == name), None)
    if r is None:
        r = {"lang": "node", "repo": name, "runs": set(), "files": [], "engine": set(), "transitions": 0,
             "verified": 0, "mismatches": 0, "wrong": 0, "missing": 0, "engine_verified": 0, "engine_mismatches": 0,
             "share_tests": [], "share_time": []}
        rows.append(r)
    r["runs"].add(os.path.basename(os.path.dirname(p)))
    r["files"].append(os.path.relpath(p, ROOT))
    for c in d.get("commits", []):
        cmp_ = c.get("compare")
        if cmp_ is None:
            continue  # the shard's first commit records only
        r["transitions"] += 1
        r["verified"] += cmp_.get("checked", 0)
        r["mismatches"] += len(cmp_.get("mismatches") or [])
        r["wrong"] += cmp_.get("confirmed_wrong", 0)
        r["missing"] += cmp_.get("n_missing", 0)
        s = (c.get("verify") or {}).get("summary") or {}
        r["engine_verified"] += s.get("verified_tests") or 0
        r["engine_mismatches"] += s.get("verify_mismatches_tests") or 0
        n = (c.get("fresh") or {}).get("n") or 0
        if n:
            r["share_tests"].append((cmp_.get("checked", 0) + cmp_.get("n_missing", 0)) / n)

if "--json" in sys.argv:
    print(json.dumps([{**r, "runs": sorted(r["runs"]), "engine": sorted(r["engine"])} for r in rows], indent=1))
    sys.exit()
print("| lang | repository | runs | transitions | reuse share by tests (median / mean %) | by time (median / mean %) | "
      "tests verified (fresh run) | mismatches | wrong (confirmed) | engine verify (tests) |")
print("|---|---|---|---:|---|---|---:|---:|---:|---:|")
tot = {"python": [0, 0, 0], "node": [0, 0, 0]}
for r in rows:
    st, sm = med_mean(r["share_tests"])
    tt, tm = med_mean(r["share_time"])
    ev = f"{r['engine_verified']} ({r['engine_mismatches']} differ)" if r["lang"] == "node" else "—"
    print(f"| {r['lang']} | {r['repo']} | {', '.join(sorted(r['runs']))} | {r['transitions']} | {st} / {sm} | "
          f"{'—' if tt is None else f'{tt} / {tm}'} | {r['verified']} | {r['mismatches']} | {r['wrong']} | {ev} |")
    t = tot[r["lang"]]
    t[0] += r["verified"]; t[1] += r["mismatches"]; t[2] += r["wrong"]
for k, (v, m, w) in tot.items():
    print(f"\nTOTAL {k}: tests verified {v}, mismatches {m}, confirmed wrong {w}")
print(f"\nTOTAL: tests verified {tot['python'][0] + tot['node'][0]}, confirmed wrong {tot['python'][2] + tot['node'][2]}")
