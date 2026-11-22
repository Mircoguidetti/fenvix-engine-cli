#!/usr/bin/env python3
"""TABLE.md from results.jsonl and specs.json: one row per (repository, parallel worker count), medians of the rounds.

Row state (one of):
  IDENTICAL AND FASTER       outcome map identical to plain serial in every round, engine verdict identical in every
                             round, parallel-with-proof median faster than the plain serial median
  IDENTICAL, NOT FASTER      as above, not faster
  OUTCOME IDENTICAL, VERDICT NOT PROVEN / DIVERGED
                             the outcome maps agree, the engine did not prove it (the cause is named)
  OUTCOME DIFFERS            the outcome maps disagree in at least one round
Every number is MEASURED by the command in results.jsonl (`cmd`).

Usage: table.py results.jsonl specs.json > TABLE.md
"""
from __future__ import annotations

import json
import statistics
import sys


def med(xs):
    return round(statistics.median(xs), 2) if xs else None


def verdict_of(v):
    s = v.get("summary") or {}
    if v["exit"] == 0:
        return "identical"
    if v["exit"] == 3:
        return "input differs"
    parts = []
    if s.get("diverged"):
        parts.append(f"diverged {s['diverged']}")
    if s.get("not_proven"):
        parts.append(f"not proven {s['not_proven']}")
    if s.get("missing"):
        parts.append(f"missing {s['missing']}")
    return (", ".join(parts) or f"exit {v['exit']}") + f" of {s.get('tests', '?')} (identical {s.get('identical', 0)})"


