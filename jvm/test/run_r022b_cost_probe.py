#!/usr/bin/env python3
"""Review R-022b: what the shared-state rule classifies as `mut` (a read of static state another test could change).

Runs one --det --deps capture of jvm/fixtures/review-r022b and prints, for each rv.Cost*Test (each reads
only state that cannot change after class initialisation: an enum's values(), an enum switch, List.of,
Optional.of, a non-final class with only final fields, a non-capturing method reference, an enum
constant), whether its capture is `mut` and the classes blamed (`mut_classes`). A `mut` test is reused
only if no rerun test before it in its JVM touched shared state: every such probe is a cost of the rule
with no soundness benefit.

Measurement, not a pass/fail check: exit 0 when the capture ran. Writes results/review-r022b-cost.json.

  python3 jvm/test/run_r022b_cost_probe.py
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_review_r022b as rb  # noqa: E402


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results", "review-r022b-cost.json")
    deps = rb.capture("/tmp/fenvix-review-r022b-cost/A", [])
    rows = {}
    for m in rb.fenvix_skip.load(deps).values():
        for tid, rec in m["tests"].items():
            if tid.startswith("rv.Cost") or tid == rb.PLAIN:
                rows[tid] = {"outcome": rec.get("outcome"), "mut": rec.get("mut"), "mut_classes": rec.get("mut_classes"),
                             "swrite": rec.get("swrite")}
    for tid, r in sorted(rows.items()):
        print(f"{tid:40} mut={r['mut']!s:5} mut_classes={r['mut_classes']}")
    json.dump(rows, open(out, "w"), indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
