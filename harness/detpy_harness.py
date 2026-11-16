#!/usr/bin/env python3
"""Measurement harness for detpy Level 0.

For every repository: clone it, install it with its test dependencies in an
isolated virtualenv (uv), then run its pytest suite N times normally and N
times with ``--det`` (interleaved: N0 D0 N1 D1 ...). Per repository it writes

* ``<out>/<repo>.csv``       one row per test (outcomes, stability, coverage)
* ``<out>/<repo>_runs.csv``  one row per run (duration, exit code, counts)

and finally ``<out>/summary.json`` and ``<out>/REPORT.md``.

Usage::

    python harness/detpy_harness.py --set validate --runs 10
    python harness/detpy_harness.py --set all --limit 50 --runs 10 --jobs 3
    python harness/detpy_harness.py --report-only          # rebuild the report
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import csv
import datetime
import glob
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEST_WORDS = ("test", "tests", "testing")
REQ_FILES = (
    "requirements/tests.txt", "requirements/test.txt", "requirements/testing.txt",
    "requirements-test.txt", "requirements-tests.txt", "requirements_test.txt", "test-requirements.txt",
    "test_requirements.txt", "tests/requirements.txt", "requirements/dev.txt", "requirements-dev.txt",
    "dev-requirements.txt", "requirements/tests.in", "requirements/test.in",
)
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd, cwd=None, env=None, timeout=None):
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return p.returncode, p.stdout + p.stderr, time.perf_counter() - t0, False
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "") if isinstance(e.stdout, str) else ""
        return -9, out, time.perf_counter() - t0, True


# ---------------------------------------------------------------------------
# Preparation
@dataclass
class Prepared:
    name: str
    url: str
    status: str = "pending"  # ok | clone-failed | install-failed | collect-failed | too-slow
    detail: str = ""
    commit: str = ""
    python: str = ""
    src: str = ""
    pytest_args: list = field(default_factory=list)
    install_cmd: str = ""
    collected: int = 0
    env: dict = field(default_factory=dict)
    max_run_seconds: float = 0


def detect_install(src: Path) -> tuple[list, list, list]:
    """Return (project args, dependency-group args, requirement-file args)."""
    args = []
    groups = []
    reqs = []
    pyproject = src / "pyproject.toml"
    data = {}
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
        except Exception:
            data = {}
    extras = [k for k in (data.get("project", {}).get("optional-dependencies") or {})
              if any(w in k.lower() for w in TEST_WORDS)]
    target = f".[{','.join(extras)}]" if extras else "."
    args += ["-e", target]
    all_groups = list(data.get("dependency-groups", {}) or {})
    test_groups = [g for g in all_groups if any(w in g.lower() for w in TEST_WORDS)]
    for g in test_groups or [g for g in all_groups if g.lower() == "dev"]:
        groups += ["--group", g]
    for f in REQ_FILES:
        if (src / f).exists():
            reqs += ["-r", f]
    return args, groups, reqs


def clean_env(venv_python: str, extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHASHSEED", "DETPY_REEXEC", "VIRTUAL_ENV", "PYTHONPATH", "PYTEST_ADDOPTS",
                        "PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")}
    env["PATH"] = str(Path(venv_python).parent) + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(Path(venv_python).parent.parent)
    env["COLUMNS"] = "160"
    env.update(extra or {})
    return env


def prepare(repo: dict, work: Path, wheel: str, python: str, max_first_run: float) -> Prepared:
    name = repo["name"]
    p = Prepared(name=name, url=repo["url"], env=repo.get("env", {}),
                 max_run_seconds=repo.get("max_run_seconds", max_first_run))
    src = work / "src" / name
    venv = work / "venvs" / name
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    p.src = str(src)
    if not src.exists():
        code, out, _, _ = sh(["git", "clone", "--depth", "1", "--quiet", repo["url"], str(src)], timeout=600)
        if code != 0:
            p.status, p.detail = "clone-failed", out[-500:]
            return p
    p.commit = sh(["git", "rev-parse", "HEAD"], cwd=src)[1].strip()[:12]
    py = venv / "bin" / "python"
    p.python = str(py)
    marker = venv / ".detpy-installed"
    if not marker.exists():
        shutil.rmtree(venv, ignore_errors=True)
        code, out, _, _ = sh(["uv", "venv", "--quiet", "--python", python, str(venv)], timeout=300)
        if code != 0:
            p.status, p.detail = "install-failed", "venv: " + out[-500:]
            return p
        base = ["uv", "pip", "install", "--quiet", "--python", str(py)]
        args, groups, reqs = detect_install(src)
        extra = repo.get("install", [])
        attempts = [args + groups + reqs + extra, args + groups + extra, args + reqs + extra, args + extra,
                    ["-e", "."] + extra]
        ok = False
        for attempt in attempts:
            code, out, _, _ = sh(base + attempt + [wheel, "pytest"], cwd=src, timeout=1200)
            (logs / f"{name}.install.log").write_text(" ".join(attempt) + "\n" + out)
            if code == 0:
                p.install_cmd = " ".join(attempt)
                ok = True
                break
        if not ok:
            p.status, p.detail = "install-failed", out[-800:]
            return p
        marker.write_text(json.dumps({"install": p.install_cmd}))
    else:
        p.install_cmd = json.loads(marker.read_text()).get("install", "")
        # Always test the current detpy build.
        code, out, _, _ = sh(["uv", "pip", "install", "--quiet", "--python", str(py), "--reinstall-package",
                              "detpy", "--no-deps", wheel], timeout=300)
        if code != 0:
            p.status, p.detail = "install-failed", "detpy wheel: " + out[-500:]
            return p
    # Collection check; some repos need their addopts cleared (e.g. xdist/cov flags).
    p.pytest_args = list(repo.get("pytest_args", []))
    env = clean_env(str(py), p.env)
    for extra in ([], ["-o", "addopts="]):
        args = p.pytest_args + extra
        code, out, _, to = sh([str(py), "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *args],
                              cwd=src, env=env, timeout=600)
        m = re.search(r"(\d+) tests? collected|^(\d+) tests?", out, re.M)
        n = sum(1 for line in out.splitlines() if "::" in line)
        if code == 0 and n > 0:
            p.pytest_args, p.collected = args, n
            break
    else:
        p.status, p.detail = "collect-failed", out[-800:]
        (logs / f"{name}.collect.log").write_text(out)
        return p
    p.status = "ok"
    return p


# ---------------------------------------------------------------------------
# Runs
@dataclass
class RunResult:
    mode: str
    index: int
    duration: float
    exit_code: int
    timed_out: bool
    outcomes: dict
    trace: str | None


def run_once(p: Prepared, mode: str, i: int, rundir: Path, timeout: float) -> RunResult:
    out_json = rundir / f"{mode}_{i}.json"
    trace = rundir / f"{mode}_{i}.jsonl" if mode == "det" else None
    cmd = [p.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--det-outcomes={out_json}", *p.pytest_args]
    if mode == "det":
        cmd += ["--det", f"--det-trace={trace}"]
    code, out, dur, to = sh(cmd, cwd=p.src, env=clean_env(p.python, p.env), timeout=timeout)
    (rundir / f"{mode}_{i}.log").write_text(out[-20000:])
    outcomes = {}
    if out_json.exists():
        try:
            outcomes = json.loads(out_json.read_text())["outcomes"]
        except Exception:
            pass
    return RunResult(mode, i, dur, code, to, outcomes, str(trace) if trace and trace.exists() else None)


def measure(p: Prepared, runs: int, outdir: Path, work: Path, run_timeout: float) -> dict:
    rundir = work / "runs" / p.name
    shutil.rmtree(rundir, ignore_errors=True)
    rundir.mkdir(parents=True)
    results: list[RunResult] = []
    for i in range(runs):
        for mode in ("normal", "det"):
            r = run_once(p, mode, i, rundir, run_timeout)
            results.append(r)
            log(f"{p.name}: {mode} #{i} {r.duration:.1f}s exit={r.exit_code}{' TIMEOUT' if r.timed_out else ''}"
                f" tests={len(r.outcomes)}")
            if i == 0 and mode == "normal" and r.duration > p.max_run_seconds:
                p.status, p.detail = "too-slow", f"first normal run took {r.duration:.0f}s"
                return {"name": p.name, "status": p.status, "detail": p.detail}
    return analyze(p, results, outdir)


# ---------------------------------------------------------------------------
# Analysis
def _hist(values) -> str:
    c = collections.Counter(v if v is not None else "missing" for v in values)
    return ";".join(f"{k}={v}" for k, v in sorted(c.items()))


def _stable(values, completed) -> bool:
    """Same outcome in every completed run (absence counts as an outcome)."""
    vals = [v for v, ok in zip(values, completed) if ok]
    return len(set(vals)) <= 1


def _majority(values):
    vals = [v for v in values if v is not None]
    return collections.Counter(vals).most_common(1)[0][0] if vals else None


def analyze(p: Prepared, results: list[RunResult], outdir: Path) -> dict:
    sys.path.insert(0, str(ROOT / "python"))
    from detpy import _core  # the harness interpreter has detpy installed

    normal = [r for r in results if r.mode == "normal"]
    det = [r for r in results if r.mode == "det"]
    n_ok = [not r.timed_out and bool(r.outcomes) for r in normal]
    d_ok = [not r.timed_out and bool(r.outcomes) for r in det]
    ids = sorted(set().union(*(r.outcomes.keys() for r in results)))

    traces = [r.trace for r in det if r.trace]
    verdicts = {}
    if len(traces) >= 2:
        report = json.loads(_core.verify(traces))
        verdicts = {t["nodeid"]: t for t in report["tests"]}

    rows = []
    agg = collections.Counter()
    reasons = collections.Counter()
    examples = collections.defaultdict(list)
    for nid in ids:
        nv = [r.outcomes.get(nid) for r in normal]
        dv = [r.outcomes.get(nid) for r in det]
        ns, ds = _stable(nv, n_ok), _stable(dv, d_ok)
        nm, dm = _majority(nv), _majority(dv)
        v = verdicts.get(nid)
        covered = v is not None and v["status"] == "stable"
        div = (v or {}).get("divergence") or {}
        reason = div.get("reason", "") if v and not covered else ("no-trace" if v is None else "")
        row = {
            "nodeid": nid,
            "normal_outcomes": _hist(nv),
            "normal_stable": ns,
            "det_outcomes": _hist(dv),
            "det_stable": ds,
            "became_stable": (not ns) and ds,
            "became_unstable": ns and not ds,
            "outcome_changed_by_det": ns and ds and nm != dm,
            "normal_majority": nm,
            "det_majority": dm,
            "fingerprint_covered": covered,
            "distinct_fingerprints": (v or {}).get("distinct_fingerprints", 0),
            "reason": reason,
            "divergence": div.get("description", "")[:300],
        }
        rows.append(row)
        agg["tests"] += 1
        agg["unstable_normal"] += not ns
        agg["unstable_det"] += not ds
        agg["became_stable"] += row["became_stable"]
        agg["became_unstable"] += row["became_unstable"]
        agg["outcome_changed_by_det"] += row["outcome_changed_by_det"]
        agg["covered"] += covered
        if v is not None and not covered:
            agg["not_covered"] += 1
            reasons[reason] += 1
            if len(examples[reason]) < 2:
                examples[reason].append(f"{nid}: {div.get('description', '')[:200]}")
        if row["outcome_changed_by_det"] and len(examples["changed:" + f"{nm}->{dm}"]) < 3:
            examples["changed:" + f"{nm}->{dm}"].append(nid)

    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / f"{p.name}.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["nodeid"])
        w.writeheader()
        w.writerows(rows)
    with open(outdir / f"{p.name}_runs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "run", "duration_s", "exit_code", "timed_out", "tests", "passed", "failed", "error",
                    "skipped", "other"])
        for r in results:
            c = collections.Counter(r.outcomes.values())
            other = sum(v for k, v in c.items() if k not in ("passed", "failed", "error", "skipped"))
            w.writerow([r.mode, r.index, f"{r.duration:.3f}", r.exit_code, r.timed_out, len(r.outcomes),
                        c["passed"], c["failed"], c["error"], c["skipped"], other])

    nd = [r.duration for r in normal if not r.timed_out]
    dd = [r.duration for r in det if not r.timed_out]
    mean_n = statistics.mean(nd) if nd else float("nan")
    mean_d = statistics.mean(dd) if dd else float("nan")
    summary = {
        "name": p.name, "status": "ok", "url": p.url, "commit": p.commit, "install": p.install_cmd,
        "pytest_args": p.pytest_args, "runs": len(normal),
        "normal_mean_s": mean_n, "normal_stdev_s": statistics.stdev(nd) if len(nd) > 1 else 0.0,
        "det_mean_s": mean_d, "det_stdev_s": statistics.stdev(dd) if len(dd) > 1 else 0.0,
        "slowdown_pct": (mean_d / mean_n - 1) * 100 if nd and dd and mean_n > 0 else float("nan"),
        "timeouts": sum(r.timed_out for r in results),
        "normal_exit_codes": sorted({r.exit_code for r in normal}),
        "det_exit_codes": sorted({r.exit_code for r in det}),
        **{k: agg[k] for k in ("tests", "unstable_normal", "unstable_det", "became_stable", "became_unstable",
                               "outcome_changed_by_det", "covered", "not_covered")},
        "reasons": dict(reasons),
        "examples": dict(examples),
        "det_header": _header(traces[0]) if traces else {},
    }
    (outdir / f"{p.name}.summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def _header(path: str) -> dict:
    with open(path) as f:
        return json.loads(f.readline()).get("meta", {})


# ---------------------------------------------------------------------------
# Report
def _fmt(x, nd=1):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def write_report(outdir: Path, meta: dict) -> Path:
    summaries = []
    for f in sorted(outdir.glob("*.summary.json")):
        summaries.append(json.loads(f.read_text()))
    skipped = json.loads((outdir / "skipped.json").read_text()) if (outdir / "skipped.json").exists() else []
    ok = [s for s in summaries if s.get("status") == "ok"]
    order = meta.get("order") or []
    ok.sort(key=lambda s: order.index(s["name"]) if s["name"] in order else 1e9)
    tot = collections.Counter()
    reasons = collections.Counter()
    for s in ok:
        for k in ("tests", "unstable_normal", "unstable_det", "became_stable", "became_unstable",
                  "outcome_changed_by_det", "covered", "not_covered"):
            tot[k] += s[k]
        reasons.update(s["reasons"])
    slow = [s["slowdown_pct"] for s in ok if s["slowdown_pct"] == s["slowdown_pct"]]
    ratio = [1 + x / 100 for x in slow]
    geo = (statistics.geometric_mean(ratio) - 1) * 100 if ratio else float("nan")

    L = []
    L.append(f"# detpy Level 0: measurement report ({meta.get('set', '')})\n")
    L.append(f"Generated {meta.get('date', '')} with detpy {meta.get('detpy', '')}, Python {platform.python_version()}, "
             f"{meta.get('runs')} normal + {meta.get('runs')} `--det` runs per repository (interleaved), "
             f"{meta.get('jobs')} repositories in parallel on {os.cpu_count()} CPUs.\n")
    L.append("## Totals\n")
    L.append(f"* repositories measured: **{len(ok)}** (excluded: {len(skipped)})")
    L.append(f"* tests: **{tot['tests']}**")
    L.append(f"* slowdown of `--det`: median **{_fmt(statistics.median(slow) if slow else None)}%**, "
             f"geometric mean {_fmt(geo)}%, min {_fmt(min(slow) if slow else None)}%, "
             f"max {_fmt(max(slow) if slow else None)}%")
    L.append(f"* unstable tests (outcome differs between runs) without `--det`: **{tot['unstable_normal']}**; "
             f"with `--det`: **{tot['unstable_det']}**")
    L.append(f"* became stable with `--det`: **{tot['became_stable']}**; became unstable: {tot['became_unstable']}")
    L.append(f"* stable in both modes but with a different outcome under `--det` (behaviour changed by Level 0): "
             f"**{tot['outcome_changed_by_det']}**")
    cov_pct = 100 * tot["covered"] / max(1, tot["covered"] + tot["not_covered"])
    L.append(f"* fingerprint identical in every `--det` run (covered by Level 0): **{tot['covered']}** "
             f"({cov_pct:.2f}%); not covered: **{tot['not_covered']}**")
    if reasons:
        L.append("* not covered, by reason: " + ", ".join(f"`{k}` {v}" for k, v in reasons.most_common()))
    L.append("")
    L.append("## Per repository\n")
    L.append("| repo | tests | normal s | det s | slowdown % | unstable normal | unstable det | became stable "
             "| changed by det | not covered | reasons |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for s in ok:
        rs = ", ".join(f"{k}:{v}" for k, v in sorted(s["reasons"].items(), key=lambda kv: -kv[1]))
        L.append(f"| [{s['name']}]({s['url']}) | {s['tests']} | {_fmt(s['normal_mean_s'], 2)} | "
                 f"{_fmt(s['det_mean_s'], 2)} | {_fmt(s['slowdown_pct'])} | {s['unstable_normal']} | "
                 f"{s['unstable_det']} | {s['became_stable']} | {s['outcome_changed_by_det']} | "
                 f"{s['not_covered']} | {rs} |")
    L.append("")
    L.append("## Examples of divergences and behaviour changes\n")
    for s in ok:
        ex = s.get("examples") or {}
        if not ex:
            continue
        L.append(f"**{s['name']}**\n")
        for k, items in sorted(ex.items()):
            for it in items:
                L.append(f"* `{k}` — {it}")
        L.append("")
    if skipped:
        L.append("## Excluded repositories\n")
        L.append("| repo | status | detail |")
        L.append("|---|---|---|")
        for sk in skipped:
            d = re.sub(r"\s+", " ", sk.get("detail", ""))[-200:].replace("|", "/")
            L.append(f"| {sk['name']} | {sk['status']} | {d} |")
        L.append("")
    L.append("## Reproduction\n")
    L.append("```bash")
    L.append(meta.get("command", "python harness/detpy_harness.py"))
    L.append("```")
    L.append("Per-test details are in `<repo>.csv`, per-run timings in `<repo>_runs.csv`. "
             "Column meanings are documented in `docs/HARNESS.md`.")
    path = outdir / "REPORT.md"
    path.write_text("\n".join(L) + "\n")
    (outdir / "summary.json").write_text(json.dumps({"meta": meta, "totals": dict(tot), "reasons": dict(reasons),
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repos", default=str(HERE / "repos.json"))
    ap.add_argument("--set", default="validate", help="'validate', 'all' or a comma separated list of names")
    ap.add_argument("--limit", type=int, default=0, help="measure the first N repositories that prepare successfully")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=2, help="repositories measured in parallel")
    ap.add_argument("--work", default=str(ROOT / ".harness-work"))
    ap.add_argument("--out", default=None, help="results directory (default harness/results/<set>)")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--wheel", default=None)
    ap.add_argument("--run-timeout", type=float, default=900)
    ap.add_argument("--max-first-run", type=float, default=240,
                    help="skip repositories whose first normal run is slower than this (seconds)")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)

    cfg = json.loads(Path(args.repos).read_text())
    by_name = {r["name"]: r for r in cfg["repos"]}
    if args.set == "validate":
        names = cfg["validate"]
    elif args.set == "all":
        names = [r["name"] for r in cfg["repos"]]
    else:
        names = [n.strip() for n in args.set.split(",") if n.strip()]
    outdir = Path(args.out or HERE / "results" / ("validate" if args.set == "validate" else
                                                  f"top{args.limit}" if args.limit else "custom"))
    work = Path(args.work)
    sys.path.insert(0, str(ROOT / "python"))
    import detpy

    meta = {"set": args.set, "runs": args.runs, "jobs": args.jobs, "detpy": detpy.__version__,
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "command": "python harness/detpy_harness.py " + " ".join(argv if argv is not None else sys.argv[1:]),
            "order": names}
    if args.report_only:
        prev = outdir / "summary.json"
        if prev.exists():
            meta = {**json.loads(prev.read_text())["meta"], **{k: meta[k] for k in ("date",)}}
        print(write_report(outdir, meta))
        return 0

    work.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    wheel = args.wheel or build_wheel(work)
    log(f"wheel: {wheel}")

    # 1. prepare everything (clone, venv, install, collect) in parallel
    prepared: dict[str, Prepared] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, args.jobs * 2)) as ex:
        futs = {ex.submit(prepare, by_name[n], work, wheel, args.python, args.max_first_run): n for n in names}
        for f in concurrent.futures.as_completed(futs):
            n = futs[f]
            try:
                prepared[n] = f.result()
            except Exception as e:  # pragma: no cover
                prepared[n] = Prepared(name=n, url=by_name[n]["url"], status="prepare-error", detail=repr(e))
            pr = prepared[n]
            log(f"prepared {n}: {pr.status} {pr.collected} tests {pr.detail[-120:]!r}")
    candidates = [prepared[n] for n in names if prepared[n].status == "ok"]
    skipped = [{"name": p.name, "status": p.status, "detail": p.detail} for n in names
               for p in [prepared[n]] if p.status != "ok"]

    # 2. measure, taking the first `limit` that succeed (too-slow ones are replaced)
    selected: list[Prepared] = []
    queue = list(candidates)
    lock = threading.Lock()
    results = []

    def worker():
        while True:
            with lock:
                done = len([r for r in results if r.get("status") == "ok"])
                running = len(selected) - len(results)
                if not queue or (args.limit and done + running >= args.limit):
                    return
                p = queue.pop(0)
                selected.append(p)
            try:
                r = measure(p, args.runs, outdir, work, args.run_timeout)
            except Exception as e:  # pragma: no cover
                r = {"name": p.name, "status": "measure-error", "detail": repr(e)}
            with lock:
                results.append(r)
                if r.get("status") != "ok":
                    skipped.append({"name": p.name, "status": r["status"], "detail": r.get("detail", "")})
            log(f"done {p.name}: {r.get('status')}")

    threads = [threading.Thread(target=worker) for _ in range(args.jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    measured = {r["name"] for r in results if r.get("status") == "ok"}
    for f in outdir.glob("*.summary.json"):
        if f.name.removesuffix(".summary.json") not in measured:
            f.unlink()
    (outdir / "skipped.json").write_text(json.dumps(skipped, indent=2))
    meta["order"] = [n for n in names if n in measured]
    print(write_report(outdir, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
