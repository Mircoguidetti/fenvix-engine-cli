#!/usr/bin/env python3
"""P2 correctness of a speed change (spec, Definitions, "Correctness of a speed change"), from committed evidence.

Rule 1  per-test verify class per worker count: class = identical | not-proven:<reason> | diverged | missing; a test's
        class per w = the set over the rounds. Baseline sets with more than one member: VARIABLE-CLASS (excluded).
        Every other change is listed; a change without a one-line explanation (--explain JSON {nodeid: line}) is a
        defect, in either direction.
Rule 2  fixed-epoch fingerprints: tests with one fingerprint over the baseline fixed runs must have it at the fix head;
        else the repeat run decides; still different -> events compared after removing only the declared event kinds
        (--declared o1,o2): equal remaining events and equal outcome = allowed, anything else = defect.
Rule 3  outcomes and exit codes: per kind (plain, serial, par w) a non-VARIABLE test's outcome equals the baseline's;
        exit codes within the baseline's set; outcome counts within the baseline's [min, max] per count and w; a run
        with a failed test and exit 0 is a defect.

Layout read: <dir>/<repo>/verify<i>w<n>.json[.gz], tests-{S<i>,P<i>w<n>,plain<i>,F-<label>}.jsonl.gz, and
<dir>/results.jsonl (rows of that repository).

Usage: correctness.py --base DIR --fix DIR --repo REPO [--base-fixed base1,base2,base3] [--fix-fixed LABEL[,REPEAT]]
                      [--declared KINDS] [--explain FILE] [--json OUT]
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract  # noqa: E402

WORKERS = (2, 4)
ROUNDS = (1, 2, 3)


def _load_json(path):
    for p in (path, path + ".gz"):
        if os.path.exists(p):
            op = gzip.open if p.endswith(".gz") else open
            with op(p, "rt") as f:
                return json.load(f)
    return None


def verify_classes(d, i, n):
    """nodeid -> class of one verify report (None when the report is absent)."""
    rep = _load_json(os.path.join(d, f"verify{i}w{n}.json"))
    if rep is None or "tests" not in rep:
        return None
    out = {}
    for t in rep["tests"]:
        s = t.get("status")
        if s == "stable":
            c = "identical"
        elif s == "not-proven":
            c = "not-proven:" + str(((t.get("divergence") or {}).get("reason")) or "?")
        elif s == "diverged":
            c = "diverged"
        else:
            c = str(s)
        out[t["nodeid"]] = c
    return out


def class_sets(d, n, rounds=ROUNDS):
    per = [verify_classes(d, i, n) for i in rounds]
    per = [p for p in per if p is not None]
    ids = set().union(*[set(p) for p in per]) if per else set()
    return {k: frozenset(p.get(k, "missing") for p in per) for k in ids}, len(per)


def rule1(base, fix, n, explain=None, rounds=ROUNDS):
    explain = explain or {}
    b, nb = class_sets(base, n, rounds)
    f, nf = class_sets(fix, n, rounds)
    variable = sorted(k for k, s in b.items() if len(s) > 1)
    changes, defects = [], []
    for k in sorted(set(b) | set(f)):
        bs = b.get(k, frozenset(["missing"]))
        if len(bs) > 1:
            continue
        fs = f.get(k, frozenset(["missing"]))
        if fs != bs:
            c = {"nodeid": k, "w": n, "baseline": sorted(bs), "fix": sorted(fs),
                 "towards_identical": "identical" in fs and "identical" not in bs, "explanation": explain.get(k)}
            changes.append(c)
            if not c["explanation"]:
                defects.append(c)
    return {"w": n, "rounds_base": nb, "rounds_fix": nf, "variable_class": variable, "changes": changes, "defects": defects}


def _ext(d, label):
    p = os.path.join(d, f"tests-{label}.jsonl.gz")
    return extract.read(p) if os.path.exists(p) else None


def rule2(base, base_labels, fix, fix_label, repeat_label=None, declared=()):
    declared = set(declared)
    bases = [_ext(base, f"F-{x}") for x in base_labels]
    if any(x is None for x in bases) or not bases:
        return {"error": f"baseline fixed extracts missing: {base_labels}"}
    fx = _ext(fix, f"F-{fix_label}")
    if fx is None:
        return {"error": f"fix fixed extract missing: F-{fix_label}"}
    rep = _ext(fix, f"F-{repeat_label}") if repeat_label else None
    stable = [k for k in bases[0] if k != "_dups" and all(k in b and b[k]["fingerprint"] == bases[0][k]["fingerprint"] for b in bases[1:])]
    passed, need_repeat, allowed, defects = 0, [], [], []
    for k in stable:
        b0 = bases[0][k]
        t = fx.get(k)
        if t is not None and t.get("fingerprint") == b0["fingerprint"]:
            passed += 1
            continue
        if rep is None:
            need_repeat.append(k)
            continue
        t = rep.get(k)
        if t is not None and t.get("fingerprint") == b0["fingerprint"]:
            passed += 1
            continue
        if t is None:
            defects.append({"nodeid": k, "why": "missing at the fix head"})
            continue
        if "events" not in t or "events" not in b0:
            defects.append({"nodeid": k, "why": "fingerprint differs and no event lists to compare"})
            continue
        ea = [e for e in b0["events"] if e.get("o") not in declared]
        eb = [e for e in t["events"] if e.get("o") not in declared]
        if ea == eb and t.get("outcome") == b0.get("outcome"):
            allowed.append({"nodeid": k, "removed_kinds": sorted({e.get("o") for e in b0["events"] + t["events"]} & declared)})
        else:
            first = next((i for i, (x, y) in enumerate(zip(ea, eb)) if x != y), min(len(ea), len(eb)))
            defects.append({"nodeid": k, "why": "outcome differs" if t.get("outcome") != b0.get("outcome") else
                            f"undeclared event difference at index {first}",
                            "baseline_event": ea[first] if first < len(ea) else None,
                            "fix_event": eb[first] if first < len(eb) else None})
    return {"stable_in_baseline": len(stable), "passed": passed, "need_repeat": need_repeat if rep is None else [],
            "allowed_declared_only": allowed, "defects": defects, "declared": sorted(declared)}


def _outcome_maps(d, rounds=ROUNDS):
    """kind -> [ {nodeid: outcome} per round ]: plain, serial, par w2, par w4."""
    kinds = {"plain": "plain{i}", "serial": "S{i}", **{f"par w{n}": f"P{{i}}w{n}" for n in WORKERS}}
    out = {}
    for kind, pat in kinds.items():
        maps = []
        for i in rounds:
            e = _ext(d, pat.format(i=i))
            if e is not None:
                maps.append({k: v.get("outcome") for k, v in e.items() if k != "_dups"})
        out[kind] = maps
    return out


NORM = {"pending": "skipped", "todo": "skipped", "disabled": "skipped", "skip": "skipped", "pass": "passed", "fail": "failed"}


def variable_tests(d, rounds=ROUNDS):
    """Tests whose outcome varied across the baseline rounds of a plain or an engine run (per kind)."""
    var = {}
    for kind, maps in _outcome_maps(d, rounds).items():
        ids = set().union(*[set(m) for m in maps]) if maps else set()
        for k in ids:
            vals = {NORM.get(m.get(k), m.get(k)) for m in maps}
            if len(vals) > 1:
                var.setdefault(k, []).append(kind)
    return var


def _rows(d, repo):
    p = os.path.join(os.path.dirname(d.rstrip("/")), "results.jsonl")
    if not os.path.exists(p):
        return []
    return [r for r in (json.loads(x) for x in open(p) if x.strip()) if r.get("repo") == repo]


def rule3(base, fix, repo, rounds=ROUNDS):
    var = variable_tests(base, rounds)
    bm, fm = _outcome_maps(base, rounds), _outcome_maps(fix, rounds)
    defects = []
    for kind in bm:
        ref = {}
        for m in bm[kind]:
            for k, v in m.items():
                ref.setdefault(k, set()).add(NORM.get(v, v))
        for i, m in enumerate(fm.get(kind, [])):
            for k in sorted(set(ref) | set(m)):
                if k in var:
                    continue
                want = ref.get(k)
                got = NORM.get(m.get(k), m.get(k))
                if want is None or got not in want:
                    defects.append({"kind": kind, "fix_round": i + 1, "nodeid": k, "baseline": sorted(want or ["absent"]),
                                    "fix": got if got is not None else "absent"})
    br, fr = _rows(base, repo), _rows(fix, repo)
    exits, counts, false_green = [], [], []
    for r in br + fr:
        oc = r.get("outcome_counts") or {}
        if r.get("kind") in ("plain", "serial", "par") and (oc.get("failed") or 0) > 0 and r.get("exit") == 0:
            false_green.append({"dir": "baseline" if r in br else "fix", "kind": r["kind"], "rep": r["rep"], "workers": r["workers"]})
    for key in sorted({(r["kind"], r["workers"]) for r in br if r["kind"] in ("plain", "plain_par", "serial", "par")}):
        be = {r["exit"] for r in br if (r["kind"], r["workers"]) == key}
        for r in fr:
            if (r["kind"], r["workers"]) == key and r["exit"] not in be:
                exits.append({"kind": key[0], "workers": key[1], "rep": r["rep"], "baseline": sorted(be), "fix": r["exit"]})
        bc = [r.get("outcome_counts") or {} for r in br if (r["kind"], r["workers"]) == key]
        for r in fr:
            if (r["kind"], r["workers"]) != key:
                continue
            for c in set().union(*bc, r.get("outcome_counts") or {}):
                lo = min(x.get(c, 0) for x in bc)
                hi = max(x.get(c, 0) for x in bc)
                v = (r.get("outcome_counts") or {}).get(c, 0)
                if not lo <= v <= hi:
                    counts.append({"kind": key[0], "workers": key[1], "rep": r["rep"], "count": c, "baseline": [lo, hi], "fix": v})
    return {"variable": var, "defects": defects, "exit_defects": exits, "count_defects": counts, "false_green": false_green}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="baseline phase dir (e.g. harness/p2/data/baseline)")
    ap.add_argument("--fix", required=True, help="fix phase dir (e.g. harness/p2/data/fix-1)")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base-fixed", default="base1,base2,base3")
    ap.add_argument("--fix-fixed", default=None, help="LABEL[,REPEAT_LABEL]")
    ap.add_argument("--declared", default="", help="event kinds (o) the fix declared, comma list")
    ap.add_argument("--explain", default=None, help="JSON {nodeid: one-line explanation}")
    ap.add_argument("--json", default=None)
    o = ap.parse_args(argv)
    b, f = os.path.join(o.base, o.repo), os.path.join(o.fix, o.repo)
    explain = json.load(open(o.explain)) if o.explain else {}
    res = {"repo": o.repo, "rule1": [rule1(b, f, n, explain) for n in WORKERS], "rule3": rule3(b, f, o.repo)}
    if o.fix_fixed:
        lab = o.fix_fixed.split(",")
        res["rule2"] = rule2(b, o.base_fixed.split(","), f, lab[0], lab[1] if len(lab) > 1 else None,
                             [x for x in o.declared.split(",") if x])
    r2 = res.get("rule2") or {}
    res["ok"] = (all(not x["defects"] for x in res["rule1"]) and not r2.get("defects") and not r2.get("error")
                 and not r2.get("need_repeat") and not any(res["rule3"][k] for k in ("defects", "exit_defects", "count_defects", "false_green")))
    if o.json:
        with open(o.json, "w") as fh:
            json.dump(res, fh, indent=1, sort_keys=True)
    s = [f"{o.repo}: ok={res['ok']}"]
    for x in res["rule1"]:
        s.append(f"  rule1 w{x['w']}: rounds {x['rounds_base']}/{x['rounds_fix']}, VARIABLE-CLASS {len(x['variable_class'])}, changes {len(x['changes'])}, unexplained {len(x['defects'])}")
    if r2:
        s.append(f"  rule2: {r2.get('error') or ''}stable {r2.get('stable_in_baseline')}, passed {r2.get('passed')}, need repeat {len(r2.get('need_repeat') or [])}, declared-only {len(r2.get('allowed_declared_only') or [])}, defects {len(r2.get('defects') or [])}")
    r3 = res["rule3"]
    s.append(f"  rule3: VARIABLE {len(r3['variable'])}, outcome defects {len(r3['defects'])}, exit {len(r3['exit_defects'])}, counts {len(r3['count_defects'])}, failed-with-exit-0 {len(r3['false_green'])}")
    print("\n".join(s))
    return res


if __name__ == "__main__":
    sys.exit(0 if main().get("ok") else 1)
