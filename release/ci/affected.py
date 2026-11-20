#!/usr/bin/env python3
"""Which tests a change needs, for the targeted runs on session branches (.github/workflows/targeted.yml).

    affected.py PATH...            (the changed paths, relative to the repository root)
    git diff --name-only BASE...HEAD | affected.py -

Prints JSON: {"python": "all" | [test files] | [], "node": "all" | [test files] | [], "why": {...}}.

The mapping, one rule per path, first match wins; ANY path no rule names selects everything (the fallback when unsure):

  docs/**, sessions/**, *.md (anywhere), **/results/**, LICENSE         nothing (no code)
  tests/test_*.py, tests/*/test_*.py                                   that Python test file
  tests/** (conftest, helpers, case tables, reference implementations)  every Python test
  python/**, crates/detpy-py/**, pyproject.toml                         every Python test
  node/test/*.test.js                                                  that Node test file
  node/** (shells, helpers, package files), crates/detpy-node/**         every Node test
  crates/detpy-core/**, Cargo.lock                                      every Python and every Node test
  release/engine/**, release/install_test.py, release/version.py,
  release/check_floor.py                                               tests/test_packaging.py
  everything else (.github/**, Cargo.toml, release/**, runner/**, harness/**, go/**, jvm/**, ...)
                                                                       every Python and every Node test

A targeted run is a convenience while working. It is never the gate: a pull request into claude/release-1 always
runs the complete sharded suite on every version (release-1.yml).
"""
from __future__ import annotations

import fnmatch
import json
import sys

NOTHING = ["docs/*", "sessions/*", "*.md", "*/results/*", "LICENSE"]


def classify(path: str):
    """(python, node, rule) for one path: each "all", a list of files, or []."""
    p = path.strip().lstrip("./")
    if any(fnmatch.fnmatch(p, g) for g in NOTHING):
        return [], [], "no code"
    if fnmatch.fnmatch(p, "tests/test_*.py") or fnmatch.fnmatch(p, "tests/*/test_*.py"):
        return [p], [], "a Python test file"
    if p.startswith("tests/"):
        return "all", [], "Python test support"
    if p.startswith(("python/", "crates/detpy-py/")) or p == "pyproject.toml":
        return "all", [], "the Python shell"
    if fnmatch.fnmatch(p, "node/test/*.test.js"):
        return [], [p[len("node/"):]], "a Node test file"
    if p.startswith(("node/", "crates/detpy-node/")):
        return [], "all", "the Node shells"
    if p.startswith("crates/detpy-core/") or p == "Cargo.lock":
        return "all", "all", "the shared core"
    if p.startswith("release/engine/") or p in ("release/install_test.py", "release/version.py", "release/check_floor.py"):
        return ["tests/test_packaging.py"], [], "the engine artifact"
    return "all", "all", "no rule (fallback: everything)"


def merge(a, b):
    if a == "all" or b == "all":
        return "all"
    return sorted(set(a) | set(b))


def affected(paths) -> dict:
    py, nd, why = [], [], {}
    for p in paths:
        if not p.strip():
            continue
        a, b, rule = classify(p)
        py, nd = merge(py, a), merge(nd, b)
        why[p.strip()] = rule
    return {"python": py, "node": nd, "why": why}


def main(argv) -> int:
    paths = sys.stdin.read().split("\n") if argv == ["-"] else argv
    print(json.dumps(affected(paths)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
