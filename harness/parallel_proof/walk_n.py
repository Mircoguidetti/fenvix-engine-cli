"""Cache-proof walk under ``-n`` (P3's acceptance measurement, design 5): over consecutive commits of one repository,
oldest first, with one cache directory per mode kept across commits:

* **A-par**: ``pytest --det --det-cache=CP -n N`` (the engine under test);
* **A-ser**: ``pytest --det --det-cache=CS`` (the serial walk on the same commits, for the reuse share);
* **B**: ``pytest --det`` serially, no cache: the ground truth. Every result A-par or A-ser reused is compared with
  B's outcome at the same commit; a difference is re-run once more serially (B', only those tests) to tell a wrong
  reuse (B' agrees with B) from a flaky test.

usage: python -m harness.parallel_proof.walk_n --repo DIR --python PY --commits K --out OUT.json [--workers 4]
           [--reinstall "CMD"] -- PYTEST ARGS...

The repository must have at least K commits of first-parent history behind its HEAD (``git fetch --depth``).
Every number written is MEASURED on the machine that runs the walk."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time

DEPS = ("requirements.txt", "requirements_test.txt", "requirements_dev.txt", "pyproject.toml", "setup.py",
        "setup.cfg", "uv.lock")


def git(repo, *args) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def pytest(repo, py, args, out_json, timeout):
    env = {k: v for k, v in os.environ.items() if k not in ("DETPY_REEXEC", "PYTHONHASHSEED")}
    t0 = time.perf_counter()
    log = out_json + ".log"
    peak_kb = None
    with open(log, "w") as fh:
        p = subprocess.Popen([py, "-m", "pytest", "-p", "no:cacheprovider", "-q", f"--det-outcomes={out_json}", *args],
                             cwd=repo, stdout=fh, stderr=subprocess.STDOUT, text=True, env=env)
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
        try:
            # py-cache item 4: the peak resident set of the pytest process and of every worker it reaped (Linux:
            # wait4's ru_maxrss covers the reaped descendants)
            _, status, ru = os.wait4(p.pid, 0)
            p.returncode = os.waitstatus_to_exitcode(status)
            peak_kb = ru.ru_maxrss
        except ChildProcessError:
            pass
    with open(log) as fh:
        lines = fh.read().strip().splitlines()
    tail = lines[-1:] or [""]
    rc = p.returncode if p.returncode is not None else "timeout"
    if rc == -9:
        rc = "killed"
    wall = round(time.perf_counter() - t0, 1)
    data = {}
    if os.path.exists(out_json):
        with open(out_json) as f:
            data = json.load(f)
    return {"wall_s": wall, "rc": rc, "tail": tail[0], "peak_rss_mb": round(peak_kb / 1024, 1) if peak_kb else None}, data


def store_mb(cache_dir) -> float | None:
    """Size of a cache directory's files (the store, its shards), MB."""
    total = 0
    for dp, _, fns in os.walk(cache_dir):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return round(total / 2**20, 2) if total else None


