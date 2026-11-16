#!/usr/bin/env python3
"""GitHub Actions driver of the Node harness (.github/workflows/node-harness.yml).

    candidates  -> matrix of candidate names (flaky pool first, then popular)
    select      -> first N per pool that passed the prepare filters (pools disjoint by repository)
    timing-pick -> up to n measured repositories for the quiet timing pass
    aggregate   -> harness/node/results/<set>/: per-repo files, REPORT.md, summary.json
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import shutil
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def emit(name: str, value) -> None:
    text = json.dumps(value)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"{name}={text}\n")
    print(f"{name}={text}")


def pools():
    cfg = json.loads((HERE / "repos.json").read_text())
    flaky = json.loads((HERE / cfg["flaky_candidates"]).read_text())["candidates"]
    return flaky, cfg["popular"]


def candidates(args) -> None:
    flaky, popular = pools()
    emit("matrix", [c["name"] for c in flaky[: args.flaky]] + [c["name"] for c in popular[: args.popular]])


def load(d: Path, pattern: str) -> list:
    return [json.loads(p.read_text()) for p in sorted(d.rglob(pattern))]


def repo_of(c: dict) -> str:
    return (c.get("repo") or c["url"].rstrip("/").split("github.com/")[-1]).lower()


def select(args) -> None:
    flaky, popular = pools()
    res = {r["name"]: r for r in load(Path(args.dir), "*.prepare.result.json")}
    chosen, discarded, used = [], [], set()
    for kind, pool in (("flaky", flaky), ("popular", popular)):
        n = 0
        for c in pool:
            r = res.get(c["name"])
            if r is None:
                continue
            if n >= args.per_pool:
                break
            if repo_of(c) in used:
                discarded.append({"name": c["name"], "kind": kind, "status": "duplicate", "detail": "repository already in the flaky pool"})
                continue
            if r.get("status") == "ok":
                chosen.append(c["name"])
                used.add(repo_of(c))
                n += 1
            else:
                discarded.append({"name": c["name"], "kind": kind, "status": r.get("status"), "detail": str(r.get("detail", ""))[-300:]})
    Path(args.selection).write_text(json.dumps({"selected": chosen, "discarded": discarded}, indent=1))
    emit("matrix", chosen)


def timing_pick(args) -> None:
    sel = json.loads(Path(args.selection).read_text())["selected"]
    ok = {r["name"] for r in load(Path(args.dir), "*.round.result.json") if r.get("status") == "ok"}
    picked = [n for n in sel if n in ok]
    # alternate pools so that both are represented
    flaky = {c["name"] for c in pools()[0]}
    a = [n for n in picked if n in flaky]
    b = [n for n in picked if n not in flaky]
    out = []
    while (a or b) and len(out) < args.n:
        for q in (a, b):
            if q and len(out) < args.n:
                out.append(q.pop(0))
    emit("matrix", out)


# ---------------------------------------------------------------------------
def _fmt(x, nd=1):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def _pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "n/a"


BUCKETS = ("0 (fixed order)", "1", "2-5", "6-10", "11-20", ">20")


def _bucket(n):
    return BUCKETS[0] if n == 0 else "1" if n == 1 else "2-5" if n <= 5 else "6-10" if n <= 10 else "11-20" if n <= 20 else ">20"


SUM = ("tests", "unstable_baseline", "unstable_det", "became_stable", "outcome_changed_by_det", "covered", "not_covered",
       "reproduced", "never_fails_under_det", "always_fails_under_det", "fails_sometimes_under_det", "known_flaky",
       "known_present", "known_unstable_baseline", "known_reproduced", "broken_by_det", "broken_always")
CAUSES = ("concurrency/event-order", "external", "l0-gap", "unknown")


def write_report(out: Path, meta: dict) -> Path:
    summaries = [json.loads(p.read_text()) for p in sorted(out.glob("*.summary.json"))]
    timings = [json.loads(p.read_text()) for p in sorted(out.glob("*.timing.json"))]
    sel = meta.get("selection", {})
    order = sel.get("selected", [])
    ok = sorted([s for s in summaries if s.get("status") == "ok"],
                key=lambda s: (s["kind"] != "flaky", order.index(s["name"]) if s["name"] in order else 1e9))
    failed_rounds = [r for r in meta.get("rounds", []) if r.get("status") != "ok"]
    tot = {k: collections.Counter() for k in ("all", "flaky", "popular")}
    reasons, pf, broken, seeds, causes = (collections.Counter() for _ in range(5))
    by_pool_causes = collections.defaultdict(collections.Counter)
    cause_rows = []
    broken_ex = collections.defaultdict(list)
    for s in ok:
        for k in SUM:
            tot["all"][k] += s.get(k, 0)
            tot[s["kind"]][k] += s.get(k, 0)
        reasons.update(s.get("reasons", {}))
        pf.update(s.get("pass_fail_reasons", {}))
        broken.update(s.get("broken_causes", {}))
        for k, ex in (s.get("broken_examples") or {}).items():
            broken_ex[k] += [f"{s['name']}: {e}" for e in ex][: max(0, 3 - len(broken_ex[k]))]
        seeds.update({"_": 0})
        for c, n in (s.get("not_reproduced_causes") or {}).items():
            causes[c] += n
            by_pool_causes[s["kind"]][c] += n
        cf = out / f"{s['name']}.causes.json"
        if cf.exists():
            cause_rows += json.loads(cf.read_text())
    seeds_needed = [v for s in ok for v in s.get("seeds_needed", [])]
    T = tot["all"]
    med = statistics.median
    L = [f"# detjs Level 0 (Node / TypeScript): measurement report (`{meta.get('set')}`)\n",
         f"Generated {meta.get('date')} with detjs {meta.get('detjs')} on {meta.get('executor')} "
         f"([run]({meta.get('run_url', '')})). Per repository: {meta.get('runs')} baseline runs interleaved with "
         f"{meta.get('runs')} `--det` runs. Baseline = the realistic configuration: random order with a different seed per "
         "run where the runner supports it (Vitest `--sequence.shuffle --sequence.seed=N`; Jest `--randomize --seed=N`, "
         "Jest >= 29.2 only) and two parallel workers (`--maxWorkers=2`). `--det` = fixed order (files sorted by path, "
         "tests in declaration order), one worker, files in sequence, all Level 0 controls. Then, for every test "
         f"unstable in the baseline, `--det --det-seed=1..{meta.get('seeds')}` with {meta.get('confirm')}/"
         f"{meta.get('confirm')} confirmation of the seed that makes it fail. Labels: MEASURED (by this harness), "
         "DECLARED (with source), UNKNOWN; NOISY = shared host.\n",
         f"Verifier: {', '.join(sorted({s.get('verifier', '?') for s in ok})) or 'n/a'}.\n",
         "## Main metric\n",
         f"**Baseline-unstable tests made reproducible: {T['reproduced']}/{T['unstable_baseline']} = "
         f"{_pct(T['reproduced'], T['unstable_baseline'])}** (MEASURED). A test counts as reproduced when some "
         f"`--det-seed` (or the fixed `--det` order) makes it fail {meta.get('confirm')} times out of {meta.get('confirm')} "
         "AND some `--det` configuration makes it pass.\n",
         "| pool | repositories | tests | unstable in baseline | reproduced | % | never fail under --det | "
         "always fail under --det | fail sometimes under --det |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for kind, label in (("flaky", "documented flaky"), ("popular", "popular (HEAD)"), ("all", "total")):
        t = tot[kind]
        n = len([s for s in ok if kind == "all" or s["kind"] == kind])
        if n:
            L.append(f"| {label} | {n} | {t['tests']} | {t['unstable_baseline']} | {t['reproduced']} | "
                     f"{_pct(t['reproduced'], t['unstable_baseline'])} | {t['never_fails_under_det']} | "
                     f"{t['always_fails_under_det']} | {t['fails_sometimes_under_det']} |")
    L.append("")
    if seeds_needed:
        b = collections.Counter(_bucket(v) for v in seeds_needed)
        L.append("**Seeds explored before the reproducing seed was found** (reproduced tests, MEASURED): "
                 + ", ".join(f"{k}: {b[k]}" for k in BUCKETS if b[k]) + f"; median {med(seeds_needed):.0f}.\n")
    if pf:
        L.append("**First diverging event between the fingerprints of a passing and a failing `--det` run** (MEASURED): "
                 + ", ".join(f"`{k}` {v}" for k, v in pf.most_common()) + ".\n")
    tf = tot["flaky"]
    L.append("## Documented flaky tests (MEASURED)\n")
    L.append("Documented = tests in the files changed by the flaky-test fix of the Hashemi et al. dataset, or matching the "
             "file/test named by the GitHub issue (issue titles often name no test: then nothing matches).\n")
    L.append("| documented flaky tests found in the measured projects | flaky in our baseline | reproduced |")
    L.append("|---:|---:|---:|")
    L.append(f"| {tf['known_present']} | {tf['known_unstable_baseline']} | {tf['known_reproduced']} |\n")
    L.append("## Causes of baseline-flaky tests not reproduced under `--det` (MEASURED, keyword heuristics)\n")
    L.append("Classes: `concurrency/event-order` (async ordering, timers racing real I/O, timeouts), `external` "
             "(network, processes, files, environment), `l0-gap` (a source Level 0 controls still differs, or shared "
             "state Level 0 should reset), `unknown`. Evidence per test in `<repo>.causes.json`.\n")
    L.append("| pool | " + " | ".join(CAUSES) + " |")
    L.append("|---|" + "---:|" * len(CAUSES))
    for kind in ("flaky", "popular"):
        c = by_pool_causes[kind]
        L.append(f"| {kind} | " + " | ".join(str(c[k]) for k in CAUSES) + " |")
    L.append("| total | " + " | ".join(str(causes[k]) for k in CAUSES) + " |\n")
    for k in CAUSES:
        ex = [r for r in cause_rows if r["class"] == k][:3]
        if ex:
            L.append(f"* `{k}`: " + "; ".join(f"{r['repo']} `{r['nodeid'][-90:]}` ({r['evidence'][:90]})" for r in ex))
    L.append("")
    L.append("## Tests broken by Level 0\n")
    L.append(f"A test is *broken by `--det`* when it fails in at least one fixed-order `--det` run but in at most one "
             f"baseline run (and less often than under `--det`). **{T['broken_by_det']} tests** (MEASURED), of which "
             f"{T['broken_always']} fail in every `--det` run."
             + (f" Before the L0 fixes: **{meta['broken_before']['broken_by_det']}** (MEASURED, {meta['broken_before']['date']})."
                if meta.get("broken_before") else "") + "\n")
    if broken:
        L.append("Cause: `fixed-order` = the test also fails under `--det` with every Level 0 control disabled (only the "
                 "fixed order and serial execution remain): an order/isolation dependency hidden by the random parallel "
                 "baseline, not a Level 0 control; otherwise the controls whose `--det-disable` makes it pass; "
                 "`unexplained` = none does.\n")
        L.append("| cause &#124; exception | tests | examples |")
        L.append("|---|---:|---|")
        for k, n in broken.most_common(15):
            L.append(f"| `{k.replace('|', '&#124;')}` | {n} | " + "<br>".join(e.replace("|", "/")[:200] for e in broken_ex[k][:2]) + " |")
        L.append("")
    L.append("## Timing\n")
    if timings:
        sl = [t["slowdown_pct"] for t in timings if t.get("slowdown_pct") is not None]
        mach = timings[0].get("machine", {})
        L.append(f"Quiet timing pass: {len(timings)} repositories, one per GitHub-hosted runner, "
                 f"{meta.get('timing_runs', 3)} serial runs without `--det` (one worker, runner's default order) vs "
                 f"{meta.get('timing_runs', 3)} `--det` runs, interleaved; median per repository. Machine: "
                 + ", ".join(f"{k}={v}" for k, v in mach.items()) + ". **DECLARED-NOISY** (shared virtual machines).\n")
        L.append(f"**Slowdown of `--det` (MEASURED, DECLARED-NOISY): median {_fmt(med(sl) if sl else None)}%**, "
                 f"min {_fmt(min(sl) if sl else None)}%, max {_fmt(max(sl) if sl else None)}%.\n")
        L.append("| repo | runner | tests | serial s (median) | --det s (median) | slowdown % |")
        L.append("|---|---|---:|---:|---:|---:|")
        for t in timings:
            L.append(f"| {t['name']} | {t.get('runner', '')} | {t['tests']} | {_fmt(med(t['serial_s']), 2)} | "
                     f"{_fmt(med(t['det_s']), 2)} | {_fmt(t.get('slowdown_pct'))} |")
        L.append("")
    else:
        L.append("Quiet timing pass: not run (UNKNOWN).\n")
    slow = [s["slowdown_pct"] for s in ok if s.get("slowdown_pct") == s.get("slowdown_pct") and s.get("slowdown_pct") is not None]
    L.append(f"* Round timings, serial `--det` vs the random parallel baseline: median {_fmt(med(slow) if slow else None)}% "
             "— **NOT COMPARABLE** (different parallelism and order).\n")
    L.append("## Other metrics (MEASURED)\n")
    L.append(f"* tests unstable under `--det` (fixed order, {meta.get('runs')} runs): {T['unstable_det']}; unstable in the "
             f"baseline and stable under `--det`: {T['became_stable']}")
    L.append(f"* stable in both modes but with a different majority outcome: {T['outcome_changed_by_det']}")
    L.append(f"* identical fingerprint in every fixed-order `--det` run (covered by Level 0): {T['covered']} "
             f"({_pct(T['covered'], T['covered'] + T['not_covered'])}); not covered: {T['not_covered']}"
             + (" (" + ", ".join(f"`{k}` {v}" for k, v in reasons.most_common()) + ")" if reasons else ""))
    L.append("")
    L.append("## Per repository (MEASURED)\n")
    L.append("| repo | pool | pinned at | node | runner | random baseline | tests | unstable | reproduced | seeds explored | "
             "broken by det | not covered | documented present / flaky / reproduced |")
    L.append("|---|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|")
    for s in ok:
        doc = f"{s['known_present']} / {s['known_unstable_baseline']} / {s['known_reproduced']}" if s["kind"] == "flaky" else ""
        src = s.get("documented_source") or ""
        pin = f"[{s['commit'][:10]}]({s['url']}/commit/{s['commit']})" + (f" ([doc]({src}))" if src else "")
        L.append(f"| [{s['name']}]({s['url']}) | {s['kind']} | {pin} | {s.get('node', '')} | {s.get('runner', '')} | "
                 f"{'yes' if s.get('random_order_baseline', True) else 'no (Jest < 29.2)'} | {s['tests']} | "
                 f"{s['unstable_baseline']} | {s['reproduced']} | {s['seeds_explored']}"
                 f"{' (budget)' if s.get('exploration_budget_hit') else ''} | {s.get('broken_by_det', 0)} | "
                 f"{s['not_covered']} | {doc} |")
    L.append("")
    disc = sel.get("discarded", []) + [{"name": r["name"], "kind": r.get("kind", ""), "status": r.get("status"),
                                        "detail": str(r.get("detail", ""))} for r in failed_rounds]
    if disc:
        L.append("## Discarded candidates\n")
        L.append("| repo | pool | reason | detail |")
        L.append("|---|---|---|---|")
        for d in disc:
            det = re.sub(r"\s+", " ", d.get("detail", ""))[-200:].replace("|", "/")
            L.append(f"| {d['name']} | {d.get('kind', '')} | {d.get('status')} | {det} |")
        L.append("")
    L.append("## Notes\n")
    for n in meta.get("notes", []):
        L.append(f"* {n}")
    path = out / "REPORT.md"
    path.write_text("\n".join(L) + "\n")
    (out / "summary.json").write_text(json.dumps({"meta": meta, "totals": {k: dict(v) for k, v in tot.items()},
                                                  "reasons": dict(reasons), "pass_fail_reasons": dict(pf),
                                                  "broken_causes": dict(broken), "not_reproduced_causes": dict(causes),
                                                  "timings": timings, "repos": ok}, indent=1, default=str))
    return path


NOTES = [
    "Flaky pool: the dataset of Hashemi, Tahir, Rasheed, 'An Empirical Study of Flaky Tests in JavaScript' (ICSME 2022, "
    "Zenodo 10.5281/zenodo.6673741) is the public dataset of JavaScript flaky tests used first: each project is pinned at "
    "the parent of a commit that fixes a flaky test. It covers only 18 projects, most of which do not run their suites with "
    "Jest or Vitest (Node core, Atom, Electron, Meteor, jQuery/QUnit, Karma suites), so it cannot supply 25 projects; the "
    "pool is completed with popular projects that have GitHub issues documenting flaky Jest/Vitest tests, each pinned at "
    "the last commit before the issue was opened.",
    "The JS-TOD (order-dependent Jest tests) and environmental-flakiness replication packages were not fetched.",
    "Only GitHub-hosted runners were used; numbers labelled NOISY come from shared virtual machines.",
]


def aggregate(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    art = Path(args.dir)
    for pat in ("*.csv", "*.summary.json", "*.timing.json", "*.causes.json", "*.result.json", "*.prepare.json"):
        for f in art.rglob(pat):
            shutil.copy(f, out / f.name)
    sel = json.loads(Path(args.selection).read_text()) if args.selection and Path(args.selection).exists() else {}
    rounds = load(out, "*.round.result.json")
    meta = {"set": args.set, "runs": args.runs, "seeds": args.seeds, "confirm": args.confirm, "timing_runs": 3,
            "executor": "GitHub Actions (ubuntu-latest)", "run_url": args.run_url,
            "detjs": json.loads((HERE.parent.parent / "node" / "package.json").read_text())["version"],
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "selection": sel, "rounds": rounds, "notes": NOTES}
    before = out / "broken-before.json"
    if before.exists():
        meta["broken_before"] = json.loads(before.read_text())
    print(write_report(out, meta))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates")
    c.add_argument("--flaky", type=int, default=60)
    c.add_argument("--popular", type=int, default=60)
    s = sub.add_parser("select")
    s.add_argument("--dir", required=True)
    s.add_argument("--per-pool", type=int, default=25)
    s.add_argument("--selection", required=True)
    t = sub.add_parser("timing-pick")
    t.add_argument("--dir", required=True)
    t.add_argument("--selection", required=True)
    t.add_argument("-n", type=int, default=10)
    a = sub.add_parser("aggregate")
    a.add_argument("--dir", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--selection", default=None)
    a.add_argument("--set", default="node")
    a.add_argument("--runs", type=int, default=10)
    a.add_argument("--seeds", type=int, default=20)
    a.add_argument("--confirm", type=int, default=10)
    a.add_argument("--run-url", default="")
    args = ap.parse_args()
    {"candidates": candidates, "select": select, "timing-pick": timing_pick, "aggregate": aggregate}[args.cmd](args)


if __name__ == "__main__":
    main()
