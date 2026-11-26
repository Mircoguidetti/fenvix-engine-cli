#!/usr/bin/env python3
"""Print REPORT.md from the committed raw rows (AC3): python3 harness/db_serial_count/report.py [--write]."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discover  # noqa: E402
import perworker  # noqa: E402
import rules as R  # noqa: E402
import status as S  # noqa: E402

RES = HERE / "results"
COVERED = "Jest, Vitest, Mocha, node:test, pytest (incl. tox/nox), Django manage.py test, Rails minitest, RSpec, Go"
STACK = {"jest": "Node/Jest", "vitest": "Node/Vitest", "mocha": "Node/Mocha", "node": "Node/node:test",
         "pytest": "Python/pytest", "django": "Python/Django", "rails": "Ruby/Rails minitest", "rspec": "Ruby/RSpec",
         "go": "Go"}


def q(vals, p):
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    return v[f] + (v[c] - v[f]) * (k - f)


def best_pair(row):
    ps = [p for p in row.get("pairs") or [] if p.get("stage") == "ge_10"]
    return max(ps, key=lambda p: p["timing"]["median_s"]) if ps else None


def build() -> str:
    out = []
    w = out.append
    rows = S.load_rows()
    c = S.counts(rows)
    leaves = discover.read_leaves()
    splits = perworker.read_jsonl(RES / "discovery" / "splits.jsonl")
    dstate = json.loads((RES / "discovery_state.json").read_text()) if (RES / "discovery_state.json").exists() else {}
    order, pool = discover.build(leaves) if leaves else ([], {})
    chunks = perworker.read_jsonl(RES / "chunks.jsonl")
    st = S.state()
    nup = st["N_upper"]
    dec = ("CONTINUE" if c["qualifying"] >= 20 else "DROP" if st["drop"] else "NO DECISION")
    budget = json.loads((HERE / "budget.json").read_text()) if (HERE / "budget.json").exists() else {}
    finished = dec != "NO DECISION" or budget.get("ended")
    w("DONE" if finished else "NOT DONE")
    w("")
    w("# DB serial count: REPORT")
    w("")
    w("Printed by `python3 harness/db_serial_count/report.py` from the committed raw rows (`results/`). Rules: "
      "`PREREG.md`.")
    w("")
    ch = HERE / "CHANGES.md"
    w("## Changes after PREREG (listed before any result)")
    w("")
    w(ch.read_text().strip() if ch.exists() else "None.")
    w("")
    w("## Decision")
    w("")
    if dec == "CONTINUE":
        w("`CONTINUE: 20 repositories meet the line.`")
    elif dec == "DROP":
        w(f"`DROP: {c['qualifying']} of {c['read']} read qualify; upper estimate {st['estimate']:.1f} (< 20).`")
    else:
        w(f"`NO DECISION: budget reached; {c['qualifying']} of {c['read']} read qualify; upper estimate "
          f"{st['estimate']:.1f}.`" if finished else
          f"`(in progress) {c['qualifying']} of {c['read']} read qualify; upper estimate {st['estimate']:.1f}.`")
    w("")
    qual = [r for r in rows if S.final_class(r) == "qualifying"]
    rs = Counter(best_pair(r)["timing"]["reason"] for r in qual)
    w(f"- qualifying by reason: declared {rs['declared']}, explicit {rs['explicit']}, default-serial "
      f"{rs['default-serial']}")
    w(f"- read {c['read']}, qualifying {c['qualifying']}, uncertain {c['uncertain']}, pending §4 "
      f"{c['pending_perworker']}, not qualifying {c['not_qualifying']} (per_worker {c['per_worker']}, hand check "
      f"failed {c['handcheck_failed']}), excluded {c['excluded']}")
    w(f"- U (Wilson 95% upper bound of (qualifying + uncertain + pending) / read) = {st['U']:.6f}; N_upper = {nup}; "
      f"U x N_upper = {st['estimate']:.2f}; DROP needs >= 300 read, no incomplete leaf "
      f"({'some' if st['any_incomplete'] else 'none'} incomplete), U x N_upper < 20; DROP reachable at q = 0 after "
      f"{st['drop_reachable']} reads")
    w("- DROP frame: keyword-discoverable, indexed public repositories with a database term and a runner term in the "
      "same workflow file (GitHub legacy code search, default branches)")
    w(f"- covered runners: {COVERED}; not covered: PHPUnit/Laravel, Maven/Gradle, others")
    w("")
    w("## Pool and feasibility")
    w("")
    rpc = [x["requests_per_candidate"] for x in chunks if x.get("requests_per_candidate")]
    k = rpc[0] if rpc else 11
    lim = next((x["rate_limit"].get("core") for x in chunks if (x.get("rate_limit") or {}).get("core")), None)
    if pool:
        est = round(k * pool["candidates"])
        fits = lim and est <= 24 * lim
        w(f"`pool: {pool['candidates']} candidates, N_upper {pool['N_upper']}, N_files {pool['N_files']}, rate limit "
          f"{lim or 'n/a'}/h, estimated REST requests {est} ({k} per candidate{' observed in chunk 1' if rpc else ', before chunk 1'}), "
          f"fits 24 h: {'yes' if fits else 'no'}, DROP reachable at q = 0 after {R.drop_reachable(pool['N_upper'])} reads`")
        w("")
        w(f"Discovery: route `{dstate.get('route')}`, started {dstate.get('started')}, finished "
          f"{dstate.get('finished')}; {len(splits)} split searches, {pool['leaves']} leaves, "
          f"{pool['truncated_leaves']} truncated, {pool['incomplete_leaves']} incomplete; distinct (repo, path) "
          f"{pool['distinct_files']} + {pool['truncated_missing']} unread in truncated leaves = N_files "
          f"{pool['N_files']}.")
    w("")
    w("## Funnel")
    w("")
    w("### Discovery per query")
    w("")
    w("| query | root total_count | leaves | sum leaf max(total_count, read) | results read | truncated leaves |")
    w("|---|---|---|---|---|---|")
    byq = defaultdict(list)
    for lf in leaves:
        byq[lf["query"]].append(lf)
    for qd in discover.queries():
        ls = byq.get(qd["key"], [])
        root = (dstate.get("queries", {}).get(qd["key"]) or {}).get("root_total")
        w(f"| `{qd['q']}` | {root} | {len(ls)} | {R.n_upper(ls)} | {sum(x.get('read') or 0 for x in ls)} | "
          f"{sum(1 for x in ls if x.get('truncated'))} |")
    w("")
    tr = [lf for lf in leaves if lf.get("truncated")]
    if tr:
        w("Truncated leaves (they make the count a lower bound): " + "; ".join(
            f"`{x['query']}` size:{x['a']}..{x['b']} total_count {x['total_count']} read {x['read']}"
            f"{' INCOMPLETE' if x.get('incomplete') else ''}" for x in tr))
        w("")
    w("### Candidates")
    w("")
    excl = Counter(e for r in rows if r.get("cls") == "excluded" for e in r.get("excluded", []))
    readrows = [r for r in rows if r.get("cls") != "excluded"]
    rank = {s: i for i, s in enumerate(pipeline_stages())}

    def reached(s):
        return sum(1 for r in readrows if r.get("furthest") and rank.get(r["furthest"], -1) >= rank[s])
    unres = Counter(r.get("stage") for r in readrows if r.get("cls") == "uncertain")
    w(f"- candidates in pool: {len(order)}; taken in §1 order so far: {len(rows)}")
    w(f"- excluded: {sum(1 for r in rows if r.get('cls') == 'excluded')} (fork {excl['fork']}, archived "
      f"{excl['archived']}, owner {excl['owner']}, stale {excl['stale']}; a row can have several)")
    w(f"- read: {len(readrows)}")
    w(f"- database job found: {reached('no_test_step')}")
    w(f"- uncertain rows: {sum(unres.values())} (unresolved {unres['unresolved']}, unsupported "
      f"{unres['unsupported']}, error {unres['error']})")
    w(f"- test step found: {reached('not_serial')}")
    w(f"- serial: {reached('too_few_runs')}")
    w(f"- timed (10 runs): {reached('below_10')}")
    w(f"- >= 10 min: {reached('ge_10')}")
    w(f"- per_worker: {c['per_worker']}")
    w(f"- qualifying: {c['qualifying']}")
    w("")
    w("## Per stack")
    w("")
    w("| stack | qualifying | median step minutes (median, Q1-Q3) | declared / explicit / default-serial |")
    w("|---|---|---|---|")
    bys = defaultdict(list)
    for r in qual:
        bys[STACK.get(best_pair(r)["timing"]["kind"], "?")].append(best_pair(r)["timing"])
    for s, ts in sorted(bys.items()):
        m = [t["median_s"] / 60 for t in ts]
        rr = Counter(t["reason"] for t in ts)
        w(f"| {s} | {len(ts)} | {statistics.median(m):.1f} ({q(m, .25):.1f}-{q(m, .75):.1f}) | "
          f"{rr['declared']} / {rr['explicit']} / {rr['default-serial']} |")
    w("")
    w("## Qualifying list")
    w("")
    w("| repository | stack | reason | median step min | last run | wrapped | sharded | workflow / job |")
    w("|---|---|---|---|---|---|---|---|")
    for r in qual:
        p = best_pair(r)
        t = p["timing"]
        w(f"| {r['html_url']} | {STACK.get(t['kind'], '?')} | {t['reason']} | {t['median_s'] / 60:.1f} | "
          f"{(t.get('last_run') or '')[:10]} | {'yes' if t.get('wrapped') else 'no'} | "
          f"{'yes' if p.get('sharded') else 'no'} | `{p['file']}` / `{p['job']}` |")
    w("")
    pwl = [r for r in rows if S.final_class(r) == "per_worker"]
    if pwl:
        w("## per_worker exclusions")
        w("")
        for r in pwl:
            w(f"- {r['html_url']}: " + "; ".join(r["perworker"]["evidence"][:3]))
        w("")
    hcl = perworker.read_jsonl(HERE / "handcheck.jsonl")
    if hcl:
        last = {}
        for x in hcl:
            last[(x["category"], x["repo"].lower())] = x
        w("## AC4 hand checks")
        w("")
        w("From `handcheck.jsonl` (last record per repository and category; evidence printed by `handcheck_show.py` "
          "from the committed raw responses). qualifying: pass = the >= 10 min step is serial and uses the database; "
          "a fail makes the row not qualifying. serial_reject: the first 10 rows (in §1 order) rejected at the serial "
          "stage; pass = the step really runs tests concurrently. per_worker: pass = the §4 hit is a per-worker "
          "database.")
        w("")
        for cat in ("qualifying", "serial_reject", "per_worker"):
            xs = [x for (k, _), x in last.items() if k == cat]
            w(f"### {cat}: {sum(1 for x in xs if x['pass'])} pass, {sum(1 for x in xs if not x['pass'])} fail")
            w("")
            for x in sorted(xs, key=lambda x: (x["pass"], x["checked_at"])):
                w(f"- {'PASS' if x['pass'] else 'FAIL'} {x['repo']}: {x['note']}")
            w("")
    w("## Chunks")
    w("")
    for x in chunks:
        w(f"- chunk {x['chunk']}: {x['candidates']} candidates, {x['requests']} requests "
          f"({x.get('requests_per_candidate')} per candidate), {x['minutes']} min, rate limit "
          f"{(x.get('rate_limit') or {}).get('core')}/h, stopped: {x.get('stopped')}")
    w("")
    w("## Limits")
    w("")
    w("- Default branches only; GitHub Actions only; public repositories indexed by legacy code search only.")
    w("- Truncated leaves (listed above) hide files: the count is a lower bound; N_upper counts file hits, so the DROP "
      "estimate errs toward not dropping.")
    w(f"- Runners not covered: PHPUnit/Laravel, Maven/Gradle, others. Covered: {COVERED}.")
    w("- Rule limits found by the hand checks (no rule was changed; each can move a row either way):")
    w("  - the runner regex also matches after a hyphen and in prose (echo, comments, SystemExit text), so a "
      "flag in a comment can decide a step (spatiumddi);")
    w("  - shlex tokenizing hides flags inside a quoted `sh -c \"...\"`, e.g. pytest `-n` there is not seen "
      "(sbomify, counted serial, hand check failed);")
    w("  - the database is detected per job, not per step: a serial step in a database job can run no database "
      "tests (aelys: SQLite step);")
    w("  - a step with several runner lines is serial if any of them is serial (tim-ai-platform);")
    w("  - Vitest multi-project configs: a per-project `fileParallelism` setting is read as global (plur);")
    w("  - Go: `-p 1` serializes packages but `t.Parallel` inside a package is not inspected; a single-package "
      "`go test` without `-p 1` is counted not serial although it runs in order (Tengrinews);")
    w("  - node:test: a single-file `node --test` is counted not serial although it runs one file in order "
      "(articweb3);")
    w("  - §4 over-excludes: a database created per test or per scenario (`CREATE DATABASE ... "
      "TEMPLATE`, fresh-database fixtures), worker-id skip guards and doc comments count as per-worker evidence (7 of 10 per_worker hand checks failed); these rows "
      "stay excluded, so the qualifying count is a lower bound.")
    w("- Process: commits from 2026-11-25 22:36Z on are authored under the founder's git identity at the "
      "coordinator's instruction (GitHub shows them Unverified); earlier commits were not rewritten. Commit "
      "trailers name the agent session.")
    return "\n".join(out) + "\n"


def pipeline_stages():
    import pipeline
    return pipeline.STAGES


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    txt = build()
    if a.write:
        (HERE / "REPORT.md").write_text(txt)
    else:
        sys.stdout.write(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
