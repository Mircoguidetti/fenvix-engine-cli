"""For placement tests (serial runs agree, a parallel run differs): is the difference confined to events whose call
site is outside the project (<site>/, <stdlib>)? Projection = events with a project call site, plus the outcome.
Only tests whose events are fully stored (not truncated) are classified."""
import glob, json, sys, collections
o = sys.argv[1]
TIMELESS = "--timeless" in sys.argv
def load(p):
    r = {}
    for f in glob.glob(p):
        if f.endswith("ran.json"):
            continue
        for l in open(f):
            x = json.loads(l)
            if x.get("type") == "test":
                r[x["nodeid"]] = x
    return r
SA, SB, PA, PB = (load(f"{o}/{p}") for p in ("ser-a.jsonl", "ser-b.jsonl", "n4-a.gw*.jsonl", "n4-b.gw*.jsonl"))
proj = lambda r: [(e["s"], e["o"], e["at"], None if (TIMELESS and e["s"] == "time") else e["v"]) for e in r["events"] if not e["at"].startswith(("<site>", "<stdlib>", "<end>"))] + [r["outcome"]]
c = collections.Counter()
for n in SA:
    if n not in SB or n not in PA or n not in PB or SA[n]["fingerprint"] != SB[n]["fingerprint"]:
        continue
    for P in (PA, PB):
        if SA[n]["fingerprint"] != P[n]["fingerprint"]:
            if SA[n]["truncated"] or P[n]["truncated"]:
                c["truncated (not classified)"] += 1
            elif proj(SA[n]) == proj(P[n]):
                c["project events equal (difference only in library call sites)"] += 1
            else:
                c["project events differ"] += 1
            break
print(json.dumps(dict(c), indent=1))
