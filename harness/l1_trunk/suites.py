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


# What a suite's own tests need, which the corpus did not record for every suite: with anyio's empty install list
# almost every test errored at import and the whole measurement finished in 5 seconds looking like "no movement".
# The anyio list is the one the frozen exam uses for the same project (exam/projects.py).
TEST_REQUIREMENTS = {
    "anyio": ["trustme", "exceptiongroup", "hypothesis", "psutil", "trio", "blockbuster", "truststore"],
    "requests": ["pytest-httpbin", "trustme"],
}


def suites() -> dict:
    out = {}
    for s in json.loads(CORPUS.read_text())["suites"]:
        s = dict(s)
        extra = [r for r in TEST_REQUIREMENTS.get(s["name"], []) if r not in (s.get("install") or [])]
        s["install"] = list(s.get("install") or []) + extra
        out[s["name"]] = s
    return out


def run(cmd: list, **kw) -> None:
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def prepare(spec: dict, root: Path) -> Path:
    d = root / spec["name"]
    root.mkdir(parents=True, exist_ok=True)
    if not d.exists():
        # The corpus pins abbreviated shas, and a server will not serve `fetch <abbrev>` (nor an exact sha that is
        # not a ref tip on some hosts). So: a blobless clone of the refs, which is quick, then check the sha out
        # locally, where an abbreviation resolves. Blobs of the checked-out tree are fetched on demand.
        run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", spec["url"], str(d)])
        run(["git", "checkout", "-q", spec["sha"]], cwd=d)
    pkgs = ["pytest", *spec.get("install", [])]
    run([sys.executable, "-m", "pip", "install", "-q", "-e", ".", *pkgs], cwd=d)
    # Prove it collects before anything is measured. A suite whose tests error at import still "runs", very fast,
    # and every mode then looks identical and unmoved: a wrong number that reads like a real one.
    p = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                        *args_of(spec)], cwd=d, capture_output=True, text=True)
    tail = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-15:]
    if p.returncode != 0:
        raise SystemExit(f"{spec['name']}: collection failed (rc {p.returncode}), so nothing can be measured:\n"
                         + "\n".join(tail))
    print(f"{spec['name']}: collection ok -> {tail[-1] if tail else '?'}", flush=True)
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
