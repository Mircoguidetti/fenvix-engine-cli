# Cache measurement B, B1: harden the proof cache (REPORT-B1)

Branch `claude/cache-harden` from `origin/claude/release-1` 6e79a62. Final engine: **26cdf8b41289** (no change under
`node/`, `crates/`, `python/` after it; every later commit is harness data or this report). Spec: cache measurement B
rev 3, gate rev 3 notes; rules and sets in `PREREG.md` (commit 90c7abd6, before the first replay).

**Verdict: DONE.** One complete harden pass on the final engine, in the URL form (gate note 9), on 9 repositories /
143 states: **0 wrong-reuse, 0 verify mismatches**, every reused result compared (`verify_unchecked` empty), 0
shared-cache errors, `push_entries_unresolved` 0 in every repository. The 7 fault tests are green and each channel
goes red when its contributions are removed. The suites show no new failure against 6e79a62.

## Test, validator and CI changes (rule 3)

- New tests only: `node/test/cache-b1-summary.test.js`, `cache-b1-remote.test.js`, `cache-b1-expand.test.js`,
  `cache-fault-{repo-file,env,outside,node-modules,config,clock,negative}.test.js` (+ `cache-fault-lib.js`),
  `harness/cache_b/test_prereg.py`. Each states protects / fails_when / no_claim.
- No existing test, validator, CI step, timeout, tolerance, threshold, snapshot or suppression pragma was changed.
- `harness/cache_b/suites.sh` copies CI's one `--deselect` (release-1.yml:147) verbatim; it is not a new exception.

## Engine changes (3 commits, `node/src/cache` only)

| commit | what | reuse | test (red before, green after) |
|---|---|---|---|
| a10f52ec | step 1: the verify summary names the recorded inputs of every mismatching would-be-reused entry (`verify_mismatch_inputs`) and the reused results the fresh run never compared (`verify_unchecked`) | unchanged | cache-b1-summary |
| a8702811 | fix 1: the shared-cache push sends (key, dependency) pairs; it sent store-v2 chunk addresses, which every pulling machine rejected (`observed: invalid type: string "g…"`), so the URL form never reused across machines | more (cross-machine reuse at all): **approved by the coordinator** with conditions (exit pass in the URL form; `push_entries_unresolved` per repository) | cache-b1-remote: red 3/3, green 3/3 |
| 2444bd02 | fix 2 (from /review): the push expands an entry exactly as the Rust store loads it: a missing or non-list data/env, a pair that is not two strings, a mixed or torn list is not pushed (it was pushable as an entry with fewer dependencies); verify mode keeps the would-be-reused entries as text and parses only mismatches (memory) | narrower only | cache-b1-expand: red 2/5, green 5/5 |

No verify rule, key rule, the 30% line, the sets or the wrong-reuse rule were changed.

## Fault channels (B1 step 2, acceptance criterion 2, gate note 10)

One test per input channel: (a) a repository file a test reads, (b) an environment variable it reads, (c) a file
outside the project it reads, (d) an installed package it loads, (e) the runner's configuration file, (f) the clock
epoch for a test that reads the clock; plus a negative (an unread file changes: must hit). Each seed / change /
cached cycle runs under Vitest and Jest. All 7 green on 26cdf8b4 (with the 3 B1 tests and `cache.test.js`,
`cache-p041.test.js`: 58/58).

Mutations (`mutations.py`: every contribution of the channel to the key removed in a scratch worktree, never
committed): (`data/mutations-a4b259580cd0.json`, run at a4b25958 = engine 26cdf8b4)

| channel | mutation | result |
|---|---|---|
| unmutated | none | 14/14 pass (expected pass) |
| a repository file | a content read of a project file not recorded | 2/2 fail (Vitest, Jest) |
| b environment | no environment read recorded | 2/2 fail |
| c outside file | a read outside the project not recorded | 2/2 fail |
| d node_modules | the runtime identity's packages and lockfiles parts constant | 2/2 fail |
| e configuration | configuration digests, project configuration, start-up reads and the configuration module as code removed | 2/2 fail |
| f clock | a clock read not recorded | 2/2 fail |

