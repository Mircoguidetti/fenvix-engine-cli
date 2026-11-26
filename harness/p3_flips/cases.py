#!/usr/bin/env python3
"""P3 step A2: every case of a `pins.py find` directory, built from the four runs' outcome files (not from the
truncated lists in flips.json: pins.py cuts `ids_only_in_det` at 50).

    python3 harness/p3_flips/cases.py <find dir>/<repo> <repo checkout>   -> writes <find dir>/<repo>/cases.json

Kinds (per test id, four results p1 p2 d1 d2, each passed / failed / skipped / None = missing; `error` counts as
failed, `pending`/`todo` as skipped):
  flip            p1 = p2 = passed, d1 and d2 failed
  mixed           p1 = p2 = passed, d1 and d2 present and not skipped, one failed and one passed
  absent          p1 = p2 = passed, missing from a --det run
  skipped-in-det  p1 = p2 = passed, present in both --det runs, skipped in at least one
  det-only        missing from both plain runs, present in a --det run
  reverse         p1, p2 failed; d1, d2 passed or skipped
  other           the four results are not all the same and none of the kinds above fits
An id is marked `unstable` when it is missing from at least one of the four runs and some other id of the same file,
with digits replaced by `#`, is present in that run: the test name embeds a run-dependent value (pid, wall clock).
Founder D2 (2026-11-26): an unstable id's pattern (digits replaced, a leading minus included) is matched when it
names exactly one id in each of the four runs, ids present by exact name in all four runs left out of the count; the four matched results then make one ordinary case of its kind (id =
the pattern, `matched_ids` = the id per run), or no case when the four agree. Any other match count leaves every id of
the pattern an unstable case (UNDECIDED "unstable id"). `patterns` in the output lists each pattern, its match count
per run and what became of it.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "parallel_measure"))
sys.path.append(os.path.join(HERE, "..", "det_pins"))
import measure  # noqa: E402
import pins  # noqa: E402

KINDS = ("flip", "mixed", "absent", "skipped-in-det", "det-only", "reverse", "other")


def norm(o):
    if o is None:
        return None
    if o in ("failed", "error"):
        return "failed"
    if o in ("skipped", "pending", "todo", "skip"):
        return "skipped"
    return o


def kind_of(p1, p2, d1, d2):
    r = (p1, p2, d1, d2)
    if len(set(r)) == 1:
        return None
    if p1 == p2 == "passed":
        if d1 is None or d2 is None:
            return "absent"
        if "skipped" in (d1, d2):
            return "skipped-in-det"
        if d1 == d2 == "failed":
            return "flip"
        return "mixed"
    if p1 is None and p2 is None:
        return "det-only"
    if p1 == p2 == "failed" and d1 in ("passed", "skipped") and d2 in ("passed", "skipped"):
        return "reverse"
    return "other"


def shape(tid):
    return re.sub(r"-?\d+", "#", tid)


def build(d, cwd):
    plain = [measure.runner_outcomes(f"{d}/plain{i}.runner.json", cwd) for i in (1, 2)]
    det = [pins.det_outcomes(f"{d}/det{i}.outcomes.json") for i in (1, 2)]
    runs = [plain[0], plain[1], det[0][0], det[1][0]]
    runs = [{k: norm(v) for k, v in r.items()} for r in runs]
    shapes = [{} for _ in runs]
    for i, r in enumerate(runs):
        for k in r:
            shapes[i].setdefault(shape(k), set()).add(k)
    cases = []
    for tid in sorted(set().union(*runs)):
        res = [r.get(tid) for r in runs]
        k = kind_of(*res)
        if k is None:
            continue
        unstable = False
        if None in res:
            sh = shape(tid)
            unstable = sh != tid and any(res[i] is None and (shapes[i].get(sh, set()) - {tid}) for i in range(4))
        exc = [det[0][1].get(tid), det[1][1].get(tid)]
        cases.append({"id": tid, "kind": k, "results": res, "unstable": unstable, "pattern": shape(tid) if unstable else None,
                      "det_failure": [pins.first_line(e) for e in exc]})
    cases, patterns = match_patterns(cases, runs, shapes, det)
    counts = {k: sum(1 for c in cases if c["kind"] == k) for k in KINDS}
    return {"counts": counts, "n_cases": len(cases), "n_unstable": sum(c["unstable"] for c in cases), "cases": cases,
            "patterns": patterns}


def match_patterns(cases, runs, shapes, det):
    """Founder D2: one case per unstable pattern that matches exactly one id in each run (see module doc)."""
    pats = sorted({c["pattern"] for c in cases if c["unstable"]})
    out, report = [c for c in cases if not c["unstable"] or c["pattern"] not in pats], []
    for pat in pats:
        # founder D2 (2026-11-26 04:47): an id whose exact name is in all four runs is matched by name, not counted
        stable = set.intersection(*(set(r) for r in runs))
        ids = [sorted(shapes[i].get(pat, set()) - stable) for i in range(4)]
        n = [len(x) for x in ids]
        members = [c for c in cases if c["unstable"] and c["pattern"] == pat]
        rec = {"pattern": pat, "matches_per_run": n, "ids": [c["id"] for c in members]}
        if n == [1, 1, 1, 1]:
            m = [x[0] for x in ids]
            res = [runs[i][m[i]] for i in range(4)]
            k = kind_of(*res)
            rec.update({"matched": True, "matched_ids": m, "results": res, "kind": k})
            if k is not None:
                exc = [det[0][1].get(m[2]), det[1][1].get(m[3])]
                out.append({"id": pat, "kind": k, "results": res, "unstable": False, "pattern": pat, "matched_ids": m,
                            "det_failure": [pins.first_line(e) for e in exc]})
        else:
            rec["matched"] = False
            out += members
        report.append(rec)
    return sorted(out, key=lambda c: c["id"]), report


if __name__ == "__main__":
    d, cwd = sys.argv[1], sys.argv[2]
    out = build(d, cwd)
    with open(os.path.join(d, "cases.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({k: out[k] for k in ("counts", "n_cases", "n_unstable")}))
