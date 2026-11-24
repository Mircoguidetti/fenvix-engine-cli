#!/usr/bin/env python3
"""Lane D: the no-engine control arm. Plain runner commands only (never detjs, never the engine).

Per repository (an entry of harness/parallel_measure/specs.json, its pinned commit, installed per RERUN.md section 2):

  S1, S2      plain serial, the runner's one-worker mode with the ids reporter (measure.py `plain`): the baseline
  SS1, SS2    plain shuffled serial, seeds 1 and 2 (order controls)
  P1..P5      plain parallel, 4 workers, shuffled with seeds 1..5

Commands: the flag lists are copied from harness/parallel_measure/repro.py main() (lines 1-14 docstring, 49-68:
`--maxWorkers=4 --fileParallelism` / `--no-file-parallelism --sequence.shuffle --sequence.seed=S` for vitest,
`--maxWorkers=4` / `--runInBand --randomize --seed=S` for jest) and from measure.py main() (`one`, `rep_json`), with the
shuffle added to the parallel runs as Lane D specifies. Tree reset, build-after-reset, the per-repository TMPDIR (D18),
the ids reporter and the id mapping come from measure.py (imported, not copied).

Before every run: tree reset (measure.reset_tree), the spec's build, the vite/vitest caches under node_modules removed,
an emptied TMPDIR (/tmp/pm-<repo>), jest `--cacheDirectory=$TMPDIR/jest`. Per-run timeout of SS/P and the pair search:
3 x the serial median (R7).

Then per test a verdict (verdicts()), and for DIVERGES tests a minimal pair search (R11, PairSearch) with a fixed-order
sequencer (fixed_order_sequencer.cjs / .mjs).

Usage:
  control_arm.py runs    --name REPO      the 9 runs (resumable: a run whose data file exists is not re-run)
  control_arm.py verdict --name REPO      verdict rows into results.jsonl
  control_arm.py pairs   --name REPO      minimal pair search, rows into pairs.jsonl
  control_arm.py all     --name REPO      the three in order
  control_arm.py loadfail --name REPO     test files that did not load, from the recorded raw reports (no run)
  control_arm.py supp_ss --name REPO      supplementary shuffled serial runs SS3..SS5 (seeds of P3..P5)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import re
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PM_DIR = os.path.join(HERE, "..", "parallel_measure")
sys.path.insert(0, os.path.abspath(PM_DIR))
import measure as M  # noqa: E402
import classify as C  # noqa: E402

SPECS = os.path.join(PM_DIR, "specs.json")
REPOS = ["codex-multi-auth", "ironcurtain", "yalc", "nestjs-pino", "agentsys", "lerna-lite", "drydock", "agentlang",
         "alakajam"]
RESULTS = os.path.join(HERE, "results.jsonl")
PAIRS = os.path.join(HERE, "pairs.jsonl")
DATA = os.path.join(HERE, "data")
JEST_SEQ = os.path.join(HERE, "fixed_order_sequencer.cjs")
VITEST_SEQ = os.path.join(HERE, "fixed_order_sequencer.mjs")
WORKERS = 4
K_PAR = 5
MIN_VALID_PAR = 3
SERIAL_TIMEOUT = 7200
MAX_VICTIMS = 10
PAIR_BUDGET_RUNS = 30
PAIR_BUDGET_S = 3 * 3600
CONFIRM_RUNS = 3

# ENV causes: classify.ENV_PATTERNS (the local ECONNREFUSED pattern of session B review R3 is there since step 4; until
# then control_arm applied the same pattern locally).
env_cause = C.env_cause


# ---------------------------------------------------------------------------------------------------------------
# commands


def run_flags(runner, kind, seed=None):
    """kind S / SS / P. Copied from repro.py main() (and measure.py `one` for S); P adds the shuffle (Lane D)."""
    if runner == "vitest":
        return {"S": ["--no-file-parallelism"],
                "SS": ["--no-file-parallelism", "--sequence.shuffle", f"--sequence.seed={seed}"],
                "P": [f"--maxWorkers={WORKERS}", "--fileParallelism", "--sequence.shuffle", f"--sequence.seed={seed}"]}[kind]
    if runner == "jest":
        return {"S": ["--runInBand"],
                "SS": ["--runInBand", "--randomize", f"--seed={seed}"],
                "P": [f"--maxWorkers={WORKERS}", "--randomize", f"--seed={seed}"]}[kind]
    raise ValueError(runner)


def report_flags(runner, raw, rep_path, tmp):
    """measure.py `rep_json` + the ids reporter (vitest); jest's cache in the fresh per-run TMPDIR."""
    if runner == "vitest":
        return ["--reporter=default", "--reporter=json", f"--outputFile.json={raw}", f"--reporter={rep_path}"]
    return ["--json", f"--outputFile={raw}", f"--cacheDirectory={tmp}/jest"]


def direct(runner, args):
    return ["npx", "--no-install", runner] + (["run"] if runner == "vitest" else []) + list(args)


def strip_config(args):
    """spec args without `--config X` / `--config=X`; returns (args, config path or None)."""
    out, cfg, i = [], None, 0
    while i < len(args):
        a = args[i]
        if a in ("--config", "-c") and i + 1 < len(args):
            cfg = args[i + 1]
            i += 2
            continue
        if a.startswith("--config="):
            cfg = a.split("=", 1)[1]
        else:
            out.append(a)
        i += 1
    return out, cfg


