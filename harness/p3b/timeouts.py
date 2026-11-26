#!/usr/bin/env python3
"""P3b step B5: wall-time evidence for timeout cases still failing at L7, and the failure-line check on timeout
THEIRS-ENV rows. The copied classify.py is not edited: this file reads and rewrites the rows it wrote.

    export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/timeouts.py measure --repo R --find $PM_WORK/find
        -> harness/p3b/data/R/timeouts.json
    python3 harness/p3b/timeouts.py annotate
        rows.jsonl (from `classify.py rows`) + data/*/timeouts.json -> rows.jsonl rewritten in place

A timeout case (gate rev 3 note 5): `(Test|Hook) timed out in (\\d+)ms` matches the first non-empty element of its
`det_failure`; group 1 is the kind, group 2 the timeout in ms.

measure (gate note 2): for every timeout row whose reason is `cause wrapper (wrapper)`, rerun through ladder.Ctx (the
repository's env and harness config, as B ran it) once per distinct (control, L7) pair, 3 times each:
  control: ctx.plain(<pair>.tw.plain.r<i>, set files)
  L7:      ctx.det(<pair>.tw.L7.r<i>, files, [--det-disable=order,seeds,time,timers,fs,net,isolation], order_ids)
order_ids are read from the L7 run's own recorded `<tag>.order.txt` (None for an alone set). Walls are the `wall_s`
of the rows ladder.Ctx returns (and appends to runs.jsonl).

annotate (spec B5.3, gate notes 4-5):
  (a) every timeout row with a measured pair gets `timeout_wall` and
      `overhead` = {ratio: median L7 / median plain, over_budget, engine_overhead}; verdict and reason unchanged.
      over_budget: plain duration (test: its own duration; hook: its file's endTime - startTime; median of the two
      plain runs of A) + overhead_s * 1000 > the timeout in ms. engine_overhead: ratio >= RATIO or over_budget.
  (b) a timeout row with verdict THEIRS-ENV whose failing runs (state 'det') on its path (condition, or whole-suite
      forced order) do not all carry the same timeout line (same kind, same ms), or carry no line, becomes UNDECIDED
      `timeout THEIRS-ENV with a different failure line`; flags keep `different-failure` and drop
      `candidate-real-bug (order)`.
  (c) nothing else changes.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classify  # noqa: E402  (first: parallel_measure/ has its own classify.py)

DATA = classify.DATA
TIMEOUT_RE = re.compile(r"(Test|Hook) timed out in (\d+)ms")
WRAPPER = "cause wrapper (wrapper)"
L7_FLAGS = ["--det-disable=order,seeds,time,timers,fs,net,isolation"]
RATIO = 1.5  # coordinator's pick (spec open question 3); changing it is a rule-7 question
DIFF_REASON = "timeout THEIRS-ENV with a different failure line"
REPS = 3


def first_line(lines):
    return next((x for x in (lines or []) if x), None)


def timeout_of(line):
    """-> (kind 'Test'|'Hook', ms) or None."""
    m = TIMEOUT_RE.search(line or "")
    return (m.group(1), int(m.group(2))) if m else None


def is_timeout(row):
    return timeout_of(first_line(row.get("det_failure"))) is not None


def pair_key(row):
    """The (control, L7) command pair of a row, named by its group prefix `<slug>.g<n>` (cases of one set share it)."""
    tag = row["ladder"]["L7"]["runs"][0]["tag"]
    return tag.rsplit(".L7.", 1)[0]


# --------------------------------------------------------------------------------------------- plain durations
def _runner_json(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


def plain_durations(find_repo, cwd):
    """From the two plain runs of A: per test id its duration (ms), per file its endTime - startTime (ms); each a list
    with one value per run that has it. Ids are built as measure.runner_outcomes builds them (with ` #n` suffixes)."""
    tests, files = {}, {}
    for i in (1, 2):
        j = _runner_json(f"{find_repo}/plain{i}.runner.json")
        seen = set()
        for tr in j.get("testResults", []):
            rel = os.path.relpath(tr["name"], cwd)
            if tr.get("endTime") is not None and tr.get("startTime") is not None:
                files.setdefault(rel, []).append(tr["endTime"] - tr["startTime"])
            for a in tr.get("assertionResults", []):
                k = "::".join([rel] + list(a.get("ancestorTitles") or []) + [a["title"]])
                n, base = 2, k
                while k in seen:
                    k, n = f"{base} #{n}", n + 1
                seen.add(k)
                if a.get("duration") is not None:
                    tests.setdefault(k, []).append(a["duration"])
    return tests, files


def _plain_key(tid):
    """A detjs id may name a Vitest project (`file@@proj::...`); the plain JSON report does not."""
    f, _, rest = tid.partition("::")
    return f.split("@@", 1)[0] + ("::" + rest if rest else "")


def case_plain(row, tests, files):
    """-> (plain_ms, source) for a timeout row, or (None, why)."""
    kind, _ = timeout_of(first_line(row["det_failure"]))
    if kind == "Test":
        v = tests.get(_plain_key(row["test_id"]))
        return (statistics.median(v), "test duration (median of plain A runs)") if v else (None, "no plain test duration")
    v = files.get(_plain_key(row["file"]))
    return (statistics.median(v), "file endTime - startTime (median of plain A runs)") if v else (None, "no plain file time")


# --------------------------------------------------------------------------------------------------- measure
def measure_cmd(o):
    import ladder  # noqa: E402  (needs the repository spec and engine; not needed by annotate)
    ctx = ladder.Ctx(o)
    rows = [r for r in classify.load_rows() if r["repo"] == o.repo and r["reason"] == WRAPPER and is_timeout(r)]
    out_path = os.path.join(DATA, o.repo, "timeouts.json")
    prev = json.load(open(out_path)) if os.path.exists(out_path) else {}
    eng = ladder.pins.engine_commit()
    pairs = prev.get("pairs", {}) if prev.get("engine_commit") == eng else {}
    tests, files = plain_durations(ctx.find, ctx.cwd)
    cases = {}
    for r in sorted(rows, key=lambda x: x["test_id"]):
        key = pair_key(r)
        if key not in pairs:
            l7tag = r["ladder"]["L7"]["runs"][0]["tag"]
            op = os.path.join(ctx.work, "runs", f"{l7tag}.order.txt")
            order_ids = [x for x in open(op).read().splitlines() if x] if os.path.exists(op) else None
            fset = r["set"]["files"]
            plain, l7 = [], []
            for i in range(1, REPS + 1):
                p = ctx.plain(f"{key}.tw.plain.r{i}", fset)
                plain.append({"tag": p["tag"], "cmd": p["cmd"], "exit": p["exit"], "wall_s": p["wall_s"],
                              "outcome": p["outcomes"].get(r["test_id"])})
                d = ctx.det(f"{key}.tw.L7.r{i}", fset, L7_FLAGS, order_ids)
                l7.append({"tag": d["tag"], "cmd": d["cmd"], "exit": d["exit"], "wall_s": d["wall_s"],
                           "outcome": d["outcomes"].get(r["test_id"])})
            pairs[key] = summarize({"control_cmd": r["control"]["runs"][0]["cmd"],
                                    "l7_cmd": r["ladder"]["L7"]["runs"][0]["cmd"], "set": r["set"],
                                    "order_ids_from": op if order_ids is not None else None, "plain": plain, "l7": l7})
            save(out_path, o.repo, eng, pairs, cases)
        kind, ms = timeout_of(first_line(r["det_failure"]))
        pm, src = case_plain(r, tests, files)
        cases[r["test_id"]] = {"pair": key, "timeout_kind": kind, "timeout_ms": ms, "plain_ms": pm, "plain_source": src}
    save(out_path, o.repo, eng, pairs, cases)
    print(json.dumps({"repo": o.repo, "pairs": len(pairs), "cases": len(cases)}))


def summarize(p):
    pw = [x["wall_s"] for x in p["plain"]]
    lw = [x["wall_s"] for x in p["l7"]]
    mp, ml = statistics.median(pw), statistics.median(lw)
    p.update({"plain_walls": pw, "l7_walls": lw, "median_plain_s": mp, "median_l7_s": ml,
              "overhead_s": round(ml - mp, 3)})
    return p


def save(path, repo, eng, pairs, cases):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"repo": repo, "engine_commit": eng, "ratio_threshold": RATIO, "pairs": pairs, "cases": cases}, f,
                  indent=1, sort_keys=True)


# -------------------------------------------------------------------------------------------------- annotate
def overhead(pair, case):
    ratio = pair["median_l7_s"] / pair["median_plain_s"] if pair["median_plain_s"] else None
    if case.get("plain_ms") is None:
        over = None  # no plain duration: unknown, never guessed
    else:
        over = case["plain_ms"] + pair["overhead_s"] * 1000 > case["timeout_ms"]
    return {"ratio": round(ratio, 4) if ratio is not None else None, "over_budget": over,
            "engine_overhead": bool((ratio is not None and ratio >= RATIO) or over)}


def path_runs(row):
    """The runs of the path that made the row THEIRS-ENV, with their states: the whole-suite forced order, or the
    condition."""
    if row["reason"].startswith("order (whole suite)"):
        s = (row.get("whole_suite_order") or {}).get("forced") or {}
    else:
        s = row.get("condition") or {}
    return list(zip(s.get("states") or [], s.get("runs") or []))


def same_timeout_lines(row):
    want = timeout_of(first_line(row["det_failure"]))
    failing = [r for st, r in path_runs(row) if st == "det"]
    if not failing:
        return False
    return all(timeout_of(r.get("failure")) == want and r.get("failure") for r in failing)


def annotate_row(row, tw):
    if not is_timeout(row):
        return row
    t = tw.get(row["repo"]) or {}
    c = (t.get("cases") or {}).get(row["test_id"])
    if c and c["pair"] in (t.get("pairs") or {}):
        pair = t["pairs"][c["pair"]]
        row["timeout_wall"] = {**pair, "case": c}
        row["overhead"] = overhead(pair, c)
    if row["verdict"] == "THEIRS-ENV" and not same_timeout_lines(row):
        row["verdict"], row["reason"] = "UNDECIDED", DIFF_REASON
        fl = [f for f in row.get("flags") or [] if f != "candidate-real-bug (order)"]
        if "different-failure" not in fl:
            fl.append("different-failure")
        row["flags"] = fl
    return row


def load_tw(data=DATA):
    out = {}
    for p in sorted(glob.glob(os.path.join(data, "*", "timeouts.json"))):
        out[os.path.basename(os.path.dirname(p))] = json.load(open(p))
    return out


def annotate_cmd(_o, rows_path=classify.ROWS, data=DATA):
    tw = load_tw(data)
    rows = [annotate_row(r, tw) for r in classify.load_rows(rows_path)]
    classify.write_rows(rows, rows_path)
    n = sum(1 for r in rows if "overhead" in r)
    print(json.dumps({"rows": len(rows), "with_overhead": n,
                      "timeout_theirs_env_different_line": sum(1 for r in rows if r["reason"] == DIFF_REASON)}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["measure", "annotate"])
    ap.add_argument("--repo")
    ap.add_argument("--find")
    o = ap.parse_args()
    if o.phase == "measure":
        if not (o.repo and o.find):
            ap.error("measure needs --repo and --find")
        measure_cmd(o)
    else:
        annotate_cmd(o)


if __name__ == "__main__":
    main()
