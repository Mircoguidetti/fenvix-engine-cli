#!/usr/bin/env python3
"""P3 step B4-B5: raw evidence -> one row per case -> one verdict per case -> CLASSIFY.md.

    python3 harness/p3_flips/classify.py rows      data/<repo>/find/cases.json + data/<repo>/b/*.json -> rows.jsonl
    python3 harness/p3_flips/classify.py render    rows.jsonl -> CLASSIFY.md (byte-identical for the same rows)

Verdict rule (spec B4; exactly one per case, no group verdicts):
  THEIRS-ENV  the plain control (no condition) gave the plain outcome 3 of 3 and the identical plain command with the
              matching condition gave the --det outcome in >= 1 of 3 valid runs; the condition is order (harness
              config checked neutral, applied order checked per run) or network (only on a NetworkBlockedError or trace
              meta network block/replay); or, when the control gave the --det outcome 3 of 3 on the smallest set,
              the whole suite in the default order gave the plain outcome 3 of 3 and with the --det file order forced
              the --det outcome >= 1 of 3.
  ARTIFACT    not THEIRS-ENV, and the case clears at one ladder step in every (valid) run of that step, or still
              reproduces at L7 (cause: wrapper).
  UNDECIDED   everything else, with the reason.
Time, seeds, timers, fs, isolation, wrapper and net under open/record have no plain equivalent: never THEIRS-ENV.
"""
from __future__ import annotations

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROWS = os.path.join(HERE, "rows.jsonl")
OUT = os.path.join(HERE, "CLASSIFY.md")
KINDS = ("flip", "mixed", "absent", "skipped-in-det", "det-only", "reverse", "other")
CAUSE = {"L1": "timers progression (virtual)", "L2a": "timers", "L2b": "net", "L3": "fs", "L4": "time", "L5": "seeds",
         "L6": "order", "L7": "isolation", "wrapper": "wrapper"}


def verdict(row, neutral=True):
    """-> (verdict, reason, flags). `neutral`: the repository's harness config passed the neutrality check."""
    flags = []
    res = row.get("results") or [None] * 4
    if not row.get("unstable") and res[0] != res[1]:
        # founder D3: an id that differs between the two plain runs of A is excluded from the neutrality check and
        # stays UNDECIDED (its plain outcome is not one outcome)
        return "UNDECIDED", f"plain flaky (plain runs of A: {res[0]} / {res[1]})", flags
    if row["kind"] == "other":
        return "UNDECIDED", "kind other", flags
    if row.get("unstable"):
        return "UNDECIDED", f"unstable id ({row.get('pattern')})", flags
    if row.get("undecided"):
        return "UNDECIDED", row["undecided"], flags
    if "alone" not in row:
        return "UNDECIDED", "not processed in B", flags
    ctl = (row.get("control") or {}).get("states") or []
    if len(ctl) != 3 or "invalid" in ctl:
        return "UNDECIDED", f"control runs invalid or missing ({ctl})", flags
    cause = row.get("clears_at")
    if ctl == ["plain"] * 3:
        cond = row.get("condition") or {}
        st = [s for s in cond.get("states") or [] if s != "invalid"]
        if cond.get("kind") == "order" and not cond.get("not_forced") and neutral and "det" in st:
            theirs = True
        elif cond.get("kind") == "network" and row.get("net_trigger") and "det" in st:
            theirs = True
        else:
            theirs = False
        if theirs:
            plain_f = next((r.get("failure") for r in cond.get("runs", []) if r.get("failure")), None)
            det_f = next((x for x in row.get("det_failure") or [] if x), None)
            if plain_f and det_f and plain_f.split(" [")[0] not in det_f and det_f.split(" [")[0] not in plain_f:
                flags.append("different-failure")
            if cond["kind"] == "order":
                flags.append("candidate-real-bug (order)")
            return "THEIRS-ENV", f"{cond['kind']}: control 3/3 plain, condition {st.count('det')}/{len(cond['states'])} --det", flags
    elif ctl == ["det"] * 3:
        ws = row.get("whole_suite_order") or {}
        d = (ws.get("default") or {}).get("states") or []
        fo = [s for s in (ws.get("forced") or {}).get("states") or [] if s != "invalid"]
        if neutral and d == ["plain"] * 3 and "det" in fo:
            flags.append("candidate-real-bug (order)")
            return "THEIRS-ENV", f"order (whole suite): default 3/3 plain, forced {fo.count('det')}/3 --det", flags
        return "UNDECIDED", "plain subset-dependent", flags
    else:
        return "UNDECIDED", f"plain flaky (control {ctl.count('plain')}/3 plain outcome)", flags
    if cause in CAUSE:
        return "ARTIFACT", f"cause {CAUSE[cause]} ({cause})", flags
    cond = row.get("condition") or {}
    if cond.get("kind") == "order" and (cond.get("not_forced") or not neutral):
        return "UNDECIDED", "order not forced" if cause is None else f"cause {cause}; order not forced", flags
    return "UNDECIDED", "clears in only some runs of every step", flags


