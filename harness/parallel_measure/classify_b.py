#!/usr/bin/env python3
"""Classify every test whose engine verdict is not "identical" into exactly one box (session B, coordinator addition).

Reads what measure.py left in OUT/<repo>/ (plain{i}.runner.json, S{i}.jsonl, P{i}w{n}.jsonl, verify{i}w{n}.json,
verify_serial_noise2w1.json); changes nothing and runs nothing.

Boxes (one per test id, over all rounds and worker counts):
  OURS       the engine is the cause, with evidence:
             - untraced: the runner reports the test, the engine's trace does not (e.g. skipped tests)
             - stable-but-unproven: the outcome is the same in every plain, serial and parallel run, and the engine also
               fails to prove serial run 1 against serial run 2 for this test (verdict not identical with no parallelism)
             - manual override with a reproduction (overrides.json), e.g. a test that fails only under `--det`
  THEIRS     only by manual override with a reproduction without the engine (overrides.json)
  UNDECIDED  everything else: an outcome change not yet reproduced, or a test the engine proves serial vs serial but
             not serial vs parallel while its outcome stays stable (could be a real concurrency hazard)

Usage: classify_b.py OUT REPO [overrides.json] > OUT/REPO/classes.json
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure import norm, runner_outcomes, trace_tests  # noqa: E402


def main():
    out, repo = sys.argv[1], sys.argv[2]
    over = json.load(open(sys.argv[3])).get(repo, {}) if len(sys.argv) > 3 else {}
    d = os.path.join(out, repo)
    rows = [json.loads(x) for x in open(os.path.join(out, "results.jsonl")) if x.strip()]
    cwd = next(r["cwd"] for r in rows if r["repo"] == repo)
    rounds = sorted({int(m.group(1)) for f in glob.glob(f"{d}/S*.jsonl") if (m := re.search(r"/S(\d+)\.jsonl$", f))})
    outcomes = {}  # test -> list of (run label, outcome)

    def add(label, m):
        for k, v in m.items():
            outcomes.setdefault(k, []).append((label, v))

    for i in rounds:
        add(f"plain{i}", norm(runner_outcomes(f"{d}/plain{i}.runner.json", cwd)))
        add(f"S{i}", norm({k: v[0] for k, v in trace_tests(f"{d}/S{i}.jsonl")[1].items()}))
        for p in sorted(glob.glob(f"{d}/P{i}w*.jsonl")):
            add(os.path.basename(p)[:-6], norm({k: v[0] for k, v in trace_tests(p)[1].items()}))
    traced = set()
    for p in glob.glob(f"{d}/S*.jsonl") + glob.glob(f"{d}/P*.jsonl"):
        traced |= set(trace_tests(p)[1])

    verdicts = {}  # test -> list of (file, status, reason, first event)
    for f in sorted(glob.glob(f"{d}/verify*.json")):
        j = json.load(open(f))
        for t in j.get("tests", []):
            dv = t.get("divergence") or {}
            verdicts.setdefault(t["nodeid"], []).append(
                (os.path.basename(f)[:-5], t["status"], dv.get("reason"), dv.get("event_a"), dv.get("event_b")))
    noise = {t: [v for v in vs if v[0].startswith("verify_serial_noise")] for t, vs in verdicts.items()}

    res = {}
    for t in sorted(set(outcomes) | set(verdicts)):
        vs = verdicts.get(t, [])
        bad = [v for v in vs if v[1] != "stable" and not v[0].startswith("verify_serial_noise")]
        oc = outcomes.get(t, [])
        distinct = sorted({o for _, o in oc})
        if t not in traced:
            box, why = "OURS", f"untraced: runner outcomes {distinct}, absent from every engine trace"
        elif not bad:
            continue
        elif t in over:
            box, why = over[t]["box"], over[t]["evidence"]
        elif len(distinct) > 1:
            box, why = "UNDECIDED", "outcome changes: " + ", ".join(f"{l}={o}" for l, o in oc)
        elif any(v[1] != "stable" for v in noise.get(t, [])):
            nz = noise[t][0]
            box, why = "OURS", (f"stable-but-unproven: outcome {distinct[0]} in all {len(oc)} runs; serial S1 vs S2 "
                                f"already {nz[1]} (reason {nz[2]})")
        else:
            box, why = "UNDECIDED", (f"outcome {distinct[0]} in all {len(oc)} runs; S1 vs S2 identical, serial vs "
                                     f"parallel not ({sorted({v[2] for v in bad if v[2]})})")
        if t in over and box != over[t]["box"]:
            box, why = over[t]["box"], over[t]["evidence"]
        first = next((v for v in bad if v[3] or v[4]), bad[0] if bad else None)
        res[t] = {"box": box, "evidence": why,
                  "statuses": sorted({v[1] for v in bad}), "reasons": sorted({v[2] for v in bad if v[2]}),
                  "first_differing_event": None if not first else {"verify": first[0], "a": first[3], "b": first[4]}}
    counts = {}
    for v in res.values():
        counts[v["box"]] = counts.get(v["box"], 0) + 1
    json.dump({"repo": repo, "counts": counts, "tests": res}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
