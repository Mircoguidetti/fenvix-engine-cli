"""Truth comparison of reused results (review R-023 F1: the mixed-store rows had none).

usage: python -m harness.parallel_proof.crosscheck --truth T.outcomes.json [T2.outcomes.json ...]
           --run R.outcomes.json [--json OUT]

``--truth``: outcomes files of fresh serial ``--det`` runs (no cache) at the same commit; ``--run``: the outcomes
file of a ``--det-cache`` run (serial or ``-n``). For every result the run reused, its outcome is compared with the
truth runs' outcomes: a reused outcome no truth run gave is a mismatch (a wrong reuse unless the test is flaky:
then the truth runs disagree among themselves, reported apart). Also: every test the run *ran*, compared the same way
(a parallel run's own verdict against the serial truth)."""

from __future__ import annotations

import argparse
import json


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def compare(truths: list[dict], run: dict) -> dict:
    t_out = [t.get("outcomes", {}) for t in truths]
    outcomes = run.get("outcomes", {})
    reused = set((run.get("cache") or {}).get("reused_ids", []))
    flaky = {n for n in t_out[0] if len({t.get(n) for t in t_out}) > 1}
    res = {"tests": len(outcomes), "reused": len(reused), "ran": len(set(outcomes) - reused)}
    for name, ids in (("reused", reused), ("ran", set(outcomes) - reused)):
        bad = sorted(n for n in ids if n in t_out[0] and n not in flaky and outcomes.get(n) != t_out[0][n])
        res[f"{name}_mismatches"] = bad
        res[f"{name}_not_in_truth"] = len([n for n in ids if n not in t_out[0]])
        res[f"{name}_flaky_in_truth"] = len([n for n in ids if n in flaky])
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", nargs="+", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    out = compare([load(p) for p in a.truth], load(a.run))
    text = json.dumps(out, indent=1, sort_keys=True)
    if a.json:
        with open(a.json, "w") as f:
            f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
