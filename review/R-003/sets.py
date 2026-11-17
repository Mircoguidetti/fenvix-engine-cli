import json, sys
from pathlib import Path
d = Path(sys.argv[1])
det = {j["name"]: j for j in (json.loads(p.read_text()) for p in d.glob("*.detpy.block2.json"))}
rnd = {j["name"]: j for j in (json.loads(p.read_text()) for p in d.glob("*.randomly.block2.json"))}
def ff(log):
    o = {}
    for x in log:
        for n in x["failing"]: o.setdefault(n, x["seed"])
    return o
DF, RF, DR, R10 = set(), set(), set(), set()
for r in det:
    D, R = det[r], rnd[r]; dff, rff = ff(D["seeds_log"]), ff(R["seeds_log"]); B = {b["test"]: b for b in D["bundles"]}
    for t in D["targets"]:
        if t in dff: DF.add((r, t))
        if t in rff: RF.add((r, t))
        if B.get(t, {}).get("status") == "reproduced": DR.add((r, t))
        rp = R["replays"].get(t)
        if rp and rp["fails"] == rp["runs"] == 10: R10.add((r, t))
print("DF", len(DF), "RF", len(RF), "DR", len(DR), "R10", len(R10))
print("RF-DF", len(RF - DF), sorted(RF - DF)); print("DF-RF", len(DF - RF), sorted(DF - RF))
print("RF-DR", len(RF - DR)); print("DR-RF", len(DR - RF), sorted(DR - RF))
print("panamah targets", det["idoft-panamah-sdk-python"]["targets"])
print("panamah det ff", {t: s for t, s in ff(det["idoft-panamah-sdk-python"]["seeds_log"]).items()})
print("panamah rnd ff", rnd["idoft-panamah-sdk-python"]["first_fail"], rnd["idoft-panamah-sdk-python"]["replays"].keys())
for r in det:
    for x in rnd[r]["replays"].items():
        if x[1]["fails"] != 10: print("rnd replay not 10/10", r, x[0], x[1]["fails"], x[1]["runs"])
