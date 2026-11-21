#!/usr/bin/env python3
"""Summary table of harness/node_parallel/results/*.json (measure.py)."""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
rows = []
for p in sorted(glob.glob(os.path.join(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results"), "*.json"))):
    r = json.load(open(p))
    pv = r["parallel_vs_serial"]
    w = r["cache_warm_parallel"]
    wr = r["wrong_reuse_vs_fresh_serial"]
    v = r["cache_verify_parallel"]
    rows.append([
        r["name"], r["runner"], str(r["det_serial"].get("tests")),
        f"{r['plain']['wall_s']} (exit {r['plain']['exit']})", f"{r['det_serial']['wall_s']} (exit {r['det_serial']['exit']})",
        f"{r['det_parallel']['wall_s']} (exit {r['det_parallel']['exit']})",
        f"{r['det_parallel'].get('lanes')} dev {r['det_parallel'].get('deviations')} hz {r['det_parallel'].get('hazards')} carried {r['det_parallel'].get('carried')}",
        "yes" if r["plan_identical"] else "NO",
        f"{pv['equal_fingerprint_and_outcome']}/{pv['common']} (outcome {pv['equal_outcome']}; only-par {pv['only_a']}, only-ser {pv['only_b']})"
        + (f"; serial noise {len(r.get('serial_noise', {}).get('differ', []))}, not noise {len(r.get('parallel_differs_not_noise', []))}" if pv["differ"] else ""),
        f"{r['cache_cold_parallel']['wall_s']} rec {r['cache_cold_parallel'].get('recorded')}",
        f"{w['wall_s']} reuse {w.get('reused_tests')}/{w.get('total_tests')} ({w.get('reuse_pct')} %)",
        f"{wr['wrong_outcome']} of {wr['reused_checked']} (fp equal {wr['fingerprint_equal']})",
        f"{v.get('mismatches_tests')} of {v.get('verified_tests')}",
        f"{r['cache_warm_serial_on_parallel_store'].get('reused_tests')}",
    ])
head = ["project", "runner", "tests", "plain s", "--det serial s", "--det 4 lanes s", "lanes/deviations/hazards/carried", "plan same 2 runs",
        "fingerprint+outcome par = ser", "cold cache par s", "warm cache par s", "wrong reuse vs fresh serial", "verify mismatches (par)", "serial reuse of par store"]
print("| " + " | ".join(head) + " |")
print("|" + "---|" * len(head))
for row in rows:
    print("| " + " | ".join(row) + " |")
