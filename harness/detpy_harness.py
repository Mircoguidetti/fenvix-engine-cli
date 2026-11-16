#!/usr/bin/env python3
"""Measurement harness for detpy Level 0.

Pools of repositories (``harness/repos.json``):

* ``flaky``: projects from the IDoFT dataset (Python section), checked out at
  the commit where their flaky tests were detected (``flaky_candidates.json``,
  built by ``select_flaky.py``), with a Python version of that era;
* ``popular``: popular projects with large suites, at HEAD.

Protocol for each repository (isolated uv virtualenv, pytest-randomly and
pytest-xdist always installed):

1. **baseline**: N normal runs, random order with a different
   ``--randomly-seed`` per run and ``-n 2`` (pytest-xdist) when the suite
   supports it;
2. **det**: N runs with ``--det`` (fixed order, serial), interleaved with the
   baseline runs;
3. **exploration**, for every test whose outcome is unstable in the baseline:
   ``--det --det-seed=s`` for s = 1..K (one run per seed); when a seed makes a
   pending unstable test fail, that seed is run 9 more times; the test is
   *reproduced* when it fails 10/10 with one seed (the fixed ``--det`` order
   counts as seed 0). The fingerprints of a passing and a failing ``--det`` run
   are compared to locate the first diverging event.

Outputs in ``harness/results/<set>/``: ``<repo>.csv`` (per test),
``<repo>_runs.csv`` (per run), ``summary.json``, ``REPORT.md``.

    python harness/detpy_harness.py --set validate --runs 10
    python harness/detpy_harness.py --set mixed --per-pool 25 --runs 10 --jobs 2
    python harness/detpy_harness.py --set mixed --report-only
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime
import glob
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEST_WORDS = ("test", "tests", "testing")
REQ_FILES = (
    "requirements/tests.txt", "requirements/test.txt", "requirements/testing.txt",
    "requirements-test.txt", "requirements-tests.txt", "requirements_test.txt", "test-requirements.txt",
    "test_requirements.txt", "tests/requirements.txt", "requirements/dev.txt", "requirements-dev.txt",
    "dev-requirements.txt", "requirements_dev.txt", "requirements.txt",
)
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd, cwd=None, env=None, timeout=None):
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                           errors="replace", stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout + p.stderr, time.perf_counter() - t0, False
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -9, out, time.perf_counter() - t0, True


def is_fail(outcome) -> bool:
    return outcome is not None and (outcome.startswith("failed") or outcome.startswith("error")
                                    or "teardown-error" in outcome)


# ---------------------------------------------------------------------------
# Preparation
@dataclass
class Prepared:
    name: str
    url: str
    kind: str
    sha: str = ""
    status: str = "pending"
    detail: str = ""
    commit: str = ""
    commit_date: str = ""
    python_version: str = ""
    python: str = ""
    src: str = ""
    pytest_args: list = field(default_factory=list)
    install_cmd: str = ""
    collected: int = 0
    xdist: bool = False
    has_xdist: bool = False
    env: dict = field(default_factory=dict)
    max_run_seconds: float = 0
    known_flaky: dict = field(default_factory=dict)


def detect_install(src: Path) -> tuple[list, list, list]:
    """(project args, dependency-group args, requirement-file args)."""
    data = {}
    pyproject = src / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
        except Exception:
            data = {}
    extras = [k for k in (data.get("project", {}).get("optional-dependencies") or {})
              if any(w in k.lower() for w in TEST_WORDS)]
    if not extras and (src / "setup.py").exists():
        text = (src / "setup.py").read_text(errors="replace")
        extras = re.findall(r"['\"](tests?|testing)['\"]\s*:", text)[:1]
    args = ["-e", f".[{','.join(extras)}]" if extras else "."]
    groups = []
    all_groups = list(data.get("dependency-groups", {}) or {})
    test_groups = [g for g in all_groups if any(w in g.lower() for w in TEST_WORDS)]
    for g in test_groups or [g for g in all_groups if g.lower() == "dev"]:
        groups += ["--group", g]
    reqs = []
    for f in REQ_FILES:
        if (src / f).exists():
            reqs += ["-r", f]
    return args, groups, reqs


def clean_env(venv_python: str, extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHASHSEED", "DETPY_REEXEC", "VIRTUAL_ENV", "PYTHONPATH", "PYTEST_ADDOPTS",
                        "PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "DETPY_PRECOMPILE_S")}
    env["PATH"] = str(Path(venv_python).parent) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(Path(venv_python).parent.parent)
    env["COLUMNS"] = "160"
    env.update(extra or {})
    return env


def checkout(p: Prepared, src: Path) -> bool:
    if (src / ".git").exists():
        return True
    if p.sha:
        src.mkdir(parents=True, exist_ok=True)
        for cmd in (["git", "init", "-q"], ["git", "remote", "add", "origin", p.url],
                    ["git", "fetch", "-q", "--depth", "1", "origin", p.sha], ["git", "checkout", "-q", "FETCH_HEAD"]):
            code, out, _, _ = sh(cmd, cwd=src, timeout=600)
            if code != 0:
                p.status, p.detail = "clone-failed", f"{' '.join(cmd[:3])}: {out[-300:]}"
                shutil.rmtree(src, ignore_errors=True)
                return False
        return True
    code, out, _, _ = sh(["git", "clone", "--depth", "1", "--quiet", p.url, str(src)], timeout=600)
    if code != 0:
        p.status, p.detail = "clone-failed", out[-300:]
        return False
    return True


def python_candidates(p: Prepared, repo: dict, default: str) -> list[str]:
    if repo.get("python"):
        return list(repo["python"])
    if p.kind != "flaky":
        return [default]
    year = int(p.commit_date[:4]) if p.commit_date[:4].isdigit() else 2024
    if year <= 2021:
        return ["3.9", "3.10"]
    if year == 2022:
        return ["3.10", "3.11"]
    if year == 2023:
        return ["3.11", "3.12"]
    return ["3.12", "3.13"]


def _collect(py: str, src: Path, env: dict, args: list) -> tuple[bool, int, str]:
    code, out, _, _ = sh([py, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-p", "no:randomly",
                          *args], cwd=src, env=env, timeout=600)
    n = sum(1 for line in out.splitlines() if "::" in line and not line.startswith(("ERROR", "FAILED")))
    return code == 0 and n > 0, n, out


def prepare(repo: dict, work: Path, wheel: str, default_python: str, max_first_run: float) -> Prepared:
    p = Prepared(name=repo["name"], url=repo["url"], kind=repo.get("kind", "popular"), sha=repo.get("sha", ""),
                 env=repo.get("env", {}), max_run_seconds=repo.get("max_run_seconds", max_first_run),
                 known_flaky=repo.get("known_flaky", {}))
    src = work / "src" / p.name
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    p.src = str(src)
    if not checkout(p, src):
        return p
    p.commit = sh(["git", "rev-parse", "HEAD"], cwd=src)[1].strip()[:12]
    p.commit_date = sh(["git", "log", "-1", "--format=%cs"], cwd=src)[1].strip()
    venv = work / "venvs" / p.name
    marker = venv / ".detpy-prepared.json"
    last = ""
    for pyver in python_candidates(p, repo, default_python):
        py = venv / "bin" / "python"
        if marker.exists() and json.loads(marker.read_text()).get("python_version") == pyver:
            p.install_cmd = json.loads(marker.read_text()).get("install", "")
            code, out, _, _ = sh(["uv", "pip", "install", "--quiet", "--python", str(py), "--reinstall-package",
                                  "detpy", "--no-deps", wheel], timeout=300)
            if code != 0:
                last = "install: detpy wheel: " + out[-300:]
                continue
        else:
            shutil.rmtree(venv, ignore_errors=True)
            code, out, _, _ = sh(["uv", "venv", "--quiet", "--python", pyver, str(venv)], timeout=600)
            if code != 0:
                last = f"install: venv {pyver}: " + out[-300:]
                continue
            base = ["uv", "pip", "install", "--quiet", "--python", str(py)]
            year = int(p.commit_date[:4]) if p.commit_date[:4].isdigit() else 2026
            tools = [wheel, "pytest>=7,<8" if year <= 2022 else "pytest>=7", "pytest-randomly", "pytest-xdist"]
            args, groups, reqs = detect_install(src)
            extra = repo.get("install", [])
            attempts = [args + groups + reqs + extra, args + groups + extra, args + reqs + extra, args + extra,
                        ["-e", "."] + extra]
            ok = False
            for attempt in attempts:
                code, out, _, _ = sh(base + attempt + tools, cwd=src, timeout=1500)
                (logs / f"{p.name}.install.log").write_text(f"python {pyver}: " + " ".join(attempt) + "\n" + out)
                if code == 0:
                    p.install_cmd, ok = " ".join(attempt), True
                    break
            if not ok:
                last = f"install with python {pyver}: " + out[-400:]
                continue
            marker.write_text(json.dumps({"python_version": pyver, "install": p.install_cmd}))
        env = clean_env(str(py), p.env)
        base_args = list(repo.get("pytest_args", []))
        for extra in ([], ["-o", "addopts="]):
            ok, n, out = _collect(str(py), src, env, base_args + extra)
            if ok:
                p.pytest_args, p.collected = base_args + extra, n
                break
        else:
            last = f"collect with python {pyver}: " + out[-500:]
            (logs / f"{p.name}.collect.log").write_text(out)
            marker.unlink(missing_ok=True)
            continue
        p.python, p.python_version = str(py), pyver
        p.has_xdist = sh([str(py), "-c", "import xdist"])[0] == 0
        if p.has_xdist:
            p.xdist = _collect(str(py), src, env, p.pytest_args + ["-n", "2"])[0]
        p.status = "ok"
        return p
    p.status = "install-failed" if last.startswith("install") else "collect-failed"
    p.detail = last
    return p


# ---------------------------------------------------------------------------
# Runs
@dataclass
class RunResult:
    mode: str  # normal | det | seed
    index: int
    seed: int | None
    duration: float
    exit_code: int
    timed_out: bool
    outcomes: dict
    trace: str | None
    precompile_s: float | None = None

    @property
    def completed(self) -> bool:
        return not self.timed_out and bool(self.outcomes)


def run_pytest(p: Prepared, rundir: Path, mode: str, index: int, timeout: float, seed: int | None = None) -> RunResult:
    tag = f"{mode}{'' if seed is None else seed}_{index}"
    out_json = rundir / f"{tag}.json"
    trace = rundir / f"{tag}.jsonl" if mode != "normal" else None
    cmd = [p.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--det-outcomes={out_json}", *p.pytest_args]
    if mode == "normal":
        cmd += [f"--randomly-seed={1000 + index}"]
        if p.xdist:
            cmd += ["-n", "2"]
    else:
        cmd += ["--det", f"--det-trace={trace}"]
        if seed is not None:
            cmd += [f"--det-seed={seed}"]
        if p.has_xdist:
            cmd += ["-n", "0"]
    code, out, dur, to = sh(cmd, cwd=p.src, env=clean_env(p.python, p.env), timeout=timeout)
    (rundir / f"{tag}.log").write_text(out[-20000:])
    outcomes = {}
    if out_json.exists():
        try:
            outcomes = json.loads(out_json.read_text())["outcomes"]
        except Exception:
            pass
    pre = None
    if trace is not None and trace.exists():
        try:
            with open(trace) as f:
                pre = json.loads(f.readline()).get("meta", {}).get("precompile_s")
        except Exception:
            pass
    return RunResult(mode, index, seed, dur, code, to, outcomes, str(trace) if trace and trace.exists() else None, pre)


def _hung_test(r: RunResult) -> str:
    if r.trace:
        try:
            lines = open(r.trace).read().splitlines()
            order = json.loads(lines[0]).get("order", [])
            done = {json.loads(line)["nodeid"] for line in lines[1:] if '"type":"test"' in line}
            return next((nid for nid in order if nid not in done), "unknown")
        except Exception:
            pass
    return "unknown"


def measure(p: Prepared, args, outdir: Path, work: Path) -> dict:
    rundir = work / "runs" / p.name
    shutil.rmtree(rundir, ignore_errors=True)
    rundir.mkdir(parents=True)
    results: list[RunResult] = []
    timeout = args.run_timeout
    t_start = time.monotonic()
    for i in range(args.runs):
        for mode in ("normal", "det"):
            r = run_pytest(p, rundir, mode, i, timeout)
            results.append(r)
            log(f"{p.name}: {mode} #{i} {r.duration:.1f}s exit={r.exit_code}{' TIMEOUT' if r.timed_out else ''} "
                f"tests={len(r.outcomes)}")
            if i == 0 and mode == "normal":
                if r.duration > p.max_run_seconds:
                    return {"name": p.name, "kind": p.kind, "status": "too-slow",
                            "detail": f"first baseline run took {r.duration:.0f}s"}
                if not r.outcomes:
                    return {"name": p.name, "kind": p.kind, "status": "baseline-broken",
                            "detail": f"first baseline run produced no outcomes (exit {r.exit_code}): "
                                      + (Path(rundir / "normal_0.log").read_text()[-200:])}
                timeout = min(args.run_timeout, max(180.0, 10 * r.duration))
            if r.timed_out:
                return {"name": p.name, "kind": p.kind, "status": f"{mode}-timeout",
                        "detail": f"{mode} run #{i} exceeded {timeout:.0f}s; running: {_hung_test(r)}"}
    explore = explore_seeds(p, results, rundir, timeout, args, t_start)
    return analyze(p, results, explore, outdir)


def explore_seeds(p: Prepared, results: list[RunResult], rundir: Path, timeout: float, args, t_start) -> dict:
    """Search, for every baseline-unstable test, a --det configuration that makes it
    fail confirm/confirm times AND evidence that it passes under another one.

    Both are required: a test that fails under every --det configuration was
    broken by Level 0 itself (e.g. by the virtual clock), it is not a
    reproduction of the baseline flakiness.
    """
    normal = [r for r in results if r.mode == "normal" and r.completed]
    det = [r for r in results if r.mode == "det" and r.completed]
    ids = set().union(*(r.outcomes.keys() for r in normal)) if normal else set()
    unstable = sorted(nid for nid in ids if len({r.outcomes.get(nid) for r in normal}) > 1)
    state = {nid: {"fail_seed": None, "pass_seen": False, "seeds_needed": None, "best": ""} for nid in unstable}
    for nid in unstable:
        fails = sum(is_fail(r.outcomes.get(nid)) for r in det)
        st = state[nid]
        st["best"] = f"fixed:{fails}/{len(det)}"
        st["pass_seen"] = any(r.outcomes.get(nid) == "passed" for r in det)
        if det and fails == len(det) and len(det) >= args.confirm:
            st["fail_seed"], st["seeds_needed"] = 0, 0

    def done(nid):
        st = state[nid]
        return st["fail_seed"] is not None and st["pass_seen"]

    seed_runs: dict[int, list[RunResult]] = {}
    explored = 0
    for s in range(1, args.seeds + 1):
        pending = [nid for nid in unstable if not done(nid)]
        if not pending or time.monotonic() - t_start > args.repo_budget:
            break
        r = run_pytest(p, rundir, "seed", 0, timeout, seed=s)
        explored = s
        seed_runs[s] = [r]
        if r.timed_out:
            log(f"{p.name}: seed {s} TIMEOUT, stopping exploration")
            break
        for nid in pending:
            if r.outcomes.get(nid) == "passed":
                state[nid]["pass_seen"] = True
        failing = [nid for nid in pending if state[nid]["fail_seed"] is None and is_fail(r.outcomes.get(nid))]
        log(f"{p.name}: seed {s} {r.duration:.1f}s pending={len(pending)} new-failing={len(failing)}")
        if not failing:
            continue
        for j in range(1, args.confirm):
            if time.monotonic() - t_start > args.repo_budget:
                break
            seed_runs[s].append(run_pytest(p, rundir, "seed", j, timeout, seed=s))
        runs = [x for x in seed_runs[s] if x.completed]
        for nid in failing:
            fails = sum(is_fail(x.outcomes.get(nid)) for x in runs)
            if any(x.outcomes.get(nid) == "passed" for x in runs):
                state[nid]["pass_seen"] = True
            if len(runs) >= args.confirm and fails == len(runs):
                state[nid]["fail_seed"], state[nid]["seeds_needed"] = s, s
            else:
                state[nid]["best"] = f"seed {s}:{fails}/{len(runs)}"
        log(f"{p.name}: seed {s} confirmed with {len(runs)} runs, reproduced so far "
            f"{sum(done(n) for n in unstable)}/{len(unstable)}")
    for nid in unstable:
        state[nid]["reproduced"] = done(nid)
        state[nid]["seed"] = state[nid]["fail_seed"]
    return {"unstable": unstable, "state": state, "seed_runs": seed_runs, "explored": explored,
            "budget_hit": any(not done(n) for n in unstable) and time.monotonic() - t_start > args.repo_budget}


# ---------------------------------------------------------------------------
# Analysis
def _hist(values) -> str:
    c = collections.Counter(v if v is not None else "missing" for v in values)
    return ";".join(f"{k}={v}" for k, v in sorted(c.items()))


def _majority(values):
    vals = [v for v in values if v is not None]
    return collections.Counter(vals).most_common(1)[0][0] if vals else None


def _verify(_core, traces) -> dict:
    try:
        return {t["nodeid"]: t for t in json.loads(_core.verify(traces))["tests"]}
    except Exception as e:  # unreadable trace
        log(f"verify failed: {e}")
        return {}


def analyze(p: Prepared, results: list[RunResult], explore: dict, outdir: Path) -> dict:
    sys.path.insert(0, str(ROOT / "python"))
    from detpy import _core

    normal = [r for r in results if r.mode == "normal" and r.completed]
    det = [r for r in results if r.mode == "det" and r.completed]
    seed_all = [x for runs in explore["seed_runs"].values() for x in runs]
    all_det = det + [x for x in seed_all if x.completed]
    ids = sorted(set().union(*(r.outcomes.keys() for r in results)))
    fixed_verdicts = _verify(_core, [r.trace for r in det if r.trace]) if len(det) >= 2 else {}

    # (c) divergence between a passing and a failing --det execution
    pair_of = {}
    for nid in explore["unstable"]:
        st = explore["state"][nid]
        fail_run = None
        if st["reproduced"] and st["seed"]:
            fail_run = next((x for x in explore["seed_runs"][st["seed"]] if x.trace and is_fail(x.outcomes.get(nid))),
                            None)
        fail_run = fail_run or next((x for x in all_det if x.trace and is_fail(x.outcomes.get(nid))), None)
        pass_run = next((x for x in all_det if x.trace and x.outcomes.get(nid) == "passed"), None)
        if fail_run and pass_run:
            pair_of[nid] = (pass_run.trace, fail_run.trace)
    pair_verdicts = {pair: _verify(_core, list(pair)) for pair in set(pair_of.values())}

    known_map = {k: sorted(i for i in ids if i == k or i.startswith(k + "[")) for k in p.known_flaky}
    known_of = {nid: k for k, nids in known_map.items() for nid in nids}
    rows = []
    agg = collections.Counter()
    reasons, div_reasons = collections.Counter(), collections.Counter()
    seeds_needed = []
    examples = collections.defaultdict(list)
    for nid in ids:
        nv = [r.outcomes.get(nid) for r in normal]
        dv = [r.outcomes.get(nid) for r in det]
        ns, ds = len(set(nv)) <= 1, len(set(dv)) <= 1
        nm, dm = _majority(nv), _majority(dv)
        v = fixed_verdicts.get(nid)
        covered = v is not None and v["status"] == "stable"
        fdiv = (v or {}).get("divergence") or {}
        st = explore["state"].get(nid)
        pdiv = {}
        if nid in pair_of:
            pdiv = (pair_verdicts[pair_of[nid]].get(nid) or {}).get("divergence") or {}
        elif st is not None and not ds:
            pdiv = fdiv
        row = {
            "nodeid": nid,
            "idoft_category": p.known_flaky.get(known_of.get(nid, ""), ""),
            "baseline_outcomes": _hist(nv),
            "baseline_unstable": not ns,
            "det_outcomes": _hist(dv),
            "det_stable": ds,
            "became_stable": (not ns) and ds,
            "outcome_changed_by_det": ns and ds and nm != dm,
            "reproduced": bool(st and st["reproduced"]),
            "repro_seed": "" if not st or st["seed"] is None else ("fixed" if st["seed"] == 0 else st["seed"]),
            "seeds_needed": "" if not st or st["seeds_needed"] is None else st["seeds_needed"],
            "best_attempt": st["best"] if st else "",
            "pass_fail_reason": pdiv.get("reason", ""),
            "pass_fail_divergence": pdiv.get("description", "")[:300],
            "fingerprint_covered": covered,
            "distinct_fingerprints": (v or {}).get("distinct_fingerprints", 0),
            "det_reason": fdiv.get("reason", "") if v and not covered else "",
            "det_divergence": fdiv.get("description", "")[:300],
        }
        rows.append(row)
        agg["tests"] += 1
        agg["unstable_baseline"] += not ns
        agg["unstable_det"] += not ds
        agg["became_stable"] += row["became_stable"]
        agg["outcome_changed_by_det"] += row["outcome_changed_by_det"]
        agg["covered"] += covered
        if v is not None and not covered:
            agg["not_covered"] += 1
            reasons[row["det_reason"]] += 1
        if st is not None:
            if st["reproduced"]:
                agg["reproduced"] += 1
                seeds_needed.append(st["seeds_needed"])
                if pdiv:
                    div_reasons[pdiv.get("reason", "")] += 1
                if len(examples["reproduced"]) < 3:
                    examples["reproduced"].append(
                        f"{nid} (seed {row['repro_seed']}): {pdiv.get('description', '')[:160]}")
            elif all(not is_fail(r.outcomes.get(nid)) for r in all_det):
                agg["never_fails_under_det"] += 1
            elif st["fail_seed"] is not None or all(is_fail(r.outcomes.get(nid)) for r in all_det
                                                    if r.outcomes.get(nid) is not None):
                agg["always_fails_under_det"] += 1
                if len(examples["always-fails-under-det"]) < 2:
                    examples["always-fails-under-det"].append(f"{nid} ({st['best']})")
            else:
                agg["fails_sometimes_under_det"] += 1
                if len(examples["not-reproduced"]) < 2:
                    examples["not-reproduced"].append(f"{nid} ({st['best']}) {pdiv.get('description', '')[:120]}")
        if row["outcome_changed_by_det"] and len(examples[f"changed:{nm}->{dm}"]) < 2:
            examples[f"changed:{nm}->{dm}"].append(nid)

    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / f"{p.name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["nodeid"])
        w.writeheader()
        w.writerows(rows)
    with open(outdir / f"{p.name}_runs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "seed", "run", "duration_s", "precompile_s", "exit_code", "timed_out", "tests", "passed",
                    "failed", "error", "skipped", "other"])
        for r in results + seed_all:
            c = collections.Counter(o.split("+")[0] for o in r.outcomes.values())
            other = sum(v for k, v in c.items() if k not in ("passed", "failed", "error", "skipped"))
            w.writerow([r.mode, "" if r.seed is None else r.seed, r.index, f"{r.duration:.3f}",
                        "" if r.precompile_s is None else r.precompile_s, r.exit_code, r.timed_out,
                        len(r.outcomes), c["passed"], c["failed"], c["error"], c["skipped"], other])

    nd = [r.duration for r in normal]
    dd = [r.duration for r in det]
    pre = [r.precompile_s for r in det if r.precompile_s is not None]
    unstable_ids = {row["nodeid"] for row in rows if row["baseline_unstable"]}
    known_present = {k: n for k, n in known_map.items() if n}
    known_unstable = {k for k, nids in known_present.items() if unstable_ids.intersection(nids)}
    known_repro = {k for k, nids in known_present.items()
                   if any(explore["state"].get(n, {}).get("reproduced") for n in nids)}
    mean_n = statistics.mean(nd) if nd else float("nan")
    mean_d = statistics.mean(dd) if dd else float("nan")
    summary = {
        "name": p.name, "kind": p.kind, "status": "ok", "url": p.url, "commit": p.commit,
        "commit_date": p.commit_date, "python": p.python_version, "install": p.install_cmd,
        "pytest_args": p.pytest_args, "xdist": p.xdist, "runs": len(normal),
        "baseline_mean_s": mean_n, "det_mean_s": mean_d,
        "slowdown_pct": (mean_d / mean_n - 1) * 100 if nd and dd and mean_n > 0 else float("nan"),
        "precompile_first_s": pre[0] if pre else None,
        "precompile_rest_median_s": statistics.median(pre[1:]) if len(pre) > 1 else None,
        **{k: agg[k] for k in ("tests", "unstable_baseline", "unstable_det", "became_stable",
                               "outcome_changed_by_det", "covered", "not_covered", "reproduced",
                               "never_fails_under_det", "always_fails_under_det", "fails_sometimes_under_det")},
        "seeds_needed": seeds_needed,
        "seeds_explored": explore["explored"],
        "exploration_runs": len(seed_all),
        "exploration_budget_hit": explore["budget_hit"],
        "reasons": dict(reasons),
        "pass_fail_reasons": dict(div_reasons),
        "known_flaky": len(p.known_flaky),
        "known_present": len(known_present),
        "known_unstable_baseline": len(known_unstable),
        "known_reproduced": len(known_repro),
        "known_categories": dict(collections.Counter(p.known_flaky.values())),
        "examples": dict(examples),
    }
    (outdir / f"{p.name}.summary.json").write_text(json.dumps(summary, indent=2))
    return summary


# ---------------------------------------------------------------------------
# Report (Italian: it is read by the project owner)
def _fmt(x, nd=1):
    return "n/d" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def _pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "n/d"


BUCKETS = ("0 (ordine fisso)", "1", "2-5", "6-10", "11-20", ">20")


def _bucket(n):
    return BUCKETS[0] if n == 0 else "1" if n == 1 else "2-5" if n <= 5 else "6-10" if n <= 10 else \
        "11-20" if n <= 20 else ">20"


def write_report(outdir: Path, meta: dict) -> Path:
    summaries = [json.loads(f.read_text()) for f in sorted(outdir.glob("*.summary.json"))]
    skipped = json.loads((outdir / "skipped.json").read_text()) if (outdir / "skipped.json").exists() else []
    order = meta.get("order") or []
    ok = sorted([s for s in summaries if s.get("status") == "ok"],
                key=lambda s: order.index(s["name"]) if s["name"] in order else 1e9)
    keys = ("tests", "unstable_baseline", "unstable_det", "became_stable", "outcome_changed_by_det", "covered",
            "not_covered", "reproduced", "never_fails_under_det", "always_fails_under_det",
            "fails_sometimes_under_det", "known_flaky",
            "known_present", "known_unstable_baseline", "known_reproduced")
    tot = {kind: collections.Counter() for kind in ("all", "flaky", "popular")}
    reasons, pf_reasons, seeds = collections.Counter(), collections.Counter(), []
    for s in ok:
        for kind in {"all", s["kind"]}:
            for k in keys:
                tot.setdefault(kind, collections.Counter())[k] += s.get(k, 0)
        reasons.update(s["reasons"])
        pf_reasons.update(s["pass_fail_reasons"])
        seeds += s["seeds_needed"]
    slow = [s["slowdown_pct"] for s in ok if s["slowdown_pct"] == s["slowdown_pct"]]
    pre_first = [s["precompile_first_s"] for s in ok if s.get("precompile_first_s") is not None]
    pre_rest = [s["precompile_rest_median_s"] for s in ok if s.get("precompile_rest_median_s") is not None]
    T = tot["all"]
    med = statistics.median

    L = [f"# detpy Livello 0 — rapporto di misura (`{meta.get('set')}`)\n",
         f"Generato il {meta.get('date')} con detpy {meta.get('detpy')}. Per repository: {meta.get('runs')} run di "
         f"baseline (ordine casuale con pytest-randomly, seme diverso per run, pytest-xdist `-n 2` dove la suite lo "
         f"supporta) alternati a {meta.get('runs')} run `--det` (ordine fisso, seriale); poi, per i test instabili in "
         f"baseline, esplorazione con `--det-seed=1..{meta.get('seeds')}` e conferma {meta.get('confirm')}/"
         f"{meta.get('confirm')} del seme che li fa fallire. {meta.get('jobs')} repository in parallelo su "
         f"{os.cpu_count()} CPU.\n",
         "## Metrica principale\n",
         f"**Test instabili in baseline resi riproducibili: {T['reproduced']}/{T['unstable_baseline']} = "
         f"{_pct(T['reproduced'], T['unstable_baseline'])}** — esiste un `--det-seed` (o l'ordine fisso di `--det`) "
         f"con cui il test fallisce {meta.get('confirm')} volte su {meta.get('confirm')}, e almeno una configurazione "
         f"`--det` in cui passa (altrimenti il fallimento è causato dal Livello 0 stesso, non riprodotto).\n",
         "| pool | repository | test | instabili in baseline | riprodotti | % | mai falliti sotto --det | "
         "falliscono sempre sotto --det | falliscono a volte sotto --det |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for kind, label in (("flaky", "dataset IDoFT"), ("popular", "popolari"), ("all", "totale")):
        t = tot[kind]
        n = len([s for s in ok if kind == "all" or s["kind"] == kind])
        if not n:
            continue
        L.append(f"| {label} | {n} | {t['tests']} | {t['unstable_baseline']} | {t['reproduced']} | "
                 f"{_pct(t['reproduced'], t['unstable_baseline'])} | {t['never_fails_under_det']} | "
                 f"{t['always_fails_under_det']} | {t['fails_sometimes_under_det']} |")
    L.append("")
    if seeds:
        b = collections.Counter(_bucket(x) for x in seeds)
        L.append("**(a) e (b) — semi esplorati prima di trovare il seme riproducente** (test riprodotti): "
                 + ", ".join(f"{k}: {b[k]}" for k in BUCKETS if b[k]) + f"; mediana {med(seeds):.0f}.\n")
    if pf_reasons:
        L.append("**(c) — primo evento divergente tra l'impronta di un run `--det` che passa e una che fallisce** "
                 "(test riprodotti): " + ", ".join(f"`{k}` {v}" for k, v in pf_reasons.most_common()) + ".\n")
    tf = tot["flaky"]
    if tf["known_flaky"]:
        L.append(f"**Test instabili noti (IDoFT)**: {tf['known_flaky']} nei progetti misurati; presenti nella suite "
                 f"raccolta {tf['known_present']}; instabili nella nostra baseline {tf['known_unstable_baseline']}; "
                 f"riprodotti {tf['known_reproduced']}.\n")
    L.append("## Altre metriche\n")
    L.append(f"* rallentamento di `--det` (seriale) rispetto alla baseline (casuale, xdist dove possibile): mediana "
             f"**{_fmt(med(slow) if slow else None)}%** (min {_fmt(min(slow) if slow else None)}%, max "
             f"{_fmt(max(slow) if slow else None)}%)")
    L.append(f"* precompilazione deterministica del bytecode, primo run `--det` di ogni repository: mediana "
             f"**{_fmt(med(pre_first) if pre_first else None, 2)} s** (max {_fmt(max(pre_first) if pre_first else None, 2)}"
             f" s); run successivi (verifica incrementale): mediana **{_fmt(med(pre_rest) if pre_rest else None, 2)} s**")
    L.append(f"* test instabili con `--det` (ordine fisso, {meta.get('runs')} run): {T['unstable_det']}; resi stabili "
             f"da `--det`: {T['became_stable']}")
    L.append(f"* esito cambiato da `--det` (stabile in entrambe le modalità ma diverso): {T['outcome_changed_by_det']}")
    L.append(f"* impronta identica in tutti i run `--det` (coperti dal Livello 0): {T['covered']} "
             f"({_pct(T['covered'], T['covered'] + T['not_covered'])}); non coperti: {T['not_covered']}"
             + (" — " + ", ".join(f"`{k}` {v}" for k, v in reasons.most_common()) if reasons else ""))
    L.append("")
    L.append("## Per repository\n")
    L.append("| repo | pool | py | xdist | test | baseline s | det s | rall. % | precomp. 1° s | instabili | "
             "riprodotti | semi esplorati | cambiati da det | non coperti |")
    L.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in ok:
        L.append(f"| [{s['name']}]({s['url']}) | {s['kind']} | {s['python']} | {'sì' if s['xdist'] else 'no'} | "
                 f"{s['tests']} | {_fmt(s['baseline_mean_s'], 2)} | {_fmt(s['det_mean_s'], 2)} | "
                 f"{_fmt(s['slowdown_pct'])} | {_fmt(s.get('precompile_first_s'), 2)} | {s['unstable_baseline']} | "
                 f"{s['reproduced']} | {s['seeds_explored']}{' (budget)' if s['exploration_budget_hit'] else ''} | "
                 f"{s['outcome_changed_by_det']} | {s['not_covered']} |")
    L.append("")
    if any(s.get("examples") for s in ok):
        L.append("## Esempi\n")
        for s in ok:
            ex = s.get("examples") or {}
            if ex:
                L.append(f"**{s['name']}**\n")
                for k, items in sorted(ex.items()):
                    L += [f"* `{k}` — {it}" for it in items]
                L.append("")
    if skipped:
        L.append("## Repository scartati\n")
        L.append("| repo | pool | motivo | dettaglio |")
        L.append("|---|---|---|---|")
        for sk in skipped:
            d = re.sub(r"\s+", " ", sk.get("detail", ""))[-220:].replace("|", "/")
            L.append(f"| {sk['name']} | {sk.get('kind', '')} | {sk['status']} | {d} |")
        L.append("")
    L.append("## Riproduzione\n")
    L += ["```bash", meta.get("command", ""), "```",
          "Dettagli per test in `<repo>.csv`, per run in `<repo>_runs.csv`; colonne in `docs/HARNESS.md`."]
    if meta.get("notes"):
        L += ["", "## Note", ""] + [f"* {n}" for n in meta["notes"]]
    path = outdir / "REPORT.md"
    path.write_text("\n".join(L) + "\n")
    (outdir / "summary.json").write_text(json.dumps({"meta": meta, "totals": {k: dict(v) for k, v in tot.items()},
                                                    "reasons": dict(reasons), "pass_fail_reasons": dict(pf_reasons),
                                                    "repos": ok, "skipped": skipped}, indent=2))
    return path


# ---------------------------------------------------------------------------
def build_wheel(work: Path) -> str:
    dist = work / "dist"
    existing = sorted(glob.glob(str(dist / "detpy-*.whl")))
    if existing:
        return existing[-1]
    code, out, _, _ = sh(["maturin", "build", "--release", "--compatibility", "linux", "-o", str(dist)],
                         cwd=ROOT, timeout=1800)
    if code != 0:
        sys.exit("wheel build failed:\n" + out[-3000:])
    return sorted(glob.glob(str(dist / "detpy-*.whl")))[-1]


def load_pools(cfg: dict) -> tuple[list[dict], list[dict]]:
    popular = [dict(r, kind="popular") for r in cfg["popular"]]
    flaky = []
    cand_file = HERE / cfg.get("flaky_candidates", "flaky_candidates.json")
    if cand_file.exists():
        overrides = cfg.get("flaky_overrides", {})
        for c in json.loads(cand_file.read_text())["candidates"]:
            flaky.append(dict(c, kind="flaky", **overrides.get(c["name"], {})))
    return flaky, popular


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repos", default=str(HERE / "repos.json"))
    ap.add_argument("--set", default="validate", help="'validate', 'mixed' or a comma separated list of names")
    ap.add_argument("--per-pool", type=int, default=25, help="repositories per pool for --set mixed")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=20, help="seeds explored per repository")
    ap.add_argument("--confirm", type=int, default=10, help="runs that must all fail to call a test reproduced")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--work", default=str(ROOT / ".harness-work"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--python", default=f"{sys.version_info.major}.{sys.version_info.minor}")
    ap.add_argument("--wheel", default=None)
    ap.add_argument("--run-timeout", type=float, default=900)
    ap.add_argument("--max-first-run", type=float, default=150,
                    help="drop repositories whose first baseline run is slower (seconds)")
    ap.add_argument("--repo-budget", type=float, default=2700,
                    help="seconds per repository after which the exploration stops")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="discard results already in --out instead of resuming")
    ap.add_argument("--checkpoint", action="store_true",
                    help="git commit + push the results directory after every repository (survives restarts)")
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.repos).read_text())
    flaky, popular = load_pools(cfg)
    by_name = {r["name"]: r for r in popular + flaky}
    if args.set == "validate":
        pools = {"popular": [by_name[n] for n in cfg["validate"]]}
        quota = {"popular": len(cfg["validate"])}
    elif args.set == "mixed":
        pools = {"flaky": flaky, "popular": popular}
        quota = {"flaky": args.per_pool, "popular": args.per_pool}
    else:
        names = [n.strip() for n in args.set.split(",") if n.strip()]
        pools = {"custom": [by_name[n] for n in names]}
        quota = {"custom": len(names)}
    outdir = Path(args.out or HERE / "results" / (args.set if args.set in ("validate", "mixed") else "custom"))
    work = Path(args.work)
    sys.path.insert(0, str(ROOT / "python"))
    import detpy

    meta = {"set": args.set, "runs": args.runs, "seeds": args.seeds, "confirm": args.confirm, "jobs": args.jobs,
            "detpy": detpy.__version__,
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "command": "python harness/detpy_harness.py " + " ".join(argv if argv is not None else sys.argv[1:]),
            "notes": ["Il dataset FlaPy di Gruber et al. è pubblicato su Zenodo, non raggiungibile da questo ambiente "
                      "(403 dal proxy di rete): il pool 'flaky' usa la sezione Python di IDoFT, con i progetti fissati "
                      "al commit in cui i test instabili furono rilevati."]}
    if args.report_only:
        prev = outdir / "summary.json"
        if prev.exists():
            meta = json.loads(prev.read_text())["meta"]
        print(write_report(outdir, meta))
        return 0
    work.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    if args.fresh:
        for f in list(outdir.glob("*.summary.json")) + list(outdir.glob("*.csv")) + list(outdir.glob("skipped.json")):
            f.unlink()
    wheel = args.wheel or build_wheel(work)
    log(f"wheel: {wheel}")

    # Resume: repositories already measured or discarded are not redone.
    results: list[dict] = [json.loads(f.read_text()) for f in sorted(outdir.glob("*.summary.json"))]
    skipped: list[dict] = json.loads((outdir / "skipped.json").read_text()) if (outdir / "skipped.json").exists() else []
    finished = {r["name"] for r in results} | {s_["name"] for s_ in skipped}
    lock = threading.Lock()
    queues = {k: [r for r in v if r["name"] not in finished] for k, v in pools.items()}
    done_ok = collections.Counter(r["kind"] for r in results if r.get("status") == "ok")
    running = collections.Counter()
    if finished:
        log(f"resuming: {len(results)} measured, {len(skipped)} discarded already")

    def checkpoint(name: str) -> None:
        if not args.checkpoint:
            return
        rel = os.path.relpath(outdir, ROOT)
        sh(["git", "add", "-A", rel], cwd=ROOT)
        msg = (f"Harness results: {name} ({sum(done_ok.values())} measured)\n\n"
               "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
               "Claude-Session: https://claude.ai/code/session_01YAF6Dii5H2Yb6A4iModrCE")
        if sh(["git", "commit", "-q", "-m", msg], cwd=ROOT)[0] == 0:
            for attempt in range(4):
                if sh(["git", "push", "-q"], cwd=ROOT, timeout=120)[0] == 0:
                    break
                time.sleep(2 ** (attempt + 1))

    def take():
        """Next candidate of a pool that still needs repositories (pools alternate)."""
        with lock:
            for kind in sorted(queues, key=lambda k: done_ok[k] + running[k]):
                q = queues[kind]
                if q and done_ok[kind] + running[kind] < quota[kind]:
                    running[kind] += 1
                    return kind, q.pop(0)
        return None, None

    def worker():
        while True:
            kind, repo = take()
            if repo is None:
                return
            try:
                p = prepare(repo, work, wheel, args.python, args.max_first_run)
                log(f"prepared {p.name} [{kind}]: {p.status} py{p.python_version} {p.collected} tests "
                    f"xdist={p.xdist} {p.detail[-100:]!r}")
                if p.status != "ok":
                    r = {"name": p.name, "kind": kind, "status": p.status, "detail": p.detail}
                else:
                    r = measure(p, args, outdir, work)
            except Exception as e:  # pragma: no cover
                import traceback
                r = {"name": repo["name"], "kind": kind, "status": "harness-error",
                     "detail": repr(e) + traceback.format_exc()[-300:]}
            with lock:
                running[kind] -= 1
                results.append(r)
                if r.get("status") == "ok":
                    done_ok[kind] += 1
                else:
                    skipped.append({"name": r["name"], "kind": kind, "status": r["status"],
                                    "detail": r.get("detail", "")})
                (outdir / "skipped.json").write_text(json.dumps(skipped, indent=2))
                meta["order"] = [x["name"] for x in results if x.get("status") == "ok"]
                write_report(outdir, meta)  # partial report after every repository
                checkpoint(r["name"])
            log(f"done {r['name']} [{kind}]: {r.get('status')} (ok so far: {dict(done_ok)})")

    threads = [threading.Thread(target=worker) for _ in range(args.jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    meta["order"] = [r["name"] for pool in pools.values() for r in pool
                     if any(x["name"] == r["name"] and x.get("status") == "ok" for x in results)]
    print(write_report(outdir, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