## Exit pass: URL form, engine 26cdf8b41289

Each repository: a local cache service (`python/detpy/cache_service.py`), an empty local mirror per run, state 0
seeds, every later state runs with `--det-cache-verify`; a mismatch would be classified by 10 plain runs (B1.3).
Rows: `data/harden/26cdf8b41289/*.jsonl`; push counts: `data/push-unresolved-26cdf8b41289.json`.

| repo | runner | states (rows / set) | ok | ENV / NO-SUMMARY | reused files | verified tests | mismatches | wrong-reuse | unchecked | remote errors | push_entries_unresolved | entry docs pushed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| codex-multi-auth | vitest | 20 / 20 | 20 | 0 | 4,443 | 61,090 | 0 | 0 | 0 | 0 | 0 | 117,162 |
| drydock | vitest | 18 / 18 | 18 | 0 | 4,550 | 119,019 | 0 | 0 | 0 | 0 | 0 | 235,988 |
| ironcurtain | vitest | 15 / 15 | 15 | 0 | 792 | 13,899 | 0 | 0 | 0 | 0 | 0 | 78,773 |
| agentsys | jest | 20 / 20 | 20 | 0 | 659 | 28,260 | 0 | 0 | 0 | 0 | 0 | 48,207 |
| yalc | vitest | 6 / 6 | 6 | 0 | 45 | 640 | 0 | 0 | 0 | 0 | 0 | 1,208 |
| agentlang | vitest | 20 / 20 | 13 | 7 / 0 | 18 | 383 | 0 | 0 | 0 | 0 | 0 | 879 |
| lerna-lite | vitest | 14 / 14 | 14 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| nestjs-pino | vitest | 10 / 10 | 10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 720 |
| alakajam | vitest | 20 / 20 | 0 | 10 / 10 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **total** | | **143 / 143** | 116 | 17 / 10 | **10,507** | **223,291** | **0** | **0** | **0** | **0** | **0** | |

Row indices are contiguous in every repository, every slice ended with a clean stop between states, no state is
CACHE-OFF, VERIFY-GAP or INTERRUPTED, and no mismatch of any cached outcome occurred (so nothing was left
unclassified). The pass ran in three < 2 h slices, 3 repositories at a time, on this container (4 CPUs).

An earlier complete pass on engine 9753874d (fix 1, before fix 2) gave the same result: 0 mismatches, 0 wrong-reuse,
0 unchecked, 0 remote errors, `push_entries_unresolved` 0 (`data/harden/9753874d1b45/`,
`data/push-unresolved-9753874d1b45.json`); 18 of its rows were rebuilt from run summaries after a harness incident
(below). It is superseded by the pass above.

### Measurability findings for B2 (not B1 defects)

- **lerna-lite**: every test file starts a subprocess (`not_cached: subprocess` 1,426), so nothing is ever recorded:
  NOT MEASURABLE as is.
- **nestjs-pino**: network connections in every file (`not_cached: network connection` 2,110); 0 reused.
- **alakajam**: harden states 0-9 do not install on Node 22 (sqlite3 5.0.x / nan does not compile: `npm error
  code 1`), states 10-19 have no Vitest (`detjs: vitest is not installed`). Its B2 states need their own check.
- **agentlang**: states 5-11 ENV (`ERR_PNPM_LOCKFILE_CONFIG_MISMATCH`: the frozen pnpm lockfile does not match
  `overrides`).
- **ironcurtain**: most states change dependencies (lockfile), so reuse is low between them.
- **Jest repositories**: `--cacheDirectory` must be a fixed path (the engine keys Jest's command-line options; a
  per-run path makes every state miss). B2 must use the same fixed path.

## Suites against 6e79a62 (no new failure)

Run serially on this container with `harness/cache_b/suites.sh`, base tree 6e79a62c, head tree = the final engine.
Details: `data/suites/*.txt`.

