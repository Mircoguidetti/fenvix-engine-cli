#!/usr/bin/env python3
"""Round-2 numbers of the exact-culprit validation, from the result rows only (plain Python).

    aggregate2.py RESULTS_DIR [--json OUT]

Kinds: a2 (code, culprit at a random position / revert-and-reland; a2-*.jsonl), b (real history: commits the
project reverted; b-*.jsonl), c-nocode (c-final.jsonl: head-to-head environment changes and the round-2 added
mechanisms), c-edit (c-edit.jsonl: data-edit commits), d (order-dependent; d.jsonl, carried over from round 1).
For every answer: correct, confident wrong (a culprit named and not the truth), or unknown (no culprit named).
Trivial rules (review R-019 H5): the oldest / newest commit of (green, red], the oldest / newest candidate commit.
"""

from __future__ import annotations

import glob
import json
import statistics as st
import sys
from pathlib import Path


def rows(d, pat):
    return [json.loads(l) for f in sorted(glob.glob(str(Path(d) / pat))) for l in open(f) if l.strip()]


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def stats(xs):
    if not xs:
        return {}
    return {"median": st.median(xs), "mean": round(st.mean(xs), 2), "p90": pct(xs, 0.9), "max": max(xs)}


def named_of(fr):
    c = (fr or {}).get("culprit") or {}
    return c.get("commit") or c.get("input")


def score(cases, truth_of, named, ex_of):
    n = len(cases)
    corr = sum(1 for r in cases if named(r) is not None and named(r) == truth_of(r))
    wrong = [r for r in cases if named(r) is not None and named(r) != truth_of(r)]
    unk = sum(1 for r in cases if named(r) is None)
    ex = [ex_of(r) for r in cases]
    return {"cases": n, "correct": corr, "confident_wrong": len(wrong), "unknown": unk,
            "confident_wrong_ids": [r["id"] for r in wrong], "executions": stats(ex), "_ex": ex}


def commit_kind(cases):
    s = score(cases, lambda r: r["truth"], lambda r: named_of(r["finder"]), lambda r: r["finder"].get("executions", 0))
    s["bisect_correct"] = sum(1 for r in cases if r.get("bisect_correct"))
    s["bisect_executions"] = stats([r["bisect"]["executions"] for r in cases if r.get("bisect")])
    tr = {"oldest_in_range": lambda r: r.get("range_first"), "newest_in_range": lambda r: r.get("range_last"),
          "oldest_candidate": lambda r: (r["finder"].get("candidates") or [None])[0],
          "newest_candidate": lambda r: (r["finder"].get("candidates") or [None])[-1]}
    s["trivial_rules_correct"] = {k: sum(1 for r in cases if f(r) == r["truth"]) for k, f in tr.items()}
    s["candidate_replays"] = sum(1 for r in cases for x in r["finder"].get("steps", []) if x["why"] == "bisect candidates")
    s["candidate_replays_pass"] = sum(1 for r in cases for x in r["finder"].get("steps", [])
                                      if x["why"] == "bisect candidates" and x["outcome"] == "pass")
    s["truth_position_first"] = sum(1 for r in cases if r.get("truth_position") == 1)
    s["truth_is_planted"] = sum(1 for r in cases if r.get("truth_is_planted"))
    sus = [r for r in cases if named_of(r["finder"]) is None and "suspect " in (r["finder"].get("why") or "")]
    s["unknown_with_suspect"] = len(sus)
    s["unknown_suspect_is_truth"] = sum(1 for r in sus if r["finder"]["why"].rsplit("suspect ", 1)[1].strip() == r["truth"])
    s["status"] = {}
    for r in cases:
        k = r["finder"].get("status", "?")
        s["status"][k] = s["status"].get(k, 0) + 1
    return s


