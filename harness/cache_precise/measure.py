#!/usr/bin/env python3
"""P-061 measurement harness: how much the Python proof cache reuses when one test fails, is new, or sits in an
edited file, and whether any result differs from uncached ``pytest --det`` (docs/CACHE-PRECISE.md, section 9).

For one project (a spec in ``specs/``) and one mode (``serial`` or ``n4``), on a pinned checkout:

1. **cold**: ``pytest --det --det-cache=C`` (everything recorded); the cache directory is kept as the base;
2. one **scenario** at a time, each from a copy of the base cache and a clean checkout:

   * ``unchanged``: rerun as is (F-05.no-edit's shape);
   * ``add-test``: a new passing test file in the middle of the collection order (it imports pytest, as real tests
     do);
   * ``edit-test``: a test file in the middle gets a new always-failing test before its first test (the exam's
     F-05.edit-test shape; for itsdangerous the exam's own edit);
   * ``failing-test``: a test file with one always-failing test in the middle, present in the cold run too (the
     attrs exam shape: 2 failing tests made an unchanged rerun reuse 256 of 1,322);

   then the warm cached run, then uncached ``pytest --det`` of the same checkout and arguments (the truth). A test
   whose cached outcome differs from the truth is run uncached once more: if the second truth agrees with the first,
   it is a **wrong** result of the cache, otherwise **flaky**.

Output: one JSON per (project, mode) with, per scenario, reused / ran / passing counts, the share reused of the
passing tests, the wall times (cold, warm, truth), the wrong and flaky node ids, and the miss reasons of the warm run
(its ``not reused:`` line). ``aggregate.py`` turns several into the table of the report.

    python harness/cache_precise/measure.py --spec harness/cache_precise/specs/attrs.json --mode serial \\
        --work /tmp/w --wheel dist/fenvix-*.whl --out /tmp/attrs-serial.json [--scenarios unchanged,add-test]

Every number it writes is MEASURED on the machine that ran it (the JSON records the host shape).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCENARIOS = ("unchanged", "add-test", "edit-test", "failing-test")
MODES = {"serial": [], "n4": ["-n", "4"]}

# like a real test, the synthetic ones import pytest (a library: their carried set reaches the library node)
ADDED = "import pytest\n\n\ndef test_p061_added():\n    assert pytest\n"
FAILING = "import pytest\n\n\ndef test_p061_always_fails():\n    pytest.fail('P-061 harness: a test that always fails')\n"
NEW_FAILURE = "def test_p061_new_failure():\n    assert False, 'P-061 harness: edit-test'\n\n\n"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd, cwd=None, env=None, timeout=None):
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL, timeout=timeout)
        return p.returncode, p.stdout + p.stderr, time.perf_counter() - t0
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return -9, out, time.perf_counter() - t0


def git(d, *args):
    return subprocess.run(["git", *args], cwd=d, capture_output=True, text=True, check=True).stdout


def checkout(spec: dict, work: Path) -> Path:
    d = work / spec["name"]
    if not (d / ".git").exists():
        d.mkdir(parents=True, exist_ok=True)
        git(d, "init", "-q")
        git(d, "remote", "add", "origin", spec["url"])
        git(d, "fetch", "-q", "--depth", "1", "origin", spec["sha"])
        git(d, "checkout", "-q", "FETCH_HEAD")
    return d


def reset(d: Path) -> None:
    git(d, "checkout", "-q", "--", ".")
    git(d, "clean", "-qfdx", "-e", ".venv-p061")


def venv(spec: dict, d: Path, wheel: str, python: str) -> Path:
    v = d / ".venv-p061"
    py = v / "bin" / "python"
    if py.exists():
        return py
    rc, out, _ = sh(["uv", "venv", "-q", "-p", python, str(v)])
    if rc:
        raise SystemExit(f"uv venv: {out[-2000:]}")
    env = dict(os.environ, PY=str(py), VENV=str(v))
    if spec.get("install_cmd"):
        rc, out, _ = sh(["bash", "-c", spec["install_cmd"]], cwd=d, env=env, timeout=3600)
    else:
        rc, out, _ = sh(["uv", "pip", "install", "-q", "--python", str(py), *spec["install"]], cwd=d, timeout=3600)
    if rc:
        raise SystemExit(f"install: {out[-3000:]}")
    rc, out, _ = sh(["uv", "pip", "install", "-q", "--python", str(py), wheel, "pytest-xdist"], cwd=d)
    if rc:
        raise SystemExit(f"wheel: {out[-2000:]}")
    return py


def run(py: Path, d: Path, spec: dict, args: list, tag: str, work: Path, timeout: int) -> dict:
    """One pytest run with the engine's outcome map (--det-outcomes)."""
    out_p = work / f"{spec['name']}-{tag}.outcomes.json"
    if out_p.exists():
        out_p.unlink()
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    env.update(spec.get("env", {}))
    cmd = [str(py), "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--det-outcomes={out_p}", *args,
           *spec["args"]]
    rc, out, wall = sh(cmd, cwd=d, env=env, timeout=timeout)
    (work / f"{spec['name']}-{tag}.log").write_text(out)
    try:
        outcomes = json.loads(out_p.read_text()).get("outcomes", {})
    except (OSError, ValueError):
        outcomes = {}
    reused = sum(int(x) for x in re.findall(r"reused (\d+) result", out))
    ran = re.findall(r"ran (\d+)", out)
    miss = [ln.strip() for ln in out.splitlines() if ln.startswith("not reused:")]
    log(f"  {tag}: rc {rc}, {len(outcomes)} outcomes, reused {reused}, wall {wall:.1f}s")
    return {"rc": rc, "wall_s": round(wall, 2), "outcomes": outcomes, "reused": reused,
            "ran": int(ran[-1]) if ran else None, "not_reused": miss[-1] if miss else ""}


