#!/usr/bin/env python3
"""Measure parallel `--det` (detjs `--det-workers`, row JS-07) on a checked-out, installed project.

Runs, one after another on an otherwise idle machine, each timed (wall seconds):

1. plain: the project's runner without detjs' controls (`detjs <runner>` without `--det`: the runner's own CLI and
   its own parallelism);
2. `--det` serial (the default), trace S;
3. `--det --det-workers=N` twice, traces P1, P2 (plan identity between them);
4. fingerprints: per test id, outcome and fingerprint of P1 against S (and, when they differ, S against a second
   serial run S2: serial noise);
5. cache in parallel: cold `--det --det-workers=N --det-cache=C` (records), warm run (reuse share, wall), a fresh
   `--det` serial run without cache F: every reused test's receipt outcome against F's outcome (a wrong reuse is a
   reused outcome the fresh run contradicts; fingerprints compared too), then `--det-cache-verify` in parallel (the
   same decision, every file run, cached vs fresh compared by the engine), then a serial warm run on the store the
   parallel runs wrote (serial reuse of parallel entries).

Output: <out>/<name>.json with every number and the exact commands.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", ".."))
DETJS = os.path.join(ENGINE, "node", "bin", "detjs.js")


def env():
    e = dict(os.environ)
    for k in ("CI", "GITHUB_ACTIONS", "DETJS", "NODE_OPTIONS", "DETJS_SEED", "DETJS_CACHE_DIR"):
        e.pop(k, None)
    return e


def run(cmd, cwd, log, timeout=3600):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           errors="replace", timeout=timeout)
        code, out = r.returncode, r.stdout
    except subprocess.TimeoutExpired as e:
        code, out = 124, (e.output or "") if isinstance(e.output, str) else ""
    dt = time.time() - t0
    with open(log, "a") as f:
        f.write(f"\n$ (cd {cwd} && {' '.join(cmd)})  # exit {code}, {dt:.2f} s\n{out[-6000:]}\n")
    return code, out, dt


def trace(cwd):
    p = os.path.join(cwd, ".detjs", "trace.jsonl")
    tests = {}
    header = None
    with open(p) as f:
        for line in f:
            if not line.strip():
                continue
            j = json.loads(line)
            if j.get("type") == "header":
                header = j
            elif j.get("type") == "test":
                tests[j["nodeid"]] = (j.get("outcome"), j.get("fingerprint"))
    return header, tests


def summary(cwd):
    try:
        with open(os.path.join(cwd, ".detjs", "cache-summary.json")) as f:
            return json.load(f)
    except OSError:
        return None


def receipts(cwd):
    out = {}
    with open(os.path.join(cwd, ".detjs", "receipts.jsonl")) as f:
        for line in f:
            if line.strip():
                j = json.loads(line)
                if j.get("reused") and "::" in j["nodeid"]:
                    out[j["nodeid"]] = (j.get("outcome"), j.get("fingerprint"))
    return out


def compare(a, b):
    common = sorted(set(a) & set(b))
    same_fp = [k for k in common if a[k] == b[k]]
    same_outcome = [k for k in common if a[k][0] == b[k][0]]
    return {"common": len(common), "only_a": len(set(a) - set(b)), "only_b": len(set(b) - set(a)),
            "equal_fingerprint_and_outcome": len(same_fp), "equal_outcome": len(same_outcome),
            "differ": [k for k in common if a[k] != b[k]][:50]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--runner", required=True, choices=["vitest", "jest"])
    ap.add_argument("--args", default="", help="runner arguments (space separated)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", required=True)
    o = ap.parse_args()
    cwd = os.path.abspath(o.dir)
    os.makedirs(o.out, exist_ok=True)
    log = os.path.join(o.out, f"{o.name}.log")
    open(log, "w").close()
    shutil.rmtree(os.path.join(cwd, ".detjs"), ignore_errors=True)
    cache = os.path.join(cwd, ".detjs-par-cache")
    shutil.rmtree(cache, ignore_errors=True)
    base = ["node", DETJS, o.runner] + (["run"] if o.runner == "vitest" else []) + [a for a in o.args.split() if a]
    W = [f"--det-workers={o.workers}"]
    res = {"name": o.name, "runner": o.runner, "workers": o.workers, "commands": {}}

    def step(key, extra, keep_trace=False):
        cmd = base + extra
        code, out, dt = run(cmd, cwd, log)
        res["commands"][key] = " ".join(cmd)
        res[key] = {"exit": code, "wall_s": round(dt, 2)}
        if keep_trace:
            h, t = trace(cwd)
            res[key]["tests"] = len(t)
            meta = (h or {}).get("meta", {})
            par = meta.get("parallel") or {}
            if par.get("plan"):
                res[key]["plan_digest"] = par["plan"]["digest"]
                res[key]["lanes"] = [len(x) for x in par["plan"]["lanes"]]
                res[key]["deviations"] = len(par.get("placement", {}).get("deviations", []))
                res[key]["hazards"] = len(par.get("hazards", []))
                res[key]["waited_s"] = par.get("placement", {}).get("waited_seconds")
            res[key]["carried"] = len(par.get("carried", []))
            if par.get("requested", {}) and par["requested"].get("refused"):
                res[key]["refused"] = par["requested"]["refused"]
            return t
        return None

    step("plain", [])
    S = step("det_serial", ["--det"], keep_trace=True)
    P1 = step("det_parallel", ["--det"] + W, keep_trace=True)
    step("det_parallel_2", ["--det"] + W, keep_trace=True)
    res["plan_identical"] = res["det_parallel"].get("plan_digest") == res["det_parallel_2"].get("plan_digest")
    res["parallel_vs_serial"] = compare(P1, S)
    if res["parallel_vs_serial"]["differ"]:
        S2 = step("det_serial_2", ["--det"], keep_trace=True)
        res["serial_noise"] = compare(S, S2)
        noisy = set(res["serial_noise"]["differ"])
        res["parallel_differs_not_noise"] = [k for k in res["parallel_vs_serial"]["differ"] if k not in noisy]
    # cache in parallel
    C = [f"--det-cache={cache}"]
    step("cache_cold_parallel", ["--det"] + W + C)
    s = summary(cwd) or {}
    res["cache_cold_parallel"].update({"recorded": s.get("recorded"), "not_cached": s.get("not_cached")})
    step("cache_warm_parallel", ["--det"] + W + C)
    s = summary(cwd) or {}
    rec = receipts(cwd)
    total = res["det_serial"].get("tests") or 0
    res["cache_warm_parallel"].update({"reused_tests": s.get("reused_tests"), "reused_files": s.get("reused_files"),
                                       "ran_files": s.get("missed_files"), "total_tests": total,
                                       "reuse_pct": round(100.0 * (s.get("reused_tests") or 0) / total, 1) if total else None,
                                       "miss_reasons": s.get("miss_reasons")})
    F = step("fresh_serial", ["--det"], keep_trace=True)
    wrong = [k for k in rec if k in F and rec[k][0] != F[k][0]]
    res["wrong_reuse_vs_fresh_serial"] = {"reused_checked": len([k for k in rec if k in F]), "reused_not_in_fresh": len([k for k in rec if k not in F]),
                                          "wrong_outcome": len(wrong), "wrong": wrong[:50],
                                          "fingerprint_equal": len([k for k in rec if k in F and rec[k][1] == F[k][1]])}
    step("cache_verify_parallel", ["--det"] + W + C + ["--det-cache-verify"])
    s = summary(cwd) or {}
    res["cache_verify_parallel"].update({"verified_tests": s.get("verified_tests"), "mismatches_tests": s.get("verify_mismatches_tests"),
                                         "mismatches": s.get("verify_mismatches", [])[:20]})
    step("cache_warm_serial_on_parallel_store", ["--det"] + C)
    s = summary(cwd) or {}
    res["cache_warm_serial_on_parallel_store"].update({"reused_tests": s.get("reused_tests"), "miss_reasons": s.get("miss_reasons")})
    with open(os.path.join(o.out, f"{o.name}.json"), "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "commands"}, indent=1)[:4000])


if __name__ == "__main__":
    main()
