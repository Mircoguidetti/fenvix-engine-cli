# P2 Phase B: where the engine's parallel time goes

Sources (all raw, all committed or reproducible):

- **Baseline timed traces** (`harness/p2/data/baseline/<repo>/P3w<n>.jsonl`, header `meta.parallel`; the original
  machine, boot ded5bcf2, warm round 3), tabulated by `python3 harness/p2/breakdown.py lanes`.
- **Phase B runs** (`harness/p2/data/phaseB`, branch engine, `fixed_run.py`, `--det-epoch=fixed`, cold engine state
  because fixed_run resets the tree; boot 406fde79 after a container reboot at about 22:10 UTC):
  - a `--cpu-prof` run (`cpuprof-summary.json`);
  - a `DETJS_PHASES=1` run (`phases-summary.json`; segments by `python3 harness/p2/breakdown.py`).
  Phase B times are compared only with each other, never with the baseline numbers (another boot, and a cold plan).
- `ironcurtain` meets both bounds and has no Phase B run. agentlang's parallel request is refused (below).

## 1. The parallel run, round 3 of the baseline (warm plan)

`outside lanes` = par wall - lanes wall (startup, plan, hazard re-run, post-run analysis, deps digest, trace write).
`plan excess` = the plan's makespan - (sum of file seconds / w): lost before the run starts, by the plan.
`runtime excess` = lanes wall - plan makespan: lost while running (worker slots blocked by lane waits, costs that
differ from the recorded ones).

| repo | w | par wall | outside lanes | lanes wall | plan makespan | sum of file s / w | waited s (sum) | together groups | plan excess (makespan - sum/w) | runtime excess (lanes - makespan) |
|---|---|---|---|---|---|---|---|---|---|---|
| nestjs-pino | 2 | 15.4 | 1.5 | 13.9 | 11.0 | 10.4 | 1.2 | 0 | 0.6 | 2.9 |
| nestjs-pino | 4 | 10.8 | 1.8 | 8.9 | 7.7 | 6.9 | 0.8 | 0 | 0.7 | 1.3 |
| agentsys | 2 | 15.8 | 2.6 | 13.2 | 12.4 | 12.4 | 0.0 | 9 | -0.0 | 0.8 |
| agentsys | 4 | 16.4 | 3.3 | 13.2 | 12.2 | 8.2 | 0.0 | 9 | 4.0 | 1.0 |
| alakajam | 2 | 54.5 | 1.7 | 52.7 | 50.4 | 36.4 | 23.5 | 10 | 14.0 | 2.3 |
| alakajam | 4 | 61.9 | 1.7 | 60.2 | 48.2 | 21.3 | 124.0 | 10 | 26.8 | 12.0 |
| agentlang | 2 | 87.9 | - | - | - | - | - | - | refused: singleThread/singleFork | - |
| agentlang | 4 | 86.6 | - | - | - | - | - | - | refused: singleThread/singleFork | - |
| yalc | 2 | 65.3 | 3.0 | 62.3 | 47.1 | 36.4 | 18.9 | 61 | 10.7 | 15.2 |
| yalc | 4 | 60.6 | 2.9 | 57.7 | 56.1 | 20.0 | 113.2 | 61 | 36.1 | 1.6 |
| ironcurtain | 2 | 135.8 | 7.6 | 128.2 | 93.1 | 76.0 | 27.8 | 62 | 17.1 | 35.1 |
| ironcurtain | 4 | 82.5 | 12.9 | 69.6 | 45.2 | 45.4 | 8.1 | 58 | -0.1 | 24.3 |
| codex-multi-auth | 2 | 293.6 | 15.4 | 278.2 | 227.7 | 214.5 | 28.0 | 1 | 13.2 | 50.6 |
| codex-multi-auth | 4 | 180.1 | 17.0 | 163.1 | 119.6 | 119.2 | 70.9 | 2 | 0.4 | 43.5 |
| drydock | 2 | 277.6 | 4.5 | 273.0 | 217.3 | 194.7 | 14.5 | 0 | 22.6 | 55.7 |
| drydock | 4 | 181.3 | 5.0 | 176.3 | 134.6 | 126.1 | 23.0 | 2 | 8.5 | 41.7 |
| lerna-lite | 2 | 598.9 | 3.6 | 595.3 | 601.8 | 297.6 | 546.0 | 11 | 304.2 | -6.5 |
| lerna-lite | 4 | 596.0 | 3.8 | 592.2 | 604.6 | 148.0 | 1606.7 | 11 | 456.6 | -12.4 |