def gone(kind, d1, d2, small_plain_5=None, was_mixed_outcome=False):
    """Spec D1: is a case gone on the final head? d1, d2 = the id's normalised outcome in the two whole-suite --det
    runs on head (None = missing); small_plain_5 = for a formerly mixed-outcome case, how many of 5 --det runs of its
    smallest set gave the plain outcome."""
    if kind in ("flip", "mixed"):
        ok = d1 == d2 == "passed"
    elif kind in ("absent", "skipped-in-det"):
        ok = d1 == d2 == "passed"
    elif kind == "det-only":
        ok = d1 is None and d2 is None
    elif kind == "reverse":
        ok = d1 == d2 == "failed"
    else:
        ok = False
    if ok and was_mixed_outcome:
        ok = small_plain_5 == 5
    return ok


# ------------------------------------------------------------------------------------------------- rows
PATTERNS, NEUTRAL_DIFFER = {}, {}


def load_side(data=DATA):
    for repo in sorted(os.listdir(data)):
        cp = os.path.join(data, repo, "find", "cases.json")
        if os.path.exists(cp):
            PATTERNS[repo] = json.load(open(cp)).get("patterns") or []
        np_ = os.path.join(data, repo, "neutral.json")
        if os.path.exists(np_):
            NEUTRAL_DIFFER[repo] = json.load(open(np_)).get("differ") or []


def build_rows(data=DATA):
    rows = []
    for repo in sorted(os.listdir(data)):
        cp = os.path.join(data, repo, "find", "cases.json")  # count-only repos have count_extra.json instead: skipped
        if not os.path.exists(cp):
            continue
        cases = json.load(open(cp))["cases"]
        b = {}
        for p in sorted(glob.glob(os.path.join(data, repo, "b", "*.json"))):
            j = json.load(open(p))
            for cid, rec in j["cases"].items():
                b[cid] = (j, rec)
        neutral = None
        np_ = os.path.join(data, repo, "neutral.json")
        if os.path.exists(np_):
            neutral = json.load(open(np_)).get("neutral")
        for c in cases:
            row = {"repo": repo, "kind": c["kind"], "test_id": c["id"], "file": c["id"].split("::", 1)[0],
                   "results": c["results"], "unstable": c["unstable"], "pattern": c.get("pattern"),
                   "det_failure": c["det_failure"], "neutral": neutral}
            if c["id"] in b:
                j, rec = b[c["id"]]
                row["engine_commit"] = j.get("engine_commit")
                for k in ("alone", "set", "undecided", "ladder", "clears_at", "control", "condition", "whole_suite_order",
                          "mixed_outcome"):
                    if k in rec:
                        row[k] = rec[k]
                row["net_trigger"] = any("NetworkBlockedError" in (x or "") for x in c["det_failure"]) or any(
                    (r.get("meta") or {}).get("network") in ("block", "replay")
                    for s in (rec.get("ladder") or {}).values() for r in s["runs"])
            v, why, flags = verdict(row, neutral is not False)
            row.update({"verdict": v, "reason": why, "flags": flags})
            rows.append(row)
    return rows


def write_rows(rows, path=ROWS):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def load_rows(path=ROWS):
    return [json.loads(x) for x in open(path) if x.strip()]


def ladder_str(r):
    lad = r.get("ladder") or {}
    return " ".join(f"{k}:{''.join(s[0] for s in v['states'])}" for k, v in lad.items()) or "-"


