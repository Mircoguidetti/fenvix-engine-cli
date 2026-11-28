# REPORT-P2: where the engine's time goes on the 9 pool repositories (DRAFT)

Status: 28 Nov 2026, before the full suites and /review. Branch `claude/p2-speed`, from `6e79a62`; `claude/release-1`
merged in twice (519bf1a0 at `72d02913`, 7cbe7b27 at `a148bca2`). Nothing merged into release-1. The final 9-repository re-measure (Phase D) is
not run yet: by founder decision R3 it runs only after P3 and P2 are both merged into release-1, on that release-1; its
table replaces section 6 then. Spec: "P2 speed" rev 4. Detailed write-ups: `PREREG.md`, `BASELINE.md` (Phase A),
`BREAKDOWN.md` (Phase B), `FIX-1.md` (C2, D4, D5), `C4.md`, `C3.md`, `C6.md` (C6, D7, D9), `HAZARDS.md` (the hazard
investigation, D10, D11), `RERUN.md`.

## 1. Bounds and baseline (Phase A, engine 6e79a62, boot ded5bcf2)

Bounds per repository: E_best <= min(1.3, speedup/2) x PP_best and PS/E_best >= 2, where E = par + verify, PS = plain
serial, PP = plain parallel (median of 3 rounds, best over w = 2, 4). Founder rule R1 (2026-11-27) adds: the engine at
1 worker costs at most +5% over plain serial (S1/PS <= 1.05; S1 = the protocol's existing serial row,
`--det --det-workers=1`). Phase A: **1 of 9** repositories met both bounds (ironcurtain); `BASELINE.md`.

## 2. Where the time goes (Phase B, `BREAKDOWN.md`)

C1 lanes merged by hazards (lerna-lite, yalc: not P2's, parallel-proof-gaps); C2 a free worker slot waiting for a lane
(about 120 s); C3 agentlang refused (singleFork, about 53 s); C4 the post-run hazard analysis (`hazards()`, about 25 s);
C5/C6 the engine's per-file cost.

## 3. Fixes

| fix | commit | what | result |
|---|---|---|---|
| C2 | `0f44776` (+ `c4f4676` test) | Vitest: a free slot goes to a file whose lane is free (`node/src/vitest/lanequeue.js`); `enter()` done-marker fix | 2 of 9 meet (was 1); lane waiting cut (codex 21.9 -> 4.8 s w2); `FIX-1.md` |
| C4 | `488e20c`, overtaken | listing index in `hazards()`; release-1's own sorted index replaced it at the merge | `hazards()` on real markers: codex 16.2 s -> 50 ms, lerna-lite 5.1 s -> 35 ms; `C4.md` |
| D6 | `9eab5f26` | the header names Vitest's per-run temp dirs (`<vitest tmpDir>`), no random paths | two identical runs write the same header |
| C3 | `17775df2` | `--det-workers=N` overrides singleThread/singleFork (D3 = A) | override works; agentlang still serial: its files share `logs/app-<date>.log` (161 hazards); `C3.md` |
| C6 / D7 | `72dd9ee5`, `cf9ac636`, `8f3f831c` | Vitest sites from the module's own source map in Vitest's worker state, kept before a mock replaces it; the outside-files recorder reads the raw stack (D7 = B) | alakajam at 1 worker 51.5-52.8 -> 36.5-36.7 s; sites now the real call lines; `C6.md` |
| D10 | `861a83bc` | a project-declared list of in-repo directories not shared (`package.json` `"detjs": { "notShared": [...] }`), header `declared_not_shared` | works and tested; agentlang does not use it (D11 R1 = A, `HAZARDS.md`) |

Measured effect on this boot (b0517ae9), the head after the release-1 519bf1a0 merge (43dc6c1f) against the fix-1
engine, E best median: nestjs-pino 11.41 -> 10.78, agentsys 20.92 -> 16.91, alakajam 54.42 -> 75.33, agentlang 87.37 ->
95.44, yalc 56.18 -> 45.86, ironcurtain 90.61 -> 88.12, codex-multi-auth 155.59 -> 180.78, drydock 203.04 -> 185.03,
lerna-lite 613.79 -> 607.01; **3 of 9** meet both bounds. The slower ones are release-1's hazard rules (alakajam: all 27
files in one lane by round 3 from `recursive-write` hazards; codex-multi-auth: a `shared-service` re-run), `C4.md`.

## 4. Correctness