def main():
    d = sys.argv[1]
    out = {}
    a2 = [r for r in rows(d, "a-*.jsonl") if r.get("green_run") == "pass" and r.get("red_run") == "fail"]
    a2_all = rows(d, "a-*.jsonl")
    for r in a2_all:
        r["truth"] = r["truth"]
    out["a2"] = commit_kind(a2)
    out["a2"]["excluded_key_runs"] = len(a2_all) - len(a2)
    for shape in ("placed", "reland"):
        out[f"a2-{shape}"] = commit_kind([r for r in a2 if r.get("shape") == shape])
    out["a2"]["by_repo"] = {}
    for repo in sorted({r["repo"] for r in a2}):
        sub = commit_kind([r for r in a2 if r["repo"] == repo])
        out["a2"]["by_repo"][repo] = {k: sub[k] for k in ("cases", "correct", "confident_wrong", "unknown")}
    b = [r for r in rows(d, "b-*.jsonl") if r.get("green_run") == "pass" and r.get("red_run") == "fail"]
    out["b"] = commit_kind(b)
    out["b"]["excluded_key_runs"] = len(rows(d, "b-*.jsonl")) - len(b)
    out["b"]["repos"] = sorted({r["repo"] for r in b})
    out["b"]["distinct_culprits"] = len({r["truth"] for r in b})
    out["b"]["truth_is_reverted_commit"] = sum(1 for r in b if r.get("truth_is_planted"))
    c = [r for r in rows(d, "c-final.jsonl") if "finder" in r]
    ce = [r for r in rows(d, "c-edit.jsonl") if "finder" in r]
    cs = score(c, lambda r: r["truth"], lambda r: r.get("finder_named") if (r["finder"].get("culprit")) else None,
               lambda r: r["finder"].get("executions", 0))
    cs["singles"] = sum(1 for r in c if not r.get("decoy"))
    cs["singles_correct"] = sum(1 for r in c if not r.get("decoy") and r.get("finder_correct"))
    cs["mechanisms"] = sorted({r["what"] for r in c})
    cs["bisect_correct"] = sum(1 for r in c if r.get("bisect_correct"))
    cs["rebuilt_exactly"] = [r["finder"].get("rebuilt_exactly") for r in c]
    out["c-nocode"] = cs
    for r in ce:
        r["finder"].setdefault("candidates", [])
        r["range_first"], r["range_last"] = (r.get("range") or [None])[0], (r.get("range") or [None])[-1]
    out["c-edit"] = commit_kind(ce)
    dd = [r for r in rows(d, "d.jsonl") if "finder_correct" in r]
    for r in dd:
        r.setdefault("id", f"{r['repo']}:{r['victim']}")
    out["d"] = score(dd, lambda r: r["truth"], lambda r: r.get("finder_named"), lambda r: r["executions"])
    out["d"]["distinct_culprits"] = len({r["truth"] for r in dd})
    out["d"]["note"] = "carried over from round 1 (orderdep.py, not changed in round 2)"
    allex = out["a2"]["_ex"] + out["b"]["_ex"] + cs["_ex"] + out["c-edit"]["_ex"] + out["d"]["_ex"]
    tot = {k: out[x][k] for k in ("cases", "correct", "confident_wrong", "unknown") for x in ("a2",)}
    for k in ("cases", "correct", "confident_wrong", "unknown"):
        tot[k] = sum(out[x][k] for x in ("a2", "b", "c-nocode", "c-edit", "d"))
    tot["executions"] = stats(allex)
    tot["share_correct"] = round(tot["correct"] / tot["cases"], 4) if tot["cases"] else None
    nd = sum(out[x]["cases"] for x in ("a2", "b", "c-nocode", "c-edit"))
    tot["without_d"] = {"cases": nd, "correct": sum(out[x]["correct"] for x in ("a2", "b", "c-nocode", "c-edit")),
                        "confident_wrong": sum(out[x]["confident_wrong"] for x in ("a2", "b", "c-nocode", "c-edit")),
                        "executions": stats(out["a2"]["_ex"] + out["b"]["_ex"] + cs["_ex"] + out["c-edit"]["_ex"])}
    # rebuild of the green environment from the green key (head-to-head scenarios: no-code and data edits)
    reb = [r for r in c + ce if r.get("placement") and r["finder"].get("green_env_replays")]
    tot["rebuild_cases"] = len(reb)
    tot["rebuild_failed"] = sum(1 for r in reb if r["finder"].get("rebuilt_exactly") is False)
    out["overall"] = tot
    for v in out.values():
        if isinstance(v, dict):
            v.pop("_ex", None)
    txt = json.dumps(out, indent=1, sort_keys=True)
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(txt + "\n")
    print(txt)


if __name__ == "__main__":
    main()