def deps_digest(repo) -> str:
    h = hashlib.sha1()
    for n in DEPS:
        p = os.path.join(repo, n)
        if os.path.exists(p):
            with open(p, "rb") as f:
                h.update(n.encode() + f.read())
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--python", required=True)
    ap.add_argument("--commits", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dist", default="")
    ap.add_argument("--reinstall", default="")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--work", default=None)
    ap.add_argument("--deadline-s", type=float, default=0,
                    help="start no further commit after this many seconds (a CI job's limit; 0: none)")
    ap.add_argument("--modes", default="a_par,a_ser",
                    help="cache modes to walk besides the truth run b (a_ser can be left out to fit a CI job)")
    ap.add_argument("--det-args", default="",
                    help="extra detpy options for every --det run (cache runs and truth), e.g. --det-urandom")
    ap.add_argument("--shard", default="",
                    help="K/M: walk only the K-th of M contiguous slices of the commits (0-based); each slice starts "
                         "with an empty cache at its first commit")
    ap.add_argument("--unchanged", action="store_true",
                    help="at each shard's first commit, run every cache mode a second time on the same commit (the "
                         "reuse of an unchanged commit, rows a_par_u / a_ser_u)")
    ap.add_argument("pytest_args", nargs="*")
    a = ap.parse_args(argv)
    det_args = a.det_args.split()
    work = os.path.abspath(a.work or os.path.join(os.path.dirname(os.path.abspath(a.out)), "walk-work"))
    os.makedirs(work, exist_ok=True)
    head = git(a.repo, "rev-parse", "HEAD").strip()
    shas = git(a.repo, "rev-list", "--first-parent", f"--max-count={a.commits}", head).split()[::-1]
    offset = 0
    if a.shard:
        k, m = (int(x) for x in a.shard.split("/"))
        size = -(-len(shas) // m)
        offset = k * size
        shas = shas[offset:offset + size]
    par = ["-n", str(a.workers)] + (["--dist", a.dist] if a.dist else [])
    rows = []
    deps = None
    t_start = time.perf_counter()
    for i, sha in enumerate(shas):
        if a.deadline_s and time.perf_counter() - t_start > a.deadline_s:
            print(f"deadline: stopped after {i} of {len(shas)} commits", flush=True)
            break
        git(a.repo, "checkout", "-q", "--force", sha)
        d = deps_digest(a.repo)
        if deps is not None and d != deps and a.reinstall:
            subprocess.run(a.reinstall, shell=True, cwd=a.repo, capture_output=True)
        deps = d
        row = {"i": i + offset, "sha": sha, "shard_first": i == 0}
        runs = {}
        modes = [m for m in a.modes.split(",") if m]
        variants = (("a_par", ["--det", *det_args, f"--det-cache={work}/cache-par", f"--det-trace={work}/a_par.jsonl",
                               *par]),
                    ("a_ser", ["--det", *det_args, f"--det-cache={work}/cache-ser", f"--det-trace={work}/a_ser.jsonl"]),
                    ("b", ["--det", *det_args, f"--det-trace={work}/b.jsonl"]))
        todo = [v for v in variants if v[0] in modes or v[0] == "b"]
        if a.unchanged and i == 0:
            # the same commit again, warm: an unchanged commit's reuse (py-cache item 5)
            todo = [v for v in todo if v[0] != "b"] + [(v[0] + "_u", v[1]) for v in todo if v[0] != "b"] + \
                [v for v in todo if v[0] == "b"]
        for name, extra in todo:
            cf = os.path.join(work, "cache-par" if name.startswith("a_par") else "cache-ser", "carried.jsonl")
            off = os.path.getsize(cf) if os.path.exists(cf) else 0
            meta, data = pytest(a.repo, a.python, [*a.pytest_args, *extra], f"{work}/{name}-{i}.json", a.timeout)
            runs[name] = data
            row[name] = meta
            if name != "b":
                meta["store_mb"] = store_mb(os.path.join(work, "cache-par" if name.startswith("a_par") else "cache-ser"))
            if name != "b" and os.path.exists(cf):
                # the carried-set rule: tests whose key carries earlier contexts of their process (every worker's
                # recording session appends one line)
                with open(cf) as fh:
                    fh.seek(off)
                    lines = [json.loads(x) for x in fh if x.strip()]
                meta["carried"] = sum(x.get("carried", 0) for x in lines)
                meta["carried_of_recorded"] = sum(x.get("recorded", 0) for x in lines)
        truth = runs["b"].get("outcomes", {})
        tdur = runs["b"].get("durations", {})  # per-test time of the truth run (setup + call + teardown)
        row["b"]["test_time_s"] = round(sum(tdur.values()), 3)
        if "--det-isolate" in det_args:
            # --det-isolate (the truth is an isolated run too): the fork overhead, and at the shard's first commit
            # the tests whose isolated outcome differs from a run without isolation (order-dependent tests)
            for mode in ("a_par", "a_ser", "b"):
                if mode in runs and runs[mode].get("isolate"):
                    row[mode]["isolate"] = runs[mode]["isolate"]
            if i == 0:
                plain_args = [x for x in det_args if x != "--det-isolate"]
                pm, pdata = pytest(a.repo, a.python, [*a.pytest_args, "--det", *plain_args,
                                                      f"--det-trace={work}/b_plain.jsonl"], f"{work}/b_plain-{i}.json",
                                   a.timeout)
                plain = pdata.get("outcomes", {})
                row["b_plain"] = pm
                row["order_dependent"] = sorted([n, plain.get(n), truth[n]] for n in truth
                                                if n in plain and plain[n] != truth[n])
        for mode in [m for m in ("a_par", "a_ser", "a_par_u", "a_ser_u") if m in runs]:
            c = runs[mode].get("cache", {})
            reused = c.get("reused_ids", [])
            outcomes = runs[mode].get("outcomes", {})
            bad = [n for n in reused if n in truth and outcomes.get(n) != truth[n]]
            row[mode].update(reused=len(reused), ran=c.get("ran"), recorded=c.get("recorded"),
                             tests=len(outcomes), miss_reasons=c.get("miss_reasons"),
                             reused_not_in_truth=len([n for n in reused if n not in truth]),
                             reused_time_s=round(sum(tdur.get(n, 0.0) for n in reused), 3))
            wrong, flaky = [], []
            if bad:
                ids = os.path.join(work, f"recheck-{mode}-{i}.txt")
                with open(ids, "w") as f:
                    f.write("\n".join(bad) + "\n")
                _, again = pytest(a.repo, a.python, [*a.pytest_args, "--det", *det_args, f"--det-order={ids}"],
                                  f"{work}/recheck-{mode}-{i}.json", a.timeout)
                o2 = again.get("outcomes", {})
                for n in bad:
                    (wrong if o2.get(n) == truth[n] else flaky).append([n, outcomes.get(n), truth[n], o2.get(n)])
            row[mode].update(mismatches=len(bad), wrong_reuses=wrong, flaky=flaky)
        rows.append(row)
        with open(a.out, "w") as f:
            json.dump({"repo": os.path.basename(os.path.abspath(a.repo)), "workers": a.workers, "args": a.pytest_args,
                       "det_args": det_args, "shard": a.shard, "commits": rows}, f, indent=1)
        print(json.dumps({k: (v if not isinstance(v, dict) else {x: v[x] for x in ("wall_s", "reused", "ran",
                                                                                   "mismatches", "wrong_reuses",
                                                                                   "peak_rss_mb", "store_mb",
                                                                                   "reused_time_s", "test_time_s")
                                                                 if x in v}) for k, v in row.items()}), flush=True)
    git(a.repo, "checkout", "-q", "--force", head)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
