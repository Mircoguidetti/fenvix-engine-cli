#!/usr/bin/env python3
"""Clone and install a suite of the L1 thread corpus (``threads-corpus.json``), pinned by commit.

The corpus is the one the L1 study measured on, carried over unchanged, so the numbers of this row can be
compared with the ones the study reported instead of standing alone.

    suites.py --suite anyio --dir /tmp/suites     # clone at the pinned sha and install it with its extras
    suites.py --suite anyio --print-args          # the pytest arguments of that suite, for measure.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "threads-corpus.json"


def suites() -> dict:
    return {s["name"]: s for s in json.loads(CORPUS.read_text())["suites"]}


def run(cmd: list, **kw) -> None:
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def prepare(spec: dict, root: Path) -> Path:
    d = root / spec["name"]
    root.mkdir(parents=True, exist_ok=True)
    if not d.exists():
        # a shallow clone cannot be checked out at an arbitrary sha: fetch that commit by name
        run(["git", "init", "-q", str(d)])
        run(["git", "remote", "add", "origin", spec["url"]], cwd=d)
        run(["git", "fetch", "-q", "--depth", "1", "origin", spec["sha"]], cwd=d)
        run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=d)
    pkgs = ["pytest", *spec.get("install", [])]
    run([sys.executable, "-m", "pip", "install", "-q", "-e", ".", *pkgs], cwd=d)
    return d


def args_of(spec: dict) -> list:
    """What to hand pytest: the suite's own arguments, plus the ones the corpus records for a full-suite run."""
    a = list(spec.get("pytest_args") or []) + list(spec.get("suite_args") or [])
    # always name a path, so the run does not depend on what pytest collects from the root
    if not any(not x.startswith("-") for x in a):
        a = ["tests", *a]
    return a


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite")
    ap.add_argument("--dir", type=Path, default=Path("/tmp/suites"))
    ap.add_argument("--print-args", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    all_s = suites()
    if a.list:
        for n, s in sorted(all_s.items()):
            print(f"{n:20} {s.get('set',''):14} {s['sha']}")
        return 0
    if not a.suite:
        ap.error("--suite is required (or --list)")
    spec = all_s.get(a.suite)
    if spec is None:
        print(f"unknown suite {a.suite!r}; known: {', '.join(sorted(all_s))}", file=sys.stderr)
        return 2
    if a.print_args:
        print(" ".join(args_of(spec)))
        return 0
    prepare(spec, a.dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