- **cargo** (`-p detpy-core -p detpy-node`): 0 failed (213 passed, 1 ignored). Rust is unchanged by B1.
- **Node** (full `node/test`, Node 24): base 6 failed / 3 cancelled of 1,106; final head (a4b25958) the same failing tests, 6 failed / 3 cancelled of
  1,129 (the 23 more are the B1 tests, all passing). An earlier head run (149a52f7, engine 9753874d) had one more
  failure, `controls.test.js:236` (Jest baseline without --det expecting interleaved workers): scheduling-dependent,
  5/5 alone on both trees, and absent from the final run.
- **Python shared** (release-1.yml LIGHT): base 3 failed, head 4 failed. The extra one,
  `test_clock_rust.py::test_cache_matches_reference`, ran while 3 harden processes loaded the machine; alone it
  passed 8/9 on head and 9/9 on base (the failing run was the slowest, 42 s vs 20-27 s), and the code it tests is
  byte-identical on both trees: load-dependent, not a B1 change.
- **attacks**: identical on both trees: the same 12 Python failures (`test_review_r056_pycache.py`), Node 60/60.

The CI baseline at 6e79a62 is incomplete (release-1.yml is fail-fast: attacks, Node shard 1 and Python shard 0
failed, the rest cancelled), so the comparison was run here.

## /review (gstack)

Specialists: Security and Simplification no findings; Testing 6, Maintainability 2, Performance 2 informational;
an adversarial pass (13 findings, all harness or informational). Acted on: fix 2 (engine); harness fixes in
26cdf8b4: an interrupted state stops the repository instead of being re-verified against its own results, CACHE-OFF
and VERIFY-GAP are not `ok`, the service must start, one process per repository (lock), the seed status in every row,
mismatches with a cached outcome other than `passed` are listed (the B1.3 rule is unchanged), classification restores
the tracked tree before each plain run and a timeout makes a file `unresolved` (never `instability`), checkpoint
failures are logged; `rebuild_rows.py` and `mutations.py` hardened. The completed 9753874d pass was checked against
each weakness: none had occurred. Gate edits: 13 listed, 2 read (new harness files), 0 findings.

## Known gaps (listed, not fixed in B1)

1. The skipped shared-cache `describe` in `node/test/cache.test.js` (coordinator: do not touch).
2. Python's push does not expand store-v2 addresses (`python/detpy/remote_cache.py:529`); stated in the no_claim of
   `cache-b1-remote.test.js`. B2 measures the Node engine.
3. A pull aborts on an old address-shaped document pushed by an earlier engine build: fails closed (no reuse), never
   a false pass. A per-candidate try/catch would make the cache reuse where it now errors; the coordinator said not
   to do it (B2 starts from fresh caches on one engine build).
4. The push recomputes `docId` for entries already pushed (CPU on every push; performance only).
5. `verify_unchecked` is only ever tested empty (the non-empty case has no test); the harness treats a non-empty
   list as VERIFY-GAP.
6. `cache-b1-remote.test.js`: its document check assumes both runners ran in the same file; the service port is
   random without retry.
7. `test_prereg.py` checks duplicates in 2 of its lists.

## Harness incidents (all repaired; none affects the exit pass)

- A checkpoint copied a whole rows folder over the repository's, truncating three repositories' rows of the 9753874d
  pass; rows were restored from git history and rebuilt from run summaries (`rebuild_rows.py`, marked
  `reconstructed`); checkpoints now copy only their own repository's files.
- agentsys reused 0 with a per-run Jest `--cacheDirectory` (keyed option): fixed path, rows deleted, rerun.
- drydock: the container's global `NODE_PATH` root changed between runs (runtime identity): `NODE_PATH` dropped
  from the run environment.
- ENV rows named npm's closing line instead of the error: they now name the first error line.
- The Python/attacks suite task hit the 2 h task limit during head's Python run; head's Python suite was rerun alone.

## Not done here

B1 is not merged: it merges into `claude/release-1` only after P2's merge and with the founder's typed
authorization. B2 starts no earlier than 5 Dec 2026 on `claude/cache-measure-b`.