def render(rows):
    out = ["# P3 flips: classification (generated by `harness/p3_flips/classify.py render` from `rows.jsonl`)", "",
           "Per-run state letters: r = reproduces the --det outcome of A, c = clears (plain outcome), i = invalid run, "
           "n = neither. Control/condition letters: p = plain outcome of A, d = --det outcome of A, i = invalid.", ""]
    repos = sorted({r["repo"] for r in rows})
    out += ["## Summary", "", "| repository | kind | cases | THEIRS-ENV | ARTIFACT | UNDECIDED | of which unstable id |",
            "|---|---|---|---|---|---|---|"]
    for repo in repos:
        rr = [r for r in rows if r["repo"] == repo]
        for k in KINDS:
            kk = [r for r in rr if r["kind"] == k]
            if not kk:
                continue
            c = {v: sum(1 for r in kk if r["verdict"] == v) for v in ("THEIRS-ENV", "ARTIFACT", "UNDECIDED")}
            out.append(f"| {repo} | {k} | {len(kk)} | {c['THEIRS-ENV']} | {c['ARTIFACT']} | {c['UNDECIDED']} | "
                       f"{sum(1 for r in kk if r.get('unstable'))} |")
        c = {v: sum(1 for r in rr if r["verdict"] == v) for v in ("THEIRS-ENV", "ARTIFACT", "UNDECIDED")}
        out.append(f"| **{repo}** | all | {len(rr)} | {c['THEIRS-ENV']} | {c['ARTIFACT']} | {c['UNDECIDED']} | "
                   f"{sum(1 for r in rr if r.get('unstable'))} |")
    out += ["", "## Unstable-id patterns (founder D2)", "",
            "A pattern is matched when it names exactly one id in each of the four runs of A (p1 p2 d1 d2).", "",
            "| repository | pattern | matches per run | matched | became |", "|---|---|---|---|---|"]
    for repo in repos:
        for p in (PATTERNS.get(repo) or []):
            became = (p.get("kind") or "no case (the four results agree)") if p.get("matched") else \
                f"{len(p['ids'])} cases UNDECIDED unstable id"
            out.append(f"| {repo} | `{p['pattern'].replace('|', '/')}` | {' '.join(map(str, p['matches_per_run']))} | "
                       f"{'yes' if p.get('matched') else 'no'} | {became} |")
    out += ["", "## Ids excluded from the neutrality check (founder D3)", "",
            "Ids whose outcome differs between the two plain runs of A, or whose digit pattern is such an id's.", "",
            "| repository | test id | plain A run 1 / harness config |", "|---|---|---|"]
    for repo in repos:
        for d in (NEUTRAL_DIFFER.get(repo) or []):
            out.append(f"| {repo} | `{d[0].replace('|', '/')}` | {d[1]} / {d[2]} |")
    out += ["", "## ARTIFACT causes", "", "| repository | cause | cases |", "|---|---|---|"]
    for repo in repos:
        causes = {}
        for r in rows:
            if r["repo"] == repo and r["verdict"] == "ARTIFACT":
                causes[r["reason"]] = causes.get(r["reason"], 0) + 1
        for k in sorted(causes):
            out.append(f"| {repo} | {k} | {causes[k]} |")
    for repo in repos:
        out += ["", f"## {repo}", "", "| test id | kind | results p1 p2 d1 d2 | alone | set | ladder | control | condition | "
                "verdict | reason |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in sorted((x for x in rows if x["repo"] == repo), key=lambda x: x["test_id"]):
            al = "".join(s[0] for s in (r.get("alone") or {}).get("states", [])) or "-"
            st = (r.get("set") or {}).get("name", "-")
            if st != "-" and st != "alone":
                st += f" ({len((r.get('set') or {}).get('files', [])) - 1} preds)"
            ctl = "".join(s[0] for s in (r.get("control") or {}).get("states", [])) or "-"
            cond = r.get("condition") or {}
            cs = (cond.get("kind", "") + ":" + "".join(s[0] for s in cond.get("states", []))) if cond else "-"
            if cond.get("not_forced"):
                cs = f"{cond.get('kind')}: not forced"
            res = " ".join(str(x) for x in r["results"])
            fl = (" [" + ", ".join(r["flags"]) + "]") if r.get("flags") else ""
            tid = r["test_id"].replace("|", "\\|")
            out.append(f"| `{tid}` | {r['kind']} | {res} | {al} | {st} | {ladder_str(r)} | {ctl} | {cs} | "
                       f"{r['verdict']}{fl} | {r['reason'].replace('|', '/')} |")
    return "\n".join(out) + "\n"


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "render"
    if cmd == "rows":
        rows = build_rows()
        write_rows(rows)
        print(f"{len(rows)} rows -> {ROWS}")
    if cmd in ("rows", "render"):
        load_side()
        text = render(load_rows())
        with open(OUT, "w") as f:
            f.write(text)
        print(f"-> {OUT}")


if __name__ == "__main__":
    main()
