"""E1: pytest-randomly replay minutes are counted once per TARGET, but the harness
re-runs the suite once per SEED (targets sharing a first failing seed share the same
10 runs and the same 'seconds' list).  usage: python3 -I e1_randomly_replay_cost.py <results/block2>"""
import json, sys
from pathlib import Path
per_target = per_seed = seeds_total = shared = 0
for p in Path(sys.argv[1]).glob("*.randomly.block2.json"):
    R = json.loads(p.read_text()); by_seed = {}
    for t, v in R["replays"].items():
        per_target += sum(v["seconds"])
        if v["seed"] in by_seed:
            shared += 1
            assert by_seed[v["seed"]] == v["seconds"], (p, t)  # identical list: same runs
        by_seed[v["seed"]] = v["seconds"]
    per_seed += sum(sum(s) for s in by_seed.values())
    seeds_total += sum(x["seconds"] for x in R["seeds_log"])
print(f"report (per target): {per_target/60:.1f} min; actual (per distinct seed): {per_seed/60:.1f} min; targets sharing a seed's runs: {shared}")
print(f"randomly find+prove K=50: seed runs {seeds_total/60:.1f} + reruns {per_seed/60:.1f} = {(seeds_total+per_seed)/60:.1f} min (report: 610); detpy 579")
assert abs(per_target/60 - 423.8) < 0.1 and per_seed < per_target, "E1 not reproduced"
print("E1 reproduced")