def main():
    rows = [json.loads(x) for x in open(sys.argv[1]) if x.strip()]
    import os
    base = os.path.dirname(os.path.abspath(sys.argv[1]))

    def classification(name):
        try:
            return json.load(open(os.path.join(base, name, "classification.json")))["summary"]
        except (OSError, ValueError, KeyError):
            return None
    specs = json.load(open(sys.argv[2]))
    repos = []
    for r in rows:
        if r["repo"] not in repos:
            repos.append(r["repo"])
    hdr = ["repo", "pinned commit", "runner", "CI mode (DECLARED)", "in plan verdict", "tests", "plain serial s",
           "runner's own parallel s (no engine)", "`--det` serial s", "workers", "parallel with proof s",
           "speedup vs plain serial", "outcome map identical (per test id, every round)", "engine verdict (per round)",
           "causes named (max per round)", "serial noise (S1 vs S2)", "row state", "engine state", "NOISY runs",
           "nproc / CPU", "engine commit", "boxes (classify.py)", "counts (rule)"]
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for name in repos:
        rr = [r for r in rows if r["repo"] == name]
        sp = specs.get(name, {})
        ok = lambda L: [r["wall_s"] for r in L if r["exit"] != 124 and not r.get("invalid")]
        get = lambda k, n=None: [r for r in rr if r["kind"] == k and (n is None or r["workers"] == n)]
        plain, serial, noise = get("plain"), get("serial"), get("verify_serial_noise")
        mp, ms = med(ok(plain)), med(ok(serial))
        nz = "-"
        if noise:
            s = noise[0].get("summary") or {}
            nz = "identical" if noise[0]["exit"] == 0 else verdict_of(noise[0]) + ": " + ", ".join(
                f"{k} {n}" for k, n in sorted((s.get("reasons") or {}).items()))
        for n in sorted({r["workers"] for r in get("par")}):
            par, ver, pp = get("par", n), get("verify", n), get("plain_par", n)
            mpar = med(ok(par))
            tests = sorted({r.get("tests") for r in par if r.get("tests")})
            ident, verdicts, causes = [], [], {}
            for v in ver:
                oc = v.get("outcomes_plain_vs_par") or {}
                ident.append(oc.get("identical"))
                verdicts.append(verdict_of(v))
                for k, c in ((v.get("summary") or {}).get("reasons") or {}).items():
                    causes[k] = max(causes.get(k, 0), c)
            all_ident = bool(ident) and all(ident)
            all_proven = bool(ver) and all(v["exit"] == 0 for v in ver)
            faster = bool(mp and mpar and mpar < mp)
            if any(r.get("invalid") for r in plain):
                state = "INVALID (plain run: " + next(r["invalid"] for r in plain if r.get("invalid")) + ")"
            elif not tests:
                state = "DID NOT RUN (no test in the parallel trace)"
            elif any(x is None for x in ident):
                state = "OUTCOME COMPARISON UNKNOWN (plain ids cannot be matched: Vitest projects)"
            elif not all_ident:
                state = "OUTCOME DIFFERS"
            elif all_proven:
                state = "IDENTICAL AND FASTER" if faster else "IDENTICAL, NOT FASTER"
            else:
                state = "OUTCOME IDENTICAL, VERDICT " + ("DIVERGED" if any("diverged" in x for x in verdicts) else "NOT PROVEN")
            idtxt = "; ".join("yes" if x else ("UNKNOWN" if x is None else "no") for x in ident)
            for v in ver:
                oc = v.get("outcomes_plain_vs_par") or {}
                if not oc.get("identical"):
                    idtxt += f" (round {v['rep']}: {oc.get('differ')} differ, {oc.get('n_only_a')} only plain, {oc.get('n_only_b')} only parallel)"
            states = sorted({r.get("engine_state", "?") for r in par + serial})
            noisy = sum(1 for r in rr if r.get("noisy"))
            cells = [name, sp.get("commit", "")[:10], rr[0]["runner"], "parallel" if sp.get("ci_parallel") else "serial",
                     "yes" if sp.get("plan_verdict") else "no: " + sp.get("why_outside", ""),
                     ", ".join(map(str, tests)), f"{mp} ({len(ok(plain))})",
                     f"{med(ok(pp))} ({len(ok(pp))})" if pp else "-", f"{ms} ({len(ok(serial))})", str(n),
                     f"{mpar} ({len(ok(par))})", f"{round(mp / mpar, 2)}x" if mp and mpar else "-", idtxt,
                     "; ".join(verdicts),
                     ", ".join(f"{k} {c}" for k, c in sorted(causes.items())) or "-", nz, state,
                     "round 1 cold, later warm" if states == ["cold", "warm"] else "/".join(states), str(noisy),
                     f"{rr[0].get('nproc', rr[0]['cpus'])} / {rr[0].get('cpu_model', '?')}",
                     ", ".join(sorted({r["engine_commit"][:8] for r in rr}))]
            cl = classification(name)
            boxes = ", ".join(f"{k} {v}" for k, v in sorted((cl or {}).get("boxes", {}).items())) if cl else "not classified"
            # counting rule (coordinator, 2026-11-22): identical and faster; or all of (1)-(4)
            if state == "IDENTICAL AND FASTER":
                counts = "yes (identical and faster)"
            elif cl is None:
                counts = "no: not classified"
            else:
                fails = []
                if not faster:
                    fails.append("(1) not faster than plain serial (re-run included)")
                b = cl.get("boxes", {})
                if any(b.get(k) for k in ("OURS", "UNDECIDED")):
                    fails.append(f"(2) OURS {b.get('OURS', 0)}, UNDECIDED {b.get('UNDECIDED', 0)}")
                if b.get("ENV"):
                    fails.append(f"(3) ENV {b['ENV']}")
                r = cl.get("rule", {})
                if not r.get("THEIRS_all_reproduced", True):
                    fails.append("(3) a THEIRS test not reproduced")
                if not r.get("THEIRS_reported_equal_or_named", True):
                    fails.append("(4) a THEIRS outcome reported differently and not named")
                counts = "yes (rule 1-4)" if not fails else "no: " + "; ".join(fails)
            cells += [boxes, counts]
            print("| " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
