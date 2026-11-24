DONE

# Lane D: the no-engine control arm (plain runs only)

Plain runner commands only; the engine (detjs, fenvix) was never run. Data: `results.jsonl` (one row per run and one per test verdict), `pairs.jsonl` (one row per victim), `data/<repo>/<run>.json` (outcome map, failure messages, per-file start/end of every run). Code: `control_arm.py`, tests `test_control_arm.py`.

## Verdicts per repository

| repository | tests (serial) | IDENTICAL | DIVERGES (order / parallel) | of which in 1 parallel run only | DIVERGES-order-only | UNDECIDED (insufficient parallel / S1≠S2 / run failed or short) | ENV | test files that did not load (per run; their tests are in no column) | `parallel` label vs SS with the same seed (holds / order / not checked) |
|---|---|---|---|---|---|---|---|---|---|
| codex-multi-auth | 8662 | 8644 | 9 (9 / 0) | 1 | 0 | 19 (0 / 1 / 18) | 6 | 0 | 0 / 0 / 0 |
| ironcurtain | 7033 | 7028 | 5 (4 / 1) | 1 | 0 | 0 (0 / 0 / 0) | 0 | 60 | 0 / 1 / 0 |
| yalc | 1483 | 1480 | 2 (0 / 2) | 1 | 0 | 1 (0 / 1 / 0) | 0 | 1 | 2 / 0 / 0 |
| nestjs-pino | 269 | 269 | 0 (0 / 0) | 0 | 0 | 0 (0 / 0 / 0) | 0 | 0 | 0 / 0 / 0 |
| agentsys | 2224 | 2224 | 0 (0 / 0) | 0 | 0 | 0 (0 / 0 / 0) | 0 | 0 | 0 / 0 / 0 |
| lerna-lite | 107 | 107 | 0 (0 / 0) | 0 | 0 | 0 (0 / 0 / 0) | 0 | 0 | 0 / 0 / 0 |
| drydock | 21578 | 21488 | 66 (40 / 26) | 29 | 0 | 216 (0 / 0 / 216) | 0 | 0 | 0 / 26 / 0 |
| agentlang | 439 | 434 | 5 (4 / 1) | 2 | 0 | 0 (0 / 0 / 0) | 0 | 0 | 0 / 1 / 0 |
| alakajam | 68 | 68 | 0 (0 / 0) | 0 | 0 | 0 (0 / 0 / 0) | 0 | 14 | 0 / 0 / 0 |

## Runs and parallelism

| repository | timed out | crashed | short (tests missing vs serial) | INVALID (serial in disguise) | parallel mode effective | UNDECIDED with a divergence seen |
|---|---|---|---|---|---|---|
| codex-multi-auth | 0 | 0 | 0 | 0 | yes (5/5 valid) | 1 |
| ironcurtain | 0 | 0 | 0 | 0 | yes (5/5 valid) | 0 |
| yalc | 0 | 0 | 0 | 0 | yes (5/5 valid) | 1 |
| nestjs-pino | 0 | 0 | 0 | 0 | yes (5/5 valid) | 0 |
| agentsys | 0 | 0 | 0 | 0 | yes (5/5 valid) | 0 |
| lerna-lite | 0 | 0 | 0 | 0 | yes (5/5 valid) | 0 |
| drydock | 0 | 0 | 0 | 0 | yes (5/5 valid) | 0 |
| agentlang | 0 | 0 | 0 | 0 | yes (5/5 valid) | 0 |
| alakajam | 0 | 0 | 0 | P2, P3 | partly (3/5 valid) | 0 |

## Minimal pairs and wall time

