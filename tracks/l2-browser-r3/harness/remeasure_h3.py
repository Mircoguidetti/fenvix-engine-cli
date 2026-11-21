#!/usr/bin/env python3
"""Review R-011 H3: write the round-3 re-measurement of a printed replay command into the round-2 result it corrects.

The round-2 value is kept (`replay_cmd_outcome_r2`), the new one is labelled with its run and engine commit.
  python3 tracks/l2-browser-r3/harness/remeasure_h3.py   (reads results/e1-actual.json of round 3)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R3 = json.loads((ROOT / "l2-browser-r3" / "results" / "e1-actual.json").read_text())
P2 = ROOT / "l2-browser-r2" / "results" / "actual.json"
R2 = json.loads(P2.read_text())

for x in R3.get("replay") or []:
    for t in R2.get("targets") or []:
        if t.get("replay_cmd") and x["grep"] in (t.get("matched_key") or t.get("key") or "") and x.get("printed_outcome"):
            if "replay_cmd_outcome_r2" not in t:
                t["replay_cmd_outcome_r2"] = t.get("replay_cmd_outcome")
                t["replay_cmd_r2"] = t.get("replay_cmd")
            t["replay_cmd_outcome"] = x["printed_outcome"]
            t["replay_cmd"] = x["printed"]
            t["replay_cmd_verify"] = None  # not comparable with the round-2 failing-seed traces
            t["replay_cmd_remeasured"] = {
                "why": "review R-011 H3: the round-2 command dropped --browser=chromium, matched no project, ran no test",
                "run_id": R3.get("run_id"), "engine_commit": R3.get("engine_commit"),
                "seed_outcome": x.get("seed_outcome"), "label": "MEASURED"}
            print(f"{t.get('matched_key')}: {t['replay_cmd_outcome_r2']} -> {t['replay_cmd_outcome']} (run {R3.get('run_id')})")
P2.write_text(json.dumps(R2, indent=1, sort_keys=False) + "\n")