## 2. Phase B runs (branch engine, cold plan)

`pre` = start to first worker ready; `window` = first worker ready to last file end (`ideal` = sum of file walls / w,
`idle` = the rest); `post` = last file end to exit; pass 2 = the hazard wrapper's one-lane re-run
(`src/parallel-rerun.js`), whose files' wall adds to the run.

| repo | w | wall | launch | pass | pre | window (ideal + idle) | post (deps_hash, trace_write) | files / processes | io_release (held s) | stack captures |
|---|---|---|---|---|---|---|---|---|---|---|
| nestjs-pino | 4 | 7.99 | 0.07 | 1 | 0.54 | 6.80 (5.09 + 1.71) | 0.54 (0.26, 0.03) | 25 / 25 | 0 (0.00) | 50439 |
| agentsys | 4 | 17.04 | 0.43 | 1 | 0.69 | 8.41 (5.93 + 2.48) | 1.10 (0.11, 0.14) | 51 / 4 | 0 (0.00) | 241352 |
| agentsys | 1 | 17.04 | 0.43 | 2 | 0.41 | 5.39 (5.33 + 0.05) | 0.25 (0.16, 0.03) | 8 / 1 | 0 (0.00) | 58163 |
| alakajam | 2 | 76.73 | 0.11 | 1 | 0.41 | 33.30 (23.51 + 9.79) | 0.75 (0.58, 0.03) | 27 / 27 | 0 (0.00) | 118532 |
| alakajam | 1 | 76.73 | 0.11 | 2 | 0.46 | 40.91 (39.47 + 1.44) | 0.67 (0.50, 0.03) | 11 / 11 | 0 (0.00) | 94804 |
| agentlang | 1 | 67.31 | 0.14 | 1 | 0.35 | 65.75 (62.57 + 3.19) | 1.02 (0.61, 0.17) | 25 / 25 | 0 (0.00) | 294171 |
| yalc | 4 | 85.99 | 0.32 | 1 | 1.40 | 38.09 (18.80 + 19.30) | 0.71 (0.28, 0.04) | 165 / 165 | 0 (0.00) | 50313 |
| yalc | 1 | 85.99 | 0.32 | 2 | 1.47 | 43.46 (34.32 + 9.14) | 0.39 (0.25, 0.02) | 64 / 64 | 0 (0.00) | 31884 |
| codex-multi-auth | 4 | 297.60 | 1.79 | 1 | 0.51 | 281.99 (95.69 + 186.30) | 11.06 (0.16, 0.77) | 459 / 459 | 12 (0.40) | 1839942 |
| codex-multi-auth | 1 | 297.60 | 1.79 | 2 | 0.44 | 1.21 (0.72 + 0.49) | 0.27 (0.19, 0.00) | 4 / 4 | 0 (0.00) | 2410 |
| drydock | 4 | 194.30 | 0.34 | 1 | 0.68 | 190.62 (95.02 + 95.59) | 2.60 (0.41, 0.56) | 651 / 651 | 0 (0.00) | 790918 |
| lerna-lite | 2 | 1128.05 | 0.09 | 1 | 0.36 | 526.77 (299.08 + 227.69) | 3.66 (0.30, 0.03) | 12 / 12 | 0 (0.00) | 37783 |
| lerna-lite | 1 | 1128.05 | 0.09 | 2 | 0.41 | 596.23 (594.65 + 1.58) | 0.41 (0.31, 0.03) | 12 / 12 | 0 (0.00) | 56552 |

CPU profiles (`cpuprof-summary.json`, self time over every profile written; Vitest fork workers are killed by the
pool and write none, so worker-side engine time shows only for Jest repositories and processes that exit):