DEFAULT_VITEST_CONFIGS = [f"{b}.config.{e}" for b in ("vitest", "vite") for e in ("ts", "mts", "cts", "js", "mjs", "cjs")]


def write_vitest_wrapper(cwd, cfg):
    """The fixed-order wrapper config under .fenvix-harness/ (removed by the next tree reset, like place_reporter's
    file): loads the repository's config (spec --config, else the default file), resolves a function-form config,
    keeps everything (projects included) and sets sequence.sequencer with vitest's mergeConfig."""
    d = os.path.join(cwd, ".fenvix-harness")
    os.makedirs(d, exist_ok=True)
    shutil.copyfile(VITEST_SEQ, os.path.join(d, "fixed_order_sequencer.mjs"))
    if cfg is None:
        cfg = next((c for c in DEFAULT_VITEST_CONFIGS if os.path.exists(os.path.join(cwd, c))), None)
    imp = f"import base from {json.dumps('../' + os.path.normpath(cfg).replace(os.sep, '/'))};" if cfg else "const base = {};"
    src = f"""// control_arm fixed-order wrapper (generated; removed by the next tree reset)
import {{ mergeConfig }} from 'vitest/config';
{imp}
import FixedOrderSequencer from './fixed_order_sequencer.mjs';
export default async (env) => {{
  const e = env || {{ command: 'serve', mode: process.env.NODE_ENV || 'test', isSsrBuild: false, isPreview: false }};
  const c = typeof base === 'function' ? await base(e) : await base;
  // CA_SEED: the diverging run's seed; tests inside each file in that run's order, the files in CA_ORDER
  const seq = process.env.CA_SEED
    ? {{ sequencer: FixedOrderSequencer, shuffle: {{ files: false, tests: true }}, seed: Number(process.env.CA_SEED) }}
    : {{ sequencer: FixedOrderSequencer }};
  return mergeConfig(c || {{}}, {{ test: {{ sequence: seq }} }});
}};
"""
    p = os.path.join(d, "vitest.control.config.mjs")
    with open(p, "w") as f:
        f.write(src)
    return p, cfg


def shell_cmd(cmd, env_add, cwd):
    parts = [f"{k}={shlex.quote(v)}" for k, v in env_add.items()] + [shlex.quote(c) for c in cmd]
    return f"cd {shlex.quote(cwd)} && " + " ".join(parts)


# ---------------------------------------------------------------------------------------------------------------
# running


class Repo:
    def __init__(self, name, out=None):
        self.name = name
        self.spec = json.load(open(SPECS))[name]
        self.cwd = os.path.expandvars(self.spec["dir"])
        self.runner = self.spec["runner"]
        self.out = os.path.abspath(out or os.path.join(os.environ.get("PM_WORK", "/tmp/pm"), "control", name))
        os.makedirs(self.out, exist_ok=True)
        self.data = os.path.join(DATA, name)
        os.makedirs(self.data, exist_ok=True)
        self.log = os.path.join(self.out, "runs.log")
        env = {k: v for k, v in os.environ.items() if k not in M.VOLATILE}
        env.update({k: os.path.expandvars(v) for k, v in self.spec.get("env", {}).items()})
        self.tmp = M.run_tmpdir(name)
        self.env = M.tmp_env(env, self.tmp)

    def prepare(self):
        """tree reset + build (measure.py), caches cleared, reporter placed; returns (build record, reporter path)."""
        M.reset_tree(self.cwd)
        built = M.build_after_reset(self.cwd, self.spec.get("build"), self.env, self.log)
        clear_caches(self.cwd)
        rep = M.place_reporter(self.cwd) if self.runner == "vitest" else None
        return built, rep

    def fresh_tmp(self):
        M.reset_tmpdir(self.tmp)
        return self.tmp


def clear_caches(cwd):
    """vite / vitest caches (node_modules/.vite, .vite-temp, .vitest, .vitest-cache) of the repository."""
    removed = []
    for p in glob.glob(os.path.join(cwd, "node_modules", ".vite*")) + glob.glob(os.path.join(cwd, "node_modules", ".vitest*")):
        shutil.rmtree(p, ignore_errors=True)
        removed.append(os.path.basename(p))
    return removed


