#!/usr/bin/env python3
"""Compose docs/REPORT-node-l0.md from the harness results (harness/node/results/node) and
the "before the L0 fixes" measurements. Every number is taken from the result files.

    python harness/node/final_report.py
"""
from __future__ import annotations

import collections
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
import sys
RES = HERE / "results" / (sys.argv[1] if len(sys.argv) > 1 else "node-final")
OUT = ROOT / "docs" / "REPORT-node-l0.md"


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "n/a"


def fmt(x, nd=1):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


def load(d: Path, pat: str):
    return [json.loads(p.read_text()) for p in sorted(d.glob(pat))]


def main() -> None:
    summary = json.loads((RES / "summary.json").read_text())
    meta = summary["meta"]
    repos = summary["repos"]
    tot = summary["totals"]
    T, F, P = (collections.Counter(tot.get(k, {})) for k in ("all", "flaky", "popular"))
    pw = [s for s in load(RES, "*.summary.json") if s.get("kind") == "playwright" and s.get("status") == "ok"]
    sel = meta.get("selection", {})
    discards = sel.get("discarded", []) + [r for r in meta.get("rounds", []) if r.get("status") != "ok"]
    timings = summary.get("timings", [])
    causes = collections.Counter(summary.get("not_reproduced_causes", {}))
    reasons = summary.get("reasons", {})
    pf = summary.get("pass_fail_reasons", {})
    broken = summary.get("broken_causes", {})
    before_runs = []
    # Latest earlier measurement of each project (later sets override earlier ones): the rounds stopped on
    # earlier shells, then the full round on d3075a1 and its re-runs before the last fixes.
    for d in ("node-before-fixes", "node-before-fixes-2", "node-before-fixes-3", "node", "node-rerun", "node-rerun2"):
        before_runs += [s for s in load(HERE / "results" / d, "*.summary.json")]
    before_by = {s["name"]: s for s in before_runs}
    inactive = {}
    for d, n in (("node-rerun", "babel-flaky"), ("node", "prettier-flaky")):
        f = HERE / "results" / d / f"{n}.summary.json"
        if f.exists():
            inactive[n] = json.loads(f.read_text())
    now_by = {s["name"]: s for s in repos}
    common = sorted(set(before_by) & set(now_by))
    seeds = [v for s in repos for v in s.get("seeds_needed", [])]
    nflaky = sum(1 for s in repos if s["kind"] == "flaky")
    npop = sum(1 for s in repos if s["kind"] == "popular")
    runners = collections.Counter(s.get("runner", "?").split()[0] for s in repos)
    sl = [t["slowdown_pct"] for t in timings if t.get("slowdown_pct") is not None]

    L = []
    A = L.append
    A("# Node L0 (detjs) — final report\n")
    A("Session node-l0, 2026-11-16. Repository fenvix-engine-cli, branch `claude/node-l0`. Labels: MEASURED (this "
      "work), ESTIMATED, DECLARED (with source), UNKNOWN; NOISY = shared host (GitHub-hosted runners).\n")
    A("## Summary\n")
    A(f"* **Main metric (MEASURED):** baseline-unstable tests made reproducible by `--det` / `--det-seed`: "
      f"**{T['reproduced']}/{T['unstable_baseline']} = {pct(T['reproduced'], T['unstable_baseline'])}** over "
      f"{len(repos)} projects ({nflaky} with documented flaky tests, {npop} popular at HEAD; "
      + ", ".join(f"{k} {v}" for k, v in runners.items()) + "). Documented-flaky pool: "
      f"{F['reproduced']}/{F['unstable_baseline']} = {pct(F['reproduced'], F['unstable_baseline'])}; popular pool: "
      f"{P['reproduced']}/{P['unstable_baseline']} = {pct(P['reproduced'], P['unstable_baseline'])}.")
    A(f"* **Fingerprint coverage (MEASURED):** {T['covered']} tests had an identical fingerprint in every fixed-order "
      f"`--det` run, {T['not_covered']} did not ({pct(T['covered'], T['covered'] + T['not_covered'])} covered)"
      + (": " + ", ".join(f"`{k}` {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])) if reasons else "") + ".")
    A(f"* **Tests broken by `--det` (MEASURED):** {T['broken_by_det']} after the L0 fixes of this session, "
      f"{T['broken_always']} of them failing in every `--det` run.")
    if sl:
        A(f"* **Slowdown of `--det` (MEASURED, DECLARED-NOISY):** median {fmt(statistics.median(sl))}% over "
          f"{len(sl)} projects (serial runner without `--det` vs `--det`, quiet timing pass).")
    A(f"* **Playwright (MEASURED, measured only):** {len(pw)} projects; see the Playwright section.")
    A(f"* Shell tests: per-control tests for Vitest and Jest, 20/20 pass locally and on CI (MEASURED).\n")

    A("## What was built (steps 1–3)\n")
    A("Details in `docs/NODE.md` and `docs/REPORT-node-l0-INTERMEDIATE-1.md`.\n")
    A("* `crates/detpy-node`: napi-rs bindings of `detpy-core` (Recorder with batched events, Cassette, verifier, "
      "seeds, hierarchical shuffle, trace merge). Same trace and cassette format as Python; the harness verifies Node "
      "traces with the Python binding of the same Rust verifier, and CI checks `python -m detpy verify` on a Node trace.")
    A("* Core: shared event vocabulary cherry-picked from the L1 study branch (2ec240f, encoding 2, with its "
      "prerequisite `Source::Sched`); additive `order::shuffle_indices` and `trace::merge_traces`.")
    A("* `node/` (`detjs vitest|jest --det`): order (files sorted / seeded shuffle files → describe → tests), seeds "
      "(`Math.random`, `crypto.getRandomValues`, `crypto.randomUUID`), virtual clock (`Date`, `performance.now`, "
      "`process.hrtime`) with the adaptive tick, virtual timers (inside tests only; released to the realm's own timers "
      "when a test ends), sorted `readdir`/`opendir`, closed network with record/replay (net, tls, dns → http, https, "
      "fetch), serial execution with the isolation recorded. Ops, sites (source-mapped original `.ts` lines) and header "
      "meta follow the shared vocabulary.")
    A("* Tests: one fixture per control and runner that fails in a realistic run without `--det` and passes with it; "
      "a deterministic suite whose outcomes `--det` does not change; regression tests for each defect found by the "
      "harness (Vitest projects, jsdom accessors, leaked timers, runner environment variables).\n")

    A("## Projects (step 4)\n")
    A("**Flaky pool.** The public dataset of JavaScript flaky tests of Hashemi, Tahir, Rasheed (ICSME 2022, Zenodo "
      "10.5281/zenodo.6673741; fetched by an Actions job into `harness/node/dataset/raw/`) was used first, each project "
      "pinned at the parent of a commit that fixes a flaky test. It has 18 projects and almost none runs on Jest ≥ 27 "
      "or Vitest at those commits (Node core, Atom, Electron, Meteor, QUnit, Karma, Jest 22–25), so it supplies "
      f"{sum(1 for s in repos if s['kind'] == 'flaky' and str(s.get('documented_source', '')).find('/commit/') >= 0)} "
      "measurable project(s). The pool was completed with projects whose GitHub issues document a flaky Jest/Vitest "
      "test (curated list of popular repositories, then a GitHub-wide issue search restricted to JS/TS repositories with "
      "≥ 1000 stars), each pinned at the last commit before the issue was opened.")
    A(f"**Selection (MEASURED).** {len(repos) + len(pw)} projects passed the filters and were measured (clone, install, runner "
      "found — also in a workspace package —, ≥ 50 test outcomes, < 50% failing, first run < 180 s): "
      f"{nflaky} documented-flaky, {npop} popular, {len(pw)} Playwright. Discarded: "
      + ", ".join(f"{k} {v}" for k, v in collections.Counter(d['status'] for d in discards).most_common())
      + f". Every discarded candidate is listed with its reason in `harness/node/results/{RES.name}/REPORT.md`.")
    if nflaky < 25:
        A(f"\n**Shortfall:** the documented-flaky pool has {nflaky} measurable projects, not 25 (MEASURED). The other "
          "candidates (all listed) need a build, a browser, services or an old toolchain (Jest < 27 without "
          "jest-circus, Vitest < 1.4), or their suites fail on a clean runner.")
    A("")
    A(f"## Main results (MEASURED, {meta.get('runs', 10)} baseline + {meta.get('runs', 10)} `--det` runs per project, "
      f"seeds 1..{meta.get('seeds', 20)}, {meta.get('confirm', 10)}/{meta.get('confirm', 10)} confirmation)\n")
    A("| pool | projects | tests | unstable in baseline | reproduced | % | never fail under --det | fail sometimes | always fail |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for label, t, n in (("documented flaky", F, nflaky), ("popular", P, npop), ("total", T, len(repos))):
        A(f"| {label} | {n} | {t['tests']} | {t['unstable_baseline']} | {t['reproduced']} | "
          f"{pct(t['reproduced'], t['unstable_baseline'])} | {t['never_fails_under_det']} | "
          f"{t['fails_sometimes_under_det']} | {t['always_fails_under_det']} |")
    A("")
    if seeds:
        b = collections.Counter("0 (fixed order)" if v == 0 else "1" if v == 1 else "2-5" if v <= 5 else "6-10"
                                if v <= 10 else "11-20" for v in seeds)
        A("Seeds explored before the reproducing seed (MEASURED): " + ", ".join(f"{k}: {v}" for k, v in sorted(b.items()))
          + f"; median {statistics.median(seeds):.0f}.\n")
    if pf:
        A("First diverging event between a passing and a failing `--det` run (MEASURED): "
          + ", ".join(f"`{k}` {v}" for k, v in sorted(pf.items(), key=lambda kv: -kv[1])) + ".\n")
    A(f"Documented flaky tests found in the measured suites: {F['known_present']}; flaky in our baseline: "
      f"{F['known_unstable_baseline']}; reproduced: {F['known_reproduced']} (MEASURED; issue titles often name no test).\n")

    A("## Tests broken by `--det` and the L0 fixes (MEASURED)\n")
    A("Rounds stopped early on earlier versions of the shell are kept in `harness/node/results/node-before-fixes*`. "
      "Defects of Level 0 / the shell found by the harness and fixed in this session (each with a regression test):\n")
    A("| defect (project where found) | effect before the fix |")
    A("|---|---|")
    A("| Vitest projects/workspaces ignored the CLI runner (date-fns) | the `--det` controls did not apply in project configs |")
    A("| Node 18: read-only `Performance.prototype` methods (luxon) | every Jest suite failed to start (58 suites) |")
    A("| jsdom: `crypto` is an accessor (mobx) | 69 Jest suites failed to start |")
    A("| leaked virtual timer fired at once (dom-testing-library) | crash of the Jest process |")
    A("| in-process runners lacked `NODE_ENV=test` / `VITEST` (user-event, jotai) | every user-event suite failed (Babel config) |")
    A("| runner outside the project root refused by Vite `server.fs` (jotai) | 0 of 44 files ran under `--det` |")
    A("| in-band Jest never exits on suites with open handles (react-testing-library) | `--det` run timed out |")
    A("| fast virtual timers fired while React `act()` / scheduler `setImmediate` chains were pending (apollo-client) | "
      "34 tests broken by `--det` in a local run (MEASURED locally), 3 after the fix (limit J15) |")
    A("| Jest compiled the detjs `testRunner` with the project's transform (matrix-js-sdk, immutable-js) | every suite "
      "failed under `--det` (`@babel/runtime` not found; buble syntax error) |")
    A("| awaited in-process `jest-cli` run added an `at async main` frame to async stacks (babel) | stack-trace inline "
      "snapshots failed under `--det` |")
    A("| adaptive tick doubled after 8 clock reads; React's scheduler reads the clock hundreds of times per render "
      "(recharts) | virtual `performance.now()` ran 194 s ahead within a test; code comparing it with Vitest's fake "
      "`requestAnimationFrame` timestamps looped: 1113 tests broken by `--det` |")
    A("| custom Jest `runner` (jest-light-runner) bypasses detjs (babel, prettier) | Level 0 not applied: 0 of ~25 000 "
      "tests traced; now reported (J16), not fixed |")
    A("")
    A("Harness defects fixed on the way (they affected the measurement, not detjs): the project's test-script flags "
      "(`--config`, Node flags, variables) were ignored (apollo-client: every suite failed), leftover web servers survived "
      "a run (process groups now killed), runs that hang after writing their report were discarded "
      "(react-testing-library), the test-script flags were applied even when a plain run was better (vercel: 3212 → 30 "
      "tests).")
    A("")
    if common:
        A("Per project, the latest measurement before the last fixes (round on d3075a1 and its re-runs, or the earlier "
          "stopped rounds) against the final round:\n")
        A("| project | broken by --det before | after |")
        A("|---|---:|---:|")
        for n in common:
            A(f"| {n} | {before_by[n].get('broken_by_det', 0)} | {now_by[n].get('broken_by_det', 0)} |")
        A("")
    if broken:
        A("Remaining causes (`fixed-order` = also fails under `--det` with every Level 0 control off, i.e. an order or "
          "isolation dependency hidden by the random parallel baseline; otherwise the controls whose `--det-disable` makes "
          "the test pass):\n")
        A("| cause &#124; exception | tests |")
        A("|---|---:|")
        for k, v in sorted(broken.items(), key=lambda kv: -kv[1])[:15]:
            A(f"| `{k.replace('|', '&#124;')}` | {v} |")
        A("")

    if inactive:
        A("**Level 0 not applied (J16).** " + ", ".join(
            f"{n} ({s.get('tests', '?')} tests, {s.get('covered', 0)} traced)" for n, s in inactive.items())
          + " run their tests with the custom Jest runner `jest-light-runner`, which bypasses jest-circus's `testRunner` "
          "hook: detjs cannot install its controls there, so these projects are excluded from the numbers above "
          "(MEASURED on the round before the last fixes; replacing the runner by `jest-runner` made every suite fail, "
          "under `--det` and the serial reference alike).\n")

    A("## Causes of baseline-flaky tests not reproduced (MEASURED, keyword heuristics)\n")
    A("| concurrency / event order | external | L0 gap | unknown |")
    A("|---:|---:|---:|---:|")
    A(f"| {causes['concurrency/event-order']} | {causes['external']} | {causes['l0-gap']} | {causes['unknown']} |\n")
    A(f"Evidence per test in `harness/node/results/{RES.name}/<repo>.causes.json`.\n")

    A("## Timing\n")
    if timings:
        A(f"Quiet timing pass (MEASURED, DECLARED-NOISY): {len(timings)} projects, 3 serial runs without `--det` vs 3 "
          f"`--det` runs, interleaved on one GitHub-hosted runner each; median slowdown {fmt(statistics.median(sl))}% "
          f"(min {fmt(min(sl))}%, max {fmt(max(sl))}%). Per project in the harness report. The main cost is the call-site "
          "resolution on clock-heavy code (J5 in `docs/NODE.md`).\n")
    else:
        A("Quiet timing pass: not available (UNKNOWN).\n")

    A("## Playwright end-to-end suites (measured, not built on)\n")
    if pw:
        Q = collections.Counter()
        for s in pw:
            for k in ("tests", "unstable_baseline", "unstable_det", "became_stable", "never_fails_under_det",
                      "fails_sometimes_under_det", "always_fails_under_det", "broken_by_det", "reproduced"):
                Q[k] += s.get(k, 0)
        A(f"{len(pw)} projects (MEASURED), Chromium, `--retries=0`; baseline = the project's own parallelism; `--det` = "
          "one worker plus the Level 0 controls inside the Playwright worker processes (no per-test brackets, no traces; "
          "browser and web servers not controlled).\n")
        A("| project | tests | unstable in baseline | unstable under --det | became stable | broken by --det |")
        A("|---|---:|---:|---:|---:|---:|")
        for s in pw:
            A(f"| {s['name']} | {s['tests']} | {s['unstable_baseline']} | {s['unstable_det']} | {s['became_stable']} | "
              f"{s.get('broken_by_det', 0)} |")
        allu = T["unstable_baseline"] + Q["unstable_baseline"]
        A(f"\nBrowser tests unstable in the baseline: {Q['unstable_baseline']} of {Q['tests']}; of all baseline-unstable "
          f"tests of the round, {pct(Q['unstable_baseline'], allu)} are browser tests (MEASURED, small sample, not weighted). "
          f"Under `--det`: never fail {Q['never_fails_under_det']}, fail sometimes {Q['fails_sometimes_under_det']}, "
          f"always fail {Q['always_fails_under_det']}. What Level 0 covers today in browser tests is only the test "
          "process (Node side): the browser's clock, randomness, network and scheduling, where most end-to-end "
          "flakiness lives, are outside it.\n")
        if len(pw) < 5:
            A(f"**Shortfall:** {len(pw)} Playwright projects measured, not 5: the other candidates need builds or "
              "services that fail on a clean runner, or Playwright versions that cannot install Chromium on the "
              "runner's Ubuntu 26.04 (listed in the harness report).\n")
    else:
        A("No Playwright project measured (UNKNOWN).\n")

    A("## Limits found\n")
    A("The full list with the project where each was found is in `docs/NODE.md` (J1–J16). The ones that matter most "
      "for the numbers: J4 (fast virtual timers versus real I/O once I/O is pending), J5 (cost of call sites), J15 (CPU "
      "time is not virtual time: loops bounded by a virtual deadline can exceed the runner's real timeout), J16 (custom "
      "Jest runners replaced by jest-runner under `--det`), J2 (vm pools / browser mode not covered), J3 (Jest "
      "`setupFiles` run before the controls), J11 (Playwright measured only). Not fixed: on matrix-js-sdk, tests that "
      "switch to Jest's modern fake timers inside a test hang under `--det` with the virtual clock on (they pass with "
      "`--det-disable=time`); the interaction between Jest's fake `Date`/`performance` and the virtual clock is not "
      "understood yet (UNKNOWN cause).\n")

    A("## Cockpit readiness\n")
    A("What the Node outputs already give per test, as the Python ones: the outcome per run, the fingerprint (trace "
      "`test` line), the first diverging event with its reason (Rust verifier, same JSON report for both runtimes), and "
      "the replay command (`detjs vitest|jest --det [--det-seed=N]` plus the cassette). What would make a stable "
      "machine-readable verdict harder:\n")
    A("* **Test identity.** Node test ids are `file::describe::…::name`; names are not unique in JS (duplicates get ` #2`), "
      "names can be built at run time (`test.each`, template strings) and contain any character, and a Vitest file run by "
      "two projects yields two identical ids (J9). A cockpit needs a stable id that includes the project and survives "
      "renames; Python node ids are much more stable.")
    A("* **Verdict sources are split.** Outcomes come from the runners' JSON reporters, fingerprints from the trace; they "
      "are joined by id (the harness does it). A single per-test record emitted by the shell (outcome + fingerprint + "
      "replay command) would remove that join; the Python plugin has `--det-outcomes` for this, the Node shell does not yet.")
    A("* **Replay command.** For a Jest/Vitest test it must name the runner, the project config, the seed and the test "
      "filter (`-t` / `--testNamePattern` with escaping of the name); the cassette path; and, for a pinned flaky project, "
      "the commit and the Node version. Today these are spread over the trace header and the harness CSV.")
    A("* **Coverage caveats per test.** A verdict must carry why a pass is not trustworthy: worker threads / child "
      "processes (J1), vm pools (J2), timers released to real time after the test (J4), Playwright (no fingerprint). "
      "The trace header has the run-level notes (`meta.notes`); per-test flags are not emitted yet.")
    A("* **Encoding.** Traces carry the event encoding (now 2); the verifier refuses mixed encodings, so cockpit history "
      "must be keyed by encoding version.\n")

    A("## Delivery notes\n")
    A("* fenvix-brain-cli could not be attached (refused twice by the session's permission system); reports are in "
      "`docs/` of this branch per the coordinator's fallback.")
    A("* A second Actions job to fetch the JS-TOD and environmental-flakiness replication packages from Zenodo was "
      "refused by the session's permission system and not retried.")
    A(f"* Harness report with every number per project and every discarded candidate: `harness/node/results/{RES.name}/REPORT.md` "
      f"(run {meta.get('run_url', '')}).")
    OUT.write_text("\n".join(L) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
