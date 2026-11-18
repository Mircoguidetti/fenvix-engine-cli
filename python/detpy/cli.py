"""Command line: ``detpy verify``, ``detpy backends``, ``detpy repro``, ``detpy explore``, ``detpy replay``."""

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

    def common(sp):
        sp.add_argument("--out", default=".detpy/repro", help="where bundles are written (default: .detpy/repro)")
        sp.add_argument("--confirm", type=int, default=10, help="replays that must all fail with one fingerprint")
        sp.add_argument("--max-runs", type=int, default=400, help="pytest runs allowed per test for search and minimisation")
        sp.add_argument("--timeout", type=float, default=1800, help="seconds per pytest run")
        sp.add_argument("--python", default=sys.executable, help="interpreter that runs pytest")
        sp.add_argument("--json", action="store_true", help="print the result as JSON")

    r = sub.add_parser("repro", help="find, minimise and bundle a failing order for one test",
                       description="Extra pytest arguments go after `--`.")
    r.add_argument("test", help="test id, as pytest prints it")
    r.add_argument("--seeds", type=int, default=50, help="seeds searched after the fixed order")
    r.add_argument("--seed", default=None, help="skip the search: the configuration known to fail ('fixed' or N)")
    common(r)
    e = sub.add_parser("explore", help="nightly exploration: seeds within a time budget, one bundle per failure",
                       description="Extra pytest arguments go after `--`.")
    e.add_argument("--budget", type=float, required=True, help="minutes")
    e.add_argument("--max-seeds", type=int, default=1000)
    e.add_argument("--targets", default=None, help="file of test ids: bundle only these")
    e.add_argument("--no-repro", action="store_true", help="explore only, no minimisation or bundles")
    common(e)
    rp = sub.add_parser("replay", help="replay a bundle and check it fails with the same fingerprint")
    rp.add_argument("bundle")
    rp.add_argument("--runs", type=int, default=10)
    rp.add_argument("--python", default=sys.executable)

    argv = list(sys.argv[1:] if argv is None else argv)
    extra: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, extra = argv[:i], argv[i + 1:]
    args = p.parse_args(argv)
    args.pytest_args = extra

    if args.cmd in ("repro", "explore", "replay"):
        from . import repro as _repro
        from pathlib import Path

        if args.cmd == "repro":
            return _repro.main_repro(args)
        if args.cmd == "explore":
            return _repro.main_explore(args)
        res = _repro.replay(Path(args.bundle), args.runs, args.python)
        print(json.dumps(res, indent=2))
        return 0 if res["fails"] == res["runs"] and res["identical_fingerprint"] else 1

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
