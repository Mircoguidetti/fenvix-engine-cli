#!/usr/bin/env python3
"""One entry point for every attack on the verifier, Python and Node.

The attacks had grown up one review at a time and lived in six places, so a change could be made and tested
without ever running most of them. This is the single door: ``python3 tests/attacks.py`` runs all of them and
exits non-zero if any fails.

    python3 tests/attacks.py                 # every attack file, Python and Node
    python3 tests/attacks.py --only python   # the Python half
    python3 tests/attacks.py --only node     # the Node half
    python3 tests/attacks.py --list          # what it would run, and nothing else

Nothing here replaces or weakens an existing file: each one is run exactly as it is, by its own runner. The
registry below is the list, and ``tests/test_attack_suite.py`` fails if an attack file exists in the tree that
this registry does not name — so a seventh place cannot quietly appear.

What counts as an attack: a file whose tests change one thing between two runs of a project and check that
`fenvix verify` does not answer IDENTICAL. The general rule's own file is in here too, because it is the one
that covers the channels nobody has thought of.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The Python attack files, with what each one attacks. Paths are relative to the repository root.
PYTHON_ATTACKS: dict[str, str] = {
    "tests/test_provable_general_rule.py":
        "the general rule: a channel the engine knows nothing about must be NOT PROVEN, never IDENTICAL",
    "tests/test_verify_inputs_attacks.py":
        "one case per channel a Python test can read its inputs through (docs/VERIFY-INPUTS.md)",
    "tests/test_review_r050_verifier.py": "review R-050's findings on the verifier",
    "tests/test_review_r051_verifier.py": "review R-051's findings on the verifier",
    "tests/test_review_r054_verifier.py": "review R-054's findings on the verifier",
    "tests/test_review_r055_verifier.py": "review R-055: the 16 channels that answered IDENTICAL on 688e4fe",
    "tests/test_verifier_truth.py":
        "the verifier tells the truth: runs differing in one source are divergent and name it",
    # The cache with proof, Python (Block 2). A wrong reuse is the same defect as a false IDENTICAL: the engine
    # states something it cannot know. Each file asserts its own precondition against uncached `pytest --det`.
    "tests/test_review_r023c.py": "review R-023c's wrong reuses through the loosened rules (E1-E8)",
    "tests/test_review_r052_pycache.py": "review R-052's wrong reuses in the Python cache (S1 S3 S5 C3 C5)",
    "tests/test_review_r053_pycache.py": "review R-053: conftest/__init__ prefix, real CPU and host name, posix.urandom",
    "tests/test_review_r056_pycache.py":
        "review R-056's 11 families of wrong reuse and wrong outcome in the Python cache (W1-W11)",
}

#: The Node attack files. Each is run by ``node --test``.
NODE_ATTACKS: dict[str, str] = {
    "node/test/verify-inputs-attacks.test.js":
        "one case per channel a Node test can read its inputs through (docs/VERIFY-INPUTS.md)",
    "node/test/verifier-inputs.test.js":
        "the Node shell's run inputs: a variable a test read with a different value is INPUT DIFFERS, never identical",
    "node/test/review-r055.test.js": "review R-055, the Node half",
    "node/test/review-p1-verifier.test.js": "reviewer p1's findings on the verifier, Node",
    "node/test/review-r050-node-recheck.test.js": "review R-050 re-checked on the Node shell",
}


def _missing(paths) -> list[str]:
    return [p for p in paths if not (ROOT / p).exists()]


def run_python(files: list[str], extra: list[str]) -> int:
    """Every Python attack file in one pytest process, in a fixed order, with the plugins the suites expect off."""
    if not files:
        return 0
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider", "-rfE",
           *extra, *files]
    print(f"\n=== python: {len(files)} attack files ===\n$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def run_node(files: list[str], extra: list[str]) -> int:
    """Every Node attack file, serially (the suites start real runs and must not share the machine)."""
    if not files:
        return 0
    cmd = ["node", "--test", "--test-concurrency=1", *extra, *files]
    print(f"\n=== node: {len(files)} attack files ===\n$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=("python", "node"), help="run one half only")
    ap.add_argument("--list", action="store_true", help="print what would run and exit")
    ap.add_argument("rest", nargs=argparse.REMAINDER,
                    help="arguments passed to the runner (after --), e.g. -- -x -k V1")
    args = ap.parse_args(argv)
    extra = [a for a in args.rest if a != "--"]

    py = list(PYTHON_ATTACKS) if args.only != "node" else []
    node = list(NODE_ATTACKS) if args.only != "python" else []

    if args.list:
        for group, reg in (("python", PYTHON_ATTACKS), ("node", NODE_ATTACKS)):
            if (group == "python" and py) or (group == "node" and node):
                print(f"{group}:")
                for f, why in reg.items():
                    print(f"  {f}\n      {why}")
        return 0

    gone = _missing(py + node)
    if gone:
        # a renamed or deleted attack file is a failure of this entry point, not something to skip over
        print(f"attacks: these files are in the registry but not in the tree: {', '.join(gone)}", file=sys.stderr)
        return 2

    t0 = time.time()
    rc_py = run_python(py, extra)
    rc_node = run_node(node, extra) if node and os.environ.get("ATTACKS_SKIP_NODE") != "1" else 0
    dt = time.time() - t0

    print(f"\n=== attacks: python rc={rc_py}, node rc={rc_node}, {dt:.0f}s "
          f"({len(py)} python + {len(node)} node files) ===")
    return rc_py or rc_node


if __name__ == "__main__":
    raise SystemExit(main())
