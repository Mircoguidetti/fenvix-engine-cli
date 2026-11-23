DONE

# Lane D: the no-engine control arm (plain runs only)

Plain runner commands only; the engine (detjs, fenvix) was never run. Data: `results.jsonl` (one row per run and one per test verdict), `pairs.jsonl` (one row per victim), `data/<repo>/<run>.json` (outcome map, failure messages, per-file start/end of every run). Code: `control_arm.py`, tests `test_control_arm.py`.

## Verdicts per repository

| repository | tests (serial) | IDENTICAL | DIVERGES (order / parallel) | DIVERGES-order-only | UNDECIDED (insufficient parallel / S1≠S2 / run failed or short) | ENV |
|---|---|---|---|---|---|---|
| codex-multi-auth | 8662 | 8644 | 9 (9 / 0) | 0 | 19 (0 / 1 / 18) | 6 |
| ironcurtain | 7033 | 7028 | 5 (4 / 1) | 0 | 0 (0 / 0 / 0) | 0 |
| yalc | 1483 | 1480 | 2 (0 / 2) | 0 | 1 (0 / 1 / 0) | 0 |
| nestjs-pino | 269 | 269 | 0 (0 / 0) | 0 | 0 (0 / 0 / 0) | 0 |
| agentsys | 2224 | 2224 | 0 (0 / 0) | 0 | 0 (0 / 0 / 0) | 0 |
| lerna-lite | 107 | 107 | 0 (0 / 0) | 0 | 0 (0 / 0 / 0) | 0 |
| drydock | 21578 | 21488 | 66 (40 / 26) | 0 | 216 (0 / 0 / 216) | 0 |
| agentlang | 439 | 434 | 5 (4 / 1) | 0 | 0 (0 / 0 / 0) | 0 |
| alakajam | 68 | 68 | 0 (0 / 0) | 0 | 0 (0 / 0 / 0) | 0 |

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

| repository | victims searched | pairs found | not found | over budget | serial median (s) | parallel run median (s, completed / valid) | 9 runs (s) | pair search (s) | total (s) |
|---|---|---|---|---|---|---|---|---|---|
| codex-multi-auth | 9 | 0 | 9 | 0 | 358.5 | 119.1 / 119.1 | 2040.7 | 7093.4 | 9134.1 |
| ironcurtain | 5 | 0 | 5 | 0 | 204.9 | 65.5 / 65.5 | 1150.5 | 3659.8 | 4810.3 |
| yalc | 2 | 0 | 2 | 0 | 78.4 | 30.7 / 30.7 | 468.0 | 200.04 | 668.0 |
| nestjs-pino | 0 | 0 | 0 | 0 | 16.3 | 6.2 / 6.2 | 96.2 | 0.03 | 96.2 |
| agentsys | 0 | 0 | 0 | 0 | 13.8 | 5.6 / 5.6 | 78.0 | 0.03 | 78.0 |
| lerna-lite | 0 | 0 | 0 | 0 | 604.2 | 292.8 / 292.8 | 3885.1 | 0.04 | 3885.1 |
| drydock | 10 | 0 | 9 | 1 | 475.0 | 145.2 / 145.2 | 2672.3 | 10861.36 | 13533.6 |
| agentlang | 5 | 0 | 5 | 0 | 49.7 | 18.5 / 18.5 | 285.8 | 669.3 | 955.1 |
| alakajam | 0 | 0 | 0 | 0 | 12.1 | 5.1 / 5.0 | 74.8 | 0.04 | 74.8 |

## How the runs were made

- Repositories and pinned commits: `harness/parallel_measure/specs.json`; fetched and installed per `RERUN.md` section 2
  (work tree `/tmp/pm`). Machine: every run row carries `nproc` and `cpu_model`.
- Before every run: `measure.reset_tree` + build, `node_modules/.vite*` and `.vitest*` removed, reporter placed, a fresh
  TMPDIR (`/tmp/pm-<repo>`, emptied) (D18); jest also `--cacheDirectory=$TMPDIR/jest`. Timeout per run: 3x the serial
  median (S1, S2 use 7200 s) (R7). stderr goes to the run log, never silenced.
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
  every other run.
- agentsys P1: `npx --no-install jest --maxWorkers=4 --randomize --seed=1 --json ... --cacheDirectory=/tmp/pm-agentsys/jest`
  - 2224 tests, 141-143 overlapping file pairs per parallel run, every test the same outcome as serial.

## Minimal pairs (R11)

- Plain runner only (never `detjs repro`). Victims: up to 10 per repository, `random.Random(1).sample` over the sorted
  DIVERGES ids (drydock: 10 of 66; the others: all). Candidates: the files that started before the victim's file ended
  in the diverging run. Fixed order enforced by a sequencer (jest `--testSequencer`; vitest a wrapper config in
  `.fenvix-harness/` made with `mergeConfig`, projects kept).
- Search serial first, then concurrent (each group in its own process, started together). Bisect: each half run twice;
  a half triggers if the victim fails in either run. The first step ran both halves twice in both modes (8 runs) and
  the victim passed every time, for all 30 victims that stopped there: recorded as "no minimal pair (interaction)" -
  no half of the candidates reproduces the failure in a fixed order. This is a measurement, not a claim that no polluter
  exists: the divergences were seen under shuffled order (within-file test order included), which a fixed-order file
  sequence does not reproduce.
- drydock's 10th victim (`store/mqtt-hass.test.ts::...hasRunHassIdentityTopicCleanup returns false before
  createCollections runs`) got 4 runs before the 3 h per-repository budget ran out: "pair not found (budget)".
- Pairs found: 0 in all 9 repositories. No confirmed pair, so nothing to reproduce.

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

| repository | control: bugs (confirmed pairs) | control: DIVERGES tests | control: wrong IDENTICAL | control: wall serial median / parallel median (s) | engine: bugs | engine: wrong identical | engine: wall |
|---|---|---|---|---|---|---|---|
| codex-multi-auth | 0 | 9 | (at verdict) | 358.5 / 119.1 | | | |
| ironcurtain | 0 | 5 | (at verdict) | 204.9 / 65.5 | | | |
| yalc | 0 | 2 | (at verdict) | 78.4 / 30.7 | | | |
| nestjs-pino | 0 | 0 | (at verdict) | 16.3 / 6.2 | | | |
| agentsys | 0 | 0 | (at verdict) | 13.8 / 5.6 | | | |
| lerna-lite | 0 | 0 | (at verdict) | 604.2 / 292.8 | | | |
| drydock | 0 | 66 | (at verdict) | 475.0 / 145.2 | | | |
| agentlang | 0 | 5 | (at verdict) | 49.7 / 18.5 | | | |
| alakajam | 0 | 0 | (at verdict) | 12.1 / 5.1 | | | |
