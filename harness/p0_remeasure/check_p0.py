#!/usr/bin/env python3
"""P0 re-measure checker: does an engine run give a false green, drop tests from the user report, or miss tests in
its trace?

Usage: check_p0.py OUT REPO --phase before|after [--results PATH]

Reads what harness/parallel_measure/measure.py wrote under OUT (results.jsonl, REPO/runs.log, REPO/S<i>.jsonl,
REPO/P<i>w<N>.jsonl, REPO/plain<i>.ids.json) and writes one row per engine run (kind serial or par) to
harness/p0_remeasure/results.jsonl (or --results), after removing the rows of the same (repo, phase) there.

  C1 false green (runs): a completed run with exit 0 and a trace record whose outcome is not passed/skipped/todo, or a
     status with failed > 0 or not_proven > 0, or a NOT PROVEN file.
  C2 dropped from the user report (tests): max(0, P - S), P = tests of the round's plain run, S = the four counts of
     the run's status line. C2_runs: runs with no status or more than one status line.
  C3 missing from the trace (tests): plain-run ids absent from the trace's ids.

A run is completed when its exit is 0 or 1 and its trace exists; other runs count in none of C1-C3. Of several
results.jsonl rows with the same (repo, kind, rep, workers) the last counts; the earlier ones are `superseded`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "parallel_measure"))
import measure  # noqa: E402  (harness/parallel_measure/measure.py: trace_tests, ids_outcomes, runner_outcomes, ...)

DEFAULT_RESULTS = os.path.join(HERE, "results.jsonl")
STATUS_RE = re.compile(r"^detjs: status: failed=(\d+) not_proven=(\d+) passed=(\d+) skipped=(\d+)$")
NOT_WRITTEN = "detjs: status: not written"
NP_RE = re.compile(r"^detjs: parallel: NOT PROVEN (.+): the one-lane re-run did not account for its tests \((.*)\)$")
GREEN = {"passed", "skipped", "todo"}
NEVER_STARTED = "sched.never_started"
UNKNOWN = "UNKNOWN"
FAIL_RE = re.compile(r"(\bFAIL\b|×|✗|AssertionError|\bError:|NOT PROVEN)")


def read_rows(path, repo):
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if line.strip():
                    j = json.loads(line)
                    if j.get("repo") == repo:
                        rows.append(j)
    return rows


def log_blocks(path):
    """runs.log -> {header line: [lines of its last block]}. A block starts at a line `$ (cd <cwd> && <cmd>)  # exit`
    and ends before the next line starting with `$ (cd ` or `# build after reset:`."""
    blocks, cur = {}, None
    if not os.path.exists(path):
        return blocks
    with open(path, errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n").rstrip("\r")
            if line.startswith("$ (cd ") or line.startswith("# build after reset:"):
                cur = None
                if line.startswith("$ (cd "):
                    cur = []
                    blocks[line] = cur  # a later block with the same header replaces the earlier one
                continue
            if cur is not None:
                cur.append(line)
    return blocks


def block_for(blocks, row):
    prefix = f"$ (cd {row.get('cwd')} && {row.get('cmd')})  # exit"
    hit = None
    for header, lines in blocks.items():  # dict order = order of first appearance; content = last block
        if header.startswith(prefix):
            hit = lines
    return hit


def read_trace(path):
    """Raw trace lines -> (header, records [(nodeid, outcome, never_started)])."""
    header, recs = None, []
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            j = json.loads(line)
            if j.get("type") == "header":
                header = j
            elif j.get("type") == "test":
                ns = any(isinstance(e, dict) and e.get("o") == NEVER_STARTED for e in (j.get("events") or []))
                recs.append((j.get("nodeid"), j.get("outcome"), ns))
    return header, recs


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def status_of(block, meta):
    """-> (status dict or None, status_from, reason or None)."""
    lines = block or []
    if any(l.startswith(NOT_WRITTEN) for l in lines):
        return None, None, "no status"
    found = [m for m in (STATUS_RE.match(l) for l in lines) if m]
    if len(found) > 1:
        return None, "log", "duplicate status"
    if len(found) == 1:
        f, np, p, s = (int(x) for x in found[0].groups())
        return {"failed": f, "not_proven": np, "passed": p, "skipped": s}, "log", None
    ms = (meta or {}).get("status")
    if isinstance(ms, dict) and all(k in ms for k in ("failed", "not_proven", "passed", "skipped")):
        return {k: int(ms[k]) for k in ("failed", "not_proven", "passed", "skipped")}, "meta", None
    return None, None, "no status"


def not_proven_files(meta, block):
    out = {}
    hr = (meta or {}).get("hazard_rerun") or {}
    for x in hr.get("not_proven") or []:
        if isinstance(x, dict) and x.get("file") is not None:
            out.setdefault(x["file"], {"file": x["file"], "cause": x.get("cause"), "source": "meta"})
    for l in block or []:
        m = NP_RE.match(l)
        if m and m.group(1) not in out:
            out[m.group(1)] = {"file": m.group(1), "cause": m.group(2), "source": "log"}
    return list(out.values())


def plain_ids(out_repo, rep, plain_row, cwd):
    """-> (ids dict or None, P or None, unknown reason or None)."""
    ids_path = os.path.join(out_repo, f"plain{rep}.ids.json")
    runner_path = os.path.join(out_repo, f"plain{rep}.runner.json")
    reason, a = None, None
    if plain_row is None:
        reason = f"no plain row for round {rep}"
    elif plain_row.get("invalid"):
        reason = "plain run INVALID: " + str(plain_row["invalid"])
    if os.path.exists(ids_path):
        a = measure.ids_outcomes(ids_path, cwd=cwd)
    else:
        reason = reason or f"plain ids file missing: {ids_path}"
    if a is not None:
        P = len(a)
    else:
        fb = measure.runner_outcomes(runner_path, cwd) if os.path.exists(runner_path) else {}
        P = len(fb) if fb else None
    return a, P, reason


def first_failure(block):
    for l in block or []:
        if FAIL_RE.search(l):
            return l[:400]
    return None


def check_run(row, out_repo, blocks, plain_row, verify_row, phase):
    kind, rep, n = row["kind"], row["rep"], row.get("workers", 1)
    trace = os.path.join(out_repo, f"S{rep}.jsonl" if kind == "serial" else f"P{rep}w{n}.jsonl")
    res = {"repo": row["repo"], "phase": phase, "engine_commit": row.get("engine_commit"), "kind": kind,
           "workers": n, "rep": rep, "exit": row.get("exit"), "wall_s": row.get("wall_s"), "cmd": row.get("cmd"),
           "cwd": row.get("cwd"), "ts": row.get("ts"), "trace": os.path.basename(trace), "superseded": False}
    if verify_row is not None:
        res["verify_verdict"] = verify_row.get("verdict")
        res["verify_exit"] = verify_row.get("exit")
    elif kind == "par":
        res["verify_verdict"], res["verify_exit"] = None, None
    exists = os.path.exists(trace)
    res["completed"] = row.get("exit") in (0, 1) and exists
    if not res["completed"]:
        res["not_completed_reason"] = f"exit {row.get('exit')}" + ("" if exists else ", no trace")
        for k in ("C1", "C2", "C2_runs", "C3"):
            res[k] = None
        return res
    res["trace_sha256"] = sha256(trace)
    header, recs = read_trace(trace)
    meta = (header or {}).get("meta") or {}
    block = block_for(blocks, row)
    res["log_block_found"] = block is not None
    status, sfrom, sreason = status_of(block, meta)
    res["status"], res["status_from"], res["status_reason"] = status, sfrom, sreason
    nps = not_proven_files(meta, block)
    res["not_proven_files"] = nps
    bad = [(i, o) for i, o, _ in recs if o not in GREEN]
    res["bad_records"] = len(bad)
    res["bad_record_ids"] = [f"{i} [{o}]" for i, o in bad[:20]]
    res["never_started"] = sum(1 for _, _, ns in recs if ns)
    _, tt = measure.trace_tests(trace)
    b = {k: v[0] for k, v in tt.items()}
    D = len(b)
    res["D"] = D
    res["trace_records"] = len(recs)
    S = sum(status.values()) if status else None
    res["S"] = S
    res["S_minus_D"] = (S - D) if S is not None else None

    green_fail = bool(bad) or bool(nps) or (status is not None and (status["failed"] > 0 or status["not_proven"] > 0))
    res["C1"] = 1 if (row.get("exit") == 0 and green_fail) else 0

    a, P, unk = plain_ids(out_repo, rep, plain_row, row.get("cwd"))
    res["P"] = P
    if unk is None:
        cmp_ = measure.compare_outcomes(a, b)
        if cmp_.get("unknown"):
            unk = cmp_["unknown"]
    if unk is not None:
        res["C3"], res["C3_reason"], res["missing_ids"] = UNKNOWN, unk, []
    else:
        missing = sorted(set(a) - set(b))
        res["C3"], res["missing_ids"] = len(missing), missing[:20]

    if phase == "before":
        res["C2"], res["C2_runs"], res["C2_reason"] = None, None, "n/a: pre-P0 engine"
    elif unk is not None:
        res["C2"], res["C2_runs"], res["C2_reason"] = UNKNOWN, (1 if sreason else 0), unk
    elif sreason is not None:
        res["C2"], res["C2_runs"], res["C2_reason"] = None, 1, sreason
    else:
        res["C2"], res["C2_runs"] = max(0, P - S), 0
    if res["C1"] or res["C3"] or (res["C2"] not in (0, None)) or res["C2_runs"]:
        res["first_failure_line"] = first_failure(block)
    return res


def check(out, repo, phase):
    out_repo = os.path.join(out, repo)
    rows = read_rows(os.path.join(out, "results.jsonl"), repo)
    blocks = log_blocks(os.path.join(out_repo, "runs.log"))
    last, superseded = {}, []
    for r in rows:
        if r.get("kind") in ("serial", "par"):
            key = (r["kind"], r["rep"], r.get("workers", 1))
            if key in last:
                superseded.append(last[key])
            last[key] = r
    plain = {}
    verify = {}
    for r in rows:
        if r.get("kind") == "plain":
            plain[r["rep"]] = r
        elif r.get("kind") == "verify":
            verify[(r["rep"], r.get("workers"))] = r
    results = []
    for key in sorted(last, key=lambda k: (k[1], k[0] != "serial", k[2])):
        r = last[key]
        vr = verify.get((r["rep"], r.get("workers"))) if r["kind"] == "par" else None
        results.append(check_run(r, out_repo, blocks, plain.get(r["rep"]), vr, phase))
    for r in superseded:
        results.append({"repo": repo, "phase": phase, "engine_commit": r.get("engine_commit"), "kind": r["kind"],
                        "workers": r.get("workers", 1), "rep": r["rep"], "exit": r.get("exit"),
                        "wall_s": r.get("wall_s"), "cmd": r.get("cmd"), "ts": r.get("ts"), "superseded": True,
                        "completed": None, "C1": None, "C2": None, "C2_runs": None, "C3": None})
    return results


def totals(results):
    live = [r for r in results if not r["superseded"] and r["completed"]]
    t = {"runs": len([r for r in results if not r["superseded"]]), "completed": len(live),
         "not_completed": [(r["kind"], r["rep"], r["workers"], r["exit"]) for r in results
                           if not r["superseded"] and not r["completed"]],
         "C1": sum(r["C1"] for r in live)}
    c2 = [r["C2"] for r in live]
    if live and all(r.get("C2_reason") == "n/a: pre-P0 engine" for r in live):
        t["C2"], t["C2_runs"] = None, None
    else:
        t["C2"] = UNKNOWN if UNKNOWN in c2 else sum(x for x in c2 if isinstance(x, int))
        t["C2_runs"] = sum(r["C2_runs"] or 0 for r in live)
    c3 = [r["C3"] for r in live]
    t["C3"] = UNKNOWN if UNKNOWN in c3 else sum(c3)
    return t


def write(results, path, repo, phase):
    kept = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if line.strip():
                    j = json.loads(line)
                    if not (j.get("repo") == repo and j.get("phase") == phase):
                        kept.append(line.rstrip("\n"))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        for line in kept:
            f.write(line + "\n")
        for r in results:
            f.write(json.dumps(r) + "\n")


def table(results, repo, phase):
    st = lambda s: "-" if not s else f"f={s['failed']} np={s['not_proven']} p={s['passed']} s={s['skipped']}"
    print(f"## {repo} ({phase})")
    print("| kind | w | rep | exit | wall_s | status (from) | D | P | C1 | C2 | C2_runs | C3 | NOT PROVEN | never_started | verify |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        if r["superseded"]:
            print(f"| {r['kind']} | {r['workers']} | {r['rep']} | {r['exit']} | {r['wall_s']} | superseded | | | | | | | | | |")
            continue
        if not r["completed"]:
            print(f"| {r['kind']} | {r['workers']} | {r['rep']} | {r['exit']} | {r['wall_s']} | NOT COMPLETED ({r['not_completed_reason']}) | | | | | | | | | |")
            continue
        sf = st(r["status"]) + (f" ({r['status_from']})" if r["status_from"] else f" ({r['status_reason']})")
        c2 = r["C2"] if r["C2"] is not None else (r.get("C2_reason") or "-")
        c3 = r["C3"] if r["C3"] != UNKNOWN else f"UNKNOWN: {r['C3_reason']}"
        ver = f"{r.get('verify_verdict')} (exit {r.get('verify_exit')})" if r["kind"] == "par" else "-"
        print(f"| {r['kind']} | {r['workers']} | {r['rep']} | {r['exit']} | {r['wall_s']} | {sf} | {r['D']} | {r['P']} | "
              f"{r['C1']} | {c2} | {r['C2_runs']} | {c3} | {len(r['not_proven_files'])} | {r['never_started']} | {ver} |")
    print("totals: " + json.dumps(totals(results)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("repo")
    ap.add_argument("--phase", choices=("before", "after"), required=True)
    ap.add_argument("--results", default=DEFAULT_RESULTS)
    o = ap.parse_args(argv)
    results = check(o.out, o.repo, o.phase)
    write(results, o.results, o.repo, o.phase)
    table(results, o.repo, o.phase)
    return 0


if __name__ == "__main__":
    sys.exit(main())