def norm(v) -> str:
    v = str(v or "").lower()
    return "passed" if v in ("passed", "xfailed", "xpassed") else v


def pick_file(d: Path, spec: dict, key: str) -> Path:
    """The test file a scenario changes (spec ``edit_file``) or next to which it adds one (spec ``add_dir``)."""
    return d / spec[key]


def apply(scenario: str, d: Path, spec: dict) -> str:
    if scenario == "unchanged":
        return "nothing changed"
    if scenario == "add-test":
        p = pick_file(d, spec, "add_dir") / "test_p061_added.py"
        p.write_text(ADDED)
        return f"added {p.relative_to(d)}"
    if scenario == "failing-test":
        return f"{spec['add_dir']}/test_p061_fails.py present in both runs"
    if scenario == "edit-test":
        p = pick_file(d, spec, "edit_file")
        s = p.read_text()
        anchor = spec.get("edit_anchor")
        if anchor:
            if anchor not in s:
                raise SystemExit(f"edit anchor not found in {p}: {anchor!r}")
            s = s.replace(anchor, NEW_FAILURE + anchor, 1)
        else:
            m = re.search(r"^(def test_|class Test)", s, re.M)
            if not m:
                raise SystemExit(f"no test in {p}")
            s = s[:m.start()] + NEW_FAILURE + s[m.start():]
        p.write_text(s)
        return f"{p.relative_to(d)}: a new always-failing test before its first test"
    raise SystemExit(f"unknown scenario {scenario}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--mode", choices=list(MODES), required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", default=None)
    ap.add_argument("--scenarios", default=",".join(SCENARIOS))
    ap.add_argument("--timeout", type=int, default=5400)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    work = Path(a.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    d = checkout(spec, work)
    reset(d)
    py = venv(spec, d, a.wheel, a.python or spec.get("python", "3.13"))
    margs = MODES[a.mode] + (["--dist", spec["dist"]] if a.mode != "serial" and spec.get("dist") else [])
    det = ["--det", *spec.get("det_args", [])]
    res = {"spec": spec, "mode": a.mode, "host": {"cpus": os.cpu_count(), "python": a.python or spec.get("python"),
                                                 "platform": platform.platform(),
                                                 "runner": os.environ.get("RUNNER_NAME", "")},
           "engine": os.environ.get("GITHUB_SHA", ""), "scenarios": {}}
    for scenario in a.scenarios.split(","):
        log(f"{spec['name']} {a.mode} {scenario}")
        reset(d)
        cache = work / f"{spec['name']}-{a.mode}-{scenario}-cache"
        shutil.rmtree(cache, ignore_errors=True)
        if scenario == "failing-test":
            (pick_file(d, spec, "add_dir") / "test_p061_fails.py").write_text(FAILING)
        cold = run(py, d, spec, [*det, f"--det-cache={cache}", *margs], f"{a.mode}-{scenario}-cold", work, a.timeout)
        what = apply(scenario, d, spec)
        warm = run(py, d, spec, [*det, f"--det-cache={cache}", *margs], f"{a.mode}-{scenario}-warm", work, a.timeout)
        truth = run(py, d, spec, [*det, *margs], f"{a.mode}-{scenario}-truth", work, a.timeout)
        diff = sorted(k for k in set(warm["outcomes"]) | set(truth["outcomes"])
                      if norm(warm["outcomes"].get(k)) != norm(truth["outcomes"].get(k)))
        wrong, flaky = [], []
        if diff:
            again = run(py, d, spec, [*det, *margs], f"{a.mode}-{scenario}-truth2", work, a.timeout)
            for k in diff:
                (wrong if norm(again["outcomes"].get(k)) == norm(truth["outcomes"].get(k)) else flaky).append(k)
        passing = sum(1 for v in truth["outcomes"].values() if norm(v) == "passed")
        res["scenarios"][scenario] = {
            "change": what, "tests": len(truth["outcomes"]), "passing": passing,
            "reused": warm["reused"], "ran": warm["ran"],
            "reused_share_of_passing": round(warm["reused"] / passing, 4) if passing else None,
            "wall_s": {"cold": cold["wall_s"], "warm": warm["wall_s"], "uncached": truth["wall_s"]},
            "rc": {"cold": cold["rc"], "warm": warm["rc"], "uncached": truth["rc"]},
            "not_reused": warm["not_reused"], "wrong": wrong, "flaky": flaky,
        }
        log(f"  => reused {warm['reused']} of {passing} passing; wrong {len(wrong)}, flaky {len(flaky)}")
        shutil.rmtree(cache, ignore_errors=True)
    reset(d)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1, sort_keys=True))
    bad = sum(len(s["wrong"]) for s in res["scenarios"].values())
    log(f"wrote {a.out}; wrong results: {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
