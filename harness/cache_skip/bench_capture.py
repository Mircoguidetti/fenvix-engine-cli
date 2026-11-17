#!/usr/bin/env python3
"""Capture overhead benchmark: plain run vs coverage.py capture vs sys.monitoring capture.

Uses a work directory already prepared by ``run_repo.py`` (``<work>/<repo>/src`` and ``venv``, checked out at the
commit to measure). Runs the variants interleaved, ``--runs`` times each, serially, and prints the medians.

    python harness/cache_skip/bench_capture.py --work /tmp/cs --runs 3 more-itertools click marshmallow \
        --deselect more-itertools=tests/test_more.py::TestConcurrentTee::test_concurrent_consumers
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from run_repo import ROOT, extract_coverage, pytest_args, sh  # noqa: E402
from sysmon_capture import fold_file  # noqa: E402
from detpy_harness import clean_env  # noqa: E402

VARIANTS = ("plain", "coverage", "sysmon")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--out", default="")
    ap.add_argument("--deselect", action="append", default=[],
                    help="<repo>=<test node id> left out of every variant (e.g. a test whose duration is a thread-scheduling "
                         "lottery even in the plain run)")
    ap.add_argument("repos", nargs="+")
    a = ap.parse_args(argv)
    variants = a.variants.split(",")
    cfg = json.loads((ROOT / "harness" / "repos.json").read_text())
    res = {}
    tmp = Path(tempfile.mkdtemp(prefix="bench-capture-"))
    for name in a.repos:
        repo = next(r for r in cfg["popular"] if r["name"] == name)
        work = Path(a.work).resolve() / name
        src, py = work / "src", str(work / "venv" / "bin" / "python")
        env = clean_env(py, repo.get("env", {}))
        env.update(PYTHONPATH=str(HERE), PYTHONHASHSEED="0", CACHE_SKIP_ROOT=str(src),
                   CACHE_SKIP_OUT=str(tmp / "collect.json"))
        args, n, why = pytest_args(repo, py, src, env)
        if not args:
            print(f"{name}: collect failed {why[-300:]}")
            continue
        for d in a.deselect:
            r, _, nid = d.partition("=")
            if r == name:
                args = [*args, "--deselect", nid]
        rc = tmp / "coveragerc"
        covdata = tmp / ".coverage"
        rc.write_text(f"[run]\nsource = {src}\ndata_file = {covdata}\nconcurrency = thread\n"
                      f"disable_warnings = no-data-collected, module-not-imported, module-not-measured, "
                      f"couldnt-parse, already-imported\n")
        walls = {v: [] for v in variants}
        cpus = {v: [] for v in variants}
        post = {v: [] for v in variants}  # post-processing outside the test process (extract / fold)
        sh([py, "-m", "pytest", *args], cwd=src, env=dict(env, CACHE_SKIP_MODE="time"))  # warm-up (pyc, page cache)
        for k in range(a.runs):
            for v in variants:
                e = dict(env, CACHE_SKIP_OUT=str(tmp / f"{v}.json"), CACHE_SKIP_COV=str(tmp / f"{v}.cov.pkl.gz"))
                if v == "plain":
                    cmd = [py, "-m", "pytest", *args]
                    e["CACHE_SKIP_MODE"] = "time"
                elif v == "coverage":
                    covdata.unlink(missing_ok=True)
                    cmd = [py, "-m", "coverage", "run", f"--rcfile={rc}", "-m", "pytest", *args]
                    e.update(CACHE_SKIP_MODE="capture", CACHE_SKIP_TRACER="coverage")
                else:
                    cmd = [py, "-m", "pytest", *args]
                    tracer, _, dbg = v.partition(":")  # e.g. "sysmon:restart" (profiling knobs, see sysmon_capture)
                    e.update(CACHE_SKIP_MODE="capture", CACHE_SKIP_TRACER=tracer, SYSMON_DBG=dbg,
                             CACHE_SKIP_SMRAW=str(tmp / f"{v}.smraw"))
                    Path(e["CACHE_SKIP_SMRAW"]).unlink(missing_ok=True)
                r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
                code, out, wall = sh(cmd, cwd=src, env=e, timeout=3600)
                r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
                cpu = (r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime)
                walls[v].append(wall)
                cpus[v].append(cpu)
                t1 = time.perf_counter()
                if v == "coverage" and covdata.exists():
                    extract_coverage(covdata, src)
                elif v.startswith("sysmon") and Path(e["CACHE_SKIP_SMRAW"]).exists():
                    fold_file(e["CACHE_SKIP_SMRAW"], e["CACHE_SKIP_COV"])
                p = time.perf_counter() - t1 if v != "plain" else 0.0
                post[v].append(p)
                print(f"{name} run {k} {v}: {wall:.2f}s wall, {cpu:.2f}s cpu, post {p:.2f}s, exit {code}", flush=True)
        med = {v: statistics.median(w) for v, w in walls.items()}
        cmed = {v: statistics.median(w) for v, w in cpus.items()}
        res[name] = {"walls": walls, "cpus": cpus, "post": post, "median": med, "median_cpu": cmed, "tests": n,
                     "median_post": {v: statistics.median(w) for v, w in post.items()},
                     "overhead": {v: med[v] / med["plain"] - 1 for v in variants if v != "plain" and "plain" in med},
                     "overhead_cpu": {v: cmed[v] / cmed["plain"] - 1 for v in variants
                                      if v != "plain" and "plain" in cmed}}
        print(f"{name}: wall " + ", ".join(f"{v} {med[v]:.2f}s" for v in variants) + " | "
              + ", ".join(f"{v} {100 * o:+.0f}%" for v, o in res[name]["overhead"].items())
              + " || cpu " + ", ".join(f"{v} {cmed[v]:.2f}s" for v in variants) + " | "
              + ", ".join(f"{v} {100 * o:+.0f}%" for v, o in res[name]["overhead_cpu"].items()), flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
