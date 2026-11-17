#!/usr/bin/env python3
"""Cache-skip study, collection stage: walk the last N first-parent commits of a
repository and, at every commit, run its pytest suite twice:

1. ``time``: plain serial run (fixed collection order, no coverage) -> per-test
   durations and outcomes, wall time;
2. ``capture``: the same run with the capture plugin, executed lines recorded
   under ``coverage run`` (``--tracer coverage``, as in the study) or by the
   plugin's ``sys.monitoring`` tracer (``--tracer sysmon``, Python 3.12+; the
   default when available) -> per-test executed lines, data files opened,
   directories listed, subprocesses, sockets, module first-load index; wall
   time. ``--tracer both`` runs both (sys.monitoring files as ``<stem>.sm.*``)
   for equivalence checks (``analyze.py --tag .sm``, ``compare_skips.py``).

Everything is written below ``<work>/<repo>/caps/<i>-<sha>.*``; ``analyze.py``
turns it into skip decisions.

    python harness/cache_skip/run_repo.py --repo toolz --work /tmp/cs --commits 51
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
from detpy_harness import detect_install, clean_env  # noqa: E402
from sysmon_capture import fold_file  # noqa: E402  (same directory as this script)

# Study-local pytest arguments: tests that hang in a serial run (each would cost the full --timeout per run).
EXTRA_ARGS = {
    # waits on a watchdog reload that never comes in a serial run (not deterministic under --det either)
    "werkzeug": ["--deselect", "tests/test_serving.py::test_reloader_sys_path[watchdog]"],
}
DEP_SPEC_NAMES = ("pyproject.toml", "setup.py", "setup.cfg", "uv.lock", "poetry.lock", "Pipfile.lock",
                  "pdm.lock", "tox.ini")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd, cwd=None, env=None, timeout=None):
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout,
                           errors="replace", stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout + p.stderr, time.perf_counter() - t0
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -9, out, time.perf_counter() - t0


def git(src, *args) -> str:
    return subprocess.run(["git", *args], cwd=src, capture_output=True, text=True, check=True).stdout


def dep_spec_hash(src: Path) -> str:
    h = hashlib.sha256()
    files = sorted(p for p in src.rglob("*") if p.is_file() and ".git" not in p.parts and (
        p.name in DEP_SPEC_NAMES or (p.name.startswith("requirements") and p.suffix in (".txt", ".in"))
        or (p.parent.name == "requirements" and p.suffix in (".txt", ".in"))) and len(p.relative_to(src).parts) <= 3)
    for p in files:
        h.update(str(p.relative_to(src)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


def install(repo: dict, src: Path, venv: Path, logf: Path) -> tuple[bool, str]:
    py = venv / "bin" / "python"
    if not py.exists():
        code, out, _ = sh(["uv", "venv", "--quiet", "--python", repo.get("python_version", "3.13"), str(venv)],
                          timeout=600)
        if code:
            return False, "venv: " + out[-300:]
    base = ["uv", "pip", "install", "--quiet", "--python", str(py)]
    args, groups, reqs = detect_install(src)
    extra = repo.get("install", [])
    tools = ["pytest", "coverage>=7.6"]
    out = ""
    for attempt in (args + groups + reqs + extra, args + groups + extra, args + reqs + extra, args + extra,
                    ["-e", "."] + extra):
        code, out, _ = sh(base + attempt + tools, cwd=src, timeout=1500)
        with open(logf, "a") as fh:
            fh.write(" ".join(attempt) + f"\n-> {code}\n{out[-2000:]}\n")
        if code == 0:
            return True, " ".join(attempt)
    return False, "install: " + out[-300:]


def pytest_args(repo: dict, py: str, src: Path, env: dict) -> tuple[list, int, str]:
    has = lambda mod: sh([py, "-c", f"import {mod}"], env=env)[0] == 0  # noqa: E731
    args = list(repo.get("pytest_args", [])) + EXTRA_ARGS.get(repo["name"], []) + ["-p", "no:cacheprovider", "-p", "no:randomly", "-p", "capture_plugin",
                                                "-q", "-rN", "--tb=no"]
    if has("xdist"):
        args += ["-n", "0"]
    if has("pytest_cov"):
        args += ["--no-cov"]
    if has("pytest_timeout"):
        args += ["--timeout=120"]  # a hung live-server test must not stall the whole walk
    out = ""
    for extra in ([], ["-o", "addopts="], ["--continue-on-collection-errors"],
                  ["-o", "addopts=", "--continue-on-collection-errors"]):
        code, out, _ = sh([py, "-m", "pytest", "--collect-only", *args, *extra], cwd=src, env=env, timeout=600)
        n = sum(1 for line in out.splitlines() if "::" in line)
        if (code == 0 or (code == 1 and "--continue-on-collection-errors" in extra)) and n:
            return args + extra, n, ""
    return [], 0, out[-1500:]


def extract_coverage(data_file: Path, src: Path) -> dict:
    """Compact form: {"files": [...], "blobs": [(file_idx, (lines...))], "ctx": {ctx: [blob_idx...]}}."""
    from coverage import CoverageData  # the driver's own coverage, reads the sqlite file
    data = CoverageData(basename=str(data_file))
    data.read()
    files, blobs, blob_ix, ctx = [], [], {}, {}
    srcs = str(src) + os.sep
    for f in sorted(data.measured_files()):
        rel = f[len(srcs):] if f.startswith(srcs) else f
        fi = len(files)
        files.append(rel)
        per_ctx: dict[str, list] = {}
        for line, cs in (data.contexts_by_lineno(f) or {}).items():
            for c in cs:
                per_ctx.setdefault(c, []).append(line)
        for c, lines in per_ctx.items():
            key = (fi, tuple(sorted(lines)))
            b = blob_ix.get(key)
            if b is None:
                b = blob_ix[key] = len(blobs)
                blobs.append(key)
            ctx.setdefault(c, []).append(b)
    return {"files": files, "blobs": blobs, "ctx": ctx}


def det_check(py, src, args, env, a, stem, work) -> dict:
    """Run the suite ``--det-runs`` times under --det (fixed order) and keep, per test, whether every run gave
    the same fingerprint and which event sources it touched."""
    if sh([py, "-c", "import detpy._core"], env=env)[0] != 0:
        code, out, _ = sh(["uv", "pip", "install", "--quiet", "--python", py, "--reinstall-package", "detpy",
                           "--no-deps", a.wheel], timeout=600)
        if code:
            return {"status": "wheel-install-failed", "detail": out[-300:]}
    fps: dict[str, list] = {}
    srcs: dict[str, set] = {}
    walls = []
    for k in range(a.det_runs):
        git(src, "clean", "-qfd")
        trace = work / f"det{k}.jsonl"
        trace.unlink(missing_ok=True)
        env_d = dict(env, CACHE_SKIP_MODE="time", CACHE_SKIP_OUT=str(work / "det.time.json"))
        code, out, wall = sh([py, "-m", "pytest", "--det", f"--det-trace={trace}", *args], cwd=src, env=env_d,
                             timeout=a.timeout)
        walls.append(wall)
        if not trace.exists():
            return {"status": "det-run-failed", "detail": out[-500:]}
        with open(trace) as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and "nodeid" in rec and "fingerprint" in rec:
                    fps.setdefault(rec["nodeid"], []).append(rec["fingerprint"])
                    srcs.setdefault(rec["nodeid"], set()).update(
                        s for s, n in (rec.get("counts") or {}).items() if n)
        trace.unlink(missing_ok=True)
    res = {nid: {"covered": len(v) == a.det_runs and len(set(v)) == 1, "sources": sorted(srcs.get(nid, ()))}
           for nid, v in fps.items()}
    Path(str(stem) + ".det.json").write_text(json.dumps(res))
    return {"status": "ok", "runs": a.det_runs, "walls": walls, "tests": len(res),
            "covered": sum(1 for r in res.values() if r["covered"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--commits", type=int, default=51)
    ap.add_argument("--timeout", type=float, default=1500)
    ap.add_argument("--sha", default="", help="pin the newest commit (default: remote HEAD)")
    ap.add_argument("--wheel", default="", help="detpy wheel: enables the --det determinism check")
    ap.add_argument("--det-every", type=int, default=10, help="--det check at commits i %% N == 0 (and the last)")
    ap.add_argument("--det-runs", type=int, default=2)
    ap.add_argument("--deselect", action="append", default=[],
                    help="test node id left out of every run (e.g. a test whose duration is a thread-scheduling "
                         "lottery: more-itertools TestConcurrentTee::test_concurrent_consumers, 1 s to 3 min)")
    ap.add_argument("--tracer", choices=("auto", "coverage", "sysmon", "both"), default="auto",
                    help="capture with coverage.py (as in the study), the sys.monitoring tracer (Python 3.12+), or "
                         "both (coverage files as <stem>.*, sys.monitoring files as <stem>.sm.*); auto = sysmon "
                         "when the repository's Python has sys.monitoring")
    a = ap.parse_args(argv)

    cfg = json.loads((ROOT / "harness" / "repos.json").read_text())
    repo = next(r for r in cfg["popular"] if r["name"] == a.repo)
    work = Path(a.work).resolve() / a.repo
    src, venv, caps = work / "src", work / "venv", work / "caps"
    caps.mkdir(parents=True, exist_ok=True)
    if not (src / ".git").exists():
        code, out, _ = sh(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", repo["url"], str(src)],
                          timeout=900)
        if code:
            log(f"clone failed: {out[-300:]}")
            return 1
    head = a.sha or git(src, "rev-parse", "origin/HEAD").strip()
    commits = git(src, "rev-list", "--first-parent", "-n", str(a.commits), head).split()[::-1]
    meta = {"repo": a.repo, "url": repo["url"], "head": head, "commits": commits, "python": sys.version.split()[0],
            "runner": os.environ.get("RUNNER_NAME", os.uname().nodename), "cpus": os.cpu_count(), "steps": []}
    log(f"{a.repo}: {len(commits)} commits, oldest {commits[0][:10]} newest {commits[-1][:10]}")

    rc = work / "coveragerc"
    last_hash, args, py = None, None, str(venv / "bin" / "python")
    tracers: list[str] = []
    for i, sha in enumerate(commits):
        step = {"i": i, "sha": sha, "date": git(src, "show", "-s", "--format=%cI", sha).strip()}
        meta["steps"].append(step)
        stem = caps / f"{i:03d}-{sha[:12]}"
        if (stem.with_suffix(".done")).exists():
            step.update(json.loads(stem.with_suffix(".done").read_text()))
            continue
        git(src, "checkout", "-q", "--force", sha)
        git(src, "clean", "-qfd")
        h = dep_spec_hash(src)
        env = clean_env(py, repo.get("env", {}))
        env["PYTHONPATH"] = str(HERE)
        env["PYTHONHASHSEED"] = "0"  # same set/dict-of-str order in every run: executed paths comparable
        env["CACHE_SKIP_ROOT"] = str(src)
        env["CACHE_SKIP_OUT"] = str(work / "collect.json")
        if h != last_hash:
            ok, how = install(repo, src, venv, work / "install.log")
            step["install"] = how
            if not ok:
                step["status"] = "install-failed"
                log(f"[{i}] {sha[:10]} install failed")
                last_hash = None
                stem.with_suffix(".done").write_text(json.dumps({"status": step["status"]}))
                continue
            args, n, why = pytest_args(repo, py, src, env)
            if args:
                args = [*args, *(x for d in a.deselect for x in ("--deselect", d))]
            if not args:
                step["status"] = "collect-failed"
                step["detail"] = why[-500:]
                log(f"[{i}] {sha[:10]} collect failed")
                last_hash = None
                stem.with_suffix(".done").write_text(json.dumps({"status": step["status"]}))
                continue
            last_hash = h
        if not tracers:
            if a.tracer == "auto":
                has_mon = sh([py, "-c", "import sys; sys.monitoring"])[0] == 0
                tracers = ["sysmon" if has_mon else "coverage"]
            else:
                tracers = ["coverage", "sysmon"] if a.tracer == "both" else [a.tracer]
            meta["tracers"] = tracers
            if "sysmon" in tracers:  # build the C recorder once, outside the timed runs
                meta["sysmon_native"] = sh([py, str(HERE / "sysmon_capture.py"), "--build"], env=env)[1].strip()
        step["args"] = args
        freeze = [x for x in sh(["uv", "pip", "freeze", "--python", py])[1].splitlines() if not x.startswith("detpy")]
        step["freeze"] = hashlib.sha256("\n".join(freeze).encode()).hexdigest()[:16]
        # 1. plain timing run
        env_t = dict(env, CACHE_SKIP_MODE="time", CACHE_SKIP_OUT=str(stem) + ".time.json")
        code, out, wall_t = sh([py, "-m", "pytest", *args], cwd=src, env=env_t, timeout=a.timeout)
        step["time_exit"], step["time_wall"] = code, wall_t
        # 2. capture run(s): coverage.py (as in the study) and/or the sys.monitoring tracer
        ok = Path(str(stem) + ".time.json").exists()
        outs = [out]
        for tracer in tracers:
            tag = "" if tracer == tracers[0] else ".sm"
            git(src, "clean", "-qfd")
            env_c = dict(env, CACHE_SKIP_MODE="capture", CACHE_SKIP_TRACER=tracer,
                         CACHE_SKIP_OUT=f"{stem}{tag}.cap.json", CACHE_SKIP_COV=f"{stem}{tag}.cov.pkl.gz")
            if tracer == "coverage":
                covdata = work / ".coverage"
                covdata.unlink(missing_ok=True)
                rc.write_text(f"[run]\nsource = {src}\ndata_file = {covdata}\nconcurrency = thread\n"
                              f"disable_warnings = no-data-collected, module-not-imported, module-not-measured, "
                              f"couldnt-parse, already-imported\n")
                code, out2, wall_c = sh([py, "-m", "coverage", "run", f"--rcfile={rc}", "-m", "pytest", *args],
                                        cwd=src, env=env_c, timeout=a.timeout)
                if covdata.exists():
                    t1 = time.perf_counter()
                    cov = extract_coverage(covdata, src)
                    with gzip.open(f"{stem}{tag}.cov.pkl.gz", "wb", compresslevel=3) as fh:
                        pickle.dump(cov, fh, protocol=pickle.HIGHEST_PROTOCOL)
                    step[f"extract_s{tag}"] = time.perf_counter() - t1
                covdata.unlink(missing_ok=True)
            else:
                raw = Path(f"{stem}{tag}.smraw")
                env_c["CACHE_SKIP_SMRAW"] = str(raw)
                code, out2, wall_c = sh([py, "-m", "pytest", *args], cwd=src, env=env_c, timeout=a.timeout)
                if raw.exists():
                    t1 = time.perf_counter()
                    fold_file(str(raw), f"{stem}{tag}.cov.pkl.gz")
                    step[f"extract_s{tag}"] = time.perf_counter() - t1
                raw.unlink(missing_ok=True)
            step[f"cap_exit{tag}"], step[f"cap_wall{tag}"] = code, wall_c
            step[f"cap_tracer{tag}"] = tracer
            outs.append(out2)
            ok = ok and Path(f"{stem}{tag}.cap.json").exists() and Path(f"{stem}{tag}.cov.pkl.gz").exists()
        if ok:
            with gzip.open(str(stem) + ".cov.pkl.gz", "rb") as fh:
                nblobs = len(pickle.load(fh)["blobs"])
            nt = len(json.loads(Path(str(stem) + ".time.json").read_text())["tests"])
            step["status"] = "ok"
            log(f"[{i}] {sha[:10]} ok: {nt} tests, plain {wall_t:.1f}s, "
                + ", ".join(f"{step['cap_tracer' + t]} {step['cap_wall' + t]:.1f}s "
                            f"(+{100 * (step['cap_wall' + t] / wall_t - 1):.0f}%)"
                            for t in ([""] + [".sm"] * (len(tracers) > 1)))
                + f", {nblobs} blobs")
        else:
            step["status"] = "run-failed"
            step["detail"] = [o[-800:] for o in outs]
            log(f"[{i}] {sha[:10]} run failed: exit {step['time_exit']}/{step.get('cap_exit')}\n{outs[-1][-600:]}")
        if ok and a.wheel and (i % a.det_every == 0 or i == len(commits) - 1):
            step["det"] = det_check(py, src, args, env, a, stem, work)
        stem.with_suffix(".done").write_text(json.dumps({k: v for k, v in step.items() if k not in ("i", "sha", "date")}))
        (work / "meta.json").write_text(json.dumps(meta, indent=1))
    git(src, "checkout", "-q", "--force", commits[-1])
    (work / "meta.json").write_text(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
