# P2 fix-1 (C2): a free worker slot goes to a file whose lane is free

Engine: `0f44776` (C2, `node/src/vitest/lanequeue.js`, plus the `enter()` done-marker fix in `node/src/parallel.js`;
its test is `c4f4676`). Baseline engine: `6e79a62`. Both measured on the same boot (`591ebcd0`), per repository back to
back: `data/base-b` (baseline engine, 3 rounds) and `data/fix-1` (fix engine, 3 rounds, fixed runs `fix1`, `fix1r`).
The Phase A baseline (`data/baseline`, boot `ded5bcf2`) is used only for rule 2 (its fixed runs F-base1..3) and as a
second set of baseline-engine rounds.

Scope: Vitest only. Jest is unchanged, by the coordinator's decision of 2026-11-26 04:47 UTC. The jest-runner
`pLimit(maxWorkers)` mutex still holds a slot for a file that is waiting for its lane. Measured on agentsys: 1.0 s of
runtime excess. `node/test/p2-c2-lanequeue.test.js` records the current Jest blocking and fails once Jest is fixed.

## Speed (`table.py compare data/base-b data/fix-1`, median [cold])

| repo | E best base | E best fix1 | saved (median) | saved (cold) | PS/E base → fix1 | E/PP base → fix1 | meets base → fix1 |
|---|---|---|---|---|---|---|---|
| nestjs-pino | 9.76 [9.76] | 9.96 [9.96] | -0.20 | -0.20 | 1.98 → 1.99 | 1.27 → 1.32 | no → no [no → yes] |
| agentsys | 19.45 [21.50] | 17.20 [21.90] | 2.25 | -0.40 | 0.66 → 0.70 | 3.20 → 2.81 | no → no [no → no] |
| alakajam | 53.59 [78.99] | 50.31 [75.04] | 3.28 | 3.95 | 0.59 → 0.60 | 5.73 → 5.43 | no → no [no → no] |
| agentlang | 88.13 [86.70] | 85.25 [89.46] | 2.88 | -2.76 | 0.93 → 0.90 | 3.26 → 3.02 | no → no [no → no] |
| yalc | 64.87 [106.44] | 63.86 [109.59] | 1.01 | -3.15 | 1.41 → 1.42 | 2.07 → 1.87 | no → no [no → no] |
| ironcurtain | 97.35 [148.09] | 89.36 [117.53] | 7.99 | 30.56 | 2.58 → 2.76 | 1.27 → 1.20 | yes → yes [no → no] |
| codex-multi-auth | 159.75 [320.46] | 174.63 [202.06] | -14.88 | 118.40 | 2.43 → 2.17 | 1.50 → 1.62 | no → no [no → no] |
| drydock | 205.46 [226.42] | 195.36 [230.21] | 10.10 | -3.79 | 2.56 → 2.59 | 1.34 → 1.28 | no → yes [no → no] |
| lerna-lite | 610.47 [925.98] | 612.29 [904.93] | -1.82 | 21.05 | 1.01 → 1.01 | 2.15 → 2.16 | no → no [no → no] |

The bounds are met on 2 of 9 repositories at the median (ironcurtain, drydock), against 1 of 9 before (ironcurtain).

What C2 removes, from the round-3 trace headers (`breakdown.py lanes`): the lane waiting summed over files.

| repo | w | waited s base → fix1 | runtime excess s base → fix1 |
|---|---|---|---|
| codex-multi-auth | 2 / 4 | 21.9 → 4.8 / 23.3 → 5.1 | 33.4 → 38.3 / 24.5 → 17.9 |
| drydock | 2 / 4 | 18.0 → 4.2 / 33.2 → 17.4 | 81.1 → 76.8 / 57.1 → 46.0 |
| ironcurtain | 2 / 4 | 7.2 → 3.5 / 11.6 → 17.2 | 48.0 → 41.5 / 22.4 → 25.4 |
| alakajam | 2 / 4 | 26.8 → 18.8 / 86.8 → 73.4 | 12.0 → 1.8 / 5.3 → -4.4 |
| yalc | 2 / 4 | 18.9 → 8.7 / 120.2 → 119.3 | 19.3 → 13.9 / 11.3 → 3.0 |

These figures come from one round each. On codex-multi-auth the waiting goes away, but the files' own run time rises
by about as much (sum of file s / w: 189 → 199 and 105 → 108), so the wall time does not fall at the median. Its warm
w4 rounds overlap: base 157 / 152, fix 172 / 154. Where lanes are merged into one by hazards (C1: lerna-lite, most of
yalc), C2 can have no effect. It does not apply to agentlang (refused, C3) or to agentsys (Jest).

## Correctness

### Rule 3 (outcomes, exit codes, counts): no change from the fix