| repo | profiles | total self s | engine self s | top engine functions (self s) |
|---|---|---|---|---|
| nestjs-pino | 2 | 42.436 | 0.152 | `depsInput` loaded.js:30 0.044; `phases.span.part` session.js:526 0.024; `projectFrame` controls.js:203 0.017 |
| agentsys | 46 | 116.795 | 8.468 | `resolveDepth` sites.js:125 2.484; `hazards` parallel.js:546 0.794; `wrapExports` jest/environment.js:132 0.785 |
| alakajam | 3 | 239.761 | 0.475 | `depsInput` loaded.js:30 0.127; `walk` loaded.js:15 0.051; `phases.span.part` session.js:526 0.048 |
| agentlang | 2 | 202.926 | 0.4 | `phases.span.part` session.js:526 0.116; `depsInput` loaded.js:30 0.063; `(anonymous)` session.js:593 0.037 |
| yalc | 29 | 273.019 | 0.659 | `hazards` parallel.js:546 0.125; `(anonymous)` cache/capture.js:1701 0.079; `depsInput` loaded.js:30 0.078 |
| codex-multi-auth | 959 | 1306.643 | 299.867 | `wait` clock.js:876 271.95; `hazards` parallel.js:546 9.103; `resolveDepth` sites.js:125 5.218 |
| drydock | 9 | 474.013 | 3.395 | `wait` clock.js:876 0.687; `phases.span.part` session.js:526 0.395; `resolveDepth` sites.js:125 0.31 |
| lerna-lite | 595 | 3523.041 | 3.431 | `hazards` parallel.js:546 3.012; `depsInput` loaded.js:30 0.092; `phases.span.part` session.js:526 0.037 |

## 3. Causes, ranked by the seconds they cost on the repositories that miss a bound

The gap is E_best - allowance × PP_best (baseline medians): how many seconds E must lose to meet the first bound.

| repo | PS | PP best | allowance | E best (w) | gap to bound 1 (s) | E needed for bound 2 (PS/2) | S/PS (engine serial / plain serial, rounds 2-3) |
|---|---|---|---|---|---|---|---|
| nestjs-pino | 21.3 | 8.0 | 1.30 | 10.7 (w4) | 0.3 | 10.6 | 1.23 |
| agentsys | 15.1 | 6.9 | 1.10 | 18.6 (w4) | 11.0 | 7.6 | 1.54 |
| alakajam | 37.0 | 9.7 | 1.30 | 54.6 (w2) | 42.0 | 18.5 | 1.98 |
| agentlang | 84.3 | 28.7 | 1.30 | 90.4 (w2) | 53.1 | 42.2 | 1.13 |
| yalc | 92.3 | 33.6 | 1.30 | 63.8 (w4) | 20.0 | 46.1 | 1.16 |
| ironcurtain | 251.1 | 80.7 | 1.30 | 95.2 (w4) | -9.6 | 125.5 | 1.22 |
| codex-multi-auth | 403.4 | 111.5 | 1.30 | 182.9 (w4) | 37.9 | 201.7 | 1.24 |
| drydock | 564.9 | 162.8 | 1.30 | 235.1 (w4) | 23.5 | 282.4 | 0.94 |
| lerna-lite | 616.9 | 283.3 | 1.09 | 606.2 (w2) | 297.8 | 308.5 | 0.98 |

