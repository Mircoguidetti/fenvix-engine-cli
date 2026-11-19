#!/usr/bin/env python3
"""Round-4 numbers of the exact-culprit validation, from the result rows only (plain Python).

    aggregate4.py RESULTS_DIR [--json OUT]

Same populations and rules as ``round2/aggregate2.py`` (whose numbers this reuses), plus what round 4 adds:
* stated share (a culprit named), confident wrong, unknown, and how often a withheld suspect is the truth, per kind
  and overall;
* cost: test executions (median, p90), wall time per case as measured (the whole finder, the machine shared with
  other lanes), and the critical-path replay time (every replay in sequence, a parallel batch as its longest
  replay: ``finder.critical_wall``);
* red-side replays (``red_probes``; step 4: ``red_side_probes``) and the commits decided by key validity;
* the stated share at smaller red-side budgets, simulated from the recorded replays: the finder is deterministic
  and replays in the same order whatever the budget, so a case answered with at most B red-side replays is answered
  identically at budget B (a multiple of the 4 workers), and any other case would be withheld. ESTIMATED: a
  restart found inside a batch cut short by a smaller budget could, in principle, end differently.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "round2"))
import aggregate2 as A  # noqa: E402

BUDGETS = (0, 4, 8, 16, 24, 32, 48, 64)


def _named(r, kind):
    if kind == "d":
        return r.get("finder_named")
    if kind == "c-nocode":
        return r.get("finder_named") if (r["finder"].get("culprit")) else None
    return A.named_of(r["finder"])


def _suspect(r, kind):
    why = r.get("red_side") if kind == "d" else (r.get("finder") or {}).get("why")
    why = why or ""
    return why.rsplit("suspect ", 1)[1].split(";")[0].strip() if "suspect " in why else None


def _red(r, kind):
    return r.get("red_side_probes", 0) if kind == "d" else (r["finder"].get("red_probes") or 0)


def _wall(r, kind):
    return r.get("finder_wall") if kind == "d" else r["finder"].get("wall")


def _crit(r, kind):
    if kind == "d":
        steps = [{"wall": s.get("wall"), "batch": s.get("batch")} for s in r.get("finder_steps", [])]
    else:
        steps = r["finder"].get("steps", [])
    tot, seen = 0.0, set()
    for s in steps:
        b = s.get("batch")
        if b is None:
            tot += s.get("wall") or 0.0
        elif b not in seen:
            seen.add(b)
            tot += max((x.get("wall") or 0.0) for x in steps if x.get("batch") == b)
    return round(tot, 2)


def _ex(r, kind):
    return r["executions"] if kind == "d" else r["finder"].get("executions", 0)


def kind_rows(d):
    a2_all = [r for r in A.rows(d, "a-*.jsonl") if r.get("rebuilt", True)]
    b_all = [r for r in A.rows(d, "b-*.jsonl") if r.get("rebuilt", True)]
    out = {
        "a2": [r for r in a2_all if r.get("green_run") == "pass" and r.get("red_run") == "fail"],
        "b": [r for r in b_all if r.get("green_run") == "pass" and r.get("red_run") == "fail"],
        # a no-code row counts only when its green run passed and its red run failed (review R-019c, R-2: two
        # round-3 rich-home rows were fail/fail and pass/pass); rows without the fields (older drivers) count
        "c-nocode": [r for r in A.rows(d, "c-final.jsonl") if "finder" in r
                     and (r.get("green_run", "pass"), r.get("red_run", "fail")) == ("pass", "fail")],
        "c-edit": [r for r in A.rows(d, "c-edit.jsonl") if "finder" in r],
        "d": [r for r in A.rows(d, "d.jsonl") if "finder_correct" in r],
    }
    return out


def summarise(rs, kind):
    n = len(rs)
    named = [r for r in rs if _named(r, kind) is not None]
    right = [r for r in named if _named(r, kind) == r["truth"]]
    wrong = [r for r in named if _named(r, kind) != r["truth"]]
    unk = [r for r in rs if _named(r, kind) is None]
    sus = [r for r in unk if _suspect(r, kind)]
    sus_ok = [r for r in sus if _suspect(r, kind) == r["truth"]]
    ex = [_ex(r, kind) for r in rs]
    wall = [x for x in (_wall(r, kind) for r in rs) if x is not None]
    crit = [_crit(r, kind) for r in rs]
    red = [_red(r, kind) for r in rs]
    budget = {}
    for b in BUDGETS:
        st = [r for r in named if _red(r, kind) <= b]
        budget[b] = {"stated": len(st), "right": sum(1 for r in st if _named(r, kind) == r["truth"]),
                     "share": round(len(st) / n, 4) if n else None}
    return {
        "cases": n, "stated": len(named), "right": len(right), "confident_wrong": len(wrong),
        "confident_wrong_ids": [r.get("id") or f"{r.get('repo')}:{r.get('victim')}" for r in wrong],
        "unknown": len(unk), "unknown_with_suspect": len(sus), "unknown_suspect_is_truth": len(sus_ok),
        "stated_share": round(len(named) / n, 4) if n else None,
        "executions": A.stats(ex), "wall_s": A.stats(wall), "critical_wall_s": A.stats(crit),
        "red_side_replays": A.stats(red),
        "red_inferred": A.stats([r["finder"].get("red_inferred") or 0 for r in rs]) if kind != "d" else None,
        "budget_curve": budget,
        "unknown_why": _why_counts(unk, kind),
        "_ex": ex, "_wall": wall, "_crit": crit,
    }


def _why_counts(unk, kind):
    out = {}
    for r in unk:
        why = (r.get("red_side") if kind == "d" else (r.get("finder") or {}).get("why")) or r.get("skip") or "?"
        k = "ambiguous (red-side budget)" if "ambiguous" in why else why.split(":")[0][:60]
        out[k] = out.get(k, 0) + 1
    return out


def main():
    d = sys.argv[1]
    ks = kind_rows(d)
    out = {k: summarise(v, k) for k, v in ks.items()}
    for shape in ("placed", "reland"):
        out[f"a2-{shape}"] = summarise([r for r in ks["a2"] if r.get("shape") == shape], "a2")
    tot = {"cases": sum(out[k]["cases"] for k in ks), "stated": sum(out[k]["stated"] for k in ks),
           "right": sum(out[k]["right"] for k in ks), "confident_wrong": sum(out[k]["confident_wrong"] for k in ks),
           "unknown": sum(out[k]["unknown"] for k in ks),
           "unknown_suspect_is_truth": sum(out[k]["unknown_suspect_is_truth"] for k in ks),
           "unknown_with_suspect": sum(out[k]["unknown_with_suspect"] for k in ks)}
    tot["stated_share"] = round(tot["stated"] / tot["cases"], 4) if tot["cases"] else None
    tot["executions"] = A.stats([x for k in ks for x in out[k]["_ex"]])
    tot["wall_s"] = A.stats([x for k in ks for x in out[k]["_wall"]])
    tot["critical_wall_s"] = A.stats([x for k in ks for x in out[k]["_crit"]])
    tot["budget_curve"] = {b: {"stated": sum(out[k]["budget_curve"][b]["stated"] for k in ks)} for b in BUDGETS}
    for b in BUDGETS:
        tot["budget_curve"][b]["share"] = round(tot["budget_curve"][b]["stated"] / tot["cases"], 4)
    nd = [k for k in ks if k != "d"]
    tot["without_d"] = {"cases": sum(out[k]["cases"] for k in nd), "stated": sum(out[k]["stated"] for k in nd),
                        "executions": A.stats([x for k in nd for x in out[k]["_ex"]])}
    out["overall"] = tot
    for v in out.values():
        for x in ("_ex", "_wall", "_crit"):
            v.pop(x, None)
    txt = json.dumps(out, indent=1, sort_keys=True)
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