| repository | victims searched (of which label order) | divergence reproduced in any trial | pairs found | not found (victim file alone reproduces 2+ of 3 with negative controls clean, of which with a control seed / not reproduced / other) | over budget | serial median (s) | parallel run median (s, completed / valid) | 9 runs (s) | pair search (s) | total (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| codex-multi-auth | 9 (9) | 9 | 0 | 9 (9, 4 / 0 / 0) | 0 | 358.5 | 119.1 / 119.1 | 2040.7 | 321.5 | 2362.2 |
| ironcurtain | 5 (4) | 5 | 0 | 5 (5, 5 / 0 / 0) | 0 | 204.9 | 65.5 / 65.5 | 1150.5 | 52.03 | 1202.5 |
| yalc | 2 (0) | 0 | 0 | 2 (0, 0 / 2 / 0) | 0 | 78.4 | 30.7 / 30.7 | 468.0 | 113.02 | 581.0 |
| nestjs-pino | 0 (0) | 0 | 0 | 0 (0, 0 / 0 / 0) | 0 | 16.3 | 6.2 / 6.2 | 96.2 | 0.04 | 96.2 |
| agentsys | 0 (0) | 0 | 0 | 0 (0, 0 / 0 / 0) | 0 | 13.8 | 5.6 / 5.6 | 78.0 | 0.03 | 78.0 |
| lerna-lite | 0 (0) | 0 | 0 | 0 (0, 0 / 0 / 0) | 0 | 604.2 | 292.8 / 292.8 | 3885.1 | 0.04 | 3885.1 |
| drydock | 10 (7) | 10 | 0 | 10 (10, 9 / 0 / 0) | 0 | 475.0 | 145.2 / 145.2 | 2672.3 | 332.04 | 3004.3 |
| agentlang | 5 (4) | 5 | 0 | 5 (5, 4 / 0 / 0) | 0 | 49.7 | 18.5 / 18.5 | 285.8 | 113.69 | 399.5 |
| alakajam | 0 (0) | 0 | 0 | 0 (0, 0 / 0 / 0) | 0 | 12.1 | 5.1 / 5.0 | 74.8 | 0.04 | 74.8 |

## How the runs were made

- Repositories and pinned commits: `harness/parallel_measure/specs.json`; fetched and installed per `RERUN.md` section 2
  (work tree `/tmp/pm`). Machine: every run row carries `nproc` and `cpu_model`.
- Before every run: `measure.reset_tree` + build, `node_modules/.vite*` and `.vitest*` removed, reporter placed, a fresh
  TMPDIR (`/tmp/pm-<repo>`, emptied) (D18); jest also `--cacheDirectory=$TMPDIR/jest`. Timeout per run: 3x the serial
  median, at least 60 s (agentsys, alakajam, nestjs-pino: 60 s) (S1, S2 use 7200 s) (R7). stderr goes to the run log, never silenced.
- Flags copied from `harness/parallel_measure/repro.py` `main()` (cited in `control_arm.py`): vitest S
  `--no-file-parallelism`, SS + `--sequence.shuffle --sequence.seed=S`, P `--maxWorkers=4 --fileParallelism
  --sequence.shuffle --sequence.seed=S`; jest S `--runInBand`, SS `--runInBand --randomize --seed=S`, P
  `--maxWorkers=4 --randomize --seed=S`. The full command of every run is the `cmd` field of its row in `results.jsonl`.
- Parallel check: a P run is valid only if at least two of its test files overlap in time (per-file start/end from the
  JSON report); otherwise INVALID ("serial in disguise") and not used as evidence.
- Short run: fewer tests than the serial runs (count). A test whose id is absent from a run (a test name that changes
  every run: a timestamp or random suffix in the title, seen in codex-multi-auth and drydock) is UNDECIDED
  (`run-failed-or-short`, "<run> missing the test") without the run being short; `missing_vs_serial` keeps the id count.

## Commands cited (observed results)

- yalc P3 (DIVERGES/parallel): `npx --no-install vitest run --maxWorkers=4 --fileParallelism --sequence.shuffle
  --sequence.seed=3 ...` (full line: `cmd` of yalc P3) - `src/__tests__/skill-migration.test.ts::0.8.C skill
  migration::all bundled framework yamls parse and reference resolvable step skills` failed with `AssertionError:
  schema-test-...yaml: skill 'schema-emit' not found`; passed in S1, S2, SS1, SS2, P1, P2; failed in P3, P4, P5.
- ironcurtain P3 (DIVERGES/parallel): `npx --no-install vitest run --maxWorkers=4 --fileParallelism --sequence.shuffle
  --sequence.seed=3 ...` - `test/docker-agent-adapter.test.ts@@main::Agent Registry::lists registered agents` failed
  with `AssertionError: expected 0 to be greater than or equal to 1` (test/docker-agent-adapter.test.ts:685); passed in
  every other run of the spec; it also failed in the supplementary SS3 (same seed, serial), see below.
- agentsys P1: `npx --no-install jest --maxWorkers=4 --randomize --seed=1 --json ... --cacheDirectory=/tmp/pm-agentsys/jest`
  - 2224 tests, 140-143 overlapping file pairs per parallel run, every test the same outcome as serial.

## Minimal pairs (R11)

- Plain runner only (never `detjs repro`). Victims: up to 10 per repository, `random.Random(1).sample` over the sorted
  DIVERGES ids (drydock: 10 of 66; the others: all). Fixed file order enforced by a sequencer (jest `--testSequencer`;
  vitest a wrapper config in `.fenvix-harness/` made with `mergeConfig`, projects kept). Inside each file the tests run
  in the diverging run's order: its seed is replayed (vitest `sequence.shuffle: {files: false, tests: true}` + seed;
  jest `--randomize --seed`).
