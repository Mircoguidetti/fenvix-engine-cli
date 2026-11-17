"""E2, E3, E5 from the raw data.  usage: python3 -I e2_e3_e5_data.py <results/block2>"""
import json, sys, collections
from pathlib import Path
d = Path(sys.argv[1]); L = lambda n, t: json.loads((d / f"{n}.{t}.block2.json").read_text())
# E2: the target with status not-found in panamah
P = L("idoft-panamah-sdk-python", "detpy")
nf = [b["test"] for b in P["bundles"] if b["status"] == "not-found"]
fails = {n for x in P["seeds_log"] for n in x["failing"]}
print("E2 not-found bundle:", nf, "| report names test_expiration_by_max_size; detpy ever failed it:",
      "tests/test_processor.py::TestStream::test_expiration_by_max_size" in fails)
# E3: flask-multi-redis targets
D, Rn = L("idoft-flask-multi-redis", "detpy"), L("idoft-flask-multi-redis", "randomly")
cd = collections.Counter(n for x in D["seeds_log"] for n in x["failing"])
cr = collections.Counter(n for x in Rn["seeds_log"] for n in x["failing"])
B = {b["test"]: b for b in D["bundles"]}
for t in D["targets"]:
    b = B[t]
    print("E3", t.split("::")[-1], f"detpy fails {cd[t]}/50 (always_failing={t in D['always_failing']}) randomly {cr[t]}/50 |",
          b["status"], b["kind"], b["replay"]["fails"], "/10 |", b["exception"][2], "@", b["exception"][3].split("site-packages/")[-1])
# E5: eppy cost split at K=50
S = json.loads((d / "summary.json").read_text())["per_repo"]
for n in ("idoft-eppy", "anyio"):
    c = S[n]["cost"]["50"]
    print(f"E5 {n}: repro {c['detpy_repro_s']/60:.1f} min, explore {c['detpy_explore_s']/60:.1f} min, total {(c['detpy_repro_s']+c['detpy_explore_s'])/60:.1f}")
