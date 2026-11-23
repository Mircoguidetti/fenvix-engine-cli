#!/usr/bin/env python3
"""Run the customer path once per engine and repository (cold: a fresh cache directory each time):

    runner/fenvix-run node --project <repo> --runner vitest --cache <fresh dir> --out <dir> --detjs "node <engine>/node/bin/detjs.js"

Same hygiene as pins.py (tree reset keeping node_modules, TMPDIR=/tmp/pm-<repo> emptied). Writes
<out>/<engine>/<repo>/{summary.json, run.json, run.log}.

    python3 harness/det_host_values/customer_run.py --out DIR --engine trunk=/tmp/fenvix-trunk --engine branch=$PWD
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "det_pins"))
sys.path.insert(0, os.path.join(HERE, "..", "parallel_measure"))
import pins  # noqa: E402
from measure import reset_tree  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine", action="append", required=True, help="name=checkout")
    ap.add_argument("--repo", action="append", default=None)
    o = ap.parse_args()
    for repo in o.repo or ["ironcurtain", "codex-multi-auth"]:
        spec = pins.load_spec(repo)
        cwd = os.path.expandvars(spec["dir"])
        for e in o.engine:
            name, checkout = e.split("=", 1)
            commit = subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            d = os.path.join(o.out, name, repo)
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
            cache = os.path.join(d, "cache")
            reset_tree(cwd)
            env = pins.base_env(repo, spec)
            cmd = [os.path.join(ROOT, "runner", "fenvix-run"), "node", "--project", cwd, "--runner", "vitest",
                   "--cache", cache, "--out", d, "--detjs", f"node {checkout}/node/bin/detjs.js"]
            t0 = time.time()
            with open(os.path.join(d, "run.log"), "w") as log:
                p = subprocess.run(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=7200)
            wall = round(time.time() - t0, 2)
            json.dump({"repo": repo, "engine": name, "engine_commit": commit, "cmd": cmd, "cwd": cwd, "exit": p.returncode,
                       "wall_s": wall, "at": pins.now_iso()}, open(os.path.join(d, "run.json"), "w"), indent=1)
            shutil.rmtree(cache, ignore_errors=True)
            print(f"{repo} {name} exit={p.returncode} {wall}s", flush=True)


if __name__ == "__main__":
    main()
