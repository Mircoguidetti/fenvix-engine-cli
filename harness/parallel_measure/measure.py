#!/usr/bin/env python3
"""Parallel with proof on a real repository: is the parallel result identical to the serial one, and how much faster.

For one repository (a spec in specs.json), REPS rounds, each round run one after another on this machine:

  plain   the suite as its own CI runs it, single worker (no --det; pytest: --det-outcomes only records outcomes)
  serial  the engine, serial: `--det`, trace S_i (the reference the proof compares against)
  par     the engine, parallel: `--det -n N` (pytest) / `--det --det-workers=N` (detjs), trace P_i
  verify  `fenvix verify S_i P_i --json`: the engine's verdict on the parallel run against the serial one

plus `fenvix verify S_1 S_2` (serial noise). Before every run the machine's busy share over 1 s is sampled from
/proc/stat; a run that starts above 80 % busy is marked NOISY. Every run appends one raw line to results.jsonl.

Usage: measure.py --spec specs.json --name REPO [--reps 3] [--workers N] --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.abspath(os.path.join(HERE, "..", ".."))
DETJS = os.path.join(ENGINE, "node", "bin", "detjs.js")
VOLATILE = ("CI", "GITHUB_ACTIONS", "DETJS", "NODE_OPTIONS", "DETJS_SEED", "DETJS_CACHE_DIR", "PYTEST_ADDOPTS")


def engine_commit():
    """The trunk commit the engine was built from: origin/claude/release-1, provided the engine's sources in this
    checkout (crates, python, node, Cargo.*) equal it; otherwise HEAD with a '+modified' suffix."""
    g = lambda *a: subprocess.run(["git", "-C", ENGINE, *a], capture_output=True, text=True).stdout.strip()
    trunk = g("rev-parse", "origin/claude/release-1")
    same = subprocess.run(["git", "-C", ENGINE, "diff", "--quiet", trunk, "--", "crates", "python", "node/src",
                           "node/bin", "Cargo.toml", "Cargo.lock", "pyproject.toml"]).returncode == 0
    return trunk if same else g("rev-parse", "HEAD") + "+modified"


def cpu_sample(dt=1.0):
    def read():
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        idle = v[3] + v[4]
        return sum(v), idle
    t0, i0 = read()
    time.sleep(dt)
    t1, i1 = read()
    return round(100.0 * (1 - (i1 - i0) / max(t1 - t0, 1)), 1)


def run(cmd, cwd, env, log, timeout):
    busy = cpu_sample()
    load = os.getloadavg()
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                           errors="replace", timeout=timeout)
        code, out = r.returncode, r.stdout
    except subprocess.TimeoutExpired as e:
        code, out = 124, e.output if isinstance(e.output, str) else (e.output or b"").decode("utf-8", "replace")
    dt = time.time() - t0
    with open(log, "a") as f:
        f.write(f"\n$ (cd {cwd} && {' '.join(cmd)})  # exit {code}, {dt:.2f} s\n{out[-8000:]}\n")
    return {"exit": code, "wall_s": round(dt, 2), "busy_before_pct": busy, "loadavg_before": [round(x, 2) for x in load],
            "noisy": busy > 80.0}, out


def trace_tests(path):
    """nodeid -> (outcome, fingerprint, worker) of a trace."""
    tests, header = {}, None
    if not os.path.exists(path):
        return header, tests
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            j = json.loads(line)
            if j.get("type") == "header":
                header = j
            elif j.get("type") == "test":
                tests[j["nodeid"]] = (j.get("outcome"), j.get("fingerprint"), j.get("worker"))
    return header, tests


def outcomes_file(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        txt = f.read()
    try:
        j = json.loads(txt)
    except ValueError:
        j = [json.loads(x) for x in txt.splitlines() if x.strip()]
    if isinstance(j, dict) and "outcomes" in j:
        return dict(j["outcomes"])
    if isinstance(j, dict) and "tests" in j:
        j = j["tests"]
    if isinstance(j, dict):
        return {k: (v.get("outcome") if isinstance(v, dict) else v) for k, v in j.items()}
    return {x["nodeid"]: x.get("outcome") for x in j if isinstance(x, dict) and "nodeid" in x}


def compare_outcomes(a, b):
    common = set(a) & set(b)
    diff = sorted(k for k in common if a[k] != b[k])
    return {"a": len(a), "b": len(b), "common": len(common), "only_a": sorted(set(a) - set(b))[:20],
            "only_b": sorted(set(b) - set(a))[:20], "n_only_a": len(set(a) - set(b)), "n_only_b": len(set(b) - set(a)),
            "differ": len(diff), "differ_ids": diff[:30],
            "identical": bool(a) and set(a) == set(b) and not diff}


def counts(m):
    c = {}
    for v in m.values():
        c[v] = c.get(v, 0) + 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--skip", default="", help="comma list of phases to skip (plain,serial,par)")
    o = ap.parse_args()
    with open(o.spec) as f:
        spec = json.load(f)[o.name]
    cwd = os.path.expandvars(spec["dir"])
    out = os.path.abspath(os.path.join(o.out, o.name))
    os.makedirs(out, exist_ok=True)
    log = os.path.join(out, "runs.log")
    results = os.path.join(os.path.abspath(o.out), "results.jsonl")
    env = {k: v for k, v in os.environ.items() if k not in VOLATILE}
    env.update({k: os.path.expandvars(v) for k, v in spec.get("env", {}).items()})
    commit = engine_commit()
    runner = spec["runner"]
    args = spec.get("args", [])
    skip = set(filter(None, o.skip.split(",")))
    fenvix = [os.path.expandvars(spec.get("python", sys.executable)), "-m", "detpy.fenvix"] if runner == "pytest" \
        else [os.path.expandvars(spec["fenvix_python"]), "-m", "detpy.fenvix"]

    if runner == "pytest":
        py = os.path.expandvars(spec["python"])
        base = [py, "-m", "pytest"] + args
        plain = lambda i: base + [f"--det-outcomes={out}/plain{i}.outcomes.json"]
        serial = lambda i: base + ["--det", f"--det-trace={out}/S{i}.jsonl"]
        par = lambda i: base + ["--det", "-n", str(o.workers), f"--det-trace={out}/P{i}.jsonl"]
    else:
        base = ["node", DETJS, runner] + (["run"] if runner == "vitest" else []) + args
        one = ["--no-file-parallelism"] if runner == "vitest" else ["--runInBand"]
        plain = lambda i: base + one + spec.get("plain_extra", [])
        serial = lambda i: base + ["--det", f"--det-trace={out}/S{i}.jsonl"]
        par = lambda i: base + ["--det", f"--det-workers={o.workers}", f"--det-trace={out}/P{i}.jsonl"]

    def record(kind, i, cmd, r, **extra):
        line = {"repo": o.name, "commit": spec.get("commit"), "runner": runner, "kind": kind, "rep": i,
                "workers": o.workers if kind == "par" else 1, "engine_commit": commit, "cpus": os.cpu_count(),
                "cmd": " ".join(cmd), "cwd": cwd, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **r, **extra}
        with open(results, "a") as f:
            f.write(json.dumps(line) + "\n")
        print(json.dumps({k: line[k] for k in ("repo", "kind", "rep", "exit", "wall_s", "busy_before_pct")}), flush=True)
        return line

    for i in range(1, o.reps + 1):
        for d in (".detpy", ".detjs"):
            shutil.rmtree(os.path.join(cwd, d), ignore_errors=True)
        if "plain" not in skip:
            cmd = plain(i)
            r, _ = run(cmd, cwd, env, log, o.timeout)
            oc = outcomes_file(f"{out}/plain{i}.outcomes.json") if runner == "pytest" else {}
            record("plain", i, cmd, r, tests=len(oc) or None, outcome_counts=counts(oc) or None)
        if "serial" not in skip:
            cmd = serial(i)
            r, _ = run(cmd, cwd, env, log, o.timeout)
            _, t = trace_tests(f"{out}/S{i}.jsonl")
            record("serial", i, cmd, r, tests=len(t), outcome_counts=counts({k: v[0] for k, v in t.items()}))
        if "par" not in skip:
            cmd = par(i)
            r, _ = run(cmd, cwd, env, log, o.timeout)
            h, t = trace_tests(f"{out}/P{i}.jsonl")
            workers = sorted({v[2] for v in t.values() if v[2]})
            record("par", i, cmd, r, tests=len(t), outcome_counts=counts({k: v[0] for k, v in t.items()}),
                   workers_seen=workers)
        # the engine's verdict on this round's parallel run against this round's serial run
        pairs = [("verify", f"{out}/S{i}.jsonl", f"{out}/P{i}.jsonl")]
        if i == 2:
            pairs.append(("verify_serial_noise", f"{out}/S1.jsonl", f"{out}/S2.jsonl"))
        for kind, a, b in pairs:
            if not (os.path.exists(a) and os.path.exists(b)):
                continue
            cmd = fenvix + ["verify", a, b, "--json"]
            r, text = run(cmd, cwd, env, log, o.timeout)
            try:
                rep = json.loads(text[text.index("{"):])
            except ValueError:
                rep = {"unparsed": text[-2000:]}
            with open(f"{out}/{kind}{i}.json", "w") as f:
                json.dump(rep, f, indent=1)
            _, ta = trace_tests(a)
            _, tb = trace_tests(b)
            oc = compare_outcomes({k: v[0] for k, v in ta.items()}, {k: v[0] for k, v in tb.items()})
            extra = {"verdict": rep.get("verdict"), "summary": rep.get("summary"), "outcomes_trace_vs_trace": oc}
            if kind == "verify" and runner == "pytest":
                extra["outcomes_plain_vs_par"] = compare_outcomes(outcomes_file(f"{out}/plain{i}.outcomes.json"),
                                                                  {k: v[0] for k, v in tb.items()})
            record(kind, i, cmd, r, **extra)


if __name__ == "__main__":
    main()