Each flagged item also appears in the baseline-engine control (`correctness.py --base data/baseline --fix data/base-b`,
the same engine on both boots), or comes from runs that do not run fix code:
- agentlang: the 3 exit-code items are in plain_par, which runs no engine.
- alakajam: the 2 outcome items include the serial run; C2 is installed only when workers > 1.
- drydock: the 510 outcome items are fuzz tests whose names contain a random seed, so the test IDs differ in every
  run, plain runs included. The control has 508.
- codex-multi-auth: 28 items, against 24 in the control.

There is no failed test with exit 0.

### Rule 2 (fixed-epoch fingerprints): no fingerprint change from the fix

The boot changed between F-base1..3 and the fix's fixed runs. Against F-base1..3, the baseline engine's own fixed run
on the new boot (`base4`, in `data/base-b`) differs as much as the fix does. `sameboot.py` classifies every difference
between the fix and that control (`data/fix-1/<repo>/sameboot.json`):
- nestjs-pino: 0.
- agentsys: 15, all unstable in F-base1..3.
- alakajam: 92, of which 90 are unstable and 2 have the fix equal to F-base1 (the control is the odd one out).
- lerna-lite: 16, of which 14 are unstable. The 2 watch-lifecycle tests race on a results file (237 vs 477 bytes); the
  stream=true/false patterns swap between runs. The boot effect on all 88 lerna tests is `env.list`: 197 variables now,
  198 before.
- yalc: 1 left. It is a race seen with both engines; 4 extra runs alternating the engines (base5, base6, fix1x5, fix1x6)
  show both fingerprints with both engines.
- ironcurtain: 5 left, all passing; in 4 of them the control also changed.
- codex-multi-auth: 14 left, all passing in every fixed run but one test, "keeps the next tick anchored when a slow run
  rejects: true". That test fails in fix1/fix1r, and the baseline engine fails it too in S1 (w1) and in P2w2/P2w4 on
  this boot.
- drydock: 1 left; fix1r equals F-base1, and the control also differs.

The fixed runs are w1, where the C2 code is not installed (`par.workers > 1`).

### Rule 1 (verify class per test): one open question for the coordinator

Explanations are generated by `explain_rule1.py`, never written by hand. A change is explained when the baseline engine
showed every class the fix shows, for that test and w, over its 6 rounds (`data/baseline` + `data/base-b`), and
showed more than one class there.

| repo | changes w2 / w4 | unexplained w2 / w4 |
|---|---|---|
| nestjs-pino, agentsys | 0 / 0 | 0 / 0 |
| lerna-lite | 4 / 1 | 0 / 0 |
| agentlang | 1 / 1 | 1 / 0 |
| alakajam | 5 / 10 | 2 / 6 |
| yalc | 3 / 5 | 1 / 3 |
| ironcurtain | 18 / 42 | 11 / 13 |
| codex-multi-auth | 68 / 67 | 31 / 35 |
| drydock | 28 / 28 | 26 / 28 (48 of them are seed-named fuzz test IDs the baseline never ran) |

For scale, the same engine against itself across the two boots (`--base data/baseline --fix data/base-b`) gives more
raw changes in most repositories: ironcurtain 30 / 51, codex-multi-auth 80 / 72, alakajam 8 / 15.

The unexplained changes lean one way. 56 tests gain `diverged` at the fix where the baseline engine never showed it in
6 rounds (codex-multi-auth 44, ironcurtain 5, yalc 4, alakajam 2, agentlang 1); 9 lose it. Per round, `diverged` is
slightly higher at the fix on several repositories (codex-multi-auth w4: 1371-1388 against 1314-1368; ironcurtain w2:
1034-1039 against 1013-1027 on the same boot, 1022-1041 on the first boot).

A likely mechanism (not proven): C2 removes the waiting, so files of different lanes overlap more in real time, and
load-sensitive tests differ from their serial run more often. The engine still reports this honestly as `diverged`;
no test becomes `identical` falsely. Placement checks are clean on every fix-1 par run: no lane-order violation (each
file started after its lane predecessor ended), and the hazards are the same as the base runs except one run each in
ironcurtain (r2 w4: 9 → 8) and drydock (r1 w4: 0 → 1).

## Changes to proof fields, tests and tools (each on its own line)

- `meta.parallel.placement.deviations`: the false "lane predecessor ... died" notes are gone (the `enter()` fix): a
  predecessor that finished and exited during the wait is no longer reported as dead. Real deaths are still reported
  (test 2 of `node/test/p2-enter-race.test.js`). Each run keeps its "no marker" deviation for a file that did not run.
- New test: `node/test/p2-c2-lanequeue.test.js` (C2 on Vitest; the Jest test records the current blocking).
- New test: `node/test/p2-enter-race.test.js` (fails on 6e79a62, passes at the head).
- Test change: `node/test/p2-phases.test.js`, the assertion now checks `['.phases.jsonl','DETJS_PHASES']`, because the
  fixture path itself contains "p2-phases". This was a false failure of my own new test.
- New analysis scripts (no thresholds, no validator change): `harness/p2/sameboot.py`, `harness/p2/explain_rule1.py`.
