#!/usr/bin/env python3
"""P3b: the excluded ids of the neutrality check and their reconciliation (gate rev 3 note 1), and the D2 "gone" list
(gate note 6).

    export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/report.py excluded --repo R --find $PM_WORK/find
        -> harness/p3b/data/R/excluded.json
    export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/report.py gone --repo R --find $PM_WORK/find [--rows rows.jsonl]
        -> harness/p3b/data/R/gone.json
    python3 harness/p3b/report.py render      -> the generated block of harness/p3b/REPORT.md

excluded: `variable` = ids whose outcome differs between plain runs 1 and 2 of A, plus every id whose digits-to-#
shape is the shape of such an id (exactly as ladder.neutral builds its exclusion; ladder.neutral does not write it).
Every id of neutral.json `differ` (plain run 1 of A vs the harness config, default order) is then one of:
  excluded (a)  not an unstable id; its plain results differ (classify.py's plain-flaky rule): must be a case row
                UNDECIDED "plain flaky ..."
  excluded (b)  its shape is a cases.json pattern: that pattern's matched case, no case, or UNDECIDED "unstable id"
  excluded, neither (a) nor (b): a defect, listed
  not excluded  one of the n_differ_outside_plain_variable ids that make `neutral` false (order not forced on R): a
                finding, listed
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classify  # noqa: E402  (first: parallel_measure/ has its own classify.py)
sys.path.append(os.path.join(HERE, "..", "parallel_measure"))
sys.path.append(os.path.join(HERE, "..", "det_pins"))
import measure  # noqa: E402
import pins  # noqa: E402
from cases import norm, shape  # noqa: E402

DATA = classify.DATA
REPORT = os.path.join(HERE, "REPORT.md")
BEGIN, END = "<!-- report.py render: begin -->", "<!-- report.py render: end -->"


def excluded_set(p1, p2):
    """-> (variable ids, shapes of variable ids, function id -> excluded?) as ladder.neutral computes them."""
    variable = {k for k in set(p1) | set(p2) if p1.get(k) != p2.get(k)}
    vshape = {shape(k) for k in variable if shape(k) != k}
    return variable, vshape, (lambda k: k in variable or shape(k) in vshape)


def reconcile(differ, p1, p2, cases_json, rows):
    """-> dict of lists: excluded_a, excluded_b, excluded_neither, not_excluded (each of [id, detail])."""
    variable, vshape, is_ex = excluded_set(p1, p2)
    pats = {p["pattern"]: p for p in cases_json.get("patterns") or []}
    by_id = {r["test_id"]: r for r in rows}
    out = {"excluded_a": [], "excluded_b": [], "excluded_neither": [], "not_excluded": []}
    for d in differ:
        k = d[0]
        if not is_ex(k):
            out["not_excluded"].append([k, f"plain1 {d[1]} / harness {d[2]}"])
            continue
        sh = shape(k)
        if sh != k and sh in pats:
            p = pats[sh]
            if p.get("matched"):
                became = f"matched case ({p.get('kind')})" if p.get("kind") else "no case (the four results agree)"
            else:
                became = "UNDECIDED unstable id"
            out["excluded_b"].append([k, f"pattern {sh}: {became}"])
            continue
        r = by_id.get(k)
        if r is not None and r["verdict"] == "UNDECIDED" and r["reason"].startswith("plain flaky"):
            out["excluded_a"].append([k, r["reason"]])
        elif sh != k and sh in vshape and k not in set(p1) | set(p2):
            # an id of the harness run only (its own pid/seed), whose shape is a plain-variable id's: accounted for
            # by its shape (gate note 1); its pattern is not a cases.json pattern when the four A runs agree
            out["excluded_b"].append([k, f"harness-run id of shape {sh} (shape of a plain-variable id)"])
        else:
            out["excluded_neither"].append([k, f"row: {r['verdict'] + ' ' + r['reason'] if r else 'none'}"])
    return variable, vshape, out


def _ctx(repo, find):
    spec = pins.load_spec(repo)
    return os.path.expandvars(spec["dir"]), os.path.join(find, repo)


def plain_runs(fr, cwd):
    return [{k: norm(v) for k, v in measure.runner_outcomes(f"{fr}/plain{i}.runner.json", cwd).items()} for i in (1, 2)]


def excluded_cmd(o):
    cwd, fr = _ctx(o.repo, o.find)
    p1, p2 = plain_runs(fr, cwd)
    neutral = json.load(open(os.path.join(DATA, o.repo, "neutral.json")))
    cj = json.load(open(os.path.join(DATA, o.repo, "find", "cases.json")))
    rows = [r for r in classify.load_rows(o.rows) if r["repo"] == o.repo]
    variable, vshape, rec = reconcile(neutral.get("differ") or [], p1, p2, cj, rows)
    ex = sorted(k for k in set(p1) | set(p2) if k in variable or shape(k) in vshape)
    out = {"repo": o.repo, "variable": sorted(variable), "variable_shapes": sorted(vshape), "excluded_a_or_b_ids": ex,
           "neutral": neutral.get("neutral"), "n_differ": len(neutral.get("differ") or []),
           "counts": {k: len(v) for k, v in rec.items()}, **rec}
    with open(os.path.join(DATA, o.repo, "excluded.json"), "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(json.dumps({"repo": o.repo, "variable": len(variable), "counts": out["counts"]}))


# ------------------------------------------------------------------------------------------------------- gone
def gone_rows(rows, d1, d2, small5=None):
    """Spec D2 per kind through the copied classify.gone(); a formerly mixed-outcome case needs its 5-run count on
    the smallest set (small5[test_id]); without it, it is not gone (fail closed)."""
    small5 = small5 or {}
    out = []
    for r in rows:
        tid = r["test_id"]
        mixed = bool(r.get("mixed_outcome"))
        g = classify.gone(r["kind"], d1.get(tid), d2.get(tid), small5.get(tid), mixed)
        out.append({"test_id": tid, "kind": r["kind"], "head_det": [d1.get(tid), d2.get(tid)], "gone": g,
                    "mixed_outcome": mixed})
    return out


def gone_cmd(o):
    _, fr = _ctx(o.repo, o.find)
    d = [{k: norm(v) for k, v in pins.det_outcomes(f"{fr}/det{i}.outcomes.json")[0].items()} for i in (1, 2)]
    rows = [r for r in classify.load_rows(o.rows) if r["repo"] == o.repo]
    small5 = json.load(open(o.small5)) if o.small5 else {}
    res = gone_rows(rows, d[0], d[1], small5)
    out = {"repo": o.repo, "engine_commit": pins.engine_commit(), "rows_from": o.rows,
           "n_gone": sum(x["gone"] for x in res), "n": len(res), "cases": res}
    with open(os.path.join(DATA, o.repo, "gone.json"), "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
    print(json.dumps({k: out[k] for k in ("repo", "engine_commit", "n", "n_gone")}))


# ----------------------------------------------------------------------------------------------------- render
def render_block(data=DATA):
    out = [BEGIN, "", "### Neutrality exclusions (founder D3, gate rev 3 note 1; generated by `report.py render`)", "",
           "| repository | neutral | differ | excluded (a) plain flaky | excluded (b) pattern | excluded, neither | "
           "not excluded |", "|---|---|---|---|---|---|---|"]
    exs = []
    for p in sorted(glob.glob(os.path.join(data, "*", "excluded.json"))):
        e = json.load(open(p))
        exs.append(e)
        c = e["counts"]
        out.append(f"| {e['repo']} | {e['neutral']} | {e['n_differ']} | {c['excluded_a']} | {c['excluded_b']} | "
                   f"{c['excluded_neither']} | {c['not_excluded']} |")
    for e in exs:
        out += ["", f"#### {e['repo']}: excluded ids ({len(e['excluded_a_or_b_ids'])})", ""]
        out += [f"- `{k}`" for k in e["excluded_a_or_b_ids"]] or ["- none"]
        for key, title in (("excluded_a", "differ, excluded (a)"), ("excluded_b", "differ, excluded (b)"),
                           ("excluded_neither", "differ, excluded but neither (a) nor (b): DEFECT"),
                           ("not_excluded", "differ, not excluded (neutral false)")):
            if e[key]:
                out += ["", f"{title}:", ""] + [f"- `{k}`: {d}" for k, d in e[key]]
    gs = [json.load(open(p)) for p in sorted(glob.glob(os.path.join(data, "*", "gone.json")))]
    if gs:
        out += ["", "### Gone on the measured head (spec D2, `report.py gone`)", "",
                "| repository | engine commit | cases | gone |", "|---|---|---|---|"]
        for g in gs:
            out.append(f"| {g['repo']} | {g['engine_commit']} | {g['n']} | {g['n_gone']} |")
    out += ["", END]
    return "\n".join(out) + "\n"


def render_cmd(_o):
    text = open(REPORT).read() if os.path.exists(REPORT) else f"# P3b report\n\n{BEGIN}\n{END}\n"
    if BEGIN not in text:
        text += f"\n{BEGIN}\n{END}\n"
    head, rest = text.split(BEGIN, 1)
    tail = rest.split(END, 1)[1].lstrip("\n")
    with open(REPORT, "w") as f:
        f.write(head + render_block() + tail)
    print(f"-> {REPORT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["excluded", "gone", "render"])
    ap.add_argument("--repo")
    ap.add_argument("--find")
    ap.add_argument("--rows", default=classify.ROWS)
    ap.add_argument("--small5", help="JSON {test_id: plain outcomes of 5} for formerly mixed-outcome cases")
    o = ap.parse_args()
    if o.phase != "render" and not (o.repo and o.find):
        ap.error(f"{o.phase} needs --repo and --find")
    {"excluded": excluded_cmd, "gone": gone_cmd, "render": render_cmd}[o.phase](o)


if __name__ == "__main__":
    main()
