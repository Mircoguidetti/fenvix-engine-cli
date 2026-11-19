#!/usr/bin/env python3
"""Numbers of the exact-culprit validation from the result files.

    aggregate.py RESULTS_DIR [--json out.json]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics as st


def load(pattern):
    rows = []
    for f in sorted(glob.glob(pattern)):
        for line in open(f):
            if line.strip():
                rows.append(json.loads(line))
    return rows


def q(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))
    return xs[i]


def summ(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return {}
    return {"n": len(xs), "median": st.median(xs), "mean": round(st.mean(xs), 2), "p90": q(xs, 0.9), "max": max(xs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    out = {}
    # (a) planted regressions
    A = load(os.path.join(a.dir, "a-*.jsonl"))
    A = [r for r in A if r.get("green_run") == "pass" and r.get("red_run") == "fail"]
    out["a"] = {
        "cases": len(A), "repos": len({r["repo"] for r in A}),
        "finder_correct": sum(r["finder_correct"] for r in A),
        "bisect_correct": sum(r["bisect_correct"] for r in A),
        "finder_exec": summ([r["finder"]["executions"] for r in A]),
        "bisect_exec": summ([r["bisect"]["executions"] for r in A]),
        "finder_wall": summ([r["finder"].get("wall") for r in A]),
        "bisect_wall": summ([round(r["bisect"]["wall"], 2) for r in A]),
        "candidates": summ([r["finder"].get("commit_candidates") for r in A]),
        "k": summ([r["k"] for r in A]),
        "exact": sum(1 for r in A if r["finder"].get("rebuilt_exactly") is not False),
        "wrong": [{"id": r["id"], "named": (r["finder"].get("culprit") or {}), "why": r["finder"].get("why"),
                   "truth": r["truth"][:10]} for r in A if not r["finder_correct"]],
        "bisect_wrong": [r["id"] for r in A if not r["bisect_correct"]],
    }
    buckets = {}
    for r in A:
        b = "5-20" if r["k"] <= 20 else "21-60" if r["k"] <= 60 else "61-120" if r["k"] <= 120 else "121-205"
        x = buckets.setdefault(b, {"n": 0, "ok": 0, "fe": [], "be": [], "cand": []})
        x["n"] += 1
        x["ok"] += r["finder_correct"]
        x["fe"].append(r["finder"]["executions"])
        x["be"].append(r["bisect"]["executions"])
        x["cand"].append(r["finder"].get("commit_candidates") or 0)
    out["a_by_k"] = {b: {"n": x["n"], "finder_correct": x["ok"], "finder_exec_median": st.median(x["fe"]),
                         "bisect_exec_median": st.median(x["be"]), "candidates_median": st.median(x["cand"])}
                     for b, x in sorted(buckets.items())}
    per_repo = {}
    for r in A:
        x = per_repo.setdefault(r["repo"], {"n": 0, "ok": 0, "fe": [], "cand": [], "k": []})
        x["n"] += 1
        x["ok"] += r["finder_correct"]
        x["fe"].append(r["finder"]["executions"])
        x["cand"].append((r["finder"].get("commit_candidates") or 0) / max(1, r["k"]))
    out["a_by_repo"] = {k: {"n": x["n"], "ok": x["ok"], "exec_median": st.median(x["fe"]),
                            "candidate_share_median": round(st.median(x["cand"]), 2)} for k, x in sorted(per_repo.items())}
    # (b) real history
    B = load(os.path.join(a.dir, "b.jsonl"))
    Bc = [r for r in B if "finder" in r]
    out["b"] = {"transitions_checked": len({(r["walk"], r["step"]) for r in B}),
                "skipped": [{"walk": r["walk"], "step": r["step"], "why": r.get("skip")} for r in B if r.get("skip")],
                "cases": len(Bc), "finder_correct": sum(r["finder_correct"] for r in Bc),
                "bisect_correct": sum(r["bisect_correct"] for r in Bc),
                "finder_exec": summ([r["finder"].get("executions") for r in Bc]),
                "bisect_exec": summ([r["bisect"]["executions"] for r in Bc]),
                "rows": [{"id": r["id"], "truth": r["truth"], "named": r["finder_named"], "ok": r["finder_correct"],
                          "exec": r["finder"].get("executions"), "exact": r["finder"].get("rebuilt_exactly"),
                          "bisect": r["bisect"]["named"], "bisect_ok": r["bisect_correct"],
                          "fix_or_revert": r.get("fix_or_revert")} for r in Bc]}
    # (c) no-code reds
    C = [r for r in load(os.path.join(a.dir, "c.jsonl")) + load(os.path.join(a.dir, "c-node.jsonl"))]
    Cc = [r for r in C if "finder" in r]
    singles = [r for r in Cc if not r.get("decoy")]
    out["c"] = {"cases": len(Cc), "finder_correct": sum(r["finder_correct"] for r in Cc),
                "bisect_correct": sum(r["bisect_correct"] for r in Cc),
                "singles": len(singles), "singles_correct": sum(r["finder_correct"] for r in singles),
                "finder_exec": summ([r["finder"].get("executions") for r in Cc]),
                "bisect_exec": summ([r["bisect"]["executions"] for r in Cc]),
                "rebuild_needed": sum(1 for r in Cc if r["finder"].get("rebuilt_exactly") is not None),
                "rebuilt_exactly": sum(1 for r in Cc if r["finder"].get("rebuilt_exactly") is True),
                "skipped": [{"id": r["id"], "why": r.get("skip")} for r in C if "finder" not in r],
                "rows": [{"id": r["id"], "truth": r["truth"], "named": r["finder_named"], "ok": r["finder_correct"],
                          "exec": r["finder"].get("executions"), "exact": r["finder"].get("rebuilt_exactly"),
                          "cands": r["finder"].get("input_candidates", r.get("input_candidates")),
                          "commits": f"{r['finder'].get('commit_candidates', r.get('commit_candidates'))}/"
                                     f"{r['finder'].get('commits_in_range', r.get('commits_in_range'))}",
                          "bisect": r["bisect"]["named"] and r["bisect"]["named"][:10], "bisect_ok": r["bisect_correct"]}
                         for r in Cc]}
    # (d) order-dependent defects
    D = load(os.path.join(a.dir, "d.jsonl"))
    Dc = [r for r in D if "finder_correct" in r]
    out["d"] = {"victims_tried": len(D), "cases": len(Dc), "finder_correct": sum(r["finder_correct"] for r in Dc),
                "finder_exec": summ([r["executions"] for r in Dc]),
                "finder_exec_polluter": summ([r["executions_polluter"] for r in Dc]),
                "finder_exec_commit": summ([r["executions_commit"] for r in Dc]),
                "finder_wall": summ([r["finder_wall"] for r in Dc]),
                "bisect_attempts": sum(len(r["bisect"]) for r in Dc),
                "bisect_wrong": sum(r["bisect_wrong"] for r in Dc),
                "bisect_cases_any_wrong": sum(1 for r in Dc if r["bisect_wrong"] > 0),
                "bisect_cases_majority_wrong": sum(1 for r in Dc if r["bisect_wrong"] > len(r["bisect"]) / 2),
                "bisect_exec": summ([b["executions"] for r in Dc for b in r["bisect"]]),
                "bisect_wall": summ([b["wall"] for r in Dc for b in r["bisect"]]),
                "named_adds_polluter_or_victim_file": sum(1 for r in Dc if r.get("named_touches_polluter_file")
                                                          or r.get("named_touches_victim_file")),
                "skipped": [{"repo": r["repo"], "victim": r["victim"], "why": r.get("skip")} for r in D
                            if "finder_correct" not in r]}
    # overall
    allx = ([r["finder"]["executions"] for r in A] + [r["finder"].get("executions") for r in Bc] +
            [r["finder"].get("executions") for r in Cc] + [r["executions"] for r in Dc])
    ok = (sum(r["finder_correct"] for r in A) + sum(r["finder_correct"] for r in Bc) +
          sum(r["finder_correct"] for r in Cc) + sum(r["finder_correct"] for r in Dc))
    n = len(A) + len(Bc) + len(Cc) + len(Dc)
    rebuild = [r["finder"].get("rebuilt_exactly") for r in Bc + Cc]
    out["overall"] = {"cases": n, "correct": ok, "share": round(ok / n, 4) if n else None,
                      "exec": summ(allx), "exec_without_d": summ(allx[: len(A) + len(Bc) + len(Cc)]),
                      "rebuild_cases": sum(1 for x in rebuild if x is not None),
                      "rebuild_failed": sum(1 for x in rebuild if x is False)}
    txt = json.dumps(out, indent=1, default=str)
    if a.json:
        open(a.json, "w").write(txt)
    print(json.dumps({k: v for k, v in out.items() if k in ("overall",)}, indent=1))
    for k in ("a", "b", "c", "d"):
        print(k, json.dumps({x: y for x, y in out[k].items() if x not in ("rows", "wrong", "skipped", "bisect_wrong")})[:900])


if __name__ == "__main__":
    main()
