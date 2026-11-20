#!/usr/bin/env python3
"""Re-derive 'verified reuses' and 'wrong' for the all-runners walks from the committed raw files."""
import gzip, json, glob, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PY = {"ar-py-3": None, "ar-py-4": ["runner-ward-thoughtspot-tml-0of1.json.gz"]}
NODE = ["ar-node-1", "ar-node-2", "nb1", "node-c-r1"]
tot = {"verified": 0, "mism": 0, "wrong": 0, "unverified_reuses": 0}
rows = []
def load(p):
    with gzip.open(p) as f:
        return json.load(f)
for run, only in PY.items():
    for p in sorted(glob.glob(f"{ROOT}/tracks/all-runners-python/results/{run}/*.json.gz")):
        if only and os.path.basename(p) not in only: continue
        d = load(p); ver = mism = wrong = trans = sampled = reused = missing = 0
        for s in d["steps"]:
            if s.get("i", 0) == 0: continue
            trans += 1
            v = s.get("verify") or {}
            ver += v.get("checked", 0); mm = v.get("mismatches", []); mism += len(mm)
            wrong += sum(1 for m in mm if m.get("verdict") == "wrong")
            reused += s.get("n_reused", 0)
            if v.get("units") is not None and not (s.get("B") or {}).get("full", True): sampled += 1
        rows.append((run, os.path.basename(p), trans, ver, mism, wrong, reused, sampled))
for run in NODE:
    for p in sorted(glob.glob(f"{ROOT}/harness/node_cache/results/{run}/*.json.gz")):
        d = load(p); ver = mism = wrong = trans = reused = 0
        for c in d["commits"]:
            v = c.get("verify") or {}
            if v.get("cold"): continue
            trans += 1; s = v.get("summary") or {}
            ver += s.get("verified", 0); mm = s.get("verify_mismatches") or []; mism += len(mm)
            reused += s.get("reused_tests", 0) or 0
        rows.append((run, os.path.basename(p), trans, ver, mism, wrong, reused, 0))
print("| run | file | transitions | verified | mismatches | wrong(py verdict) | reused (sum) | sampled-verify steps |")
print("|---|---|---:|---:|---:|---:|---:|---:|")
for r in rows:
    print("| " + " | ".join(map(str, r)) + " |")
    tot["verified"] += r[3]; tot["mism"] += r[4]; tot["wrong"] += r[5]
print(f"\nTOTAL verified={tot['verified']} mismatches={tot['mism']} wrong={tot['wrong']} files={len(rows)}")
