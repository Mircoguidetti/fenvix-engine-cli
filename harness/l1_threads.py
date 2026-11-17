#!/usr/bin/env python3
"""L1 threads study harness (track l1-threads, P-012): ``--det-threads`` on real projects.

Two kinds of job, one GitHub Actions job per project of ``harness/l1/threads-corpus.json``:

``corpus`` (the 10 easypy thread tests of Block 2 and the class-a tests of the mixed round):
  per unit (one test with its minimised order, or all the corpus tests of the project in
  one invocation), serial, fixed order, interleaved so runner load hits every mode alike:
  * ``runs`` runs of each mode: baseline (plain pytest), ``det`` (Level 0), ``det-u``
    (Level 0 + ``--det-urandom``), ``l1`` (``--det --det-threads``, calm seed 0) and ``l1-u``
    (``l1`` + ``--det-urandom``); outcome and execution fingerprint per test;
  * ``loaded_runs`` runs of baseline / det-u / l1-u under CPU contention (one spinning
    process per core: a busy CI runner);
  * exploration: ``--det-threads-seed=1..seeds`` (l1-u flags, preemption on);
  * confirmation: the first failing seed of each test re-run until ``confirm`` runs; a test
    is *replayed* when every run fails with one fingerprint, *reproduced* when it is also
    seen passing (another seed, or the test run alone for the order-dependent easypy tests).

``suite`` (Block 1 popular pool + easypy): the full suite, serial, ``timing_runs`` rounds of
  plain / det / l1 / l1-s1 (``--det-threads-seed=1``); wall time, outcome counts, tests broken
  by ``--det-threads`` (pass in every det run, fail in every l1 run), scheduler counters.

Output ``<out>/<name>.<kind>.json``; ``--aggregate DIR`` writes REPORT.md + CSVs.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import detpy_harness as H  # noqa: E402
import l1_async as A  # noqa: E402  (clone, log, is_fail, hist)

CORPUS = ROOT / "harness" / "l1" / "threads-corpus.json"
STATS = re.compile(r"threads: decisions=(\d+) switches=(\d+) escapes=(\d+) deadlocks=(\d+) "
                   r"timer_jumps=(\d+) managed=(\d+)")
L1 = ["--det", "--det-threads", "--det-threads-seed=0"]
MODES = {
    "baseline": [],
    "det": ["--det"],
    "det-u": ["--det", "--det-urandom"],
    "l1": L1,
    "l1-u": L1 + ["--det-urandom"],
}
SUITE_MODES = {"plain": [], "det": ["--det"], "l1": L1, "l1-s1": ["--det", "--det-threads", "--det-threads-seed=1"]}


def suite_modes(seeds) -> dict:
    """plain, det, l1 (calm) and one exploration mode per seed (l1-s<N>)."""
    modes = {"plain": [], "det": ["--det"], "l1": L1}
    for sd in seeds:
        modes[f"l1-s{sd}"] = ["--det", "--det-threads", f"--det-threads-seed={sd}"]
    return modes
log, is_fail, hist = A.log, A.is_fail, A.hist
ARTIFACT_MARKERS = ("DeadlockError", "Timeout (>", "deadlock", "detpy", "BlockingError")


def pytest_run(p, args: list, out_json: Path, timeout: float, trace: Path | None = None) -> dict:
    cmd = [p.python, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", "-p", "no:randomly", "-p", "no:xdist",
           f"--det-outcomes={out_json}", *p.pytest_args, *args]
    if trace is not None:
        cmd.append(f"--det-trace={trace}")
    out_json.unlink(missing_ok=True)
    t0 = time.monotonic()
    env = H.clean_env(p.python, p.env)
    env["PYTHONFAULTHANDLER"] = "1"  # SIGABRT on timeout dumps every thread's stack
    proc = subprocess.Popen(cmd, cwd=p.src, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace")
    try:
        so, se = proc.communicate(timeout=timeout)
        code, out, timed_out = proc.returncode, so + se, False
    except subprocess.TimeoutExpired:
        import signal

        proc.send_signal(signal.SIGABRT)
        try:
            so, se = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            so, se = proc.communicate()
        code, out, timed_out = -9, (so or "") + (se or ""), True
    dur = time.monotonic() - t0
    outcomes, fps = {}, {}
    if out_json.exists():
        try:
            data = json.loads(out_json.read_text())
            outcomes, fps = data.get("outcomes", {}), data.get("fingerprints", {})
        except Exception:
            pass
    msgs = {}
    for line in out.splitlines():
        if line.startswith(("FAILED ", "ERROR ")):
            body = line.split(" ", 1)[1]
            nodeid, _, msg = body.partition(" - ")
            msgs.setdefault(nodeid.strip(), (line.split(" ", 1)[0] + " " + msg.strip())[:240])
    m = STATS.search(out)
    stats = dict(zip(("decisions", "switches", "escapes", "deadlocks", "timer_jumps", "managed"),
                     map(int, m.groups()))) if m else None
    return {"exit": code, "duration_s": round(dur, 3), "timed_out": timed_out, "outcomes": outcomes, "fps": fps,
            "stats": stats, "msgs": msgs, "tail": out[-1500:] if (code not in (0, 1) or timed_out) else "",
            # A hung run: the faulthandler dump of the stuck test (every thread's stack).
            "hang": _hang_dump(out) if timed_out else ""}


def _hang_dump(out: str) -> str:
    i = out.find("Timeout (0:")
    if i < 0:
        i = out.find("Fatal Python error: Aborted")
    return (out[max(0, i - 2000):i + 40000] if i >= 0 else out[-20000:])


def _prepare(project: dict, args):
    work = Path(args.work)
    src = work / "src" / project["name"]
    src.parent.mkdir(parents=True, exist_ok=True)
    res = {"name": project["name"], "set": project.get("set", ""), "url": project.get("url", ""),
           "runner": platform.node(), "cpu": H.runner_info(), "python_requested": project.get("python")}
    try:
        res["commit"] = A.clone(project, src)
    except Exception as e:
        res["status"] = f"clone-failed: {e}"
        return res, None
    repo = {"name": project["name"], "url": project.get("url", ""), "kind": "flaky", "sha": "",
            "python": project.get("python"), "install": project.get("install", []),
            "pytest_args": project.get("pytest_args", []), "env": project.get("env", {})}
    p = H.prepare(repo, work, args.wheel, "3.13", 100000)
    res.update(status=p.status, detail=p.detail, python=p.python_version, install=p.install_cmd,
               collected=p.collected)
    if p.status != "ok":
        log(f"{p.name}: {p.status} {p.detail[-300:]}")
        return res, None
    return res, p


# ---------------------------------------------------------------------------
def measure_corpus(project: dict, args) -> dict:
    res, p = _prepare(project, args)
    res["kind"] = "corpus"
    res["tests"] = project["tests"]
    res["baseline_exception"] = project.get("baseline_exception", {})
    if p is None:
        return res
    rd = Path(args.work) / "runs" / p.name
    rd.mkdir(parents=True, exist_ok=True)
    units = []
    if project.get("orders"):
        for k, (target, order) in enumerate(project["orders"].items()):
            f = rd / f"order-{k}.txt"
            f.write_text("\n".join(order) + "\n")
            units.append({"id": k, "targets": [target], "nodeids": order, "order_file": str(f)})
    else:
        units.append({"id": 0, "targets": list(project["tests"]), "nodeids": list(project["tests"]),
                      "order_file": None})
    runs = res["runs"] = []
    tmo = args.run_timeout

    def go(unit, mode, flags, i, seed=None, trace=None):
        if flags and unit["order_file"]:
            sel = [f"--det-order={unit['order_file']}"]
        else:
            sel = unit["nodeids"]
        r = pytest_run(p, sel + flags, rd / f"u{unit['id']}-{mode}-{seed}-{i}.json", tmo, trace)
        row = {"unit": unit["id"], "mode": mode, "seed": seed, "run": i, "exit": r["exit"],
               "duration_s": r["duration_s"], "timed_out": r["timed_out"], "stats": r["stats"], "tail": r["tail"][-600:],
               "outcomes": {t: r["outcomes"].get(t, "missing") for t in unit["targets"]},
               "fps": {t: r["fps"].get(t) for t in unit["targets"]},
               "msgs": {t: r["msgs"][t] for t in unit["targets"] if t in r["msgs"]}}
        runs.append(row)
        fails = sum(is_fail(o) for o in row["outcomes"].values())
        log(f"{p.name} u{unit['id']} {mode} seed={seed} run={i}: {r['duration_s']}s exit={r['exit']} "
            f"failing={fails}/{len(unit['targets'])} stats={r['stats']}")
        return row

    for i in range(args.runs):
        for u in units:
            for mode, flags in MODES.items():
                go(u, mode, flags, i)
    if args.loaded_runs:
        hogs = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(os.cpu_count() or 2)]
        try:
            for i in range(args.loaded_runs):
                for u in units:
                    for mode in ("baseline", "det-u", "l1-u"):
                        go(u, "loaded-" + mode, MODES[mode], i)
        finally:
            for h in hogs:
                h.kill()
    # The order-dependent targets alone (does the test pass without its polluter?).
    if project.get("orders"):
        for u in units:
            alone = dict(u, nodeids=u["targets"], order_file=None)
            go(alone, "alone-l1-u", MODES["l1-u"], 0)
    confirm = res["confirm"] = {}
    for u in units:
        first_fail, first_pass = {}, {}
        for s in range(1, args.seeds + 1):
            flags = ["--det", "--det-threads", f"--det-threads-seed={s}", "--det-urandom"]
            r = go(u, "explore", flags, 0, s)
            for t in u["targets"]:
                o = r["outcomes"].get(t)
                if is_fail(o):
                    first_fail.setdefault(t, s)
                elif o in ("passed", "xfailed"):
                    first_pass.setdefault(t, s)
        by_seed = collections.defaultdict(list)
        for t, s in first_fail.items():
            by_seed[s].append(t)
        for s, tests in sorted(by_seed.items()):
            flags = ["--det", "--det-threads", f"--det-threads-seed={s}", "--det-urandom"]
            rows = [next(r for r in runs if r["unit"] == u["id"] and r["mode"] == "explore" and r["seed"] == s)]
            traces = []
            for i in range(1, args.confirm):
                t = rd / f"u{u['id']}-confirm-{s}-{i}.jsonl"
                rows.append(go(u, "confirm", flags, i, s, trace=t))
                traces.append(t)
            verdict = {}
            try:
                out = subprocess.run([p.python, "-c", "import sys,detpy._core as c; print(c.verify(sys.argv[1:]))",
                                      *map(str, traces)], capture_output=True, text=True, timeout=300).stdout
                verdict = {x["nodeid"]: x for x in json.loads(out)["tests"]}
            except Exception as e:
                log(f"verify failed: {e}")
            for t in tests:
                fails = sum(is_fail(r["outcomes"].get(t)) for r in rows)
                fps = {r["fps"].get(t) for r in rows}
                d = (verdict.get(t) or {}).get("divergence") or {}
                failmsgs = [r["msgs"].get(t, "") for r in rows if is_fail(r["outcomes"].get(t))]
                confirm[t] = {"seed": s, "fails": fails, "runs": len(rows), "distinct_fps": len(fps),
                              "messages": sorted(set(failmsgs))[:5],
                              "replayed": fails == len(rows) and len(fps) == 1 and None not in fps,
                              "passing_seed": first_pass.get(t), "divergence": d.get("description", "")[:300]}
    return res


# ---------------------------------------------------------------------------
def _snapshot_mtimes(src: Path) -> dict:
    """File times of the checkout. A test that stamps a repository file with the
    (virtual, identical every run) time leaks into the next run: jinja's
    test_caches_template_based_on_mtime fails in any --det run that follows another
    --det run. Each suite run starts from the checkout's own times instead."""
    snap = {}
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in (".git", ".venv", "node_modules", "__pycache__", ".detpy")]
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            snap[p] = (st.st_atime_ns, st.st_mtime_ns)
    return snap


