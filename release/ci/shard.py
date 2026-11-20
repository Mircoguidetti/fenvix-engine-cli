#!/usr/bin/env python3
"""Shards of the Python suite for the trunk gate (.github/workflows/release-1.yml), and the checks that keep them
equal to the full serial suite.

    shard.py files  --shard K --of N           the test files of shard K (0 = the serial shard), one per line
    shard.py check  --full FULL.txt --shard-collected S0.txt S1.txt ... [--junit S0.xml ...]
    shard.py compare --a SERIAL.xml --b S0.xml S1.xml ...

Rules (the founder's conditions for a faster gate that is not a weaker one):
* A shard is a set of whole test files; a file is never split, so the tests of one file keep pytest's order and run
  in one process, as in the serial suite.
* Shard 0 is the serial shard: the files listed in release/ci/serial-files.txt (tests that write into the
  interpreter's own site-packages or host files, the reason the gate ran serially), in collection order, alone.
  The list is explicit; nothing is guessed.
* The other files go to shards 1..N-1 by measured duration (release/ci/durations.json, seconds per file from a full
  serial run; an unknown file costs the median), longest first onto the least loaded shard; ties by name. The plan
  depends only on the file list and that table: every Python version gets the same shards.
* `check` fails unless the union of the shards' collected test ids equals the full collection exactly (no id
  missing, none extra, none in two shards), and, with --junit, unless every collected id of every shard has a result.
* `compare` fails unless the pass / fail / skip / xfail / error sets of a serial run and of the sharded run are equal.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SERIAL = os.path.join(HERE, "serial-files.txt")
DURATIONS = os.path.join(HERE, "durations.json")


def test_files(root: str = ROOT) -> list[str]:
    """Every test module pytest collects from tests/ (test_*.py, recursively), as paths relative to the root."""
    out = []
    for d, dirs, files in os.walk(os.path.join(root, "tests")):
        dirs[:] = sorted(x for x in dirs if not x.startswith((".", "__")))
        for f in sorted(files):
            if f.startswith("test_") and f.endswith(".py"):
                out.append(os.path.relpath(os.path.join(d, f), root))
    return sorted(out)


def serial_files() -> list[str]:
    lines = [ln.split("#", 1)[0].strip() for ln in open(SERIAL)]
    return [ln for ln in lines if ln]


def plan(n: int, root: str = ROOT) -> list[list[str]]:
    if n < 2:
        raise SystemExit("shard: --of must be at least 2 (the serial shard and one more)")
    files = test_files(root)
    serial = serial_files()
    missing = [f for f in serial if f not in files]
    if missing:
        raise SystemExit(f"shard: serial-files.txt names files that do not exist: {missing}")
    dur = json.load(open(DURATIONS)) if os.path.exists(DURATIONS) else {}
    known = [v for v in dur.values() if isinstance(v, (int, float))]
    if not known:  # no measurement yet: a file's size stands for its cost
        dur = {f: os.path.getsize(os.path.join(root, f)) / 1000.0 for f in files}
        known = list(dur.values())
    default = statistics.median(known)
    rest = [f for f in files if f not in serial]
    rest.sort(key=lambda f: (-float(dur.get(f, default)), f))
    shards: list[list[str]] = [list(serial)] + [[] for _ in range(n - 1)]
    load = [0.0] * n
    for f in rest:
        k = min(range(1, n), key=lambda i: (load[i], i))
        shards[k].append(f)
        load[k] += float(dur.get(f, default))
    return [sorted(s) if i else s for i, s in enumerate(shards)]


def read_ids(path: str) -> list[str]:
    """Test ids of `pytest --collect-only -q` output (lines with '::')."""
    return [ln.strip() for ln in open(path, encoding="utf-8", errors="replace") if "::" in ln and not ln.startswith(" ")]


def junit_results(paths) -> dict[str, str]:
    """(file-ish classname + name) -> outcome, from JUnit XML files."""
    out: dict[str, str] = {}
    for p in paths:
        for tc in ET.parse(p).getroot().iter("testcase"):
            key = f"{tc.get('classname')}::{tc.get('name')}"
            kinds = [c.tag for c in tc]
            if "failure" in kinds:
                o = "failed"
            elif "error" in kinds:
                o = "error"
            elif "skipped" in kinds:
                sk = next(c for c in tc if c.tag == "skipped")
                o = "xfailed" if (sk.get("type") or "").endswith("xfail") else "skipped"
            else:
                o = "passed"
            if key in out:
                o = out[key] if out[key] != "passed" else o  # setup + call + teardown entries of one test
            out[key] = o
    return out


def cmd_check(a) -> int:
    full = read_ids(a.full)
    problems = []
    if len(set(full)) != len(full):
        problems.append(f"the full collection has duplicate ids: {len(full) - len(set(full))}")
    seen: dict[str, str] = {}
    for p in a.shard_collected:
        for i in read_ids(p):
            if i in seen:
                problems.append(f"{i} collected in two shards: {seen[i]} and {p}")
            seen[i] = p
    missing = sorted(set(full) - set(seen))
    extra = sorted(set(seen) - set(full))
    if missing:
        problems.append(f"{len(missing)} ids of the full collection in no shard, e.g. {missing[:10]}")
    if extra:
        problems.append(f"{len(extra)} ids in a shard but not in the full collection, e.g. {extra[:10]}")
    if a.junit:
        n_results = len(junit_results(a.junit))
        if n_results < len(seen) - a.allow_uncounted:
            problems.append(f"{len(seen)} ids collected by the shards but only {n_results} results in their JUnit files")
    print(f"full collection {len(full)} ids; shards {len(a.shard_collected)}, union {len(seen)} ids")
    for p in problems:
        print("SHARD CHECK FAILED:", p)
    return 1 if problems else 0


def cmd_durations(a) -> int:
    """Seconds per test file, summed from JUnit files (the measured table release/ci/durations.json holds)."""
    per: dict[str, float] = {}
    for p in a.junit:
        for tc in ET.parse(p).getroot().iter("testcase"):
            cls = tc.get("classname") or ""
            parts = cls.split(".")
            f = None
            for k in range(len(parts), 0, -1):  # tests.review_r032.test_x.Class -> tests/review_r032/test_x.py
                cand = "/".join(parts[:k]) + ".py"
                if os.path.exists(os.path.join(ROOT, cand)):
                    f = cand
                    break
            if f:
                per[f] = per.get(f, 0.0) + float(tc.get("time") or 0)
    print(json.dumps({k: round(v, 1) for k, v in sorted(per.items())}, indent=1))
    return 0


def cmd_compare(a) -> int:
    ra, rb = junit_results(a.a), junit_results(a.b)
    diff = sorted(k for k in set(ra) | set(rb) if ra.get(k) != rb.get(k))
    for kind in ("passed", "failed", "error", "skipped", "xfailed"):
        print(f"{kind:8} serial {sum(v == kind for v in ra.values()):5}  sharded {sum(v == kind for v in rb.values()):5}")
    for k in diff[:50]:
        print(f"DIFFERENT: {k}: serial={ra.get(k)} sharded={rb.get(k)}")
    print("IDENTICAL" if not diff else f"{len(diff)} tests differ")
    return 1 if diff else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("files")
    f.add_argument("--shard", type=int, required=True)
    f.add_argument("--of", type=int, required=True)
    p = sub.add_parser("plan")
    p.add_argument("--of", type=int, required=True)
    c = sub.add_parser("check")
    c.add_argument("--full", required=True)
    c.add_argument("--shard-collected", nargs="+", required=True)
    c.add_argument("--junit", nargs="*")
    c.add_argument("--allow-uncounted", type=int, default=0)
    d = sub.add_parser("durations")
    d.add_argument("--junit", nargs="+", required=True)
    m = sub.add_parser("compare")
    m.add_argument("--a", nargs="+", required=True)
    m.add_argument("--b", nargs="+", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "files":
        print("\n".join(plan(a.of)[a.shard]))
        return 0
    if a.cmd == "plan":
        dur = json.load(open(DURATIONS)) if os.path.exists(DURATIONS) else {}
        for i, s in enumerate(plan(a.of)):
            print(f"shard {i}: {len(s)} files, {sum(float(dur.get(x, 0)) for x in s):.0f} s measured")
        return 0
    if a.cmd == "check":
        return cmd_check(a)
    if a.cmd == "durations":
        return cmd_durations(a)
    return cmd_compare(a)


if __name__ == "__main__":
    sys.exit(main())
