#!/usr/bin/env python3
"""After a measure.py round: write the committed evidence of one repository's out dir (P2 spec, "What is committed").

  tests-S<i>.jsonl.gz, tests-P<i>w<n>.jsonl.gz   per-test extract of every serial and parallel trace (extract.py)
  tests-plain<i>.jsonl.gz                       per-test outcomes of the plain run (measure.py runner_outcomes)
  verify*.json.gz                               every verify report (per-test status)
  runs.log.gz                                   the raw runs.log, gzipped (the raw log is not committed)

Idempotent: an extract is rewritten only when its trace is newer. Traces and state-* dirs stay uncommitted.
Usage: post.py OUT_DIR REPO [--spec specs.json]
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "parallel_measure"))
sys.path.insert(0, HERE)
import extract  # noqa: E402
import measure  # noqa: E402


def newer(src, dst):
    return not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst)


def gz(src, dst):
    with open(src, "rb") as a, gzip.open(dst, "wb") as b:
        shutil.copyfileobj(a, b)


def main(out, repo, spec_path):
    d = os.path.join(out, repo)
    with open(spec_path) as f:
        spec = json.load(f)[repo]
    cwd = os.path.expandvars(spec["dir"])
    done = []
    for t in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
        b = os.path.basename(t)
        if not re.match(r"^(S\d+|P\d+w\d+)\.jsonl$", b):
            continue
        dst = os.path.join(d, f"tests-{b[:-6]}.jsonl.gz")
        if newer(t, dst):
            extract.write(t, dst)
            done.append(dst)
    for p in sorted(glob.glob(os.path.join(d, "plain*.runner.json")) + glob.glob(os.path.join(d, "plain*.ids.json"))):
        m = re.match(r"^plain(\d+)\.", os.path.basename(p))
        dst = os.path.join(d, f"tests-plain{m.group(1)}.jsonl.gz")
        src = os.path.join(d, f"plain{m.group(1)}.runner.json")
        if not newer(p, dst):
            continue
        oc = measure.runner_outcomes(src, cwd)
        with gzip.open(dst, "wt") as g:
            for k, v in oc.items():
                g.write(json.dumps({"nodeid": k, "outcome": v}) + "\n")
        done.append(dst)
    for v in sorted(glob.glob(os.path.join(d, "verify*.json"))):
        if newer(v, v + ".gz"):
            gz(v, v + ".gz")
            done.append(v + ".gz")
    log = os.path.join(d, "runs.log")
    if os.path.exists(log) and newer(log, log + ".gz"):
        gz(log, log + ".gz")
        done.append(log + ".gz")
    return done


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    sp = sys.argv[sys.argv.index("--spec") + 1] if "--spec" in sys.argv else os.path.join(HERE, "..", "parallel_measure", "specs.json")
    a = [x for x in a if x != sp]
    for x in main(a[0], a[1], sp):
        print(x)
