#!/usr/bin/env python3
"""P2 tables, printed only from raw `results.jsonl` rows (acceptance criterion 2).

  table.py baseline DIR [--title T]          one phase: BASELINE.md (also the final table of REPORT-P2.md)
  table.py compare DIR_A DIR_B [--labels a,b]  two phases side by side (refused across containers: `not comparable`)

Per repository (PREREG §5): PS = median plain wall; PP(w) = median plain_par wall; E(w) = median over rounds of
(par wall + verify wall of the same round and w); best = min over w; speedup = PS/PP_best; allowance =
min(1.3, speedup/2); meets = E_best <= allowance*PP_best and PS/E_best >= 2. Every value also on the cold round
(round 1). `meets` is also printed with E = par alone. Refusals: rows of one repository with more than one
(cpu_model, host, container_boot); a repository whose runs.log shows phases output (gate note 4).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import correctness  # noqa: E402

POOL = ["nestjs-pino", "agentsys", "alakajam", "agentlang", "yalc", "ironcurtain", "codex-multi-auth", "drydock", "lerna-lite"]
WORKERS = (2, 4)
PHASES_MARKERS = ("DETJS_PHASES", ".phases.jsonl")


class Refused(Exception):
    pass


def rows_of(d):
    p = os.path.join(d, "results.jsonl")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(x) for x in f if x.strip()]


def machine(rows):
    return {(r.get("cpu_model"), r.get("host"), r.get("container_boot")) for r in rows}


def phases_in_log(d, repo):
    for name in ("runs.log", "runs.log.gz"):
        p = os.path.join(d, repo, name)
        if os.path.exists(p):
            op = gzip.open if name.endswith(".gz") else open
            with op(p, "rt", errors="replace") as f:
                txt = f.read()
            return any(m in txt for m in PHASES_MARKERS)
    return False


def med(xs):
    return statistics.median(xs) if xs else None


def summarize(d, repo, rows):
    rr = [r for r in rows if r.get("repo") == repo]
    if not rr:
        env = os.path.join(d, repo, "ENV.txt")
        if os.path.exists(env):
            return {"repo": repo, "env": open(env).read().strip().splitlines()[0]}
        return {"repo": repo, "missing": True}
    m = machine(rr)
    if len(m) != 1:
        raise Refused(f"{repo}: rows from {len(m)} machines/containers {sorted(map(str, m))}")
    if phases_in_log(d, repo):
        raise Refused(f"{repo}: runs.log shows phases output (DETJS_PHASES reached a timed row)")
    reps = sorted({r["rep"] for r in rr})
    wall = lambda kind, w, i: next((r["wall_s"] for r in rr if r["kind"] == kind and r["workers"] == w and r["rep"] == i), None)
    ps = {i: wall("plain", 1, i) for i in reps}
    s1 = {i: wall("serial", 1, i) for i in reps}  # the engine at 1 worker (`--det --det-workers=1`)
    pp = {w: {i: wall("plain_par", w, i) for i in reps} for w in WORKERS}
    par = {w: {i: wall("par", w, i) for i in reps} for w in WORKERS}
    ver = {w: {i: wall("verify", w, i) for i in reps} for w in WORKERS}
    e = {w: {i: (par[w][i] + ver[w][i]) if par[w][i] is not None and ver[w][i] is not None else None for i in reps} for w in WORKERS}
    vals = lambda dct: [v for v in dct.values() if v is not None]
    s = {"repo": repo, "rounds": reps, "machine": next(iter(m)), "engine_commit": sorted({r.get("engine_commit") for r in rr}),
         "noisy": sum(1 for r in rr if r.get("noisy")), "complete": reps == [1, 2, 3] and all(
            len(vals(x[w])) == 3 for x in (pp, par, ver) for w in WORKERS) and len(vals(ps)) == 3,
         "invalid_plain": [r["rep"] for r in rr if r["kind"] == "plain" and r.get("invalid")]}
    for tag, pick in (("med", lambda dct: med(vals(dct))), ("cold", lambda dct: dct.get(1))):
        PS = pick(ps)
        S1 = pick(s1)
        PPw = {w: pick(pp[w]) for w in WORKERS}
        Ew = {w: pick(e[w]) for w in WORKERS}
        Pw = {w: pick(par[w]) for w in WORKERS}
        Vw = {w: pick(ver[w]) for w in WORKERS}
        best = lambda dct: min(((v, w) for w, v in dct.items() if v is not None), default=(None, None))
        PPb, PPw_best = best(PPw)
        Eb, Ew_best = best(Ew)
        Pb, Pw_best = best(Pw)
        x = {"PS": PS, "PP": PPw, "PP_best": PPb, "PP_w": PPw_best, "E": Ew, "par": Pw, "verify": Vw, "E_best": Eb,
             "E_w": Ew_best, "par_best": Pb, "par_w": Pw_best, "S1": S1}
        # founder rule R1 (2026-11-27): in serial the engine costs at most +5% over the plain serial run
        if PS and S1:
            x.update(S1_PS=S1 / PS, w1_within_5pct=S1 <= 1.05 * PS)
        if PS and PPb and Eb:
            sp = PS / PPb
            allow = min(1.3, sp / 2)
            x.update(speedup=sp, allowance=allow, E_PP=Eb / PPb, PS_E=PS / Eb,
                     meets=Eb <= allow * PPb and PS / Eb >= 2,
                     meets_par=(Pb <= allow * PPb and PS / Pb >= 2) if Pb else None)
        s[tag] = x
    # outcome counts per kind and w, with their spread over the rounds
    oc = {}
    for r in rr:
        if r["kind"] in ("plain", "plain_par", "serial", "par") and r.get("outcome_counts"):
            oc.setdefault((r["kind"], r["workers"]), []).append(r["outcome_counts"])
    s["counts"] = {}
    for key, lst in sorted(oc.items()):
        names = sorted(set().union(*lst))
        s["counts"][f"{key[0]} w{key[1]}"] = {c: (med([x.get(c, 0) for x in lst]), max(x.get(c, 0) for x in lst) - min(x.get(c, 0) for x in lst)) for c in names}
    s["exits"] = {f"{k} w{w}": sorted({r['exit'] for r in rr if r['kind'] == k and r['workers'] == w})
                  for k, w in sorted({(r["kind"], r["workers"]) for r in rr})}
    s["variable"] = correctness.variable_tests(os.path.join(d, repo))
    return s


f2 = lambda x: "-" if x is None else f"{x:.2f}"
yn = lambda x: "-" if x is None else ("yes" if x else "no")


def main_table(d, title, pool=POOL):
    rows = rows_of(d)
    out = [f"# {title}", "",
           f"Printed by `harness/p2/table.py baseline {os.path.relpath(d)}` from `results.jsonl` (every row carries its `cmd`). "
           "Seconds. Median of 3 rounds; `cold` = round 1 (engine state and node_modules caches cold for the engine rows). "
           "E = par + verify of the same round and w; best = min over w=2,4. allowance = min(1.3, speedup/2).", ""]
    sums, refused = [], []
    for repo in pool:
        try:
            sums.append(summarize(d, repo, rows))
        except Refused as e:
            refused.append(str(e))
    hdr = "| repo | PS | PP best (w) | speedup | allowance | E best (w) | par / verify at E's w | E/PP | PS/E | meets | meets (par only) |"
    out += ["## Bounds (median of 3 rounds; cold round in brackets)", "", hdr, "|" + "---|" * (hdr.count("|") - 1)]
    n_meet = n_meet_cold = 0
    for s in sums:
        if s.get("env"):
            out.append(f"| {s['repo']} | ENV: {s['env']} |" + " |" * 9)
            continue
        if s.get("missing"):
            out.append(f"| {s['repo']} | not measured |" + " |" * 9)
            continue
        m, c = s["med"], s["cold"]
        if "meets" not in m:
            out.append(f"| {s['repo']} | incomplete (rounds {s['rounds']}) |" + " |" * 9)
            continue
        n_meet += bool(m["meets"])
        n_meet_cold += bool(c.get("meets"))
        w = m["E_w"]
        out.append(f"| {s['repo']} | {f2(m['PS'])} [{f2(c['PS'])}] | {f2(m['PP_best'])} (w{m['PP_w']}) [{f2(c['PP_best'])}] | "
                   f"{f2(m['speedup'])} | {f2(m['allowance'])} | {f2(m['E_best'])} (w{w}) [{f2(c['E_best'])}] | "
                   f"{f2(m['par'][w])} / {f2(m['verify'][w])} [{f2(c['par'][w])} / {f2(c['verify'][w])}] | "
                   f"{f2(m['E_PP'])} [{f2(c.get('E_PP'))}] | {f2(m['PS_E'])} [{f2(c.get('PS_E'))}] | "
                   f"{yn(m['meets'])} [{yn(c.get('meets'))}] | {yn(m['meets_par'])} [{yn(c.get('meets_par'))}] |")
    out += ["", f"Repositories meeting both bounds: **{n_meet} of {len(pool)}** on the medians, {n_meet_cold} of {len(pool)} on the cold round.", ""]
    out += ["## The engine at 1 worker against plain serial (founder rule R1, 2026-11-27: at most +5%)", "",
            "S1 = the protocol's `serial` row (`--det --det-workers=1`), PS = the `plain` row; median of 3 [cold].", "",
            "| repo | PS | S1 | S1/PS | within +5% | PS/E |", "|---|---|---|---|---|---|"]
    for s in sums:
        if "med" not in s:
            continue
        m, c = s["med"], s["cold"]
        out.append(f"| {s['repo']} | {f2(m['PS'])} [{f2(c['PS'])}] | {f2(m.get('S1'))} [{f2(c.get('S1'))}] | "
                   f"{f2(m.get('S1_PS'))} [{f2(c.get('S1_PS'))}] | {yn(m.get('w1_within_5pct'))} [{yn(c.get('w1_within_5pct'))}] | "
                   f"{f2(m.get('PS_E'))} [{f2(c.get('PS_E'))}] |")
    out += [""]
    out += ["## Per worker count (median [cold])", "", "| repo | PP w2 | PP w4 | E w2 (par+verify) | E w4 (par+verify) | rounds | noisy rows | engine_commit | machine |", "|---|---|---|---|---|---|---|---|---|"]
    for s in sums:
        if "med" not in s:
            continue
        m, c = s["med"], s["cold"]
        ew = lambda w: f"{f2(m['E'][w])} ({f2(m['par'][w])}+{f2(m['verify'][w])}) [{f2(c['E'][w])}]"
        out.append(f"| {s['repo']} | {f2(m['PP'][2])} [{f2(c['PP'][2])}] | {f2(m['PP'][4])} [{f2(c['PP'][4])}] | {ew(2)} | {ew(4)} | "
                   f"{','.join(map(str, s['rounds']))}{'' if s['complete'] else ' INCOMPLETE'} | {s['noisy']} | {', '.join(s['engine_commit'])} | "
                   f"{s['machine'][0]} / {s['machine'][1]} / {s['machine'][2][:8]} |")
    out += ["", "## Outcome counts (median over rounds; spread = max - min) and exit codes", ""]
    for s in sums:
        if "counts" not in s:
            continue
        out.append(f"**{s['repo']}**" + (f" (plain run INVALID in round(s) {s['invalid_plain']})" if s["invalid_plain"] else ""))
        out.append("")
        out.append("| run | counts (median, spread) | exit codes |")
        out.append("|---|---|---|")
        for k, cs in s["counts"].items():
            out.append(f"| {k} | {', '.join(f'{c} {v[0]:g} (±{v[1]})' for c, v in cs.items())} | {s['exits'].get(k)} |")
        for k in ("verify w2", "verify w4"):
            if k in s["exits"]:
                out.append(f"| {k} | | {s['exits'][k]} |")
        out.append("")
        var = s["variable"]
        out.append(f"VARIABLE tests (outcome varied over the 3 rounds of one kind; excluded from correctness rule 3): {len(var)}")
        for k, kinds in sorted(var.items())[:40]:
            out.append(f"- `{k}` ({', '.join(kinds)})")
        if len(var) > 40:
            out.append(f"- ... {len(var) - 40} more (correctness.py prints all)")
        out.append("")
    if refused:
        out += ["## REFUSED", ""] + [f"- {x}" for x in refused] + [""]
    return "\n".join(out), sums


def compare(da, db, labels, pool=POOL):
    ra, rb = rows_of(da), rows_of(db)
    out = [f"# {labels[0]} vs {labels[1]}", "", f"`table.py compare {os.path.relpath(da)} {os.path.relpath(db)}`; median [cold].", "",
           f"| repo | E best {labels[0]} | E best {labels[1]} | saved (median) | saved (cold) | PS/E {labels[0]} → {labels[1]} | E/PP {labels[0]} → {labels[1]} | meets {labels[0]} → {labels[1]} | S1/PS {labels[0]} → {labels[1]} (≤ 1.05) |",
           "|---|---|---|---|---|---|---|---|---|"]
    for repo in pool:
        try:
            a, b = summarize(da, repo, ra), summarize(db, repo, rb)
        except Refused as e:
            out.append(f"| {repo} | REFUSED: {e} |" + " |" * 6)
            continue
        if "med" not in a or "med" not in b:
            out.append(f"| {repo} | {'ENV/missing' if 'med' not in a else ''} | {'ENV/missing' if 'med' not in b else ''} |" + " |" * 5)
            continue
        if a["machine"] != b["machine"]:
            out.append(f"| {repo} | not comparable (different container: {a['machine'][2][:8]} vs {b['machine'][2][:8]}) |" + " |" * 6)
            continue
        am, bm, ac, bc = a["med"], b["med"], a["cold"], b["cold"]
        out.append(f"| {repo} | {f2(am.get('E_best'))} [{f2(ac.get('E_best'))}] | {f2(bm.get('E_best'))} [{f2(bc.get('E_best'))}] | "
                   f"{f2((am.get('E_best') or 0) - (bm.get('E_best') or 0))} | {f2((ac.get('E_best') or 0) - (bc.get('E_best') or 0))} | "
                   f"{f2(am.get('PS_E'))} → {f2(bm.get('PS_E'))} | {f2(am.get('E_PP'))} → {f2(bm.get('E_PP'))} | "
                   f"{yn(am.get('meets'))} → {yn(bm.get('meets'))} [{yn(ac.get('meets'))} → {yn(bc.get('meets'))}] | "
                   f"{f2(am.get('S1_PS'))} → {f2(bm.get('S1_PS'))} ({yn(am.get('w1_within_5pct'))} → {yn(bm.get('w1_within_5pct'))}) |")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["baseline", "compare"])
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--title", default="P2 baseline (Phase A)")
    ap.add_argument("--labels", default="before,after")
    ap.add_argument("--repos", default=None, help="comma list (default: the 9 pool repositories)")
    ap.add_argument("--json", default=None)
    o = ap.parse_args(argv)
    pool = o.repos.split(",") if o.repos else POOL
    if o.mode == "baseline":
        txt, sums = main_table(o.dirs[0], o.title, pool)
        if o.json:
            with open(o.json, "w") as f:
                json.dump(sums, f, indent=1, default=str)
    else:
        txt = compare(o.dirs[0], o.dirs[1], o.labels.split(","), pool)
    print(txt)


if __name__ == "__main__":
    main()