def _restore_mtimes(snap: dict) -> int:
    n = 0
    for p, (a, m) in snap.items():
        try:
            if os.stat(p).st_mtime_ns != m:
                os.utime(p, ns=(a, m))
                n += 1
        except OSError:
            pass
    return n


def measure_suite(project: dict, args) -> dict:
    res, p = _prepare(project, args)
    res["kind"] = "suite"
    if p is None:
        return res
    rd = Path(args.work) / "runs" / p.name
    rd.mkdir(parents=True, exist_ok=True)
    suite = project.get("suite_args", [])
    per_mode = collections.defaultdict(list)  # mode -> [outcomes dict per run]
    timing = res["timing"] = []
    seeds = [int(x) for x in str(args.suite_seeds).split(",") if x.strip()]
    res["suite_seeds"] = seeds
    snap = _snapshot_mtimes(Path(p.src))
    restored = res["mtimes_restored"] = []
    # A first --det run pays one-off costs (detpy's modules compiled, caches filled):
    # measured on Actions, several seconds on small suites. One discarded run first.
    warm = res["warmup"] = []
    for _ in range(args.warmup):
        _restore_mtimes(snap)
        w = pytest_run(p, suite + ["--det", "--det-threads"], rd / "suite-warmup.json", args.suite_timeout)
        warm.append({"duration_s": w["duration_s"], "exit": w["exit"], "timed_out": w["timed_out"]})
    for i in range(args.timing_runs):
        for mode, flags in suite_modes(seeds).items():
            restored.append(_restore_mtimes(snap))
            # faulthandler_timeout: a test stuck for that long dumps every thread's stack.
            r = pytest_run(p, suite + flags + [f"-o", f"faulthandler_timeout={args.hang_dump}"],
                           rd / f"suite-{mode}-{i}.json", args.suite_timeout)
            c = collections.Counter(o.split("+", 1)[0] for o in r["outcomes"].values())
            timing.append({"mode": mode, "run": i, "duration_s": r["duration_s"], "exit": r["exit"],
                           "timed_out": r["timed_out"], "counts": dict(c), "stats": r["stats"],
                           "tail": r["tail"][-600:], "hang": r["hang"],
                           "msgs": {t: m for t, m in r["msgs"].items()} if mode.startswith("l1") else {}})
            if not r["timed_out"] and r["outcomes"]:
                per_mode[mode].append(r["outcomes"])
            log(f"{p.name} suite {mode} run={i}: {r['duration_s']}s {dict(c)} stats={r['stats']}")

    def ok(o):
        return o is not None and not is_fail(o) and o != "missing"

    def fail(o):
        return o is not None and is_fail(o)

    def compare(a: str, b: str) -> dict:
        ra, rb = per_mode.get(a, []), per_mode.get(b, [])
        if not ra or not rb:
            return {"runs": [len(ra), len(rb)], "broken": [], "sometimes": []}
        tests = set().union(*ra, *rb)
        broken = sorted(t for t in tests if all(ok(r.get(t)) for r in ra) and all(fail(r.get(t)) for r in rb))
        sometimes = sorted(t for t in tests if all(ok(r.get(t)) for r in ra) and any(fail(r.get(t)) for r in rb)
                           and t not in broken)
        return {"runs": [len(ra), len(rb)], "broken": broken[:200], "n_broken": len(broken),
                "sometimes": sometimes[:200], "n_sometimes": len(sometimes)}

    res["broken_by_det"] = compare("plain", "det")
    res["broken_by_l1"] = compare("det", "l1")
    for sd in seeds:
        res[f"broken_by_l1_s{sd}"] = compare("det", f"l1-s{sd}")
    unstable = {}
    for mode, rs in per_mode.items():
        tests = set().union(*rs) if rs else set()
        unstable[mode] = sorted(t for t in tests if len({r.get(t) for r in rs}) > 1)[:200]
    res["unstable"] = unstable
    return res


