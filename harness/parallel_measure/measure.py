#!/usr/bin/env python3
"""Parallel with proof on a real repository: is the parallel result identical to the serial one, and how much faster.

For one repository (a spec in specs.json), REPS rounds, each round run one after another on this machine:

  bare      (Python, round 1) pytest with the engine plugin not loaded (-p no:detpy): the cost of --det-outcomes
  plain     the suite single worker, no engine (pytest + --det-outcomes for the outcome map; Node: npx vitest/jest
            directly, JSON reporter)
  plain_par (repositories whose CI runs in parallel) the runner's own parallel mode with N workers, no engine
  serial  the engine, serial: `--det`, trace S_i (the reference the proof compares against)
  par     the engine, parallel: `--det -n N` (pytest) / `--det --det-workers=N` (detjs), trace P_i
  verify  `fenvix verify S_i P_i --json`: the engine's verdict on the parallel run against the serial one

plus `fenvix verify S_1 S_2` (serial noise). Before every run the machine's busy share over 1 s is sampled from
/proc/stat; a run that starts above 80 % busy is marked NOISY. Every run appends one raw line to results.jsonl.

Usage: measure.py --spec specs.json --name REPO [--reps 3] [--workers N] --out DIR
"""
from __future__ import annotations

import argparse
import datetime
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


def run_tmpdir(name):
    """coordinator D18: one fixed temp directory per repository, emptied before every run. Short on purpose (Unix
    socket paths are limited to 108 bytes; tests create sockets in the temp directory)."""
    return f"/tmp/pm-{name}"


def reset_tmpdir(path):
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


def tmp_env(env, path):
    return {**env, "TMPDIR": path, "TMP": path, "TEMP": path}


def run(cmd, cwd, env, log, timeout):
    tmpdir = env.get("TMPDIR")
    if tmpdir and tmpdir.startswith("/tmp/pm-"):
        reset_tmpdir(tmpdir)
    before = set(os.listdir("/tmp"))
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
    new = sorted(set(os.listdir("/tmp")) - before - {os.path.basename(tmpdir or "")})
    tmp_rec = {"tmpdir_reset": f"TMPDIR=TMP=TEMP={tmpdir}, emptied before the run"} if tmpdir else {}
    tmp_rec["hardcoded_tmp"] = ("yes: " + ", ".join("/tmp/" + x for x in new[:20]) + (f" (+{len(new) - 20})" if len(new) > 20 else "")) if new else "no"
    return {"exit": code, "wall_s": round(dt, 2), "busy_before_pct": busy, "loadavg_before": [round(x, 2) for x in load],
            "noisy": busy > 80.0, **tmp_rec}, out


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


def epoch_args(trace):
    """`--det-epoch=<ISO>` from a trace header's `meta.epoch_ns` (spec 2026-11-23, det-host-values: the default epoch
    is the host time, so the runs compared with S_i get S_i's epoch); [] when the trace has none."""
    try:
        with open(trace) as f:
            meta = json.loads(f.readline()).get("meta") or {}
        ns = int(meta["epoch_ns"])
    except (OSError, ValueError, KeyError, TypeError):
        return []
    ms = ns // 1_000_000
    t = datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)
    return [f"--det-epoch={t.strftime('%Y-%m-%dT%H:%M:%S')}.{ms % 1000:03d}Z"]


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


NPROC = os.cpu_count()
try:
    CPU_MODEL = next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
except (OSError, StopIteration):
    CPU_MODEL = "UNKNOWN"


def norm(m):
    """one vocabulary for outcomes: pending / todo / disabled are skipped."""
    return {k: ("skipped" if v in ("pending", "todo", "disabled", "skip") else v) for k, v in m.items()}


IDS_REPORTER = os.path.join(HERE, "vitest_ids_reporter.mjs")


def build_after_reset(cwd, build, env, log):
    """coordinator D16: the spec's optional `build` command (shell), run after every tree reset, outside the timed
    region. Returns what goes into the row: {"build": cmd, "build_exit": code, "build_s": seconds} or {}."""
    if not build:
        return {}
    t0 = time.time()
    r = subprocess.run(build, shell=True, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                       errors="replace")
    dt = round(time.time() - t0, 2)
    with open(log, "a") as f:
        f.write(f"\n# build after reset: (cd {cwd} && {build})  # exit {r.returncode}, {dt} s (not timed)\n{r.stdout[-3000:]}\n")
    return {"build": build, "build_exit": r.returncode, "build_s": dt}


REPORTER_IN_REPO = os.path.join(".fenvix-harness", "vitest_ids_reporter.mjs")


