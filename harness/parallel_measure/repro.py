#!/usr/bin/env python3
"""Reproduction runs without the engine, for classify.py (not timings: nothing here enters TABLE.md's wall clocks).

For one repository (specs.json), runs the plain runner, no engine, several ways, and keeps each run's per-test
outcome map:

  par4-K     the runner's own parallel mode, 4 workers (pytest -n 4 -p no:detpy; vitest --maxWorkers=4
             --fileParallelism; jest --maxWorkers=4), K = 1..--runs
  shuffle-S  serial, files and tests shuffled with seed S (pytest -p randomly is not assumed: -p no:detpy with
             pytest-randomly when installed, else skipped; vitest --sequence.shuffle --sequence.seed=S;
             jest --randomize --seed=S)

Output: <out>/<repo>/repro/<name>.json (outcome map) and one line per run in <out>/repro.jsonl.
Usage: repro.py --spec specs.json --name REPO --out DIR [--runs 2] [--seeds 1,2]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time

import measure as M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--seeds", default="1,2")
    ap.add_argument("--timeout", type=int, default=3600)
    o = ap.parse_args()
    spec = json.load(open(o.spec))[o.name]
    cwd = os.path.expandvars(spec["dir"])
    out = os.path.abspath(os.path.join(o.out, o.name, "repro"))
    os.makedirs(out, exist_ok=True)
    log = os.path.join(out, "repro.log")
    env = {k: v for k, v in os.environ.items() if k not in M.VOLATILE}
    env.update({k: os.path.expandvars(v) for k, v in spec.get("env", {}).items()})
    runner, args = spec["runner"], spec.get("args", [])
    plans = []
    for k in range(1, o.runs + 1):
        plans.append((f"par4-{k}", "par", None))
    for s in [x for x in o.seeds.split(",") if x]:
        plans.append((f"shuffle-{s}", "shuffle", s))
    for name, mode, seed in plans:
        f = os.path.join(out, f"{name}.raw.json")
        if runner == "pytest":
            py = os.path.expandvars(spec["python"])
            cmd = [py, "-m", "pytest"] + args + [f"--det-outcomes={f}"]
            if mode == "par":
                cmd += ["-n", "4"]
            else:
                chk = subprocess.run([py, "-c", "import pytest_randomly"], capture_output=True)
                if chk.returncode != 0:
                    continue
                cmd += ["-p", "randomly", f"--randomly-seed={seed}"]
        else:
            direct = ["npx", "--no-install", runner] + (["run"] if runner == "vitest" else []) + args
            if runner == "vitest":
                rep = ["--reporter=default", "--reporter=json", f"--outputFile.json={f}", "--reporter={rep}"]
                extra = ["--maxWorkers=4", "--fileParallelism"] if mode == "par" else \
                    ["--no-file-parallelism", "--sequence.shuffle", f"--sequence.seed={seed}"]
            else:
                rep = ["--json", f"--outputFile={f}"]
                extra = ["--maxWorkers=4"] if mode == "par" else ["--runInBand", "--randomize", f"--seed={seed}"]
            cmd = direct + extra + rep
        M.reset_tree(cwd)
        built = M.build_after_reset(cwd, spec.get("build"), env, log)
        rep_path = M.place_reporter(cwd) if runner == "vitest" else None
        f_ids = f.replace(".raw.json", ".ids.json")
        cmd = [c.replace("{rep}", rep_path) if rep_path else c for c in cmd]
        r, text = M.run(cmd, cwd, {**env, "PM_IDS_OUT": f_ids}, log, o.timeout)
        oc = M.outcomes_file(f) if runner == "pytest" else (M.ids_outcomes(f_ids, cwd) if os.path.exists(f_ids) else M.runner_outcomes(f, cwd))
        oc = M.norm(oc)
        bad = M.plain_invalid(runner, r, text, len(oc))
        if bad:
            r["invalid"] = bad
            oc = {}  # no outcome data from an INVALID run
        if not bad:  # an INVALID run leaves no outcome map for classify.py
            with open(os.path.join(out, f"{name}.json"), "w") as g:
                json.dump(oc, g)
        line = {"repo": o.name, "run": name, "cmd": " ".join(cmd), "cwd": cwd, "tests": len(oc),
                "outcome_counts": M.counts(oc), "engine_commit": M.engine_commit(),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **built, **r}
        with open(os.path.join(os.path.abspath(o.out), "repro.jsonl"), "a") as g:
            g.write(json.dumps(line) + "\n")
        print(json.dumps({k: line[k] for k in ("repo", "run", "exit", "wall_s", "tests")}), flush=True)


if __name__ == "__main__":
    main()
