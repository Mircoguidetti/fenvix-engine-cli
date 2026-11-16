"""Command line: ``detpy verify TRACE TRACE [...]`` and ``detpy backends``."""

from __future__ import annotations

import argparse
import json
import sys

from . import _core


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="detpy", description="deterministic Python test execution (Level 0)")
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="compare the fingerprints of several runs")
    v.add_argument("traces", nargs="+")
    v.add_argument("--json", action="store_true", help="print the full report as JSON")
    v.add_argument("--show-stable", action="store_true")
    sub.add_parser("backends", help="list interception backends and their capabilities")
    args = p.parse_args(argv)

    if args.cmd == "backends":
        print(json.dumps(json.loads(_core.backends()), indent=2))
        return 0
    if len(args.traces) < 2:
        p.error("verify needs at least two traces")
    if args.json:
        print(_core.verify(args.traces))
        report = json.loads(_core.verify(args.traces))
    else:
        print(_core.verify_text(args.traces, args.show_stable), end="")
        report = json.loads(_core.verify(args.traces))
    s = report["summary"]
    return 0 if s["diverged"] == 0 and s["missing"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