Rules 1-3 (PREREG §5) per fix: `FIX-1.md` (C2: no outcome, exit-code or fingerprint change from the fix; one rule-1
shift towards `diverged` on codex-multi-auth w4, accepted by the founder as known behaviour, D5 = A), `C4.md` (head vs a
release-1-alone control: no fingerprint difference beyond each engine's own repeat noise on 8 repositories; one flaky
codex-multi-auth test open), `C3.md` (fixed runs are w1, unaffected), `C6.md` (D7 against a148bca2 on alakajam, agentsys,
yalc, codex-multi-auth: no outcome changes; the changed fields are `files_read_outside_tests` (alakajam 311 -> 149) and
sites (alakajam 114 tests, codex-multi-auth 50), both accepted by the founder, and on codex-multi-auth 5 tests whose
events differ by timing (an un-awaited write, a detached child's lock, real-clock file times), explained in D9). No
failed test reported with exit 0.

## 5. Changes to tests, proof fields, protocol (each on its own line)

- New test `node/test/p2-c2-lanequeue.test.js` (C2; the Jest test records the current Jest blocking).
- New test `node/test/p2-enter-race.test.js` (fails on 6e79a62).
- Test change `node/test/p2-phases.test.js`: the assertion checks `['.phases.jsonl','DETJS_PHASES']` (the fixture path
  contains "p2-phases"; a false failure of my own new test).
- Test deleted (founder approval 2026-11-27): `node/test/p2-c4-hazards.test.js`, compared `hazards()` with the 6e79a62
  algorithm; release-1 changed the rules on purpose.
- New test `node/test/p2-skipdirs-stable.test.js` (D6; failed before the fix on Vitest).
- Proof field `meta.parallel.skip_dirs`: Vitest's per-run temp dirs are written as `<vitest tmpDir>` and
  `<vitest project N tmpDir>` instead of their random paths (D6 = A).
- Proof field `meta.parallel.placement.deviations`: the false "lane predecessor ... died" notes are gone (C2's `enter()`
  fix); real deaths are still reported.
- New proof field `meta.parallel.requested.override` and an `override` clause in `meta.isolation` (C3).
- New test `node/test/p2-c3-override.test.js` (C3).
- New counters in `DETJS_PHASES` phase lines only: `resolve_calls`, `stack_deep`, `stack_runner`, `site_formatted` (C6).
- Proof field sites (`at` of every event): under Vitest the source line comes from the module's own map in Vitest's
  worker state, not from the installed stack formatter (D7 = B, accepted by the founder).
- Proof field `meta.files_read_outside_tests`: no longer carries the reads the engine's own stack formatting caused through
  a project's source-map support (D7 = B, accepted by the founder; alakajam 311 -> 149 entries).
- New tests `node/test/p2-c6-site-map.test.js`, `node/test/p2-c6-vite-map.test.js`, and `node/test/p2-c6-outside-stack.test.js`
  again (D7).
- New proof field `meta.parallel.declared_not_shared` { source, dirs, refused } (D10); new test
  `node/test/p2-d10-declared.test.js`.
- Harness: `measure.reset_tree()` applies a repository's `declared_change` from `specs.json` after every reset and every
  row records it (D10); no repository has one (agentlang's was removed, D11 R1 = A).
- New limit `docs/LIMITS.md` G1: file names derived from the virtual clock are equal in every lane (D11 R2 = A).
- Test added and deleted within P2, never released: `node/test/p2-c6-depth.test.js` (with its reverted change,
  `C6.md`).
- Protocol addition (R1): S1/PS against 1.05 printed by `table.py` beside PS/E; no new runs.
- Protocol addition (D4): rounds 4-6 per engine on codex-multi-auth and ironcurtain (`FIX-1.md`).
- New analysis tools (no thresholds, no validator change): `sameboot.py`, `explain_rule1.py`, `d4.py`,
  `tools/keep_lanes.js`, `tools/bench_hazards.js`, `c4_pair.sh`; `phase_b.sh` takes `PHASEB_OUT`.
- No timeout, tolerance, threshold, HOLD_MAX_MS, worker count, plain command, pool repository or verify rule changed.

## 6. Final table (Phase D)

Not run yet (R3: after P3 and P2 are both in release-1). Command: the baseline protocol on that release-1 into
`data/final`, `table.py baseline data/final` and `table.py compare data/baseline data/final`.

## 7. Open

- alakajam: its specs share one SQLite test database; not order-dependent (4 serial orders), a real conflict for
  concurrency; not counted for 22 Dec (founder decision alakajam = A), the first SQLite case for live step 3 (DB copies
  per lane).
- agentlang: stays together through its `logs/` hazards and is not counted for 22 Dec (D11 R1 = A); G1 and the native-
  addon gap (PG9) are routed after the verdict (D11 R2 = A).
- codex-multi-auth's `shared-service` re-runs (release-1's rule).
- codex-multi-auth `test/runtime-policy-cache.test.ts::...re-resolves the project key when a worktree...`: flaky with
  every engine, more often at the head (3/11 against 2/79); not shown to come from P2.
- Jest: C2 not applied (coordinator decision 2026-11-26); agentsys 1.0 s.
