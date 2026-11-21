#!/usr/bin/env python3
"""PY-07 measurement: what --det-threads / --det-async move, and what they cost.

The row is judged on two numbers, so this harness produces exactly those two, per suite:

* **movement**: how many tests go from NOT PROVEN to IDENTICAL because the schedulers control what was only
  observed before. Each mode runs the suite ``--runs`` times and the runs of that mode are compared with
  ``fenvix verify --json``; the movement is the per-test status transition between the two modes. Transitions the
  wrong way (a test that was IDENTICAL and is no longer) are counted and named too: they are the number that
  decides whether this is shippable, not a footnote.
* **slowdown**: wall time of the suite per mode (median and worst of ``--runs`` rounds).

Modes:

  ``plain``  pytest as the project runs it (no engine), for the cost of --det itself
  ``det``    ``--det``: Level 0, where a test that starts a thread is NOT PROVEN
  ``l1``     ``--det --det-threads --det-async``: Level 1 on top, calm seed 0

The rounds are interleaved (round 1 of every mode, then round 2, ...) so runner load hits every mode alike
instead of landing on whichever mode happens to run last.

Usage:
    measure.py --suite DIR --name NAME --out DIR [--runs 3] [--args "tests -p no:cacheprovider"]
    measure.py --aggregate DIR            # REPORT table over every <name>.json in DIR
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import statistics
import subprocess
import sys
import time
from pathlib import Path

MODES = {
    "plain": [],
    "det": ["--det"],
    "l1": ["--det", "--det-threads", "--det-async"],
}
# `fenvix verify --json` gives a test one of these (verify.rs `Status`, kebab-case): stable, diverged, missing,
# input-differs, not-proven. "stable" means the same fingerprint in every run with nothing uncontrolled, which is
# what the report prints as IDENTICAL: it is the only one that is a proof. Everything else is not.
PROVEN = "stable"


def run_once(suite: Path, args: list, mode: str, trace: Path | None, timeout: float) -> dict:
    """One run of the suite in one mode. Returns wall time, return code and whether it timed out."""
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args, *MODES[mode]]
    if trace is not None and mode != "plain":
        cmd.append(f"--det-trace={trace}")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, cwd=suite, env=env, capture_output=True, text=True, timeout=timeout)
        rc, out, timed_out = p.returncode, (p.stdout or "") + (p.stderr or ""), False
    except subprocess.TimeoutExpired as e:
        rc, out, timed_out = -1, (e.stdout or "") if isinstance(e.stdout, str) else "", True
    return {"seconds": time.monotonic() - t0, "rc": rc, "timed_out": timed_out, "tail": out.strip()[-2000:]}


def verify(traces: list, cwd: Path) -> dict:
    """``fenvix verify --json`` over the traces of one mode."""
    cmd = ["fenvix", "verify", "--json", *[str(t) for t in traces]]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    try:
        return {"rc": p.returncode, "report": json.loads(p.stdout)}
    except Exception:
        return {"rc": p.returncode, "report": None, "error": (p.stdout + p.stderr).strip()[-2000:]}


def statuses(report: dict | None) -> dict:
    if not report:
        return {}
    return {t["nodeid"]: t.get("status") for t in report.get("tests") or []}


def outcomes(report: dict | None) -> dict:
    """nodeid -> the set of outcomes seen across the runs of that mode."""
    if not report:
        return {}
    return {t["nodeid"]: sorted(set(t.get("outcomes") or [])) for t in report.get("tests") or []}


def movement(det: dict, l1: dict, det_out: dict, l1_out: dict) -> dict:
    """Per-test status transition from --det to Level 1, both directions."""
    moved, regressed, unchanged, broken = [], [], 0, []
    for nodeid, before in sorted(det.items()):
        after = l1.get(nodeid)
        if after is None:
            continue  # not in both modes: nothing to compare
        if before != PROVEN and after == PROVEN:
            moved.append({"nodeid": nodeid, "from": before, "to": after})
        elif before == PROVEN and after != PROVEN:
            regressed.append({"nodeid": nodeid, "from": before, "to": after})
        else:
            unchanged += 1
        # a test the schedulers break: the same outcome in every --det run, a different one in every L1 run
        b, a = det_out.get(nodeid) or [], l1_out.get(nodeid) or []
        if b and a and len(b) == 1 and len(a) == 1 and b != a:
            broken.append({"nodeid": nodeid, "det": b[0], "l1": a[0]})
    common = len(set(det) & set(l1))
    # every transition by name, so a move to "diverged" cannot hide inside "not proven any more"
    import collections

    transitions = collections.Counter(f"{b}->{l1[n]}" for n, b in det.items() if n in l1)
    return {
        "transitions": dict(transitions),
        "tests_compared": common,
        "moved_to_proven": moved,
        "n_moved": len(moved),
        "lost_proven": regressed,
        "n_lost": len(regressed),
        "unchanged": unchanged,
        "broken_by_l1": broken,
        "n_broken": len(broken),
        "share_proven_det": round(sum(1 for s in det.values() if s == PROVEN) / len(det), 4) if det else None,
        "share_proven_l1": round(sum(1 for s in l1.values() if s == PROVEN) / len(l1), 4) if l1 else None,
    }


def cost(times: dict) -> dict:
    """Wall time per mode, and the slowdown of each engine mode over plain and of L1 over --det."""
    med = {m: (statistics.median(v) if v else None) for m, v in times.items()}
    worst = {m: (max(v) if v else None) for m, v in times.items()}

    def ratio(a, b):
        return round(a / b - 1.0, 4) if (a and b) else None

    return {
        "median_seconds": {m: (round(v, 3) if v else None) for m, v in med.items()},
        "worst_seconds": {m: (round(v, 3) if v else None) for m, v in worst.items()},
        "slowdown_det_over_plain": ratio(med.get("det"), med.get("plain")),
        "slowdown_l1_over_plain": ratio(med.get("l1"), med.get("plain")),
        "slowdown_l1_over_det": ratio(med.get("l1"), med.get("det")),
        "worst_slowdown_l1_over_det": ratio(worst.get("l1"), worst.get("det")),
    }


def measure(suite: Path, name: str, args: list, runs: int, out: Path, timeout: float) -> dict:
    work = out / f"{name}.traces"
    work.mkdir(parents=True, exist_ok=True)
    times = {m: [] for m in MODES}
    runs_log = {m: [] for m in MODES}
    traces = {m: [] for m in MODES}
    # One engine run first, discarded. The first --det run of an environment compiles the standard library and
    # site-packages under PYTHONHASHSEED=0 into a cache shared by every later run, which cost 5.4 s of a 5.4 s run
    # when this was MEASURED on anyio: whichever mode happens to run first would otherwise carry that one-off and
    # the slowdown would be a fiction. Not counted, not verified.
    warmup = run_once(suite, args, "det", work / "warmup.jsonl", timeout)
    for r in range(runs):  # interleaved: round r of every mode before round r+1
        for mode in MODES:
            trace = work / f"{mode}-{r}.jsonl" if mode != "plain" else None
            res = run_once(suite, args, mode, trace, timeout)
            runs_log[mode].append(res)
            if res["timed_out"]:
                print(f"  !! {name} {mode} round {r}: TIMED OUT after {timeout}s (reported, not retried)",
                      file=sys.stderr)
                continue
            times[mode].append(res["seconds"])
            if trace is not None and trace.exists():
                traces[mode].append(trace)
    # `fenvix verify` compares two or more runs: with one round there is nothing to compare and it answers rc 2.
    ver = {m: (verify(traces[m], suite) if len(traces[m]) >= 2 else
               {"rc": None, "report": None, "error": f"{len(traces[m])} trace(s): verify needs two or more"})
           for m in ("det", "l1")}
    det_s, l1_s = statuses(ver["det"].get("report")), statuses(ver["l1"].get("report"))
    return {
        "name": name,
        "suite": str(suite),
        "warmup": {"seconds": round(warmup["seconds"], 3), "rc": warmup["rc"], "timed_out": warmup["timed_out"]},
        "args": args,
        "runs": runs,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cost": cost(times),
        "verify": {m: {"rc": ver[m]["rc"], "summary": (ver[m].get("report") or {}).get("summary")}
                   for m in ver},
        "movement": movement(det_s, l1_s, outcomes(ver["det"].get("report")), outcomes(ver["l1"].get("report"))),
        "runs_log": runs_log,
    }


def aggregate(d: Path) -> None:
    rows = []
    for f in sorted(d.glob("*.json")):
        if f.name == "REPORT.json":
            continue
        try:
            rows.append(json.loads(f.read_text()))
        except Exception as e:
            print(f"skip {f}: {e}", file=sys.stderr)
    print(f"{'suite':22} {'tests':>6} {'proven --det':>13} {'proven L1':>10} {'moved':>6} {'lost':>5} "
          f"{'broken':>7} {'L1/det':>8} {'worst':>8}")
    tot_moved = tot_lost = tot_broken = 0
    for r in rows:
        m, c = r["movement"], r["cost"]
        sd = c["slowdown_l1_over_det"]
        wd = c["worst_slowdown_l1_over_det"]
        tot_moved += m["n_moved"]
        tot_lost += m["n_lost"]
        tot_broken += m["n_broken"]
        print(f"{r['name'][:22]:22} {m['tests_compared']:>6} {str(m['share_proven_det']):>13} "
              f"{str(m['share_proven_l1']):>10} {m['n_moved']:>6} {m['n_lost']:>5} {m['n_broken']:>7} "
              f"{(f'{sd:+.1%}' if sd is not None else 'n/a'):>8} {(f'{wd:+.1%}' if wd is not None else 'n/a'):>8}")
    print(f"\nMEASURED: {tot_moved} tests moved to IDENTICAL, {tot_lost} lost it, {tot_broken} broken by L1, "
          f"over {len(rows)} suites.")
    (d / "REPORT.json").write_text(json.dumps(rows, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", type=Path)
    ap.add_argument("--name")
    ap.add_argument("--args", default="tests", help="pytest arguments of the suite (shell-quoted)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("harness/l1_trunk/results"))
    ap.add_argument("--timeout", type=float, default=1800.0, help="real seconds per run; a run that reaches it is "
                                                                 "reported as a hang, never retried with more time")
    ap.add_argument("--aggregate", type=Path)
    a = ap.parse_args()
    if a.aggregate:
        aggregate(a.aggregate)
        return 0
    if not (a.suite and a.name):
        ap.error("--suite and --name are required (or --aggregate)")
    a.out.mkdir(parents=True, exist_ok=True)
    res = measure(a.suite.resolve(), a.name, shlex.split(a.args), a.runs, a.out.resolve(), a.timeout)
    (a.out / f"{a.name}.json").write_text(json.dumps(res, indent=1))
    m, c = res["movement"], res["cost"]
    print(f"{a.name}: {m['n_moved']} tests moved to IDENTICAL, {m['n_lost']} lost it, {m['n_broken']} broken; "
          f"L1 over --det {c['slowdown_l1_over_det']}, worst {c['worst_slowdown_l1_over_det']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