Seconds below are from section 1 (round 3, at each repository's E_best w unless stated). A cause's seconds are an
upper bound on what its fix can save: the causes overlap where a lane wait is both the plan's and the runtime's.

### C1. Files grouped into one lane by "together" edges (plan excess) — about 520 s over 4 repositories

Round 1 records cross-lane hazards; from the next run the plan keeps the files of a hazard in one atom
(`src/parallel.js` plan, `together`). One large atom makes the plan's makespan far above sum/w:

| repo | plan excess at E_best w | what made the atom (round-1 hazards, `meta.parallel.hazards`) |
|---|---|---|
| lerna-lite | 304 s (w2); 457 s at w4: all 12 files in one lane | 54 × write-write on the directory `/tmp/pm-lerna-lite/lerna-lite-e2e` |
| yalc | 36 s (w4); 84 of 165 files in one lane | 871 × write-write on the repository root directory itself; 67 × list-write `configs/frameworks` |
| alakajam | 14 s (w2), 27 s (w4) | read-write on `data/tmp/unit-test.sqlite` (a real shared database), write-write `data/tmp`, read-write `static/uploads` |
| agentsys | 4 s (w4) | read-write on `AGENTS.md` and similar |

For lerna-lite and yalc the hazard is a *directory* every file writes into (each file creates its own child
under one parent). For alakajam it is a real shared file (plain parallel runs of alakajam also fail tests).
Possible fix: do not count the creation or removal of distinct children as a write to the parent directory.
**Design question** (it narrows a correctness control: what counts as a hazard): coordinator.

### C2. Worker slots held by files waiting for their lane predecessor (runtime excess) — about 120 s

The runner dispatches files in the plan's `dispatch` order; a file whose lane predecessor has not finished waits
inside its worker (`src/parallel.js` `enter()`, from line 246), holding the slot. A long file blocks its lane's
next file, which blocks a slot, until every slot waits on that lane. Phase B, codex-multi-auth (cold plan): 209 of
the 282 s window ran **one** file at a time; the CPU profile shows 272 s in the patched `Atomics.wait`
(`src/clock.js:876`, the lane wait's sleep). Round 3: codex-multi-auth 43.5 s (w4), drydock 41.7 s (w4),
ironcurtain 24.3 s (w4), alakajam 12.0 s (w4), yalc 15.2 s (w2), nestjs-pino 1.3 s (w4).
Possible fix: hand the runner a lane's next file only once its predecessor has finished (dispatch driven by the lane
markers), so that a slot never waits; the plan, the lanes and their order stay the same. No event kind is expected
to change. Implementation choice in the Vitest pool / Jest worker binding: coordinator to confirm.

### C3. agentlang's parallel request is refused — about 53 s

`meta.parallel.requested.refused = "singleThread/singleFork"`: the repository's Vitest config asks for one
thread, so `--det-workers` runs one lane (E = serial, 88-90 s); the plain parallel command runs it at w4 (28.7 s).
**Design question** (whether `--det-workers` may override the repository's own single-thread setting): coordinator.

### C4. Main-process work outside the lanes — about 25 s

Round 3 `outside lanes`: codex-multi-auth 15-17 s, ironcurtain 8-13 s, drydock 5 s, agentsys 3 s, nestjs-pino 1.8 s.
The largest piece found is the post-run hazard analysis, `hazards` (`src/parallel.js:546`): 9.1 s self in
codex-multi-auth's profile, 3.0 s in lerna-lite's (main process, after the last file). The deps digest
(`src/loaded.js`, every file of node_modules) costs 0.1-0.6 s warm, 3.6 s on a cold page cache. The hazard
wrapper's one-lane re-run (pass 2) is large on a cold plan (lerna-lite 596 s, yalc 45 s, alakajam 42 s,
agentsys 6 s in Phase B) and small or absent in the warm rounds. Possible fix: make `hazards` cheaper (same
result). No event kind is expected to change.

### C5. Engine overhead inside each test file — repository-dependent

S/PS (engine serial / plain serial, rounds 2-3): 1.13-1.24 on most repositories, 1.54 on agentsys and 1.98 on
alakajam (where about 110 tests also fail under the engine). The largest engine function in the profiles that
cover workers is the stack capture `resolveDepth` (`src/sites.js:125`): 2.5 s in agentsys (Jest), 5.2 s in
codex-multi-auth. Possible fix: cheaper stack capture with the same recorded site. No event kind is expected to
change.

### What each repository needs

- **nestjs-pino** (gap 0.3 s): C2 or C4 alone closes it.
- **codex-multi-auth** (gap 37.9 s): C2 (43.5 s) and C4 (part of 17 s).
- **drydock** (gap 23.5 s): C2 (41.7 s).
- **yalc** (gap 20.0 s): C1 (36 s).
- **lerna-lite** (gap 297.8 s): C1; its longest file alone is 282 s, so the best possible makespan is about the
  plain parallel time (283 s) and the bound (309 s) is reachable only with no atom.
- **agentlang** (gap 53.1 s): C3 only.
- **alakajam** (gap 42.0 s): not reachable by C1-C4 alone. At w2, sum of file seconds / 2 is 36.4 s against an
  allowed E of 12.6 s: the per-file overhead (C5, S/PS 1.98) dominates, and its atom is a real shared database.
- **agentsys** (bound 2 needs E ≤ 7.6 s): not reachable without C5 (sum of file seconds / 4 is already 8.2 s).

### Proposed fix order (rank by seconds, design questions marked)

1. C1 (about 520 s): **design question** first.
2. C2 (about 120 s): dispatch driven by the lane markers.
3. C3 (about 53 s): **design question**.
4. C4 (about 25 s): cheaper `hazards`.
5. C5: cheaper stack capture, if time remains before 8 Dec 2026 12:00 UTC.

If C1 and C3 are not approved, the order is C2, C4, C5.