- Order of a search (each trial is one plain run of the 30-run budget; 3 h per repository): (1) control: the victim's
  file alone with the diverging run's seed, twice. If the victim's outcome differs from serial, confirm with 2 more runs: it
  must differ in at least 2 runs and in at least 2 of 3 of all its alone runs (a miss before the first hit counts); then two negative controls must keep the serial outcome: the file alone without a seed
  (2 runs) and the file alone with up to 2 distinct control seeds (seeds of runs where the victim kept its serial
  outcome). All pass -> "no minimal pair (victim file alone reproduces)": the cause is inside its own file. (2) per
  mode, serial (candidates: files started before the victim's file ended in the diverging run, in start order) then
  concurrent (candidates: files whose run overlapped the victim's file; victim file and candidates in two processes
  started together): the full candidate set twice; if the divergence does not show, "not reproduced". (3) bisect,
  each half run twice; neither half triggers -> "no minimal pair (interaction)". (4) confirm: pair differs >= 2 of 3
  and victim alone keeps its serial outcome 3 of 3. A trial in which a file outside the trial's set ran before the
  victim's file ended (vitest CLI file arguments are substring filters) yields no evidence and ends the search as
  "trial failed" (none occurred).
- Result (third search, 199 runs, 932.4 s in all): 29 of 31 victims reproduce with their own file alone under the
  diverging run's seed in 3 of 3 runs. Negative controls: unseeded 58 runs, 0 reproduced; control seeds 42 runs over
  22 victims, 0 reproduced. The other 7 victims (codex-multi-auth 5, drydock 1, agentlang 1) differed in all 5
  parallel runs, so no control seed was available; their unseeded controls were clean. These are dependences on test
  order inside one file, not pairs of files: 0 confirmed pairs. The 2 yalc victims (label `parallel`) were not
  reproduced: alone 2 runs, full serial candidate set 2 runs (59 and 37 files), full concurrent set 2 runs (2 and 7
  files), 6 runs each; nothing is claimed about their cause.
- Earlier searches. The first (commit 70b27fd, 22484 s over 31 victims) bisected without controls and without the seed
  replay: 0 of 244 trials reproduced a divergence, recorded as "no minimal pair (interaction)" (30) and "pair not
  found (budget)" (1). On the pre-merge review showing it could not reproduce within-file order, the user chose to
  rerun the search with controls (decision D1, 2026-11-23). The second search added the seed replay and a single
  control-seed run; the second review asked for a 2-of-3 confirmation, an unseeded control and distinct control seeds,
  which the third search adds. Each search's rows replace the previous ones in `pairs.jsonl`; wall times in the tables
  are the third search's.
- A trial with no victim outcome (timeout, crash, no report) ends a search as "no minimal pair (trial failed)" (none
  occurred).
- Three rules were tightened after the third search (review pass 3): a miss before the first alone hit now counts; a
  seed under which the victim differed in any run (SS included) is no control seed; a trial without the victim file's
  start/end is no evidence. Checked on the recorded trials: every first alone run hit, no control seed used diverged
  in any run, every trial has the victim file's start/end; so the recorded results are those the tightened code gives.

## The `parallel` label checked against shuffled serial runs with the same seed

- Inside a file, the test order depends only on the seed (vitest shuffles each suite's tasks with `sequence.seed`; jest
  `--randomize --seed`), so Pk and SSk share it. Every DIVERGES test labelled `parallel` diverged only in P3, P4 or P5,
  whose seeds no SS run of the spec used. Supplementary runs SS3, SS4, SS5 (`control_arm.py supp_ss`, rows
  `"row": "run_supp"` in `results.jsonl`, data `data/<repo>/SS3..SS5.json`) were made for all 9 repositories; they do
  not enter any verdict.
- Result (column "`parallel` label vs SS with the same seed"): of 30 tests labelled `parallel`, 28 (drydock 26,
  ironcurtain 1, agentlang 1) also differ from serial in the serial run with the same seed: their divergence is test
  order under that seed, not parallelism. The 2 yalc tests keep their serial outcome in SS3, SS4 and SS5: the label
  holds for them. The verdicts keep the spec's labels; the column is the correction.
- Each of the 28 rests on one same-seed SS run (5 of them were also pair-search victims reproduced 3 of 3 with their
  file alone). Of drydock's 29 DIVERGES tests seen in one parallel run only, 21 are among the 28 (reproduced in the
  same-seed serial run, so not a one-off parallel failure); the other 8 are labelled `order`.

## Tests in no verdict column