def run_procs(jobs, cwd, timeout, log):
    """Start every (cmd, env) at the same time, own process groups, stdout+stderr captured (never silenced).
    Returns per job {exit, timed_out, wall_s} and the output text."""
    res = [None] * len(jobs)

    def one(i, cmd, env):
        t0 = time.time()
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             errors="replace", start_new_session=True)
        try:
            out, _ = p.communicate(timeout=timeout)
            code, to = p.returncode, False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, _ = p.communicate()
            code, to = 124, True
        res[i] = ({"exit": code, "timed_out": to, "wall_s": round(time.time() - t0, 2)}, out or "")

    th = [threading.Thread(target=one, args=(i, c, e)) for i, (c, e) in enumerate(jobs)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    with open(log, "a") as f:
        for (cmd, _), (r, out) in zip(jobs, res):
            f.write(f"\n$ (cd {cwd} && {' '.join(cmd)})  # exit {r['exit']}, {r['wall_s']} s, timed_out={r['timed_out']}\n"
                    f"{out[-8000:]}\n")
    return res


def read_report(runner, raw, ids, cwd):
    """-> (outcomes, failure messages, per-file [start, end]) or (None, {}, {}) when no usable report exists."""
    try:
        j = json.load(open(raw))
    except (OSError, ValueError):
        j = None
    times, msgs = {}, {}
    if j:
        for tr in j.get("testResults", []):
            if tr.get("startTime") is not None and tr.get("endTime") is not None:
                times[tr["name"]] = [tr["startTime"], tr["endTime"]]
    if runner == "vitest":
        if not os.path.exists(ids):
            return None, {}, times
        try:
            oc = M.ids_outcomes(ids, cwd)
        except (OSError, ValueError):
            return None, {}, times
        seen = set()
        for t in json.load(open(ids)).get("tests", []):
            head = os.path.relpath(t["file"], cwd).replace(os.sep, "/") + (f"@@{t['project']}" if t.get("project") else "")
            k = "::".join([head] + list(t.get("ancestors") or []) + [t["title"]])
            n, base = 2, k
            while k in seen:
                k, n = f"{base} #{n}", n + 1
            seen.add(k)
            if t.get("errors"):
                msgs[k] = " ".join(t["errors"])[:3000]
    else:
        if j is None:
            return None, {}, times
        oc = M.runner_outcomes(raw, cwd)
        for tr in j.get("testResults", []):
            rel = os.path.relpath(tr["name"], cwd)
            seen = set()
            for a in tr.get("assertionResults", []):
                k = "::".join([rel] + list(a.get("ancestorTitles") or []) + [a["title"]])
                n, base = 2, k
                while k in seen:
                    k, n = f"{base} #{n}", n + 1
                seen.add(k)
                if a.get("failureMessages"):
                    msgs[k] = " ".join(a["failureMessages"])[:3000]
    return M.norm(oc), msgs, times


def load_failures(raw):
    """test files the runner reports as failed with no test in them (the file did not load): {file: first message line},
    or None without a usable report. Their tests are in no outcome map, so in no verdict."""
    try:
        j = json.load(open(raw))
    except (OSError, ValueError):
        return None
    out = {}
    for tr in j.get("testResults", []):
        if tr.get("status") == "failed" and not tr.get("assertionResults"):
            lines = [x.strip() for x in (tr.get("message") or "").splitlines() if x.strip()]
            out[tr["name"]] = lines[0][:300] if lines else ""
    return out


def overlapping_pairs(times):
    """number of (file, file) pairs whose [start, end] intervals overlap: 0 means the run ran its files serially."""
    iv = sorted(tuple(v) for v in times.values())
    n = 0
    for i, (s1, e1) in enumerate(iv):
        for s2, e2 in iv[i + 1:]:
            if s2 >= e1:
                break
            n += 1
    return n


def run_names():
    return ([("S1", "S", None), ("S2", "S", None), ("SS1", "SS", 1), ("SS2", "SS", 2)] +
            [(f"P{s}", "P", s) for s in range(1, K_PAR + 1)])


def do_run(repo, name, kind, seed, timeout):
    built, rep = repo.prepare()
    tmp = repo.fresh_tmp()
    raw = os.path.join(repo.out, f"{name}.raw.json")
    ids = os.path.join(repo.out, f"{name}.ids.json")
    for f in (raw, ids):
        if os.path.exists(f):
            os.remove(f)
    cmd = direct(repo.runner, repo.spec.get("args", [])) + run_flags(repo.runner, kind, seed) + \
        report_flags(repo.runner, raw, rep, tmp)
    env_add = {"TMPDIR": tmp, "TMP": tmp, "TEMP": tmp}
    if repo.runner == "vitest":
        env_add["PM_IDS_OUT"] = ids
    (r, text), = run_procs([(cmd, {**repo.env, **env_add})], repo.cwd, timeout, repo.log)
    oc, msgs, times = read_report(repo.runner, raw, ids, repo.cwd)
    lf = load_failures(raw)
    bad = M.plain_invalid(repo.runner, r, text, len(oc or {}))
    crashed = (not r["timed_out"]) and (oc is None or bool(bad) or r["exit"] not in (0, 1))
    if bad:
        oc = None
    row = {"row": "run", "repo": repo.name, "commit": repo.spec.get("commit"), "runner": repo.runner, "run": name,
           "kind": kind, "seed": seed, "workers": WORKERS if kind == "P" else 1,
           "cmd": shell_cmd(cmd, env_add, repo.cwd), "exit": r["exit"], "wall_s": r["wall_s"],
           "tests": len(oc) if oc is not None else 0, "timed_out": r["timed_out"], "timeout_s": timeout,
           "crashed": crashed, "crash_reason": (bad or ("no usable report" if oc is None else f"exit {r['exit']}"))
           if crashed else None, "files": len(times), "overlapping_file_pairs": overlapping_pairs(times),
           "outcome_counts": M.counts(oc or {}),
           "load_failed_files": len(lf) if lf is not None else None, "nproc": M.NPROC, "cpu_model": M.CPU_MODEL,
           "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **built}
    data = {"row": row, "outcomes": oc, "messages": msgs, "file_times": times, "load_failures": lf}
    return row, data


def cmd_loadfail(name):
    """Adds load_failures to recorded runs from their raw report (the path in the run's own command); no run is made."""
    for rn, _, _ in run_names():
        f = os.path.join(DATA, name, f"{rn}.json")
        d = json.load(open(f))
        m = re.search(r"--outputFile(?:\.json)?=(\S+)", d["row"]["cmd"])
        lf = load_failures(m.group(1)) if m else None
        d["load_failures"] = lf
        d["row"]["load_failed_files"] = len(lf) if lf is not None else None
        with open(f, "w") as g:
            json.dump(d, g)
        print(json.dumps({"repo": name, "run": rn, "load_failed_files": d["row"]["load_failed_files"]}), flush=True)


def serial_median(rows):
    w = [r["wall_s"] for r in rows if r["kind"] == "S" and not r["timed_out"] and not r["crashed"]]
    return statistics.median(w) if w else None


def finish_rows(rows):
    """short (fewer tests than serial) and the parallelism check (P: no overlap = INVALID, serial in disguise)."""
    s_ids = None
    for r in rows:
        if r["kind"] == "S" and r.get("_ids") is not None:
            s_ids = (s_ids or set()) | r["_ids"]
    for r in rows:
        ids = r.get("_ids")
        r["missing_vs_serial"] = (len(s_ids - ids) if ids is not None else len(s_ids)) if s_ids is not None else None
        # short = fewer tests than serial (Lane D rule 1); missing_vs_serial (ids of S1 or S2 absent here) is kept as
        # information: tests whose names change per run make it non-zero without the run being short
        s_n = [x["tests"] for x in rows if x["kind"] == "S" and not x["timed_out"] and not x["crashed"]]
        r["short"] = bool(s_n) and not r["timed_out"] and not r["crashed"] and r["tests"] < min(s_n)
        if r["kind"] == "P":
            ok = not r["timed_out"] and not r["crashed"] and r["overlapping_file_pairs"] > 0
            r["valid"] = "valid" if ok else "INVALID"
            r["invalid_reason"] = None if ok else ("timed out" if r["timed_out"] else "crashed" if r["crashed"] else
                                                    "no two test files overlapped in time (ran serially)")
        else:
            r["valid"] = "n/a"
    return rows


def cmd_runs(name, out=None):
    repo = Repo(name, out)
    rows = []
    med = None
    for rn, kind, seed in run_names():
        f = os.path.join(repo.data, f"{rn}.json")
        if os.path.exists(f):
            d = json.load(open(f))
        else:
            if kind == "S":
                timeout = SERIAL_TIMEOUT
            else:
                med = med or serial_median(rows)
                timeout = int(max(3 * med, 60)) if med else SERIAL_TIMEOUT
            row, d = do_run(repo, rn, kind, seed, timeout)
            with open(f, "w") as g:
                json.dump(d, g)
            print(json.dumps({k: row[k] for k in ("repo", "run", "exit", "wall_s", "tests", "timed_out", "crashed",
                                                  "overlapping_file_pairs")}), flush=True)
        r = dict(d["row"])
        r["_ids"] = set(d["outcomes"]) if d["outcomes"] is not None else None
        rows.append(r)
    finish_rows(rows)
    M.reset_tree(repo.cwd)
    keep = [x for x in read_jsonl(RESULTS) if not (x.get("repo") == name and x.get("row") == "run")]
    for r in rows:
        r.pop("_ids", None)
    write_jsonl(RESULTS, keep + rows)
    return rows


SUPP_SS = [3, 4, 5]


def cmd_supp_ss(name, out=None):
    """Supplementary shuffled serial runs with the seeds of P3..P5 (review of 2026-11-23): inside a file the test order
    depends only on the seed, so P3..P5 had orders no SS run had. Not used by verdicts() (the spec's rule uses SS1,
    SS2); report.py uses them to check the `parallel` label against SS with the same seed. Resumable."""
    repo = Repo(name, out)
    rows = [x for x in read_jsonl(RESULTS) if x.get("repo") == name and x.get("row") == "run"]
    med = serial_median(rows)
    timeout = int(max(3 * med, 60)) if med else SERIAL_TIMEOUT
    out_rows = []
    for sd in SUPP_SS:
        rn = f"SS{sd}"
        f = os.path.join(repo.data, f"{rn}.json")
        if os.path.exists(f):
            d = json.load(open(f))
        else:
            _, d = do_run(repo, rn, "SS", sd, timeout)
            with open(f, "w") as g:
                json.dump(d, g)
        r = dict(d["row"], row="run_supp")
        out_rows.append(r)
        print(json.dumps({k: r[k] for k in ("repo", "run", "exit", "wall_s", "tests", "timed_out", "crashed")}), flush=True)
    M.reset_tree(repo.cwd)
    keep = [x for x in read_jsonl(RESULTS) if not (x.get("repo") == name and x.get("row") == "run_supp")]
    write_jsonl(RESULTS, keep + out_rows)


# ---------------------------------------------------------------------------------------------------------------
# verdicts


def verdicts(runs, messages):
    """runs: [{name, kind S/SS/P, status ok|timeout|crash, valid (P: bool), outcomes: dict or None}] (S1 and S2 first)
    messages: test id -> failure text over all runs. Returns {test id: {verdict, label, reason, runs...}}."""
    by = {r["name"]: r for r in runs}
    s1, s2 = by["S1"], by["S2"]
    ss = [r for r in runs if r["kind"] == "SS"]
    par = [r for r in runs if r["kind"] == "P"]
    valid_par = [r for r in par if r["valid"] and r["status"] == "ok"]
    universe = set()
    for r in runs:
        universe |= set(r["outcomes"] or {})
    out = {}
    for t in sorted(universe):
        def oc(r):
            return (r["outcomes"] or {}).get(t) if r["status"] == "ok" else None
        a, b = oc(s1), oc(s2)
        diverging = [r["name"] for r in valid_par if a is not None and oc(r) is not None and oc(r) != a]
        v = {"verdict": None, "label": None, "reason": None, "serial": a, "diverging_runs": diverging}
        env = env_cause(messages.get(t, ""))
        failed_runs = [r["name"] for r in runs if r["status"] != "ok" or t not in (r["outcomes"] or {})]
        if env:
            v.update(verdict="ENV", reason=env)
        elif a is not None and b is not None and a != b:
            v.update(verdict="UNDECIDED", label="serial-disagree", reason=f"S1={a} S2={b}")
        elif failed_runs:
            why = []
            for n in failed_runs:
                r = by[n]
                why.append(f"{n} {'timed out' if r['status'] == 'timeout' else 'crashed' if r['status'] == 'crash' else 'missing the test'}")
            v.update(verdict="UNDECIDED", label="run-failed-or-short", reason="; ".join(why))
        elif len(valid_par) < MIN_VALID_PAR:
            v.update(verdict="UNDECIDED", label="insufficient-parallel",
                     reason=f"{len(valid_par)} valid parallel runs (< {MIN_VALID_PAR})")
        else:
            ssdiff = [r["name"] for r in ss if oc(r) != a]
            if diverging:
                v.update(verdict="DIVERGES", label="order" if ssdiff else "parallel",
                         reason=f"differs in {','.join(diverging)}" + (f"; shuffled serial {','.join(ssdiff)} differs" if ssdiff else ""))
            elif ssdiff:
                v.update(verdict="DIVERGES-order-only", reason=f"shuffled serial {','.join(ssdiff)} differs")
            else:
                v.update(verdict="IDENTICAL", reason=f"S1,S2,{','.join(r['name'] for r in ss)},"
                                                     f"{','.join(r['name'] for r in valid_par)} agree")
        out[t] = v
    return out


def load_runs(name):
    runs, msgs, times = [], {}, {}
    for rn, kind, seed in run_names():
        f = os.path.join(DATA, name, f"{rn}.json")
        if not os.path.exists(f):
            raise SystemExit(f"missing run data {f}: run `control_arm.py runs --name {name}` first")
        d = json.load(open(f))
        row = d["row"]
        status = "timeout" if row["timed_out"] else "crash" if row["crashed"] else "ok"
        runs.append({"name": rn, "kind": kind, "status": status, "outcomes": d["outcomes"],
                     "valid": kind == "P" and status == "ok" and row["overlapping_file_pairs"] > 0})
        for k, m in (d.get("messages") or {}).items():
            msgs[k] = msgs.get(k, "") + " " + m  # every run's message: an ENV cause seen in any run is kept
        times[rn] = d.get("file_times") or {}
    return runs, msgs, times


def cmd_verdict(name):
    runs, msgs, _ = load_runs(name)
    vs = verdicts(runs, msgs)
    rows = [{"row": "verdict", "repo": name, "test": t, **v} for t, v in vs.items()]
    keep = [x for x in read_jsonl(RESULTS) if not (x.get("repo") == name and x.get("row") == "verdict")]
    write_jsonl(RESULTS, keep + rows)
    c = {}
    for v in vs.values():
        k = v["verdict"] + (f"/{v['label']}" if v["label"] else "")
        c[k] = c.get(k, 0) + 1
    print(json.dumps({"repo": name, "verdicts": c}), flush=True)
    return vs


# ---------------------------------------------------------------------------------------------------------------
# minimal pair search (R11)


class Budget(Exception):
    pass


class TrialFailed(Exception):
    """a trial reported no outcome for the victim (timeout, crash, no report): it is no evidence either way"""


DEFAULT = object()  # trial seed: the diverging run's seed given to the trial

# pair search results (report.py counts by these)
R_PAIR = "pair found"
R_ALONE = "no minimal pair (victim file alone reproduces)"
R_ALONE_ONCE = "no minimal pair (victim file alone reproduces once in 3)"
R_ALONE_UNSEEDED = "no minimal pair (victim file alone diverges without the seed too)"
R_ALONE_CTL = "no minimal pair (victim file alone diverges under a control seed too)"
R_INTERACTION = "no minimal pair (interaction)"
R_NOT_CONFIRMED = "no minimal pair (not confirmed)"
R_NOT_REPRO = "no minimal pair (not reproduced)"
R_BUDGET = "pair not found (budget)"
R_TRIAL_FAILED = "no minimal pair (trial failed)"


class PairSearch:
    """trial(mode, polluters, victim_file, seed=DEFAULT) -> (True when the victim's outcome differs from its serial
    outcome, None when the trial reported no outcome for it, record). Mode 'serial': polluters + victim in one process,
    given order; 'concurrent': victim process and polluter process started together. seed: DEFAULT = the diverging run's
    seed (order inside files), None = no shuffle, or a control seed. Every trial is one plain run of the budget."""

    def __init__(self, trial, budget_runs=PAIR_BUDGET_RUNS, deadline=None):
        self.trial = trial
        self.budget_runs = budget_runs
        self.deadline = deadline
        self.spent = 0
        self.log = []

    def _try(self, mode, polluters, victim, step, seed=DEFAULT):
        if self.spent >= self.budget_runs or (self.deadline and time.time() > self.deadline):
            raise Budget()
        self.spent += 1
        hit, rec = self.trial(mode, list(polluters), victim, seed)
        self.log.append({"mode": mode, "step": step, "polluters": list(polluters), "triggered": hit,
                         "seed_used": "diverging run's" if seed is DEFAULT else seed, **(rec or {})})
        if hit is None:
            raise TrialFailed()
        return hit

    def triggers(self, mode, half, victim, step, seed=DEFAULT):
        """a half triggers if the victim fails in either of two runs (the second run is not made once the first
        triggered: it cannot change the decision)."""
        for _ in range(2):
            if self._try(mode, half, victim, step, seed):
                return True
        return False

    def bisect(self, mode, cands, victim):
        cands = list(cands)
        step = 0
        while len(cands) > 1:
            step += 1
            h1, h2 = cands[:len(cands) // 2], cands[len(cands) // 2:]
            if self.triggers(mode, h1, victim, step):
                cands = h1
            elif self.triggers(mode, h2, victim, step):
                cands = h2
            else:
                return None
        return cands[0] if cands else None

    def confirm(self, mode, polluter, victim):
        if self.budget_runs - self.spent < 2 * CONFIRM_RUNS:
            raise Budget()
        with_p = sum(bool(self._try(mode, [polluter], victim, "confirm-pair")) for _ in range(CONFIRM_RUNS))
        alone = sum(bool(self._try(mode, [], victim, "confirm-alone")) for _ in range(CONFIRM_RUNS))
        return {"pair_fail": with_p, "pair_runs": CONFIRM_RUNS, "alone_fail": alone, "alone_runs": CONFIRM_RUNS,
                "confirmed": with_p >= 2 and alone == 0}

    def alone(self, victim, control_seeds):
        """the victim's file alone reproduced: confirm it (CONFIRM_RUNS - 1 more runs with the diverging seed; every
        control-alone run counts, a miss before the first hit included; at least 2 hits and 2 of 3 of all runs), then
        two negative controls: without shuffle (twice) and with each control seed (once); none may reproduce."""
        first = [bool(x["triggered"]) for x in self.log if x["step"] == "control-alone"]
        conf = [bool(self._try("serial", [], victim, "alone-confirm")) for _ in range(CONFIRM_RUNS - 1)]
        hits, n = sum(first) + sum(conf), len(first) + len(conf)
        info = {"alone_hits": hits, "alone_runs": n, "unseeded": [], "control_seeds": []}
        if hits < 2 or 3 * hits < 2 * n:
            return R_ALONE_ONCE, info
        for _ in range(2):
            info["unseeded"].append(self._try("serial", [], victim, "control-unseeded", None))
        for sd in control_seeds:
            info["control_seeds"].append({"seed": sd, "reproduced": self._try("serial", [], victim,
                                                                              f"control-seed-{sd}", sd)})
        if any(info["unseeded"]):
            return R_ALONE_UNSEEDED, info
        if any(c["reproduced"] for c in info["control_seeds"]):
            return R_ALONE_CTL, info
        return R_ALONE, info

    def search(self, cands, victim, conc_cands=None, control_seeds=()):
        """Controls first (review decision D1, 2026-11-23): the victim's file alone, with the diverging run's
        within-file order (if it reproduces: confirmed and negative-controlled in alone()); per mode, the full candidate
        set must reproduce the divergence before it is bisected (else nothing is claimed about pairs)."""
        res = {"result": None, "polluter": None, "search": None, "confirm": None, "attempts": [], "alone": None}
        try:
            if self.triggers("serial", [], victim, "control-alone"):
                res["result"], res["alone"] = self.alone(victim, control_seeds)
            else:
                for mode, cs in (("serial", cands), ("concurrent", cands if conc_cands is None else conc_cands)):
                    att = {"search": mode, "n_candidates": len(cs), "found": None}
                    res["attempts"].append(att)
                    if not cs:
                        att["stop"] = "no candidate"
                        continue
                    if not self.triggers(mode, cs, victim, "control-full"):
                        att["stop"] = "not reproduced (full candidate set)"
                        continue
                    p = self.bisect(mode, cs, victim)
                    att["found"] = p
                    if p is None:
                        att["stop"] = R_INTERACTION
                        continue
                    c = self.confirm(mode, p, victim)
                    att["confirm"] = c
                    if c["confirmed"]:
                        res.update(result=R_PAIR, polluter=p, search=mode, confirm=c)
                        break
                    att["stop"] = "not confirmed"
                else:
                    stops = [a.get("stop") for a in res["attempts"]]
                    res["result"] = (R_INTERACTION if R_INTERACTION in stops else
                                     R_NOT_CONFIRMED if "not confirmed" in stops else R_NOT_REPRO)
        except Budget:
            res["result"] = R_BUDGET
        except TrialFailed:
            res["result"] = R_TRIAL_FAILED
        res["runs_spent"] = self.spent
        res["reproduced_in_trials"] = sum(1 for x in self.log if x["triggered"])
        return res


def control_seeds_for(runs, vid, verdict):
    """distinct seeds of runs where the victim kept its serial outcome, up to 2. A seed under which the victim differed
    from serial in any run (a diverging P run, an SS run, an invalid or crashed P run that reported it) is excluded."""
    seed_of = {rn: sd for rn, _, sd in run_names()}
    bad = {seed_of[rn] for rn in verdict["diverging_runs"]}
    bad |= {seed_of.get(r["name"]) for r in runs if vid in (r["outcomes"] or {}) and r["outcomes"][vid] != verdict["serial"]}
    out = []
    for r in runs:
        sd = seed_of.get(r["name"])
        if sd is None or sd in bad or sd in out:
            continue
        if r["status"] == "ok" and (r["outcomes"] or {}).get(vid) == verdict["serial"]:
            out.append(sd)
    return out[:2]


def trial_evidence(got, serial_outcome, vtimes, victim, asked):
    """(hit, extra files, extra files started before the victim's file ended) of one trial. vitest file arguments are
    substring filters: a file not requested that started before the victim's file ended in the victim's process makes
    the trial no evidence (hit None); later ones are recorded only. Without the victim's outcome, or without its file's
    start/end (the rule cannot be checked), hit is None too."""
    vt = vtimes.get(victim)
    extra = sorted(f for f in vtimes if f not in set(asked))
    extra_before = [f for f in extra if vt and vtimes[f][0] < vt[1]]
    hit = None if got is None or vt is None or extra_before else got != serial_outcome
    return hit, extra, extra_before


def victim_file(test_id):
    return test_id.split("::", 1)[0].split("@@", 1)[0]


def overlapping(times, vfile_abs):
    """files whose [start, end] overlapped the victim's file in the diverging run, in start order (concurrent search)"""
    if vfile_abs not in times:
        return None
    vs, ve = times[vfile_abs]
    c = [(v[0], f) for f, v in times.items() if f != vfile_abs and v[0] < ve and v[1] > vs]
    return [f for _, f in sorted(c)]


def candidates(times, vfile_abs):
    """files that started before the victim's file ended in the diverging run, in start order (victim excluded)."""
    if vfile_abs not in times:
        return None
    vend = times[vfile_abs][1]
    c = [(v[0], f) for f, v in times.items() if f != vfile_abs and v[0] < vend]
    return [f for _, f in sorted(c)]


class RealTrial:
    def __init__(self, repo, serial_outcome, victim_id, timeout, seed=None):
        self.repo = repo
        self.seed = seed
        self.serial_outcome = serial_outcome
        self.victim_id = victim_id
        self.timeout = timeout
        self.n = 0
        args, cfg = strip_config(repo.spec.get("args", []))
        self.args, self.cfg = args, cfg

    def _cmd(self, files, raw, rep, tmp, wrapper, gi=0, concurrent=False, seed=DEFAULT):
        r = self.repo
        seed = self.seed if seed is DEFAULT else seed
        if r.runner == "jest":
            return direct("jest", self.args) + (["--config", self.cfg] if self.cfg else []) + ["--runInBand", f"--testSequencer={JEST_SEQ}"] + \
                (["--randomize", f"--seed={seed}"] if seed is not None else []) + [
                                                 f"--cacheDirectory={tmp}/jest", "--json", f"--outputFile={raw}",
                                                 "--runTestsByPath"] + files
        return direct("vitest", self.args) + ["--config", wrapper, "--no-file-parallelism", "--maxWorkers=1",
                                              "--reporter=default", "--reporter=json", f"--outputFile.json={raw}",
                                              f"--reporter={rep}"] + \
            ([f"--coverage.reportsDirectory={tmp}/coverage-{gi}"] if concurrent else []) + files

    def __call__(self, mode, polluters, victim, seed=DEFAULT):
        r = self.repo
        self.n += 1
        seed = self.seed if seed is DEFAULT else seed
        built, rep = r.prepare()
        wrapper = write_vitest_wrapper(r.cwd, self.cfg)[0] if r.runner == "vitest" else None
        tmp = r.fresh_tmp()
        tag = f"pair-{hashlib.sha1(self.victim_id.encode()).hexdigest()[:10]}-{self.n}"
        jobs, meta = [], []
        groups = [polluters + [victim]] if mode == "serial" else ([[victim], polluters] if polluters else [[victim]])
        for gi, files in enumerate(groups):
            raw = os.path.join(r.out, f"{tag}-{gi}.raw.json")
            ids = os.path.join(r.out, f"{tag}-{gi}.ids.json")
            for f in (raw, ids):
                if os.path.exists(f):
                    os.remove(f)
            env_add = {"TMPDIR": tmp, "TMP": tmp, "TEMP": tmp, "CA_ORDER": json.dumps(files)}
            if seed is not None:
                env_add["CA_SEED"] = str(seed)
            if r.runner == "vitest":
                env_add["PM_IDS_OUT"] = ids
            cmd = self._cmd(files, raw, rep, tmp, wrapper, gi, mode == "concurrent", seed)
            jobs.append((cmd, {**r.env, **env_add}))
            meta.append((raw, ids, shell_cmd(cmd, env_add, r.cwd)))
        res = run_procs(jobs, r.cwd, self.timeout, r.log)
        raw, ids, _ = meta[0]
        oc, _, vtimes = read_report(r.runner, raw, ids, r.cwd)
        ptimes = read_report(r.runner, meta[1][0], meta[1][1], r.cwd)[2] if len(meta) > 1 else {}
        got = (oc or {}).get(self.victim_id)
        vt = vtimes.get(victim)
        overlapped = sorted(f for f, (a, b) in ptimes.items() if vt and a < vt[1] and b > vt[0]) if mode == "concurrent" else None
        hit, extra, extra_before = trial_evidence(got, self.serial_outcome, vtimes, victim, groups[0])
        rec = {"cmds": [m[2] for m in meta], "exits": [x[0]["exit"] for x in res],
               "wall_s": max(x[0]["wall_s"] for x in res), "timed_out": any(x[0]["timed_out"] for x in res),
               "victim_outcome": got, "seed": seed, "extra_files": extra, "extra_before_victim": extra_before, "file_times": {**vtimes, **ptimes},
               "overlapped_victim": overlapped, "build": built, "prep": "tree reset, build, caches cleared, fresh TMPDIR; vitest: wrapper "
               ".fenvix-harness/vitest.control.config.mjs written by control_arm.write_vitest_wrapper" if r.runner == "vitest"
               else "tree reset, build, fresh TMPDIR (jest cache in it)"}
        return hit, rec


def cmd_pairs(name, out=None, max_victims=MAX_VICTIMS):
    repo = Repo(name, out)
    runs, _, times = load_runs(name)
    rows = [x for x in read_jsonl(RESULTS) if x.get("repo") == name]
    vs = {x["test"]: x for x in rows if x.get("row") == "verdict"}
    med = serial_median([x for x in rows if x.get("row") == "run"])
    div = sorted(t for t, v in vs.items() if v["verdict"] == "DIVERGES")
    victims = div if len(div) <= max_victims else sorted(random.Random(1).sample(div, max_victims))
    deadline = time.time() + PAIR_BUDGET_S
    timeout = int(max(3 * (med or 600), 60))
    t_repo0 = time.time()
    out_rows = []
    for vid in victims:
        v = vs[vid]
        drun = v["diverging_runs"][0]
        vabs = os.path.join(repo.cwd, victim_file(vid))
        cands = candidates(times[drun], vabs)
        conc = overlapping(times[drun], vabs)
        seed = next(sd for rn, _, sd in run_names() if rn == drun)
        t0 = time.time()
        row = {"repo": name, "victim": vid, "victim_file": victim_file(vid), "label": v["label"],
               "serial_outcome": v["serial"], "diverged_in": drun,
               "diverged_outcome": next(r["outcomes"].get(vid) for r in runs if r["name"] == drun),
               "n_candidates": len(cands) if cands is not None else None,
               "n_overlapping": len(conc) if conc is not None else None, "seed": seed,
               "victims_sampled": f"{len(victims)} of {len(div)} (random.Random(1).sample over sorted ids)" if len(div) > max_victims else f"all {len(div)}"}
        if not cands:
            row.update(result="no minimal pair", why="no candidate file started before the victim's file ended"
                       if cands is not None else "victim file has no start/end time in the diverging run",
                       runs_spent=0, attempts=[], trials=[])
        else:
            ps = PairSearch(RealTrial(repo, v["serial"], vid, timeout, seed), deadline=deadline)
            res = ps.search(cands, vabs, conc, control_seeds_for(runs, vid, v))
            row.update(res)
            row["polluter"] = os.path.relpath(res["polluter"], repo.cwd) if res.get("polluter") else None
            row["trials"] = ps.log
        row["search_s"] = round(time.time() - t0, 2)
        out_rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("victim", "result", "polluter", "search", "runs_spent")}), flush=True)
        keep = [x for x in read_jsonl(PAIRS) if not (x.get("repo") == name and x.get("victim") == vid)]
        write_jsonl(PAIRS, keep + [row])
    M.reset_tree(repo.cwd)
    summ = {"row": "pair_search", "repo": name, "victims": len(victims), "diverges": len(div),
            "pair_search_s": round(time.time() - t_repo0, 2)}
    keep = [x for x in read_jsonl(RESULTS) if not (x.get("repo") == name and x.get("row") == "pair_search")]
    write_jsonl(RESULTS, keep + [summ])
    return out_rows


# ---------------------------------------------------------------------------------------------------------------


def read_jsonl(p):
    if not os.path.exists(p):
        return []
    return [json.loads(x) for x in open(p) if x.strip()]


def write_jsonl(p, rows):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    os.replace(tmp, p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["runs", "verdict", "pairs", "all", "loadfail", "supp_ss"])
    ap.add_argument("--name", required=True)
    ap.add_argument("--out")
    o = ap.parse_args()
    if o.what == "loadfail":
        cmd_loadfail(o.name)
    if o.what == "supp_ss":
        cmd_supp_ss(o.name, o.out)
    if o.what in ("runs", "all"):
        cmd_runs(o.name, o.out)
    if o.what in ("verdict", "all"):
        cmd_verdict(o.name)
    if o.what in ("pairs", "all"):
        cmd_pairs(o.name, o.out)


if __name__ == "__main__":
    main()
