#!/usr/bin/env python3
"""Go flaky round (P-021 step 5a): one project, pinned to the commit where a flaky test is documented.

For the packages that contain the documented flaky test(s):

1. baseline: N runs of plain `go test -count=1 -shuffle=on -json` (random order, default parallelism and
   GOMAXPROCS: what CI does);
2. --det seed 0: 3 runs (outcome + fingerprint per test, from the fenvix trace);
3. exploration: seeds 1..K, one --det run each;
4. confirmation: for every target test (documented, or unstable in the baseline) that failed under some
   seed, 10 more --det runs with that seed: reproduced = 10/10 failures with one fingerprint, and the test
   passes in some --det run (some seed);
5. broken by --det: tests that passed in every baseline run and failed in every seed-0 --det run;
6. timing (quiet, serial): package test time (go test's own Elapsed) of plain `go test -p 1` and of
   `--det`, median of 3 each, after one warm-up build;
7. fingerprint coverage: share of tests whose fingerprint is the same in the 3 seed-0 runs.

    python3 harness/go/flaky_round.py --spec spec.json --fenvix /path/fenvix-go --work /tmp/w --out out.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, file=sys.stderr, flush=True)


def sh(cmd, cwd=None, env=None, timeout=None):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -9, out, "TIMEOUT"


def parse_json(out):
    """go test -json output -> ({pkg: {test: outcome}}, {pkg: elapsed}) for top-level tests."""
    res, elapsed = {}, {}
    for line in out.splitlines():
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        pkg, test, act = ev.get("Package"), ev.get("Test"), ev.get("Action")
        if not pkg:
            continue
        if test and "/" not in test and act in ("pass", "fail", "skip"):
            res.setdefault(pkg, {})[test] = {"pass": "passed", "fail": "failed", "skip": "skipped"}[act]
        elif not test and act in ("pass", "fail"):
            elapsed[pkg] = ev.get("Elapsed")
    return res, elapsed


def read_trace(path):
    tests = {}
    order = []
    try:
        with open(path) as f:
            for line in f:
                d = json.loads(line)
                if d.get("type") == "test":
                    tests[d["nodeid"]] = (d["outcome"], d["fingerprint"])
                    order.append(d["nodeid"])
    except (OSError, ValueError):
        pass
    return tests, order


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--fenvix", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--confirm", type=int, default=10)
    ap.add_argument("--budget", type=float, default=150 * 60, help="seconds for the whole project")
    a = ap.parse_args()
    spec = json.load(open(a.spec))
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    src = work / "src"
    result = {"spec": spec, "status": "started", "notes": []}

    def flush():
        result["seconds"] = round(time.time() - T0, 1)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        json.dump(result, open(a.out, "w"), indent=1)

    # 1. checkout at the pinned commit
    if not src.exists():
        sh(["git", "init", "-q", str(src)])
        url = spec.get("local_path") or f"https://github.com/{spec['repo']}"
        sh(["git", "remote", "add", "origin", url], cwd=src)
    code, out, err = sh(["git", "fetch", "-q", "--depth", "1", "origin", spec["sha"]], cwd=src, timeout=1200)
    if code != 0:
        result["status"] = "fetch-failed"
        result["error"] = err[-2000:]
        flush()
        return
    sh(["git", "checkout", "-q", "FETCH_HEAD"], cwd=src)
    env = dict(os.environ)
    for k, v in (spec.get("env") or {}).items():
        env[k] = v
    # 2. packages that contain the documented tests, and their module. A test can be a plain function, a
    # method run as a subtest of a top-level test (grpc-go: `func (s) TestX(t *testing.T)` under
    # `func Test(t *testing.T) { grpctest.RunSubTests(t, s{}) }`), or not be found at the pinned commit (then
    # the package named in the fix commit's title is used and its unstable tests are the targets).
    pkgs, moddir = set(), None
    toplevel = set()
    located = {}

    def add_file(f):
        nonlocal moddir
        d = (src / f).parent
        m = d
        while m != src and not (m / "go.mod").exists():
            m = m.parent
        if moddir is None:
            moddir = m
        if m != moddir:
            return None
        rel = os.path.relpath(d, moddir)
        pkgs.add("." if rel == "." else "./" + rel)
        return d

    for t in spec["tests"]:
        code, out, _ = sh(["grep", "-rlE", "--include=*_test.go", f"func {t}\\(", "."], cwd=src)
        if out.split():
            for f in out.split():
                add_file(f)
            toplevel.add(t)
            located[t] = "function"
            continue
        code, out, _ = sh(["grep", "-rlE", "--include=*_test.go", f"func \\([^)]*\\) {t}\\(", "."], cwd=src)
        if out.split():
            for f in out.split():
                d = add_file(f)
                if d is None:
                    continue
                for tf in d.glob("*_test.go"):
                    text = tf.read_text(errors="replace")
                    for m in re.finditer(r"^func (Test\w*)\(t \*testing\.T\) \{(.*?)^}", text, re.S | re.M):
                        if "RunSubTests(" in m.group(2):
                            toplevel.add(m.group(1))
            located[t] = "method (subtest of " + ",".join(sorted(toplevel)) + ")"
            continue
        title_pkg = spec.get("title", "").split(":")[0].strip()
        if title_pkg and (src / title_pkg).is_dir() and list((src / title_pkg).glob("*_test.go")):
            add_file(os.path.join(title_pkg, next((src / title_pkg).glob("*_test.go")).name))
            located[t] = f"not found; package {title_pkg} from the fix commit title"
        else:
            located[t] = "not found"
    result["located"] = located
    if not pkgs:
        result["status"] = "tests-not-found"
        flush()
        return
    result["module_dir"] = os.path.relpath(moddir, src)
    pkgs = sorted(pkgs)
    result["packages"] = pkgs
    code, out, err = sh(["go", "list", "-f", "{{.ImportPath}}", *pkgs], cwd=moddir, env=env, timeout=1800)
    if code != 0:
        result["status"] = "list-failed"
        result["error"] = (out + err)[-3000:]
        flush()
        return
    imports = out.split()
    result["imports"] = imports
    targets = {f"{p}::{t}" for p in imports for t in toplevel}
    gv = sh(["go", "env", "GOVERSION"], cwd=moddir, env=env)[1].strip()
    result["go_version"] = gv
    log(spec["repo"], spec["sha"][:10], gv, pkgs)

    timeout = str(spec.get("timeout", "10m"))
    extra = spec.get("go_args", [])

    # warm build (both flavours) so build time stays out of the measurements
    t = time.time()
    sh(["go", "test", "-count=1", "-run", "^$", *extra, *pkgs], cwd=moddir, env=env, timeout=3600)
    result["build_plain_s"] = round(time.time() - t, 1)
    t = time.time()
    sh([a.fenvix, "test", "--det", "-run", "^$", f"--det-trace={work}/warm.jsonl", *extra, *pkgs], cwd=moddir, env=env,
       timeout=3600)
    result["build_det_s"] = round(time.time() - t, 1)

    # 3. baseline
    base = {}
    base_fail_output = {}
    for i in range(a.baseline):
        code, out, err = sh(["go", "test", "-count=1", "-shuffle=on", "-json", f"-timeout={timeout}", *extra, *pkgs],
                            cwd=moddir, env=env, timeout=3600)
        res, _ = parse_json(out)
        for p, tests in res.items():
            for t_, o in tests.items():
                base.setdefault(f"{p}::{t_}", []).append(o)
                if o == "failed" and f"{p}::{t_}" not in base_fail_output:
                    outl = [json.loads(l).get("Output", "") for l in out.splitlines() if l.startswith("{") and
                            f'"Test":"{t_}' in l and '"Action":"output"' in l]
                    base_fail_output[f"{p}::{t_}"] = "".join(outl)[-2000:]
        if i == 0 and not res:
            result["baseline_error"] = (out + err)[-3000:]
        log("baseline", i, sum(len(v) for v in res.values()), "tests")
    result["baseline"] = base
    result["baseline_fail_output"] = base_fail_output
    flush()

    def det_run(seed, tag, run_filter=None):
        trace = work / f"trace-{tag}.jsonl"
        args = [a.fenvix, "test", "--det", f"--det-seed={seed}", f"--det-trace={trace}", f"-timeout={timeout}", *extra]
        if run_filter:
            args += ["-run", run_filter]
        code, out, err = sh(args + pkgs, cwd=moddir, env=env, timeout=3600)
        tests, order = read_trace(trace)
        return tests, (out + err)[-1500:]

    # 4. --det seed 0 x3 (with -json: the failure output of every test is kept for diagnosis)
    det0 = []
    det0_fail_output = {}
    for r in range(3):
        trace = work / f"trace-s0-r{r}.jsonl"
        code, out, err = sh([a.fenvix, "test", "--det", "--det-seed=0", f"--det-trace={trace}", "-json", f"-timeout={timeout}",
                             *extra, *pkgs], cwd=moddir, env=env, timeout=3600)
        tests, _ = read_trace(trace)
        det0.append(tests)
        if r == 0:
            if not tests:
                result["det_error"] = (out + err)[-3000:]
            lines = {}
            for line in out.splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("Test") and ev.get("Action") == "output":
                    k = f"{ev.get('Package')}::{ev['Test'].split('/')[0]}"
                    lines.setdefault(k, []).append(ev.get("Output", ""))
            for k, v in tests.items():
                if v[0] == "failed":
                    det0_fail_output[k] = "".join(lines.get(k, []))[-2500:]
    result["det0_fail_output"] = det0_fail_output
    # events per source in the first seed-0 run (what the hooks saw; explains the slowdown)
    by_src, top = {}, []
    try:
        for line in open(work / "trace-s0-r0.jsonl"):
            d = json.loads(line)
            if d.get("type") == "test":
                for k, v in (d.get("counts") or {}).items():
                    by_src[k] = by_src.get(k, 0) + v
                top.append((d["n_events"], d["nodeid"]))
    except (OSError, ValueError):
        pass
    result["det0_events_by_source"] = by_src
    result["det0_top_tests_by_events"] = sorted(top, reverse=True)[:8]
    # verifier over the 3 seed-0 runs: every test whose fingerprint differs, with the first diverging event
    code, out, err = sh([a.fenvix, "verify", "--json", *[str(work / f"trace-s0-r{r}.jsonl") for r in range(3)]], timeout=600)
    try:
        rep = json.loads(out)
        result["det0_divergences"] = [{"nodeid": t["nodeid"], "status": t["status"], "outcomes": t["outcomes"],
                                       "divergence": (t.get("divergence") or {})} for t in rep["tests"] if t["status"] != "stable"]
        result["det0_summary"] = rep.get("summary")
    except (ValueError, KeyError):
        result["det0_verify_error"] = (out + err)[-1500:]
    result["det0"] = {k: [d.get(k) for d in det0] for k in set().union(*[d.keys() for d in det0])}
    flush()
    # 5. exploration
    explore = {}
    for s in range(1, a.seeds + 1):
        if time.time() - T0 > a.budget * 0.6:
            result["notes"].append(f"exploration stopped at seed {s} (budget)")
            break
        tests, _ = det_run(s, f"s{s}")
        for k, v in tests.items():
            explore.setdefault(k, {})[s] = v
    result["explore"] = explore
    flush()

    # targets: documented tests + baseline-unstable tests
    unstable = {k for k, v in base.items() if "failed" in v and "passed" in v}
    result["baseline_unstable"] = sorted(unstable)
    cand = sorted(targets | unstable)
    confirm = {}
    for k in cand:
        seeds_fail = [0] if any(d.get(k, ("",))[0] == "failed" for d in det0) else []
        seeds_fail += [s for s, v in explore.get(k, {}).items() if v[0] == "failed"]
        passes = any(d.get(k, ("",))[0] == "passed" for d in det0) or any(v[0] == "passed" for v in explore.get(k, {}).values())
        item = {"fail_seeds": seeds_fail[:10], "passes_in_some_seed": passes}
        if seeds_fail and time.time() - T0 < a.budget:
            s = seeds_fail[0]
            pkg, name = k.split("::", 1)
            fps, outs = set(), []
            for r in range(a.confirm):
                tests, _ = det_run(s, f"c-{abs(hash(k)) % 10**8}-{r}")
                v = tests.get(k)
                outs.append(v[0] if v else "missing")
                if v:
                    fps.add(v[1])
            item.update({"seed": s, "outcomes": outs, "fingerprints": len(fps)})
            item["reproduced"] = outs.count("failed") == a.confirm and len(fps) == 1 and passes
        else:
            item["reproduced"] = False
        confirm[k] = item
        flush()
    result["confirm"] = confirm

    # broken by --det: passed in every baseline run, failed in every seed-0 run
    broken = []
    for k, v in base.items():
        if v and all(o == "passed" for o in v) and len(v) == a.baseline:
            d = [x.get(k) for x in det0]
            if all(x and x[0] == "failed" for x in d):
                broken.append(k)
    result["broken"] = broken
    # fingerprint coverage over the 3 seed-0 runs
    same = total = 0
    for k, v in result["det0"].items():
        if all(v):
            total += 1
            same += len({x[1] for x in v}) == 1
    result["fingerprint_coverage"] = [same, total]

    # 6. timing (serial)
    if time.time() - T0 < a.budget:
        plain_t, det_t, detpar_t = [], [], []
        for r in range(3):
            code, out, _ = sh(["go", "test", "-count=1", "-p", "1", "-json", f"-timeout={timeout}", *extra, *pkgs],
                              cwd=moddir, env=env, timeout=3600)
            _, el = parse_json(out)
            plain_t.append(sum(x for x in el.values() if x))
            trace = work / f"timing-{r}.jsonl"
            code, out, _ = sh([a.fenvix, "test", "--det", f"--det-trace={trace}", "-json", f"-timeout={timeout}", *extra, *pkgs],
                              cwd=moddir, env=env, timeout=3600)
            _, el = parse_json(out)
            det_t.append(sum(x for x in el.values() if x))
            # --det with t.Parallel kept: separates the cost of running tests one at a time from the hooks' cost
            code, out, _ = sh([a.fenvix, "test", "--det", "--det-keep-parallel", f"--det-trace={trace}.par", "-json",
                               f"-timeout={timeout}", *extra, *pkgs], cwd=moddir, env=env, timeout=3600)
            _, el = parse_json(out)
            detpar_t.append(sum(x for x in el.values() if x))
        result["timing_keep_parallel"] = detpar_t
        result["timing"] = {"plain": plain_t, "det": det_t}
        mp, md = statistics.median(plain_t), statistics.median(det_t)
        result["slowdown"] = (md - mp) / mp if mp > 0 else None
    result["status"] = "done"
    flush()
    log("done", spec["repo"])


if __name__ == "__main__":
    main()
