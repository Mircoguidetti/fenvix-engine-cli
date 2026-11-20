#!/usr/bin/env python3
"""Run the exam checks of some rows on this leg.

    python3 exam/run.py --rows PY-01,F-03 --work /tmp/exam --out exam-out/PY-01.json

The leg is described by EXAM_PLATFORM / EXAM_PYTHON / EXAM_NODE / EXAM_VARIANT; the install by EXAM_INSTALL_INFO
(written by exam/install.sh) and EXAM_WHEEL. Exit code 0 always: the verdicts are in the JSON (the aggregate decides).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lib  # noqa: E402
import probes  # noqa: E402
import rows_f  # noqa: E402
import rows_js  # noqa: E402
import rows_py  # noqa: E402

ROWS = {
    "PY-01": rows_py.PY_01, "PY-02": rows_py.PY_02, "PY-03": rows_py.PY_03, "PY-04": rows_py.PY_04,
    "PY-05": rows_py.PY_05, "PY-06": rows_py.PY_06, "PY-07": rows_py.PY_07, "PY-08": rows_py.PY_08,
    "JS-01": rows_js.JS_01, "JS-02": rows_js.JS_02, "JS-03": rows_js.JS_03, "JS-04": rows_js.JS_04,
    "JS-05": rows_js.JS_05, "JS-06": rows_js.JS_06, "JS-07": rows_js.JS_07, "JS-08": rows_js.JS_08,
    "JS-09": rows_js.JS_09,
    "F-01": rows_f.F_01, "F-02": rows_f.F_02, "F-03": rows_f.F_03, "F-05": rows_f.F_05, "F-06": rows_f.F_06,
    "F-09": rows_f.F_09, "F-10": rows_f.F_10, "F-18": rows_f.F_18,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="", help="comma list of check-id prefixes to run (debugging)")
    ap.add_argument("--no-probes", action="store_true")
    a = ap.parse_args()
    rows = [r.strip() for r in a.rows.split(",") if r.strip()]
    ctx = lib.Ctx(a.work, rows)
    if a.only:
        pre = tuple(a.only.split(","))
        orig = ctx.run_check

        def filt(cid, expected, fn, gaps=None):
            if cid.startswith(pre):
                return orig(cid, expected, fn, gaps)
        ctx.run_check = filt
    t0 = time.time()
    for r in rows:
        print(f"######## {r} on {ctx.leg}", flush=True)
        ROWS[r](ctx)
        if not a.no_probes:
            probes.run_row_probes(ctx, r)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump({"rows": rows, "leg": ctx.leg, "install": ctx.install, "seconds": round(time.time() - t0),
                   "run_id": os.environ.get("GITHUB_RUN_ID"), "job": os.environ.get("EXAM_JOB_NAME"),
                   "runner": {"os": os.environ.get("RUNNER_OS"), "arch": os.environ.get("RUNNER_ARCH"),
                              "image": os.environ.get("ImageOS"), "image_version": os.environ.get("ImageVersion")},
                   "results": ctx.results}, fh, indent=1)
    n = len(ctx.results)
    print(f"{sum(r['ok'] for r in ctx.results)}/{n} checks passed on {ctx.leg}")


if __name__ == "__main__":
    main()
