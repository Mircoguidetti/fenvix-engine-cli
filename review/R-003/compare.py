import json, sys, collections
from pathlib import Path
d = Path(sys.argv[1])
det = {j["name"]: j for j in (json.loads(p.read_text()) for p in d.glob("*.detpy.block2.json"))}
rnd = {j["name"]: j for j in (json.loads(p.read_text()) for p in d.glob("*.randomly.block2.json"))}
def ff(log):
    o = {}
    for x in log:
        for n in x["failing"]: o.setdefault(n, x["seed"])
    return o
onlyR, onlyD = [], []
dx, rx = set(), set()
fam_p = fam_d = 0; famsizes = []
for r in sorted(det):
    D, R = det[r], rnd[r]
    dff, rff = ff(D["seeds_log"]), ff(R["seeds_log"])
    B = {b["test"]: b for b in D["bundles"]}
    for t in D["targets"]:
        if t in rff and t not in dff: onlyR.append((r, t, "never" ))
        elif t in rff and B.get(t, {}).get("status") != "reproduced": onlyR.append((r, t, B[t]["status"] + " fails %s/%s" % (B[t].get("replay",{}).get("fails"), B[t].get("replay",{}).get("runs"))))
        if t in dff and B[t]["status"] == "reproduced" and t not in rff: onlyD.append((r, t))
    # flaky outside targets: failing under some seed but not all
    def flaky(log):
        nseeds = len(log); c = collections.Counter(n for x in log for n in x["failing"])
        return {n for n, k in c.items() if k < nseeds}
    df_, rf_ = flaky(D["seeds_log"]) - set(D["targets"]), flaky(R["seeds_log"]) - set(R["targets"])
    dx |= {(r, n) for n in df_}; rx |= {(r, n) for n in rf_}
    # also detpy's own flaky_failing field
    ffield = set(D["flaky_failing"]) - set(D["targets"])
    if ffield != df_: print("flaky field differs", r, len(ffield), len(df_))
    if r == "idoft-flask-multi-redis": print("fmr: detpy flaky-outside", len(df_), "randomly", len(rf_), "detpy always_failing", len(D["always_failing"]), "seeds d/r", len(D["seeds_log"]), len(R["seeds_log"]))
    fam_p += len(D["families_by_polluter"]); fam_d += len(D["families_by_divergence"])
    for k, v in D["families_by_polluter"].items(): famsizes.append((r, k[:50], len(v)))
    tests_d = sorted({x["tests"] for x in D["seeds_log"]}); tests_r = sorted({x["tests"] for x in R["seeds_log"]})
    print(f"{r:32s} seeds {len(D['seeds_log'])}/{len(R['seeds_log'])} tests det {tests_d[:3]} rnd {tests_r[:3]} collected {D.get('collected')} timeouts d{sum(x['timed_out'] for x in D['seeds_log'])} r{sum(x['timed_out'] for x in R['seeds_log'])} exits d{sorted({x['exit'] for x in D['seeds_log']})} r{sorted({x['exit'] for x in R['seeds_log']})}")
print("only randomly", len(onlyR)); [print("  ", x) for x in onlyR]
print("only detpy", len(onlyD)); [print("  ", x) for x in onlyD]
print("outside flaky: detpy", len(dx), "randomly", len(rx), "common", len(dx & rx))
print("families polluter", fam_p, "divergence", fam_d, "members in polluter fams", sum(x[2] for x in famsizes))
