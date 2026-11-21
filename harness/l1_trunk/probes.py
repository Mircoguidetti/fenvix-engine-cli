#!/usr/bin/env python3
"""The PY-07 conditions of the frozen exam, run against this branch directly.

The exam at ``claude/exam`` is the authority and is not changed by this row; it installs a released engine
artifact, so it cannot be pointed at a working branch. This script asks the same questions of the branch, with
the probe bodies copied verbatim from ``exam/rows_py.py``, so a failure shows up here before the exam sees it.

  options        ``--det-threads`` and ``--det-async`` exist in ``fenvix python --help``
  probe-stable   8 runs of a thread race and an executor race under ``--det --det-threads --det-async``: one
                 outcome and one fingerprint each. INCONCLUSIVE (not a pass) unless the race shows at least two
                 outcomes in 8 plain runs: a race that did not happen proves nothing about controlling it.
  verify-honest  without the L1 options, 8 runs whose outcomes differed must make ``fenvix verify`` exit nonzero
                 (never "identical"). INCONCLUSIVE when the 8 runs agree, as in the exam.

A hang is reported, never retried with a longer budget.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# verbatim from exam/rows_py.py (claude/exam)
THREAD_RACE = '''
import threading, sys


def test_thread_race():
    sys.setswitchinterval(1e-6)
    n = [0]

    def work():
        for _ in range(200000):
            v = n[0]
            n[0] = v + 1
    ts = [threading.Thread(target=work) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert n[0] == 400000
'''

EXECUTOR_RACE = '''
import asyncio, time


def test_executor_race():
    order = []

    def job(name, spin):
        x = 0
        for i in range(spin):
            x += i
        order.append(name)

    async def main():
        loop = asyncio.get_running_loop()
        await asyncio.gather(loop.run_in_executor(None, job, "a", 200000), loop.run_in_executor(None, job, "b", 200000))
    asyncio.run(main())
    assert order == ["a", "b"]
'''

L1 = ["--det", "--det-threads", "--det-async"]
TIMEOUT = 300.0


def pytest_run(d: Path, rel: str, extra: list, trace: Path | None) -> dict:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *extra, rel]
    if trace is not None:
        cmd.append(f"--det-trace={trace}")
    try:
        p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=TIMEOUT)
        return {"rc": p.returncode, "hang": False}
    except subprocess.TimeoutExpired:
        return {"rc": None, "hang": True}


def outcome_of(trace: Path) -> tuple:
    """(outcome, fingerprint) of the single test in a trace."""
    try:
        for line in trace.read_text().splitlines():
            r = json.loads(line)
            if r.get("type") == "test":
                return (r.get("outcome"), r.get("fingerprint"))
    except Exception:
        pass
    return (None, None)


def probe_stable(work: Path) -> dict:
    res, ok, notes = {}, True, []
    for name, body in (("thread_race", THREAD_RACE), ("executor_race", EXECUTOR_RACE)):
        d = work / f"stable-{name}"
        d.mkdir(parents=True, exist_ok=True)
        rel = f"test_{name}.py"
        (d / rel).write_text(body)
        plain, det, hangs = set(), set(), 0
        for i in range(8):
            r = pytest_run(d, rel, [], None)
            hangs += bool(r["hang"])
            plain.add(r["rc"])
            t = d / f"l1-{i}.jsonl"
            r = pytest_run(d, rel, L1, t)
            hangs += bool(r["hang"])
            det.add(outcome_of(t))
        exercised = len(plain) >= 2
        stable = len(det) == 1
        res[name] = {"plain_distinct": len(plain), "l1_distinct": len(det), "exercised": exercised,
                     "stable": stable, "hangs": hangs, "l1_outcomes": sorted(str(x) for x in det)}
        if hangs:
            notes.append(f"{name}: {hangs} run(s) reached the {TIMEOUT:.0f}s budget (reported as a hang)")
        if not exercised:
            notes.append(f"{name}: INCONCLUSIVE, the race did not show in 8 plain runs on this host")
        ok = ok and exercised and stable and not hangs
    return {"check": "PY-07.probe-stable", "ok": ok, "detail": res, "notes": notes}


def verify_honest(work: Path) -> dict:
    d = work / "honest"
    d.mkdir(parents=True, exist_ok=True)
    rel = "test_thread_race.py"
    (d / rel).write_text(THREAD_RACE)
    traces, outs, hangs = [], set(), 0
    for i in range(8):
        t = d / f"hon-{i}.jsonl"
        r = pytest_run(d, rel, ["--det"], t)
        hangs += bool(r["hang"])
        traces.append(t)
        outs.add(outcome_of(t))
    if len(outs) == 1:
        return {"check": "PY-07.verify-honest", "ok": False, "inconclusive": True,
                "detail": {"distinct_outcomes": 1, "hangs": hangs},
                "notes": ["INCONCLUSIVE: one outcome over 8 --det runs, the race was not exercised: nothing to "
                          "judge. The same question is asked of a real suite by measure.py."]}
    p = subprocess.run(["fenvix", "verify", *[str(t) for t in traces]], cwd=d, capture_output=True, text=True)
    return {"check": "PY-07.verify-honest", "ok": p.returncode != 0,
            "detail": {"distinct_outcomes": len(outs), "verify_rc": p.returncode, "hangs": hangs,
                       "last_line": (p.stdout or "").strip().splitlines()[-1:] or [""]}}


def options() -> dict:
    p = subprocess.run(["fenvix", "python", "--help"], capture_output=True, text=True)
    have = {o: (o in p.stdout) for o in ("--det-threads", "--det-async")}
    return {"check": "PY-07.options", "ok": all(have.values()), "detail": have}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        checks = [options(), probe_stable(work), verify_honest(work)]
    report = {"python": sys.version.split()[0], "seconds": round(time.monotonic() - t0, 1), "checks": checks}
    text = json.dumps(report, indent=1)
    if a.out:
        a.out.write_text(text)
    print(text)
    bad = [c["check"] for c in checks if not c["ok"]]
    # An INCONCLUSIVE probe-stable / verify-honest is a property of the host, not of the engine: it is reported
    # and does not fail the job, because declaring it green would be a green on a doubt and failing it would hide
    # the real result. The exam is the authority on the verdict.
    hard = [c["check"] for c in checks if not c["ok"] and not c.get("inconclusive")
            and not any("INCONCLUSIVE" in n for n in c.get("notes") or [])]
    print(f"\nnot ok: {bad or 'none'}; failing this job: {hard or 'none'}", file=sys.stderr)
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
