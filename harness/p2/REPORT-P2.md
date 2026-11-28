# REPORT-P2: where the engine's time goes on the 9 pool repositories (DRAFT)

Status: DRAFT, 28 Nov 2026. Branch `claude/p2-speed`, from `6e79a62`; `claude/release-1` merged in twice (519bf1a0 at
`72d02913`, 7cbe7b27 at `a148bca2`). Nothing merged into release-1. The final 9-repository re-measure (Phase D) is
not run yet: by founder decision R3 it runs only after P3 and P2 are both merged into release-1, on that release-1; its
table replaces section 6 then. Spec: "P2 speed" rev 4. Detailed write-ups: `PREREG.md`, `BASELINE.md` (Phase A),
`BREAKDOWN.md` (Phase B), `FIX-1.md` (C2, D4, D5), `C4.md`, `C3.md`, `C6.md`, `RERUN.md`.

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
| C6 | counters only | two changes tried and reverted (`C6.md`) | open question D7 |

Measured effect on this boot (b0517ae9), the head after the release-1 519bf1a0 merge (43dc6c1f) against the fix-1
engine, E best median: nestjs-pino 11.41 -> 10.78, agentsys 20.92 -> 16.91, alakajam 54.42 -> 75.33, agentlang 87.37 ->
95.44, yalc 56.18 -> 45.86, ironcurtain 90.61 -> 88.12, codex-multi-auth 155.59 -> 180.78, drydock 203.04 -> 185.03,
lerna-lite 613.79 -> 607.01; **3 of 9** meet both bounds. The slower ones are release-1's hazard rules (alakajam: all 27
files in one lane by round 3 from `recursive-write` hazards; codex-multi-auth: a `shared-service` re-run), `C4.md`.

## 4. Correctness

Rules 1-3 (PREREG §5) per fix: `FIX-1.md` (C2: no outcome, exit-code or fingerprint change from the fix; one rule-1
shift towards `diverged` on codex-multi-auth w4, accepted by the founder as known behaviour, D5 = A), `C4.md` (head vs a
release-1-alone control: no fingerprint difference beyond each engine's own repeat noise on 8 repositories; one flaky
codex-multi-auth test open), `C3.md` (fixed runs are w1, unaffected). No failed test reported with exit 0.

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
- Tests added and deleted within P2, never released: `node/test/p2-c6-outside-stack.test.js`,
  `node/test/p2-c6-depth.test.js` (with their reverted changes, `C6.md`).
- Protocol addition (R1): S1/PS against 1.05 printed by `table.py` beside PS/E; no new runs.
- Protocol addition (D4): rounds 4-6 per engine on codex-multi-auth and ironcurtain (`FIX-1.md`).
- New analysis tools (no thresholds, no validator change): `sameboot.py`, `explain_rule1.py`, `d4.py`,
  `tools/keep_lanes.js`, `tools/bench_hazards.js`, `c4_pair.sh`; `phase_b.sh` takes `PHASEB_OUT`.
- No timeout, tolerance, threshold, HOLD_MAX_MS, worker count, plain command, pool repository or verify rule changed.

## 6. Final table (Phase D)

Not run yet (R3: after P3 and P2 are both in release-1). Command: the baseline protocol on that release-1 into
`data/final`, `table.py baseline data/final` and `table.py compare data/baseline data/final`.

## 7. Open

- D7 (C6): the per-file cost on alakajam (about 19 s of about 60 s at 1 worker) is the outside-files recorder formatting
  stacks through the repository's source-map support; removing it changes recorded sites and
  `files_read_outside_tests` (`C6.md`).
- Hazard-rule findings for parallel-proof-gaps (not P2's): alakajam's `recursive-write` together-groups; agentlang's
  shared log file; codex-multi-auth's `shared-service` re-runs.
- codex-multi-auth `test/runtime-policy-cache.test.ts::...re-resolves the project key when a worktree...`: flaky with
  every engine, more often at the head (3/11 against 2/79); not shown to come from P2.
- Jest: C2 not applied (coordinator decision 2026-11-26); agentsys 1.0 s.
