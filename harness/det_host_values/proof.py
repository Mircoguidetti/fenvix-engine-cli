#!/usr/bin/env python3
"""Step 3 proof table (AC3), printed from the raw rows of measure.py:

    <dir>/<repo>/<engine>/results.jsonl            rows kind serial / par / verify (one round, --workers nproc)
    <dir>/<repo>/<engine>/<repo>/verify1w<N>.json   `fenvix verify S1 P1w<N> --json`, per-test verdicts

Per repository and engine: tests run, proven identical, NOT PROVEN, not identical, failed, exit code and wall time of
the --det parallel run; then the bounds of AC3 and every test identical on the trunk but not on the branch, with the
branch's verdict and reason.

    python3 harness/det_host_values/proof.py <dir>
"""
import gzip
import json
import os
import sys

REPOS = ["nestjs-pino", "agentsys", "claudekit", "sqlectron", "ironcurtain", "codex-multi-auth"]
ENGINES = ["trunk", "branch"]


def load(d, repo, eng):
    p = os.path.join(d, repo, eng, "results.jsonl")
    if not os.path.exists(p):
        return None
    rows = [json.loads(x) for x in open(p) if x.strip()]
    rows = [r for r in rows if r.get("repo") == repo]
    par = next((r for r in rows if r["kind"] == "par"), None)
    ser = next((r for r in rows if r["kind"] == "serial"), None)
    ver = next((r for r in rows if r["kind"] == "verify"), None)
    rep = {}
    if par:
        vp = os.path.join(d, repo, eng, repo, f"verify{par['rep']}w{par['workers']}.json")
        if os.path.exists(vp):
            rep = json.load(open(vp))
        elif os.path.exists(vp + ".gz"):
            rep = json.load(gzip.open(vp + ".gz", "rt"))
    return {"par": par, "ser": ser, "ver": ver, "rep": rep}


def tests_by_status(rep):
    return {t["nodeid"]: t for t in rep.get("tests", [])}


def main(d):
    print("| repository | engine | engine commit | tests run | proven identical | NOT PROVEN | not identical | input differs | failed (par) | exit (par) | wall s (par) | wall s (serial) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    data = {}
    for repo in REPOS:
        for eng in ENGINES:
            x = load(d, repo, eng)
            data[(repo, eng)] = x
            if not x or not x["par"]:
                print(f"| {repo} | {eng} | (not measured) |||||||||")
                continue
            s = (x["ver"] or {}).get("summary") or {}
            oc = x["par"]["outcome_counts"] or {}
            print(f"| {repo} | {eng} | {x['par']['engine_commit'][:12]} | {x['par']['tests']} | {s.get('identical')} | "
                  f"{s.get('not_proven')} | {s.get('diverged')} | {s.get('input_differs')} | "
                  f"{oc.get('failed', 0) + oc.get('error', 0)} | {x['par']['exit']} | {x['par']['wall_s']} | "
                  f"{x['ser']['wall_s'] if x['ser'] else ''} |")
    print("\n## AC3 bounds\n")
    print("| repository | identical trunk / branch | allowed drop (0.5% of tests) | identical | exit trunk -> branch | wall par branch / trunk (<= 1.10) |")
    print("|---|---|---|---|---|---|")
    details = []
    for repo in REPOS:
        t, b = data[(repo, "trunk")], data[(repo, "branch")]
        if not (t and b and t["par"] and b["par"] and t["ver"] and b["ver"]):
            print(f"| {repo} | (incomplete) |||||")
            continue
        it, ib = t["ver"]["summary"]["identical"], b["ver"]["summary"]["identical"]
        allow = 0.005 * b["par"]["tests"]
        ok_id = "met" if ib >= it - allow else "MISSED"
        ex = f"{t['par']['exit']} -> {b['par']['exit']}" + (" (CHECK)" if t["par"]["exit"] == 0 and b["par"]["exit"] != 0 else "")
        ratio = b["par"]["wall_s"] / t["par"]["wall_s"] if t["par"]["wall_s"] else 0
        print(f"| {repo} | {it} / {ib} | {allow:.1f} | {ok_id} | {ex} | {ratio:.3f} {'met' if ratio <= 1.10 else 'MISSED'} |")
        tt, tb = tests_by_status(t["rep"]), tests_by_status(b["rep"])
        lost = sorted(n for n, x in tt.items() if x.get("status") == "stable" and tb.get(n, {}).get("status") != "stable")
        gained = sorted(n for n, x in tb.items() if x.get("status") == "stable" and tt.get(n, {}).get("status") != "stable")
        details.append(f"\n### {repo}: identical on the trunk, not on the branch ({len(lost)}); the reverse: {len(gained)}\n")
        if lost:
            details.append("| test | branch status | reason | description |\n|---|---|---|---|")
            for n in lost:
                x = tb.get(n, {})
                dv = x.get("divergence") or {}
                details.append(f"| `{n[:150]}` | {x.get('status', 'absent')} | {dv.get('reason', '')} | "
                               f"`{str(dv.get('description', ''))[:220]}` |")
    print("\n".join(details))


if __name__ == "__main__":
    main(sys.argv[1])
