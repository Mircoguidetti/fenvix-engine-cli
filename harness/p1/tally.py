#!/usr/bin/env python3
"""P1 tally: classify the tests `fenvix verify` does not call identical into the P1 false-alarm items.

Usage: tally.py OUT REPO [--json FILE] [--e-dir DIR]

  OUT    measure.py's --out directory (holds results.jsonl and <REPO>/)
  REPO   the repository name (specs.json key)
  --json merge this repository's tally into FILE (a JSON object keyed by repository)
  --e-dir write, for each test counted under E, its fs.stat / fs.readdir* events from both traces to DIR

Round 1's `verify1w4.json` (serial S1 against parallel P1w4): each test that is not identical is counted once,
under the divergence verify reports for it. Categories, first match wins (docs/DESIGN-P1.md):

  A      input-differs naming a variable in the headers' meta.env_read_outside_tests (or any variable when that list
         holds "*", an enumeration: counted apart as A_only_via_enumeration), or a not-proven test whose
         description starts with "outside any test"
  B-tmp  run-level input `file:<tmp>/...` (meta.files_read_outside_tests) or a per-test `fs.read.outside` event
  B-abs  the same with a `<abs>/` path
  C      a divergent event with op `process.pid`
  D      a divergent event with source `entropy`
  E      the first divergent op is fs.stat / fs.readdir* on both sides and the test's events of those ops, sorted,
         are equal in both traces (only the order differs)
  F      reason `io`, or op `uncontrolled.io` / `io.release`, or a description containing either
  noise  none of the above, and not identical in round 2's serial-vs-serial verify_serial_noise2w1.json
  other  the rest, grouped by reason

A run-level input difference (any input but an environment variable) makes every test diverge and hides other
causes: the number of such tests is reported on its own (`run_level`), and they are classified by the first
differing input (file: -> B, anything else -> other).
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import os
import re
import sys

CATS = ["A", "B-tmp", "B-abs", "C", "D", "E", "F", "noise", "other"]
IDENTICAL = {"stable", "identical"}
E_OPS = re.compile(r"^fs\.(?:stat|readdir\w*|promises\.readdir)$")
F_OPS = {"uncontrolled.io", "io.release"}


def opn(path):
    """A file or its committed gzip copy (harness/p1/data/: files over 1 MB are gzipped)."""
    if not os.path.exists(path) and os.path.exists(path + ".gz"):
        return gzip.open(path + ".gz", "rt")
    return open(path)


def exists(path):
    return os.path.exists(path) or os.path.exists(path + ".gz")


def load(path):
    with opn(path) as f:
        return json.load(f)


def header(path):
    """The trace header: the trace (OUT from measure.py) or its committed first line (<name>.header.json)."""
    if not exists(path):
        path = path[: -len(".jsonl")] + ".header.json"
    with opn(path) as f:
        h = json.loads(f.readline())
    return h.get("meta", h)


def trace_events(path, ids):
    """nodeid -> events, for the tests in `ids` only (traces are large; not committed: E needs OUT)."""
    out = {}
    if not exists(path):
        return out
    with opn(path) as f:
        for line in f:
            if not line.startswith('{"type":"test"'):
                continue
            j = json.loads(line)
            if j.get("nodeid") in ids:
                out[j["nodeid"]] = j.get("events") or []
    return out


def ev_ops(d):
    return [e for e in (d.get("event_a"), d.get("event_b")) if e]


def input_names(desc):
    """The variable names of an input-differs description: 'input differs: A, B (read at x): ...'."""
    rest = desc.split("input differs: ", 1)[1] if "input differs: " in desc else ""
    rest = re.split(r" \(read at |: the test read", rest, maxsplit=1)[0]
    return [n.strip() for n in rest.split(",") if n.strip()]


def path_class(p):
    if p.startswith("<tmp>/"):
        return "B-tmp"
    if p.startswith("<abs>/"):
        return "B-abs"
    return None


def b_path(d):
    for e in ev_ops(d):
        o = e.get("o", "")
        if o.startswith("input.file:"):
            return o[len("input.file:"):]
        if o == "fs.read.outside":
            return e.get("v", "").split("|", 1)[0]
    return None


def classify(t, outside_env, f_and_e):
    d = t.get("divergence") or {}
    st = t["status"]
    desc = d.get("description", "") or ""
    evs = ev_ops(d)
    ops = {e.get("o", "") for e in evs}
    if st == "input-differs":
        names = input_names(desc)
        if any(n in outside_env for n in names):
            return "A"
        if "*" in outside_env and names:
            return "A*"  # counted under A: the environment was enumerated outside any test

    if st == "not-proven" and desc.startswith("outside any test"):
        return "A"
    p = b_path(d)
    if p and path_class(p):
        return path_class(p)
    if "process.pid" in ops:
        return "C"
    if any(e.get("s") == "entropy" for e in evs):
        return "D"
    if f_and_e.get("E") is not None and f_and_e["E"](t, d):
        return "E"
    if d.get("reason") == "io" or ops & F_OPS or any(x in desc for x in F_OPS):
        return "F"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("repo")
    ap.add_argument("--json")
    ap.add_argument("--e-dir")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--pair", choices=["par", "serial"], default="par",
                    help="par: verify<round>w4.json (S<round> vs P<round>w4, the default); serial: "
                         "verify_serial_noise2w1.json (S1 vs S2: what a run-level difference hides in the other pair)")
    o = ap.parse_args()
    base = os.path.join(o.out, o.repo)
    vpath = os.path.join(base, f"verify{o.round}w4.json" if o.pair == "par" else "verify_serial_noise2w1.json")
    v = load(vpath)
    npath = os.path.join(base, "verify_serial_noise2w1.json")
    noise = load(npath) if exists(npath) and o.pair == "par" else None
    noise_tests = {t["nodeid"]: t for t in (noise or {}).get("tests", []) if t["status"] not in IDENTICAL}
    noisy = set(noise_tests)
    s_path, p_path = os.path.join(base, f"S{o.round}.jsonl"), os.path.join(base, f"P{o.round}w4.jsonl")
    if o.pair == "serial":
        s_path, p_path = os.path.join(base, "S1.jsonl"), os.path.join(base, "S2.jsonl")
    hs, hp = header(s_path), header(p_path)
    outside_env = set(hs.get("env_read_outside_tests") or []) | set(hp.get("env_read_outside_tests") or [])

    bad = [t for t in v["tests"] if t["status"] not in IDENTICAL]
    # E needs the traces: the tests whose first divergent op is fs.stat / fs.readdir* on both sides
    e_cand = set()
    for t in bad:
        d = t.get("divergence") or {}
        a, b = d.get("event_a"), d.get("event_b")
        if a and b and E_OPS.match(a.get("o", "")) and E_OPS.match(b.get("o", "")):
            e_cand.add(t["nodeid"])
    s_ev = trace_events(s_path, e_cand) if e_cand else {}
    p_ev = trace_events(p_path, e_cand) if e_cand else {}
    e_name = "events.json" if o.round == 1 else f"events-round{o.round}.json"
    committed = os.path.join(base, "E", e_name)
    if e_cand and not exists(s_path) and os.path.exists(committed) and o.pair == "par":
        # the committed data: the fs.stat / fs.readdir* events of each E test, both traces (written by --e-dir)
        ev = load(committed)
        s_ev = {k: v["serial"] for k, v in ev.items()}
        p_ev = {k: v["parallel"] for k, v in ev.items()}

    def e_sel(evs):
        return sorted((e.get("o"), e.get("at"), e.get("v")) for e in evs if E_OPS.match(e.get("o", "")))

    e_events = {}

    def is_e(t, d):
        n = t["nodeid"]
        if n not in e_cand:
            return False
        a, b = e_sel(s_ev.get(n, [])), e_sel(p_ev.get(n, []))
        if a and a == b:
            e_events[n] = {"serial": [e for e in s_ev[n] if E_OPS.match(e.get("o", ""))],
                           "parallel": [e for e in p_ev[n] if E_OPS.match(e.get("o", ""))]}
            return True
        return False

    counts = collections.Counter()
    noise_in = collections.Counter()
    other = collections.Counter()
    abs_paths = collections.Counter()
    status_of = collections.defaultdict(collections.Counter)
    f_detail = collections.Counter()
    run_level = 0
    a_star = 0
    noise_hidden = collections.Counter()
    noise_hidden_reason = collections.Counter()
    run_level_first = collections.Counter()
    examples = collections.defaultdict(list)
    for t in bad:
        d = t.get("divergence") or {}
        if any(e.get("o", "").startswith("input.") and not e.get("o", "").startswith("input.env:") for e in ev_ops(d)):
            run_level += 1
            run_level_first[ev_ops(d)[0].get("o")] += 1
        c = classify(t, outside_env, {"E": is_e})
        if c == "A*":
            a_star += 1
            c = "A"
        if c is None:
            c = "noise" if t["nodeid"] in noisy else "other"
            if c == "other":
                other[d.get("reason", t["status"])] += 1
            else:
                # the serial-vs-serial verdict of a noise test may itself be an A-F false alarm (A or B make every
                # test of both pairs not identical): then it is no evidence of noise; counted apart, with the reason
                # the S1-vs-P1 verdict gives
                nc = classify(noise_tests[t["nodeid"]], outside_env, {})
                nc = "A" if nc == "A*" else nc
                if nc:
                    noise_hidden[nc] += 1
                    noise_hidden_reason[d.get("reason", t["status"])] += 1
        counts[c] += 1
        status_of[c][t["status"]] += 1
        if t["nodeid"] in noisy:
            noise_in[c] += 1
        if c == "B-abs":
            abs_paths[b_path(d)] += 1
        if c == "F":
            ops = sorted({e.get("o") for e in ev_ops(d)})
            f_detail[f"{t['status']} {','.join(ops) or d.get('reason')}"] += 1
        if len(examples[c]) < 3:
            ev = (ev_ops(d) or [{}])[0]
            examples[c].append({"nodeid": t["nodeid"], "status": t["status"], "reason": d.get("reason"),
                                "op": ev.get("o"), "at": ev.get("at"), "description": (d.get("description") or "")[:300]})

    rpath = os.path.join(o.out, "results.jsonl")
    if not os.path.exists(rpath):
        rpath = os.path.join(base, "results.jsonl")  # the committed copy: the repository's rows only
    rows = [json.loads(l) for l in open(rpath) if l.strip()]
    rows = [r for r in rows if r.get("repo") == o.repo]
    vrow = next((r for r in rows if (r.get("kind"), r.get("rep"), r.get("workers")) ==
                 (("verify", o.round, 4) if o.pair == "par" else ("verify_serial_noise", 2, 1))), {})
    res = {
        "repo": o.repo,
        "pair": o.pair,
        "engine_commit": sorted({r.get("engine_commit") for r in rows if r.get("engine_commit")}),
        "verify_cmd": vrow.get("cmd"),
        "verify_file": os.path.relpath(vpath, o.out),
        "noise_file": os.path.relpath(npath, o.out) if noise else None,
        "tests": len(v["tests"]),
        "identical": sum(1 for t in v["tests"] if t["status"] in IDENTICAL),
        "not_identical": len(bad),
        "summary": v.get("summary"),
        "counts": {c: counts.get(c, 0) for c in CATS},
        "also_not_identical_serial_vs_serial": {c: noise_in.get(c, 0) for c in CATS},
        "status_by_category": {c: dict(status_of[c]) for c in CATS if status_of[c]},
        "run_level": run_level,
        "A_only_via_enumeration": a_star,
        "run_level_first_input": dict(run_level_first),
        "input_differences": [x.get("name") for x in v.get("input_differences", [])],
        "noise_pair_not_identical": len(noisy) if noise else None,
        "other_by_reason": dict(other.most_common()),
        "noise_whose_serial_pair_verdict_is_A_F": dict(noise_hidden),
        "noise_whose_serial_pair_verdict_is_A_F_by_reason": dict(noise_hidden_reason.most_common()),
        "F_detail": dict(f_detail.most_common()),
        "B_abs_top20": abs_paths.most_common(20),
        "env_read_outside_tests": len(outside_env),
        "examples": dict(examples),
    }
    if o.e_dir and e_events:
        os.makedirs(o.e_dir, exist_ok=True)
        with open(os.path.join(o.e_dir, e_name), "w") as f:
            json.dump(e_events, f, indent=1, sort_keys=True)
    if o.json:
        allr = load(o.json) if os.path.exists(o.json) else {}
        allr[o.repo] = res
        with open(o.json, "w") as f:
            json.dump(allr, f, indent=1, sort_keys=True)
    json.dump({k: res[k] for k in ("repo", "engine_commit", "tests", "not_identical", "counts", "run_level",
                                   "also_not_identical_serial_vs_serial", "other_by_reason")}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