def place_reporter(cwd):
    """coordinator (session B, sqlectron): some Vitest versions refuse a reporter file outside the project. After the
    tree reset (and the optional build) the reporter is copied into the repository, under .fenvix-harness/ (removed by
    the next reset); its absolute path is what the plain run passes."""
    dst = os.path.join(cwd, REPORTER_IN_REPO)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(IDS_REPORTER, dst)
    return dst


REPORTER_LOAD_ERROR = "Failed to load custom Reporter"


def plain_invalid(runner, r, text, n_tests):
    """Guard: a plain Vitest run that reports 0 tests, or exits with a reporter load error, is INVALID (no outcome
    data is taken from it)."""
    if runner != "vitest":
        return None
    if REPORTER_LOAD_ERROR in (text or ""):
        return f"reporter load error ({REPORTER_LOAD_ERROR}), exit {r['exit']} after {r['wall_s']} s"
    if not n_tests:
        return f"0 tests reported, exit {r['exit']} after {r['wall_s']} s"
    return None


def reset_tree(cwd):
    """The working tree back to the pinned commit (coordinator fix 2), installed node_modules kept."""
    for d in (".detpy", ".detjs"):
        shutil.rmtree(os.path.join(cwd, d), ignore_errors=True)
    for c in (["git", "checkout", "-q", "--", "."], ["git", "clean", "-fdxq", "-e", "node_modules"],
              ["git", "submodule", "foreach", "--recursive", "-q", "git checkout -q -- . && git clean -fdxq -e node_modules"]):
        subprocess.run(c, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ids_outcomes(path, cwd):
    """vitest_ids_reporter.mjs output -> test id exactly as detjs writes it (`<file>@@<project>::...` in a named
    project, node/src/vitest/shell.js `qualified`) -> outcome; with the detjs `#n` suffix for duplicate names."""
    j = json.load(open(path))
    out = {}
    for t in j.get("tests", []):
        head = os.path.relpath(t["file"], cwd).replace(os.sep, "/") + (f"@@{t['project']}" if t.get("project") else "")
        k = "::".join([head] + list(t.get("ancestors") or []) + [t["title"]])
        n, base = 2, k
        while k in out:
            k, n = f"{base} #{n}", n + 1
        out[k] = t.get("status")
    return out


def runner_outcomes(path, cwd):
    """Vitest / Jest JSON report -> test id in detjs' form (relative file::ancestor::...::title) -> outcome.
    Vitest: the ids file of vitest_ids_reporter.mjs next to the report is preferred (it names the project)."""
    ids = path.replace(".runner.json", ".ids.json")
    if ids != path and os.path.exists(ids):
        return ids_outcomes(ids, cwd)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        j = json.load(f)
    out = {}
    for tr in j.get("testResults", []):
        rel = os.path.relpath(tr["name"], cwd)
        for a in tr.get("assertionResults", []):
            k = "::".join([rel] + list(a.get("ancestorTitles") or []) + [a["title"]])
            # detjs names the second test with the same full name `<name> #2`, the third `#3`, ...
            n, base = 2, k
            while k in out:
                k, n = f"{base} #{n}", n + 1
            out[k] = a.get("status")
    return out


def compare_outcomes(a, b):
    # coordinator fix 1: engine ids of a named Vitest project carry `@@<project>`; plain ids without a project name
    # cannot be matched to them: the comparison is UNKNOWN, never guessed
    if any("@@" in k.split("::", 1)[0] for k in b) and a and not any("@@" in k.split("::", 1)[0] for k in a):
        return {"a": len(a), "b": len(b), "common": 0, "identical": None,
                "unknown": "engine ids name Vitest projects (@@<project>), the plain report does not"}
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


def summary_counts(text):
    """pytest / vitest / jest final summary line -> {outcome: n} (for runs that write no per-test file)."""
    import re
    c = {}
    for line in text.splitlines()[::-1]:
        if re.search(r"\b(passed|failed)\b", line) and (" in " in line or "Tests" in line):
            for n, w in re.findall(r"(\d+) (passed|failed|skipped|xfailed|xpassed|errors?|todo)", line):
                c[w] = int(n)
            if c:
                return c
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--first-rep", type=int, default=1, help="number of the first round (to run rounds in separate processes)")
    ap.add_argument("--workers", default=f"2,{os.cpu_count()}", help="comma list of parallel worker counts")
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--skip", default="", help="comma list of phases to skip (bare,plain,plain_par,serial,par)")
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
    env = tmp_env(env, run_tmpdir(o.name))
    commit = engine_commit()
    runner = spec["runner"]
    args = spec.get("args", [])
    skip = set(filter(None, o.skip.split(",")))
    wlist = [int(x) for x in str(o.workers).split(",") if x]
    ci_parallel = bool(spec.get("ci_parallel"))
    fenvix = [os.path.expandvars(spec.get("python") or spec["fenvix_python"]), "-m", "detpy.fenvix"]

    if runner == "pytest":
        py = os.path.expandvars(spec["python"])
        base = [py, "-m", "pytest"] + args
        bare = lambda i: base + ["-p", "no:detpy"]
        plain = lambda i: base + [f"--det-outcomes={out}/plain{i}.outcomes.json"]
        plain_par = lambda i, n: base + ["-p", "no:detpy", "-n", str(n)]
        serial = lambda i: base + ["--det", f"--det-trace={out}/S{i}.jsonl"]
        par = lambda i, n: base + ["--det", "-n", str(n), f"--det-trace={out}/P{i}w{n}.jsonl"]
        plain_oc = lambda i: outcomes_file(f"{out}/plain{i}.outcomes.json")
    else:
        # the runner itself, not through detjs (coordinator review, fix 2)
        direct = ["npx", "--no-install", runner] + (["run"] if runner == "vitest" else []) + args
        rep_json = (["--reporter=default", "--reporter=json", "--outputFile.json={f}"] if runner == "vitest"
                    else ["--json", "--outputFile={f}"])
        one = ["--no-file-parallelism"] if runner == "vitest" else ["--runInBand"]
        bare = None
        ids_rep = [f"--reporter={os.path.join(cwd, REPORTER_IN_REPO)}"] if runner == "vitest" else []
        plain = lambda i: direct + one + spec.get("plain_extra", []) + [a.format(f=f"{out}/plain{i}.runner.json") for a in rep_json] + ids_rep
        plain_par = lambda i, n: direct + [f"--maxWorkers={n}"] + (["--fileParallelism"] if runner == "vitest" else [])
        base = ["node", DETJS, runner] + (["run"] if runner == "vitest" else []) + args
        # --det-workers=1: on the trunk at 5a6463fd `--det` alone is parallel (node/src/parallel.js:62, G-1044)
        serial = lambda i: base + ["--det", "--det-workers=1", f"--det-trace={out}/S{i}.jsonl"]
        par = lambda i, n: base + ["--det", f"--det-workers={n}", f"--det-trace={out}/P{i}w{n}.jsonl"]
        plain_oc = lambda i: runner_outcomes(f"{out}/plain{i}.runner.json", cwd)

    def record(kind, i, cmd, r, workers=1, **extra):
        line = {"repo": o.name, "commit": spec.get("commit"), "runner": runner, "kind": kind, "rep": i,
                "workers": workers, "engine_commit": commit, "cpus": os.cpu_count(), "nproc": NPROC,
                "cpu_model": CPU_MODEL, "ci_parallel": ci_parallel, "tree_reset": TREE_RESET, **last_build,
                "cmd": " ".join(cmd), "cwd": cwd, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **r, **extra}
        with open(results, "a") as f:
            f.write(json.dumps(line) + "\n")
        if kind == "plain":
            plain_rows.append(line)
        print(json.dumps({k: line[k] for k in ("repo", "kind", "rep", "workers", "exit", "wall_s", "busy_before_pct")}),
              flush=True)
        return line

    def engine_run(kind, n, cmd):
        """Same starting-state rule for the serial and the parallel engine runs (coordinator review, fix 4): each
        (kind, workers) has its own engine state (.detpy / .detjs: durations, sticky plan, bytecode cache); round 1
        starts cold, later rounds start from what the previous run of the same kind left (warm)."""
        warm = False
        clean()
        for d in (".detpy", ".detjs"):
            kept = os.path.join(out, f"state-{kind}-w{n}", d)
            if os.path.isdir(kept):
                shutil.copytree(kept, os.path.join(cwd, d), symlinks=True)
                warm = True
        r, text = run(cmd, cwd, env, log, o.timeout)
        r["engine_state"] = "warm" if warm else "cold"
        for d in (".detpy", ".detjs"):
            kept = os.path.join(out, f"state-{kind}-w{n}", d)
            shutil.rmtree(kept, ignore_errors=True)
            if os.path.isdir(os.path.join(cwd, d)):
                shutil.copytree(os.path.join(cwd, d), kept, symlinks=True)
        return r, text

    last_build = {}
    plain_rows = []
    TREE_RESET = ("git checkout -- . && git clean -fdxq -e node_modules (and the same in every submodule); "
                  "installed dependencies (node_modules, venvs outside the checkout) and the harness output kept")

    def clean():
        """coordinator fix 2: before every plain, serial and parallel run the working tree is the pinned commit again
        (files earlier runs left: tmp, data, caches, .detpy/.detjs). node_modules are kept (installed dependencies)."""
        reset_tree(cwd)
        last_build.clear()
        last_build.update(build_after_reset(cwd, spec.get("build"), env, log))
        if runner == "vitest":
            place_reporter(cwd)

    for i in range(o.first_rep, o.first_rep + o.reps):
        if i == 1 and bare and "bare" not in skip:
            # once per Python repository: pytest with the engine's plugin not loaded (fix 5)
            clean()
            cmd = bare(i)
            r, text = run(cmd, cwd, env, log, o.timeout)
            record("bare", i, cmd, r, outcome_counts=summary_counts(text))
        if "plain" not in skip:
            clean()
            cmd = plain(i)
            r, text = run(cmd, cwd, {**env, "PM_IDS_OUT": f"{out}/plain{i}.ids.json"}, log, o.timeout)
            oc = plain_oc(i)
            bad = plain_invalid(runner, r, text, len(oc))
            if bad:
                r["invalid"] = bad
            record("plain", i, cmd, r, tests=len(oc) or None, outcome_counts=counts(norm(oc)) or None)
        if "plain_par" not in skip:
            # the runner's own parallel mode, no engine, timed for every repository (coordinator, 2026-11-22 memo)
            for n in wlist:
                clean()
                cmd = plain_par(i, n)
                r, text = run(cmd, cwd, env, log, o.timeout)
                record("plain_par", i, cmd, r, workers=n, outcome_counts=summary_counts(text))
        if "serial" not in skip:
            # S_2.. get S_1's epoch (S_1 vs S_2 is the serial noise, the same epoch as the trunk's fixed one)
            cmd = serial(i) + (epoch_args(f"{out}/S1.jsonl") if i > 1 else [])
            r, _ = engine_run("serial", 1, cmd)
            _, t = trace_tests(f"{out}/S{i}.jsonl")
            record("serial", i, cmd, r, tests=len(t), outcome_counts=counts({k: v[0] for k, v in t.items()}))
        for n in ([] if "par" in skip else wlist):
            cmd = par(i, n) + epoch_args(f"{out}/S{i}.jsonl")
            r, _ = engine_run("par", n, cmd)
            h, t = trace_tests(f"{out}/P{i}w{n}.jsonl")
            seen = sorted({v[2] for v in t.values() if v[2]})
            record("par", i, cmd, r, workers=n, tests=len(t), outcome_counts=counts({k: v[0] for k, v in t.items()}),
                   workers_seen=seen)
        clean()
        # the engine's verdict on this round's parallel runs against this round's serial run
        pairs = [("verify", f"{out}/S{i}.jsonl", f"{out}/P{i}w{n}.jsonl", n) for n in wlist]
        if i == 2:
            pairs.append(("verify_serial_noise", f"{out}/S1.jsonl", f"{out}/S2.jsonl", 1))
        for kind, a, b, n in pairs:
            if not (os.path.exists(a) and os.path.exists(b)):
                continue
            cmd = fenvix + ["verify", a, b, "--json"]
            r, text = run(cmd, cwd, env, log, o.timeout)
            try:
                rep = json.loads(text[text.index("{"):])
            except ValueError:
                rep = {"unparsed": text[-2000:]}
            with open(f"{out}/{kind}{i}w{n}.json", "w") as f:
                json.dump(rep, f, indent=1)
            _, ta = trace_tests(a)
            _, tb = trace_tests(b)
            oc = compare_outcomes({k: v[0] for k, v in ta.items()}, {k: v[0] for k, v in tb.items()})
            extra = {"verdict": rep.get("verdict"), "summary": rep.get("summary"), "outcomes_trace_vs_trace": oc}
            if kind == "verify":
                pl = [x for x in plain_rows if x["rep"] == i]
                if pl and pl[-1].get("invalid"):
                    extra["outcomes_plain_vs_par"] = {"identical": None, "unknown": "plain run INVALID: " + pl[-1]["invalid"]}
                else:
                    extra["outcomes_plain_vs_par"] = compare_outcomes(norm(plain_oc(i)), norm({k: v[0] for k, v in tb.items()}))
            record(kind, i, cmd, r, workers=n, **extra)


if __name__ == "__main__":
    main()