- Test files that did not load (the runner reports the file failed with no test in it) are in no outcome map, so their
  tests are in no column. Same count in all 9 runs of each repository (column "test files that did not load"), causes
  from the S1 raw report: alakajam 14 of its files (`Knex: run ... npm install sqlite3`, sqlite3 native bindings not
  built), ironcurtain 60 (33 `Cannot find module .../@provos/memory-mcp-server/dist/index.js`, 21 `Cannot find package
  '@provos/memory-mcp-server/prompts'`, 5 `No native build was found` (isolated-vm), 1 vitest mocking error), yalc 1
  (`Cannot find module .../lost-deal-revival`). The IDENTICAL counts of these three repositories cover only the files
  that loaded; the 22 Dec comparison must compare the same test set.
- Duplicate test names inside one file get a ` #n` suffix by report order (measure.py), which a shuffle can swap. Such
  groups: 70 (228 ids); 224 IDENTICAL ids are in 68 of them, the other 2 groups (4 ids, drydock) are DIVERGES; in no run does a duplicate group have mixed outcomes, so no verdict depends on
  the swap.

## Verdict rule notes

- ENV is checked first, on failure messages pooled over all 9 runs (as the spec orders). A test that passes serially
  and fails only in a parallel run with a local `ECONNREFUSED` would be ENV, not DIVERGES. Measured: all 6 ENV tests
  (codex-multi-auth) failed in all 9 runs with the ENV message, so no verdict here is affected.
- DIVERGES needs one valid parallel run that differs; column "of which in 1 parallel run only" counts the DIVERGES
  tests that differ in exactly one of the 5 (drydock 29 of 66). A rare flaky failure would also produce that; the
  same-seed SS check above shows which ones do not.

## Per-repository remarks

- lerna-lite, alakajam: exit 0/1 of the runner does not enter a verdict; outcomes per test do.
- alakajam: P2 and P3 had no overlapping files (INVALID); P1, P4, P5 had 1 overlapping file pair each. Exactly 3 valid
  parallel runs remain, the minimum the rule allows, so its 68 IDENTICAL rest on thin parallel evidence.
- yalc: parallel runs overlapped (228-260 file pairs) despite the repository's single-fork setting.
- UNDECIDED serial-disagree: codex-multi-auth `test/codex-bin-wrapper.test.ts::codex bin wrapper::stress: metadata stays
  bounded across many launch/exit cycles` (S1 failed, S2 passed); yalc `src/__tests__/capability-adapters.test.ts::
  icp-company-search adapters::crustdata adapter calls autocomplete_filter ...` (S1 passed, S2 failed).
- ENV (codex-multi-auth, 6): messages matched `classify.ENV_PATTERNS` (no IPv6 loopback; a file the test copies is
  missing). No measured failure matched the local ECONNREFUSED pattern.

## Step 4 (classify.py, session B review R3)

DONE. Lane A's `REPORT-lane-a.md` (first line DONE) was on `claude/release-1` on 2026-11-23, before the 1 December
deadline. Merged the trunk; added one `ENV_PATTERNS` entry for `ECONNREFUSED` to `127.x.x.x`/`localhost` (`::1` was
already matched by the IPv6 loopback pattern, not duplicated); added `harness/parallel_measure/test_classify_env.py`
(local refused connection is ENV, non-local is not, `::1` still the existing cause). Until then the same pattern was
applied locally in `control_arm.py` only; after the merge `control_arm.py` defers to `classify.env_cause`. Verdicts
were recomputed from the recorded runs after the change: 0 of 42071 changed.

## For the 22 Dec comparison

Control arm columns measured here; engine columns left empty (filled at the verdict).

| repository | control: bugs (confirmed pairs) | control: within-file order dependences reproduced alone (victims) | control: DIVERGES tests | control: wrong IDENTICAL | control: wall serial median / parallel median (s) | engine: bugs | engine: wrong identical | engine: wall |
|---|---|---|---|---|---|---|---|---|
| codex-multi-auth | 0 | 9 of 9 | 9 | (at verdict) | 358.5 / 119.1 | | | |
| ironcurtain | 0 | 5 of 5 | 5 | (at verdict) | 204.9 / 65.5 | | | |
| yalc | 0 | 0 of 2 | 2 | (at verdict) | 78.4 / 30.7 | | | |
| nestjs-pino | 0 | 0 of 0 | 0 | (at verdict) | 16.3 / 6.2 | | | |
| agentsys | 0 | 0 of 0 | 0 | (at verdict) | 13.8 / 5.6 | | | |
| lerna-lite | 0 | 0 of 0 | 0 | (at verdict) | 604.2 / 292.8 | | | |
| drydock | 0 | 10 of 10 | 66 | (at verdict) | 475.0 / 145.2 | | | |
| agentlang | 0 | 5 of 5 | 5 | (at verdict) | 49.7 / 18.5 | | | |
| alakajam | 0 | 0 of 0 | 0 | (at verdict) | 12.1 / 5.1 | | | |
