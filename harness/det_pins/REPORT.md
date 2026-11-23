DONE

# Lane C: `--det` outcome flips vs the engine's pins (ironcurtain, codex-multi-auth)

Measured 2026-11-23 in this session's container (`nproc` 4), engine = trunk `origin/claude/release-1` at
`e7338950` (contains P0 81f838c6), built with `cd node && npm ci && npm run build`. Flips were re-derived on this trunk;
no list from bfaf70b4 was reused. Driver: `harness/det_pins/pins.py` (imports `place_reporter`, `ids_outcomes`,
`runner_outcomes`, `reset_tree`, `run` from `harness/parallel_measure/measure.py`); tables below are printed by
`python3 harness/det_pins/report.py` from `results.jsonl` and `data/<repo>/{flips,sample,runs}.json*` (no number typed by
hand). Repositories at their `specs.json` commits (ironcurtain `abf2b44c`, codex-multi-auth `b9886168`),
`npm ci --ignore-scripts --no-audit --no-fund`, `$PM_WORK=/tmp/pm`.

Hygiene, every run (recorded per run in `data/<repo>/runs.jsonl` and per variant run in `results.jsonl`:
`tmpdir_reset`, `detjs_dir_removed`): `git checkout -- . && git clean -fdx -e node_modules` in the checkout (removes
`.detjs/`), TMPDIR=TMP=TEMP=`/tmp/pm-<repo>` emptied (measure.py D18). Plain runs: ids reporter copied into the
repository with `place_reporter`, `PM_IDS_OUT=<dir>/plainN.ids.json`. Every cited command was run with stderr merged
into its log (`/tmp/pm/det_pins/<repo>/runs.log`, last 1500 chars in each `runs.jsonl` row as `tail`).

Definitions (spec): flip = passed in both plain serial runs and failed/error in both whole-suite `--det --det-workers=1`
runs. Variants run the flip's file alone (`detjs vitest run <file> [--project main] --det --det-workers=1 ...`), two
runs each; cleared = passed in both runs; one pass + one fail = "unstable in Vn" (not cleared); V1-V5 use
`--det-epoch=<UTC now at the start of that run>`. V0 control: passed twice = "not reproduced alone" (excluded from
cleared counts).

| variant | flags added to `--det --det-workers=1` |
|---|---|
| V0 | (none) |
| V1 | `--det-epoch=<now>` |
| V2 | V1 + `--det-tz=keep --det-locale=keep` |
| V3 | V2 + `--det-timers=real` |
| V4 | V3 + `--det-disable=net` |
| V5 | V3 + `--det-disable=net,fs` (= V4 + fs; one list) |
| V6 | `--det-disable=time,timers,net,fs --det-tz=keep --det-locale=keep` |

The `controls` field of each variant run's `--det-outcomes` file confirms the flags took effect (V4: `net` absent; V6:
only isolation, order, seeds left).

## Summary (MEASURED)

| | ironcurtain | codex-multi-auth |
|---|---|---|
| flips on trunk (2 plain x 2 `--det`) | 206 | 362 |
| absent / skipped in a `--det` run | 0 / 10 | 0 / 0 |
| failed in one `--det` run only (not flips) | 0 | 45 |
| sampled (`random.Random(1)`, sorted ids) | 50 (15 files) | 50 (8 files) |
| not reproduced alone (V0 passed twice) | 0 | 2 |
| unstable at V0 | 0 | 0 |
| reproduced | 50 | 48 |
| cleared cumulative V1 / V2 / V3 / V4 / V5 / V6 | 34 / 34 / 37 / 49 / 49 / 50 | 0 / 2 / 42 / 42 / 42 / 46 |
| remain at V6 | 0 | 2 |
| ENV verdicts (container) | 0 | 0 |

Reading:

- **ironcurtain: the epoch is the main pin.** 34/50 clear at V1 alone; 31 of them fail under V0 with `certificate has
  expired` (TLS certificates generated at real time, validated on the virtual 2025-01-01 clock; 149 of the 206 flips
  carry this message in a `--det` run's exception, `data/ironcurtain/flips.json` `flip_exceptions`). 12 more clear at V4 (network control off):
  `NetworkBlockedError: detjs: network access ...` and 502 from a proxy whose upstream connection the engine refuses.
  3 clear at V3 (real timers: process-kill / watchdog / metrics-poll waits). One (`test/ca.test.ts ... publishes one
  authority under concurrent first-use creator/loaders`) clears only at V6, i.e. with the `time` control fully off
  (the host epoch alone at V1-V5 is not enough).
- **codex-multi-auth: virtual timers are the main pin.** 0/48 clear at V1; 40 clear first at V3 (`--det-timers=real`),
  nearly all `Test timed out in 5000ms` under V0. The +2 at V2 (tz/locale) are both in
  `test/runtime-rotation-proxy.test.ts`, where 5 other sampled tests are "unstable in V2" and clear at V3: these timeouts
  are borderline in V2; tz/locale is not shown to be their cause. 4 clear only at V6 (time control off: property tests
  `too many pre-condition failures`, `expected 503 to be 200`, a ledger snapshot mismatch). 2 remain failing at V6:
  `crash-mid-write.test.ts` (`Storage is busy with another live ...`) and `json-store-lock.test.ts`
  (`ELOCKTIMEOUT`), cross-process lock tests: a non-pin cause (still under `--det` with time/timers/net/fs off:
  order, seeds, isolation remain). No sampled flip in either repository fails with a stack overflow (J17-like): 0 flips
  of 568 carry `call stack` in their exception.
- No flip cleared at one variant failed again at a later variant (monotone in both repositories).
- `detjs verify --json` on the two V0 traces names `fs` for 32/50 ironcurtain rows and `other`/`env`/`fs`/`io`/`time`
  mixtures on codex-multi-auth; as expected it does not name the pin that causes the flip (it names the first
  divergent event between two runs).

Failure classes are a regex on the V0 first line (`pins.py classify`): timeout = `timed out|timeout|not met within N
ms`; date/time = dates, `expired`, clock words; `certificate has expired` therefore counts as date/time (it is a TLS
validity check against the clock, not an assertion in the test).

No claim: this does not show that a host-matched engine still proves these tests; it only shows which pins make them
fail. Counts are on a 50-test sample per repository, not the full flip lists.

## Reproduce

```bash
export PM_WORK=/tmp/pm   # repositories under $PM_WORK/repos as harness/parallel_measure/RERUN.md step 2
cd harness/det_pins
python3 pins.py find --repo ironcurtain        # 2 plain + 2 --det whole-suite runs -> flips.json
python3 pins.py variants --repo ironcurtain    # sample.json + V0..V6 x 2 per file
python3 pins.py rows --repo ironcurtain        # results.jsonl rows (+ detjs verify --json on V0 traces)
# same for codex-multi-auth; then
python3 report.py
```

Raw outcome files and traces stay in `/tmp/pm/det_pins/` (not committed: size); every row of `results.jsonl` carries
the exact command, cwd, exit, wall time and timestamp of each of its 14 variant runs and of the 4 find runs.

Not done: merge into `claude/release-1` (needs a gstack `/review` first; branch pushed only). Wall time used: about
3 h of the 10 h cap.

## ironcurtain

Engine `e7338950262acc4bd24ed6d3af6a59e3f765a3af`. Find runs (`data/ironcurtain/runs.jsonl`, kind plain/det):

| run | exit | wall s | outcome counts | command |
|---|---|---|---|---|
| plain 1 | 1 | 231.82 | {"passed": 6900, "skipped": 113, "failed": 20} | `npx --no-install vitest run --no-file-parallelism --reporter=default --reporter=/tmp/pm/repos/ironcurtain/.fenvix-harness/vitest_ids_reporter.mjs --reporter=json --outputFile.json=/tmp/pm/det_pins/ironcurtain/plain1.runner.json` |
| plain 2 | 1 | 226.57 | {"passed": 6900, "skipped": 113, "failed": 20} | `npx --no-install vitest run --no-file-parallelism --reporter=default --reporter=/tmp/pm/repos/ironcurtain/.fenvix-harness/vitest_ids_reporter.mjs --reporter=json --outputFile.json=/tmp/pm/det_pins/ironcurtain/plain2.runner.json` |
| det 1 | 1 | 243.9 | {"passed": 6684, "skipped": 123, "failed": 226} | `node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --det --det-workers=1 --det-outcomes=/tmp/pm/det_pins/ironcurtain/det1.outcomes.json --det-trace=/tmp/pm/det_pins/ironcurtain/det1.trace.jsonl` |
| det 2 | 1 | 243.08 | {"passed": 6684, "skipped": 123, "failed": 226} | `node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --det --det-workers=1 --det-outcomes=/tmp/pm/det_pins/ironcurtain/det2.outcomes.json --det-trace=/tmp/pm/det_pins/ironcurtain/det2.trace.jsonl` |

- passed in both plain runs: 6900; of these passed in both `--det` runs: 6684
- **flips** (passed in both plain runs, failed/error in both `--det` runs): **206**
- absent from a `--det` run: 0; skipped in a `--det` run: 10; failed in one `--det` run and passed in the other (not flips): 0
- sampled: 50 (random.Random(1).sample(sorted(flips), 50)); affected files: 15
- V0 control alone (file alone, `--det`, 2 runs): reproduced 50, not reproduced alone 0, unstable at V0 0

Cumulative cleared (passed in both runs) among the reproduced flips, by first clearing variant:

| | V1 epoch | V2 +tz/locale | V3 +timers real | V4 +net off | V5 +fs off | V6 upper bound |
|---|---|---|---|---|---|---|
| cleared, cumulative (of 50) | 34 (+34) | 34 (+0) | 37 (+3) | 49 (+12) | 49 (+0) | 50 (+1) |
| verdict in this variant | cleared 34, still fails 16 | cleared 34, still fails 16 | cleared 37, still fails 13 | cleared 49, still fails 1 | cleared 49, still fails 1 | cleared 50 |

Remain at V6 (not cleared in any variant): **0**

Cleared at a variant but not at every later one: 0

Failure class (V0 first line) x first clearing variant:

| class | V1 | V2 | V3 | V4 | V5 | V6 | none | total |
|---|---|---|---|---|---|---|---|---|
| timeout | 3 | 0 | 0 | 2 | 0 | 0 | 0 | 5 |
| date/time assertion | 31 | 0 | 0 | 0 | 0 | 0 | 0 | 31 |
| network error | 0 | 0 | 0 | 8 | 0 | 0 | 0 | 8 |
| file error | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| other | 0 | 0 | 3 | 2 | 0 | 1 | 0 | 6 |

V0 failure lines (first line, grouped):

| class | first clears | n | V0 failure line |
|---|---|---|---|
| date/time assertion | V1 29 | 29 | `Error: certificate has expired` |
| network error | V4 6 | 6 | `AssertionError: promise rejected "NetworkBlockedError: detjs: network acces… { …(6) }" instead of resolving` |
| timeout | V1 1, V4 2 | 3 | `Error: Test timed out in 30000ms. / If this is a long-running test, pass a timeout value as the last argument ` |
| date/time assertion | V1 2 | 2 | `AssertionError: promise rejected "Error: certificate has expired { …(1) }" instead of resolving` |
| other | V4 2 | 2 | `Error: Expected upgrade but got response: 502` |
| timeout | V1 2 | 2 | `Error: condition not met within 1000ms` |
| network error | V4 1 | 1 | `AssertionError: expected 'Upstream error: detjs: network access…' to match /non-public address/u` |
| network error | V4 1 | 1 | `AssertionError: expected NetworkBlockedError: detjs: network acces… { …(6) } to match object { message: String` |
| other | V6 1 | 1 | `AssertionError: expected '-----BEGIN CERTIFICATE-----\r\nMIIDLD…' to be '-----BEGIN CERTIFICATE-----\r\nMIIDLD` |
| other | V3 1 | 1 | `AssertionError: expected 0 to be greater than 0` |
| other | V3 1 | 1 | `Error: smoke process group 10945 survived SIGKILL` |
| other | V3 1 | 1 | `Error: watchdog supervisor never closed after the breach (state=revoking)` |

`detjs verify --json` on the two V0 traces of each file, `divergence.reason` of the sampled tests: fs 32, other 8, net 6, None 4 (None = the two traces agree: stable)

## codex-multi-auth

Engine `e7338950262acc4bd24ed6d3af6a59e3f765a3af`. Find runs (`data/codex-multi-auth/runs.jsonl`, kind plain/det):

| run | exit | wall s | outcome counts | command |
|---|---|---|---|---|
| plain 1 | 1 | 393.45 | {"passed": 8644, "failed": 6, "skipped": 12} | `npx --no-install vitest run --no-file-parallelism --reporter=default --reporter=/tmp/pm/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs --reporter=json --outputFile.json=/tmp/pm/det_pins/codex-multi-auth/plain1.runner.json` |
| plain 2 | 1 | 378.04 | {"passed": 8644, "failed": 6, "skipped": 12} | `npx --no-install vitest run --no-file-parallelism --reporter=default --reporter=/tmp/pm/repos/codex-multi-auth/.fenvix-harness/vitest_ids_reporter.mjs --reporter=json --outputFile.json=/tmp/pm/det_pins/codex-multi-auth/plain2.runner.json` |
| det 1 | 1 | 429.87 | {"passed": 8275, "failed": 375, "skipped": 12} | `node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --det --det-workers=1 --det-outcomes=/tmp/pm/det_pins/codex-multi-auth/det1.outcomes.json --det-trace=/tmp/pm/det_pins/codex-multi-auth/det1.trace.jsonl` |
| det 2 | 1 | 449.38 | {"passed": 8244, "failed": 406, "skipped": 12} | `node /home/user/fenvix-engine-cli/node/bin/detjs.js vitest run --det --det-workers=1 --det-outcomes=/tmp/pm/det_pins/codex-multi-auth/det2.outcomes.json --det-trace=/tmp/pm/det_pins/codex-multi-auth/det2.trace.jsonl` |

- passed in both plain runs: 8642; of these passed in both `--det` runs: 8235
- **flips** (passed in both plain runs, failed/error in both `--det` runs): **362**
- absent from a `--det` run: 0; skipped in a `--det` run: 0; failed in one `--det` run and passed in the other (not flips): 45
- sampled: 50 (random.Random(1).sample(sorted(flips), 50)); affected files: 8
- V0 control alone (file alone, `--det`, 2 runs): reproduced 48, not reproduced alone 2, unstable at V0 0

Cumulative cleared (passed in both runs) among the reproduced flips, by first clearing variant:

| | V1 epoch | V2 +tz/locale | V3 +timers real | V4 +net off | V5 +fs off | V6 upper bound |
|---|---|---|---|---|---|---|
| cleared, cumulative (of 48) | 0 (+0) | 2 (+2) | 42 (+40) | 42 (+0) | 42 (+0) | 46 (+4) |
| verdict in this variant | still fails 48 | cleared 2, still fails 41, unstable in V2 5 | cleared 42, still fails 6 | cleared 42, still fails 6 | cleared 42, still fails 6 | cleared 46, still fails 2 |

Remain at V6 (not cleared in any variant): **2**
- `test/crash-mid-write.test.ts::SIGKILL mid-write recovery::kill after the temp file is durable: orphaned temp holds the full payload, primary stays committed`: V6 ['failed', 'failed'], V0 `AssertionError: promise rejected "Error: Storage is busy with another live … { code: '…' }" instead of resolving [call @ test/crash-mid-write.test.ts:240]`
- `test/json-store-lock.test.ts::never lets a stale takeover unlink a live lock owned by another process`: V6 ['failed', 'failed'], V0 `Error: Lock worker failed in round 1: fail:ELOCKTIMEOUT [call @ test/json-store-lock.test.ts:288]`

Cleared at a variant but not at every later one: 0

Failure class (V0 first line) x first clearing variant:

| class | V1 | V2 | V3 | V4 | V5 | V6 | none | total |
|---|---|---|---|---|---|---|---|---|
| timeout | 0 | 2 | 38 | 0 | 0 | 0 | 1 | 41 |
| date/time assertion | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| network error | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| file error | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| other | 0 | 0 | 2 | 0 | 0 | 4 | 1 | 7 |

V0 failure lines (first line, grouped):

| class | first clears | n | V0 failure line |
|---|---|---|---|
| timeout | V2 2, V3 37 | 39 | `Error: Test timed out in 5000ms. / If this is a long-running test, pass a timeout value as the last argument o` |
| other | V3 1 | 1 | `AssertionError: expected 'codex-home-env:/tmp/pm-codex-multi-au…' to contain 'close\n'` |
| other | V6 1 | 1 | `AssertionError: expected 503 to be 200 // Object.is equality` |
| other | V3 1 | 1 | `AssertionError: expected true to be false // Object.is equality` |
| other | V6 1 | 1 | `AssertionError: expected { version: 1, …(14) } to match object { Object (outcome, tokens) } / (15 matching pro` |
| other | none 1 | 1 | `AssertionError: promise rejected "Error: Storage is busy with another live … { code: '…' }" instead of resolvi` |
| other | V6 1 | 1 | `Error: Failed to run property, too many pre-condition failures encountered / { seed: 24301 } / Ran 10 time(s) ` |
| other | V6 1 | 1 | `Error: Failed to run property, too many pre-condition failures encountered / { seed: 24301 } / Ran 52 time(s) ` |
| timeout | V3 1 | 1 | `Error: Hook timed out in 10000ms. / If this is a long-running hook, pass a timeout value as the last argument ` |
| timeout | none 1 | 1 | `Error: Lock worker failed in round 1: fail:ELOCKTIMEOUT` |

`detjs verify --json` on the two V0 traces of each file, `divergence.reason` of the sampled tests: other 15, None 11, env 9, fs 8, io 4, time 3 (None = the two traces agree: stable)

