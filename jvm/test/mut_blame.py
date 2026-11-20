#!/usr/bin/env python3
"""Review R-022b: per capture, how many tests are `mut` and which classes are blamed (mut_classes of the test and its non-session scopes).

  python3 jvm/test/mut_blame.py <deps dir> <out.json> [top N]
"""
import sys, json, glob, collections
n = 0; mutn = 0; blame = collections.Counter(); sets = []; ids=[]
for f in sorted(glob.glob(sys.argv[1] + "/*.jsonl")):
    recs = [json.loads(l) for l in open(f) if l.strip()]
    scopes = {r["id"]: r for r in recs if r["type"] not in ("test", "jvm")}
    for r in recs:
        if r["type"] != "test": continue
        n += 1
        ch = [r] + [scopes[s] for s in r.get("scopes", []) if s in scopes]
        mc = set(); mut = False
        for s in ch:
            if s.get("type") == "session": continue
            if s.get("mut"): mut = True; mc |= set(s.get("mut_classes") or [])
        if mut: mutn += 1; sets.append(sorted(mc)); blame.update(mc); ids.append(r["id"])
print("tests", n, "mut", mutn)
for c, k in blame.most_common(int(sys.argv[3]) if len(sys.argv)>3 else 30): print(f"{k:5} {c}")
json.dump({"tests": n, "mut": mutn, "sets": dict(zip(ids, sets))}, open(sys.argv[2], "w"))
