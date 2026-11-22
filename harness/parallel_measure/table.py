#!/usr/bin/env python3
"""TABLE.md from results.jsonl (and specs.json): one row per repository, medians of the runs.

Usage: table.py results.jsonl specs.json > TABLE.md
"""
from __future__ import annotations

import json
import statistics
import sys


def med(xs):
    return round(statistics.median(xs), 2) if xs else None


def main():
    rows = [json.loads(x) for x in open(sys.argv[1]) if x.strip()]
    specs = json.load(open(sys.argv[2]))
    repos = []
    for r in rows:
        if r["repo"] not in repos:
            repos.append(r["repo"])
    print("| repo | pinned commit | runner | tests | plain serial s (median, n) | `--det` serial s (median) | "
          "parallel with proof s (median, n) | speedup vs plain serial | cores | outcome map identical (plain serial vs parallel, every run) | "
          "engine verdict (parallel vs serial, per run) | cause named when not identical | serial noise (S1 vs S2) | NOISY runs | engine commit |")
    print("|" + "---|" * 15)
    for name in repos:
        rr = [r for r in rows if r["repo"] == name]
        sp = specs.get(name, {})
        get = lambda k: [r for r in rr if r["kind"] == k]
        plain, serial, par, ver, noise = get("plain"), get("serial"), get("par"), get("verify"), get("verify_serial_noise")
        ok = lambda L: [r["wall_s"] for r in L if r["exit"] not in (124,)]
        mp, ms, mpar = med(ok(plain)), med(ok(serial)), med(ok(par))
        tests = sorted({r.get("tests") for r in par + plain if r.get("tests")})
        ident = []
        verdicts = []
        causes = {}
        for v in ver:
            oc = v.get("outcomes_plain_vs_par") or v.get("outcomes_trace_vs_trace") or {}
            ident.append("yes" if oc.get("identical") else f"no ({oc.get('differ')} differ, {oc.get('n_only_a')}/{oc.get('n_only_b')} missing)")
            s = v.get("summary") or {}
            if v["exit"] == 0:
                verdicts.append("identical")
            elif v["exit"] == 3:
                verdicts.append("input differs")
            elif s.get("diverged"):
                verdicts.append(f"diverged {s['diverged']}/{s['tests']}, not proven {s.get('not_proven', 0)}")
            elif s.get("not_proven"):
                verdicts.append(f"not proven {s['not_proven']}/{s['tests']}")
            else:
                verdicts.append(f"exit {v['exit']}")
            for k, n in (s.get("reasons") or {}).items():
                causes[k] = max(causes.get(k, 0), n)
        nz = ""
        if noise:
            s = noise[0].get("summary") or {}
            nz = "identical" if noise[0]["exit"] == 0 else f"exit {noise[0]['exit']}: " + ", ".join(f"{k} {n}" for k, n in sorted((s.get('reasons') or {}).items()))
        noisy = sum(1 for r in rr if r.get("noisy"))
        commits = sorted({r["engine_commit"][:8] for r in rr})
        cores = sorted({r["workers"] for r in par})
        print(f"| {name} | {sp.get('commit', '')[:10]} | {rr[0]['runner']} | {', '.join(map(str, tests))} | "
              f"{mp} ({len(ok(plain))}) | {ms} | {mpar} ({len(ok(par))}) | "
              f"{round(mp / mpar, 2) if mp and mpar else ''}x | {', '.join(map(str, cores))} of {rr[0]['cpus']} | {'; '.join(ident)} | "
              f"{'; '.join(verdicts)} | {', '.join(f'{k} {n}' for k, n in sorted(causes.items())) or '-'} | {nz} | {noisy} | "
              f"{', '.join(commits)} |")


if __name__ == "__main__":
    main()