# ---------------------------------------------------------------------------
def _median(xs):
    return round(statistics.median(xs), 3) if xs else None


def aggregate(indir: Path, outdir: Path, meta: dict) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    corpus, suites = [], []
    for f in sorted(indir.rglob("*.json")):
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        if r.get("kind") == "corpus":
            corpus.append(r)
        elif r.get("kind") == "suite":
            suites.append(r)
    rows = []
    for r in corpus:
        if r.get("status") != "ok":
            continue
        for t, cat in r["tests"].items():
            per = collections.defaultdict(list)
            fps = collections.defaultdict(set)
            for run in r["runs"]:
                if t in run["outcomes"]:
                    per[run["mode"]].append(run["outcomes"][t])
                    if run["fps"].get(t):
                        fps[run["mode"]].add(run["fps"][t])
            cf = r.get("confirm", {}).get(t, {})
            row = {"project": r["name"], "set": r["set"], "nodeid": t, "category": cat}
            for m in ("baseline", "det", "det-u", "l1", "l1-u", "loaded-baseline", "loaded-det-u", "loaded-l1-u",
                      "alone-l1-u", "explore"):
                row[m] = hist(per.get(m, []))
                if m in ("det", "det-u", "l1", "l1-u", "loaded-det-u", "loaded-l1-u"):
                    row[m + " fps"] = len(fps.get(m, ()))
            row["baseline_flaky"] = len(set(per["baseline"] + per["loaded-baseline"])) > 1
            row["seeds_failing"] = sum(map(is_fail, per["explore"]))
            row["seeds_passing"] = sum(o == "passed" for o in per["explore"])
            row["repro_seed"] = cf.get("seed")
            row["confirm"] = f"{cf.get('fails', 0)}/{cf.get('runs', 0)}" if cf else ""
            row["confirm_fps"] = cf.get("distinct_fps")
            row["replayed"] = bool(cf.get("replayed"))
            passes_somewhere = cf.get("passing_seed") is not None or "passed" in row["alone-l1-u"]
            row["passes_somewhere"] = passes_somewhere
            row["reproduced"] = row["replayed"] and passes_somewhere
            msgs = cf.get("messages", [])
            row["confirm_messages"] = " | ".join(msgs)[:400]
            artifact = any(k in m for m in msgs for k in ARTIFACT_MARKERS)
            expected = (r.get("baseline_exception") or {}).get(t, "")
            row["baseline_exception"] = expected
            row["artifact"] = artifact
            row["matches_baseline"] = bool(expected) and bool(msgs) and all(expected in m for m in msgs)
            # A flake is reproduced when the replay is exact, the test passes elsewhere, the
            # failure is not a scheduler artefact and (when known) is the baseline's exception.
            row["flake_reproduced"] = row["reproduced"] and not artifact and (row["matches_baseline"] or not expected)
            row["divergence"] = cf.get("divergence", "")
            rows.append(row)
    if rows:
        with open(outdir / "tests.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    srows = []
    for r in suites:
        row = {"project": r["name"], "set": r.get("set"), "status": r.get("status"), "python": r.get("python"),
               "commit": (r.get("commit") or "")[:12]}
        if r.get("status") == "ok":
            by = collections.defaultdict(list)
            managed = []
            for t in r["timing"]:
                if not t["timed_out"] and t["exit"] in (0, 1):
                    by[t["mode"]].append(t["duration_s"])
                if t["mode"] == "l1" and t.get("stats"):
                    managed.append(t["stats"]["managed"])
            seeds = r.get("suite_seeds", [1])
            for m in suite_modes(seeds):
                row[m + "_s"] = _median(by.get(m, []))
                row[m + "_timeouts"] = sum(1 for t in r["timing"] if t["mode"] == m and t["timed_out"])
                row[m + "_runs"] = sum(1 for t in r["timing"] if t["mode"] == m)
            d = row["det_s"]
            row["l1_vs_det_pct"] = round(100 * (row["l1_s"] / d - 1), 1) if d and row["l1_s"] else None
            for sd in seeds:
                v = row.get(f"l1-s{sd}_s")
                row[f"l1s{sd}_vs_det_pct"] = round(100 * (v / d - 1), 1) if d and v else None
            pl = row["plain_s"]
            row["det_vs_plain_pct"] = round(100 * (d / pl - 1), 1) if pl and d else None
            row["l1_vs_plain_pct"] = round(100 * (row["l1_s"] / pl - 1), 1) if pl and row["l1_s"] else None
            row["managed_threads"] = max(managed) if managed else None
            st = [t["stats"] for t in r["timing"] if t["mode"] == "l1" and t.get("stats")]
            row["escapes"] = max((s["escapes"] for s in st), default=None)
            row["deadlocks"] = max((s["deadlocks"] for s in st), default=None)
            row["tests"] = sum(next((t["counts"] for t in r["timing"] if t["mode"] == "det"), {}).values())
            row["broken_by_det"] = r["broken_by_det"].get("n_broken", 0)
            row["broken_by_l1"] = r["broken_by_l1"].get("n_broken", 0)
            row["sometimes_by_l1"] = r["broken_by_l1"].get("n_sometimes", 0)
            for sd in seeds:
                b = r.get(f"broken_by_l1_s{sd}", {})
                row[f"broken_by_l1_s{sd}"] = b.get("n_broken", 0)
                row[f"sometimes_by_l1_s{sd}"] = b.get("n_sometimes", 0)
                row[f"broken_l1_s{sd}_tests"] = " ".join(b.get("broken", [])[:20])
            row["l1_unstable"] = len(r["unstable"].get("l1", []))
            row["det_unstable"] = len(r["unstable"].get("det", []))
            row["broken_l1_tests"] = " ".join(r["broken_by_l1"].get("broken", [])[:20])
            row["sometimes_l1_tests"] = " ".join(r["broken_by_l1"].get("sometimes", [])[:20])
        else:
            row["detail"] = (r.get("detail") or "")[:200]
        srows.append(row)
    if srows:
        keys = list(dict.fromkeys(k for s in srows for k in s))
        with open(outdir / "suites.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(srows)
    summary = {"meta": meta, "tests": rows, "suites": srows,
               "projects": [{k: r.get(k) for k in ("name", "kind", "status", "detail", "python", "commit", "cpu")}
                            for r in corpus + suites]}
    (outdir / "summary.json").write_text(json.dumps(summary, indent=1))
    log(f"aggregate: {len(rows)} corpus tests, {len(srows)} suites -> {outdir}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--kind", choices=("corpus", "suite"))
    ap.add_argument("--list", action="store_true", help="print the job matrix as JSON")
    ap.add_argument("--only", default="", help="comma separated kind:name filter for --list")
    ap.add_argument("--aggregate", metavar="DIR")
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--wheel", default="")
    ap.add_argument("--work", default="/tmp/l1twork")
    ap.add_argument("--out", default="out")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--confirm", type=int, default=10)
    ap.add_argument("--timing-runs", type=int, default=3)
    ap.add_argument("--suite-seeds", default="1", help="comma separated exploration seeds for suite runs")
    ap.add_argument("--warmup", type=int, default=1, help="discarded --det runs before the timed suite runs")
    ap.add_argument("--loaded-runs", type=int, default=5)
    ap.add_argument("--run-timeout", type=float, default=600)
    ap.add_argument("--suite-timeout", type=float, default=2400)
    ap.add_argument("--hang-dump", type=float, default=300, help="faulthandler_timeout for suite runs (s)")
    ap.add_argument("--run-url", default="")
    a = ap.parse_args(argv)
    doc = json.loads(Path(a.corpus).read_text())
    if a.list:
        only = {x.strip() for x in a.only.split(",") if x.strip()}
        inc = [{"kind": "corpus", "name": c["name"]} for c in doc["corpus"]] + \
              [{"kind": "suite", "name": s["name"]} for s in doc["suites"]]
        if only:
            inc = [x for x in inc if f"{x['kind']}:{x['name']}" in only]
        print(json.dumps({"include": inc}))
        return
    if a.aggregate:
        aggregate(Path(a.aggregate), Path(a.out), {"run_url": a.run_url})
        return
    if a.wheel:
        a.wheel = str(Path(a.wheel).resolve())
    pool = doc["corpus"] if a.kind == "corpus" else doc["suites"]
    project = next(p for p in pool if p["name"] == a.project)
    res = measure_corpus(project, a) if a.kind == "corpus" else measure_suite(project, a)
    res["args"] = {k: getattr(a, k) for k in ("runs", "seeds", "confirm", "timing_runs", "loaded_runs")}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    out = Path(a.out) / f"{project['name']}.{a.kind}.json"
    out.write_text(json.dumps(res, indent=1))
    log(f"wrote {out}")


if __name__ == "__main__":
    main()
