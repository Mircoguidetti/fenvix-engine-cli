"""Independent recompute of Block 2 exit numbers from the raw per-repo JSON files.
usage: python3 -I recompute.py <results/block2 dir>"""
import json, sys, statistics as st, collections
from pathlib import Path
d = Path(sys.argv[1])
det = {}; rnd = {}
for p in d.glob("*.detpy.block2.json"):
    j = json.loads(p.read_text()); det[j["name"]] = j
for p in d.glob("*.randomly.block2.json"):
    j = json.loads(p.read_text()); rnd[j["name"]] = j
repos = sorted(set(det) | set(rnd))
print("repos", len(repos), "det", len(det), "rnd", len(rnd))
def ff(log):
    o = {}
    for x in sorted(log, key=lambda x: x["seed"]):
        for n in x["failing"]: o.setdefault(n, x["seed"])
    return o
T = []
for r in repos:
    D, R = det[r], rnd[r]
    assert D["targets"] == R["targets"], r
    dff, rff = ff(D["seeds_log"]), ff(R["seeds_log"])
    assert rff == R["first_fail"], r
    B = {b["test"]: b for b in D["bundles"]}
    for t in D["targets"]:
        T.append(dict(repo=r, t=t, dff=dff.get(t), rff=rff.get(t), b=B.get(t), rp=R["replays"].get(t)))
print("targets", len(T), "unique", len({(x['repo'],x['t']) for x in T}))
n = len(T)
pc = lambda a: f"{a} ({100*a/n:.1f}%)"
print("\nTable 1")
for K in (1,5,10,20,50):
    df = [x for x in T if x["dff"] and x["dff"] <= K]
    ident = sum(1 for x in df if x["b"] and (x["b"].get("replay") or {"fails":-1,"runs":-2,"identical_fingerprint":False})["fails"] == (x["b"].get("replay") or {"fails":-1,"runs":-2,"identical_fingerprint":False})["runs"] == 10 and (x["b"].get("replay") or {"fails":-1,"runs":-2,"identical_fingerprint":False})["identical_fingerprint"])
    any10 = sum(1 for x in df if x["b"] and x["b"].get("replay") and (x["b"].get("replay") or {"fails":-1,"runs":-2,"identical_fingerprint":False})["fails"] == (x["b"].get("replay") or {"fails":-1,"runs":-2,"identical_fingerprint":False})["runs"] == 10)
    stat_rep = sum(1 for x in df if x["b"] and x["b"]["status"] == "reproduced")
    rf = [x for x in T if x["rff"] and x["rff"] <= K]
    r10 = sum(1 for x in rf if x["rp"] and x["rp"]["runs"] == 10 and x["rp"]["fails"] == 10)
    print(K, pc(len(df)), pc(ident), "(status reproduced", stat_rep, ")", pc(any10), pc(len(rf)), pc(r10))
print("\nTable 2")
bund = [x for x in T if x["b"]]
print("targets failed<=50", sum(1 for x in T if x["dff"]), "bundles", len(bund), collections.Counter(x["b"]["status"] for x in bund))
ok = [x for x in bund if (x["b"].get("replay") or {"fails":-1,"runs":-2,"identical_fingerprint":False})["fails"] == (x["b"].get("replay") or {"fails":-1,"runs":-2,"identical_fingerprint":False})["runs"] == 10 and (x["b"].get("replay") or {"fails":-1,"runs":-2,"identical_fingerprint":False})["identical_fingerprint"]]
print("10/10 identical", len(ok))
for x in bund:
    b = x["b"]
    if x not in ok:
        print("  nonident:", x["repo"], x["t"][-60:], b["status"], b.get("replay",{}).get("fails"), b.get("replay",{}).get("runs"), len(b.get("replay",{}).get("fingerprints",[])), (b.get("divergence") or {}).get("reason"))
for x in T:
    if x["dff"] and not x["b"]: print("  failed, no bundle:", x["repo"], x["t"])
    if not x["dff"] and x["b"]: print("  bundle but not failed:", x["repo"], x["t"])
print("\nTable 3 (over status reproduced)")
rep = [x["b"] for x in bund if x["b"]["status"] == "reproduced"]
print("n", len(rep), "prefix median/max", st.median([b["prefix_length"] for b in rep]), max(b["prefix_length"] for b in rep))
print("minimal median/max", st.median([b["minimal_length"] for b in rep]), max(b["minimal_length"] for b in rep), collections.Counter(b["minimal_length"] for b in rep))
print("polluter", sum(1 for b in rep if b["polluters"]), "setter", sum(1 for b in rep if b["setters"]), "both", sum(1 for b in rep if b["polluters"] and b["setters"]), "neither", sum(1 for b in rep if not b["polluters"] and not b["setters"]), collections.Counter(b["kind"] for b in rep))
print("runs median/max", st.median([b["runs"] for b in rep]), max(b["runs"] for b in rep), "sec median/max", st.median([b["seconds"] for b in rep]), max(b["seconds"] for b in rep))
print("div reasons", collections.Counter((b.get("divergence") or {}).get("reason") for b in rep))
print("\nTable 4 (minutes)")
for K in (1,5,10,20,50):
    ex, rp, rr, tot = [], [], [], []
    for r in repos:
        D, R = det[r], rnd[r]
        dff = ff(D["seeds_log"])
        e = sum(x["seconds"] for x in D["seeds_log"] if x["seed"] <= K)
        p = sum(b.get("seconds") or 0 for b in D["bundles"] if dff.get(b["test"]) and dff[b["test"]] <= K)
        q = sum(x["seconds"] for x in R["seeds_log"] if x["seed"] <= K)
        ex.append(e/60); rp.append(p/60); rr.append(q/60); tot.append((e+p)/60)
    print(K, "explore %.2f / %.1f" % (st.median(ex), sum(ex)), "repro %.2f / %.1f" % (st.median(rp), sum(rp)), "randomly %.2f / %.1f" % (st.median(rr), sum(rr)), "explore+repro median/max %.1f / %.1f" % (st.median(tot), max(tot)))
# randomly replay cost: per target sum (as report) vs per distinct seed (actual)
pt = 0; ps = 0
for r in repos:
    R = rnd[r]; seen = {}
    for t, v in R["replays"].items():
        pt += sum(v["seconds"]); seen[v["seed"]] = sum(v["seconds"])
    ps += sum(seen.values())
print("\nrandomly replay min: per-target sum %.1f, per distinct seed (actual wall) %.1f" % (pt/60, ps/60))
dp = sum(b.get("seconds") or 0 for r in repos for b in det[r]["bundles"]) / 60
print("detpy repro all bundles min %.1f" % dp)
print("detpy explore seconds field total min %.1f, randomly seconds field total min %.1f" % (sum(det[r]["seconds"] for r in repos)/60, sum(rnd[r]["seconds"] for r in repos)/60))
