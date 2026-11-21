# Block 4 — cache with proof for Node (row F-06)

Branch `claude/cache-node`, rebased onto `origin/claude/verifier-cli` @ `fbafafdc`.

**Headline: the Node cache had a reuse rule of its own and never called `judge()`. It reused tests
the engine's own predicate says must be rerun, and erased the evidence on the way. Fixed in
section 2.** The fake-timers check named in the brief is a different, still-open question that no
cache change can close (section 2.5).

Numbers are labelled MEASURED (a command run in this container, Node 22.23.5, Vitest 5.1.0),
DECLARED (from a brief or another session's report, not re-run here) or UNKNOWN.

## 1. The engine state vs the brief

### 1.1 The single predicate exists, and the Node cache was not calling it

A correction to the first version of this report, which said `provable.rs` did not exist. It did not
exist in the tree I had: I branched from `origin/claude/verifier-cli` @ `bbb7a8a1`, and Block 1
landed the predicate on that branch at 20:47-21:20 the same evening. This branch is now rebased
onto `fbafafdc`, which carries:

* `crates/detpy-core/src/provable.rs` (66,038 bytes): `account(module, qualname)` (line 242),
  `account_node(module, export)` (625), `enum Verdict` (896), `judge(&Attestation) -> Verdict`
  (926), `judge_record(record, header, outside)` (995);
* `node/src/provable.js` (13,238 bytes): the Node sensor.

`judge()` is default-deny by construction: no sensor, a sensor built against another accounting
table, an unaudited runtime, a channel mark, anything the sensor could not place, or anything
outside the tests, and the verdict is `NotProven`.

**The Node cache was not calling it.** That is section 2, and it was the real defect in this row.
`node_session.rs::UNCACHEABLE` (29 channels) is a separate, older per-channel table; it is now the
second layer below `judge`, not the rule.

### 1.2 The 90% reuse target and default-deny are in tension (open)

`origin/claude/measure-provable` (fa999ce3, dated 2026-11-21) measured the cost of charging a test
with every information-carrying syscall: **0.0% of 879 real tests stay PROVABLE** as stated;
34.9% counting only the test phase; 72.1% if the project's own source files are recorded; 92.0%
with five more channels (all DECLARED by that session, not re-run here). Cause: no run input pins
the *content* of any file (`docs/LIMITS.md` F1).

The frozen check `F-06.no-edit` requires **>= 90% of tests reused on an unchanged checkout**.
Note the two figures are not measured on the same scale — `measure-provable` charges syscalls,
`UNCACHEABLE` charges 29 named channels — so they are not directly comparable, and the real reuse
share on this engine is UNKNOWN until section 4 is run. I flag the tension rather than assume it:
**if measured reuse lands under 90%, I will report the number and not loosen a flag to reach it.**

### 1.3 `claude/node-cache-proof` cannot be merged — unrelated history

MEASURED: `git merge-base origin/claude/verifier-cli origin/claude/node-cache-proof` is **empty**.
It is also the smaller, older tree:

| | files in `node/src` | `node/src/cache` |
|---|---|---|
| `claude/verifier-cli` (this base) | 86 | capture, early, **groups**, **loader-hooks**, proof, remote, runtime-id, **trace-reused** |
| `claude/node-cache-proof` | 24 | capture, early, proof, remote, runtime-id |

Its 478 commits are overwhelmingly measurement output (MEASURED: 1,487 files under
`harness/results`, 1,077 under `harness/node`, 99 under `harness/node_cache`). So "do not lose it"
can only mean its **evidence**: 0 wrong in 738,552 verified reuses; capture overhead docusaurus
+11.4%, TanStack +6.0%, vue-core +5.8% (DECLARED by that branch). Proposal: cite those as prior
results, re-measure on this engine, leave the branch untouched. **Confirm.**

### 1.4 There is no 60% baseline for F-06; no F-06 check has ever run

MEASURED from `origin/claude/exam:exam/results.json`, run 44925123655:

```
F-06: status FAIL, n_checks 0, n_passed 0,
      missing_legs [linux-x64/py3.13/node22, linux-x64/py3.13/node26],
      gaps: total 6, closed 0, open 0, no_check_ran 6
```

The brief's "today 60%" is DECLARED and unverifiable here. The exam also tests an **installed
release artifact** (that run used one built from `claude/py-cache` @ 2b67ac02), not a worktree, so
green F-06 needs a release build of this branch through Actions.

Also MEASURED: the base commit the brief names, `2b2f8e6a`, is not a valid object in this
repository.

## 2. The wrong reuse: the Node cache had a reuse rule of its own (FIXED)

### 2.1 What was wrong

`node_session.rs::record_session` admitted a test on `uncacheable(flags, outcome)` alone and never
called the one predicate. Verified by reading the code at `fbafafdc`:

* grep for `judge`, `judge_record`, `Verdict` or `provable` in `node_session.rs`: **zero hits**;
* `CapturedTest` had fields `id, upto, outcome, fingerprint, duration` — **no `unaccounted`**, so
  the sensor's per-test findings could not reach the policy even in principle;
* `cache.rs::admit_record` — whose own doc says *"This is the second caller of
  `crate::provable::judge` the founder's rule asks for: the cache must not have a reuse rule of its
  own"* — **has no callers**. An exhaustive grep for `admit_record` across the repository returns
  its definition and one comment. The only production caller of `judge_record` anywhere is
  `verify.rs:908`.
* `node/src/session.js:340` declares sensor `cache-reuse/1` for a fully reused run, and the comment
  justifying it cites that dead function.

### 2.2 The demonstration (MEASURED)

Two tests calling builtin exports the accounting table does not account for:

```js
import { createRequire } from 'node:module'; const req = createRequire(import.meta.url);
test('a', () => { expect(req('node:v8').getHeapStatistics().heap_size_limit).toBeGreaterThan(0); });
test('b', () => { expect(typeof req('node:tty').isatty(1)).toBe('boolean'); });
```

Same engine, same build, two answers:

| | result |
|---|---|
| `fenvix verify`, two full `--det` runs | **NOT PROVEN: 2 of 2** — *"not accounted for: api:v8.getHeapStatistics ... Identical fingerprints are no evidence of an identical execution, so the verdict is NOT PROVEN and the test must be rerun"* |
| `--det-cache`, run 1 then run 2 | run 1 "recorded 2 tests"; run 2 **"reused with proof 2 tests in 1 files"** |

It also **erased the evidence**. In the fully reused run's trace: the header declared
`{"sensor":"cache-reuse/1","contract":1,"runtime":"node22","surface":"71284ad1…"}` — well-formed,
carrying the build's own surface digest, so `judge()`'s clauses 1-2 pass — while each reused test
record carried `unaccounted: null`. The recording run's finding was gone, so a later `verify` of two
reused runs would call those tests Provable. The cache did not merely skip the predicate; it
produced an attestation that satisfies it.

### 2.3 The fix

The sensor's findings now reach the policy and the policy calls the predicate:

* `node/src/state.js`: the capture's existing `onEvent` hook carries the event's `op`.
* `node/src/cache/capture.js`: `levelEvent` collects `unaccounted.<kind>` findings per test;
  `testEnd` attaches them; `fileCapture` attaches the sensor declaration of the process that ran
  the file.
* `crates/detpy-core/src/node_session.rs`: `CapturedTest.unaccounted`, `Capture.provable` /
  `provable_absent`, and `why_not_cached`, which builds a `provable::Attestation` and calls
  `provable::judge`. The file's entry answers for every test in it, so it takes the union of their
  findings.

`provable.rs` and `verify.rs` are untouched, and there is no JavaScript copy of `judge`.

**Clause order.** My first attempt put the sensor's finding first and broke three tests that assert
the reason text. `judge()`'s own documentation explains why that is wrong: a channel rule that names
the gap is reported before the wide sensor's finding, because "the test started a thread" tells the
reader more than the callable's name. So the order is: an absent or mismatched sensor first (the
most fundamental gap), then the Node channel rule when it names the gap, then the sensor's own
finding for the channels no rule names. The verdict is the same either way — only the wording
differs — and the three tests pass again unmodified.

After (MEASURED): the recording run reports `not cached: api 3` (two tests and the file entry) and
run 2 runs both tests again.

### 2.4 One open item, for Block 1 (`provable.rs` is not mine to edit)

`native.provableAccount('async_hooks', k)` returns `unaccounted` for every export:
`AsyncLocalStorage`, `AsyncResource`, `createHook`, `executionAsyncId`, `triggerAsyncId`,
`executionAsyncResource`, `asyncWrapProviders`. `AsyncResource` and `AsyncLocalStorage` look
misclassified — they are in-process bookkeeping and expose no outside state, unlike the
run-dependent ids or `createHook`. The cost is concrete: Node constructs an `AsyncResource` inside
`fs.createReadStream`, so **a test that reads a file through a stream is no longer reusable**. This
is the one failing test in section 3, left failing rather than worked around. Fleet impact UNKNOWN
(zustand does not hit it); streams are common, so I expect it to cost real reuse share.

Also open, found while building the reproduction: the ESM form `import v8 from 'node:v8'` is **not**
marked, while the `createRequire` form is. Vitest and Jest transform test files to ESM, so the
unmarked form is the common one and the sensor is likely missing most real occurrences. My fix
carries whatever the sensor reports, so it inherits that gap exactly.

### 2.5 The fake-timers check is a separate question, still open

`F-06.fake-timers` is **not** this defect, and no cache change makes it pass. Measured: with the
cache switched off entirely (`--det`, `.detjs` removed between runs) the probe passes before and
after the deadline, while a plain run fails — so the engine disagrees with reality with no cache in
the picture. `vi.useFakeTimers()` makes **zero** calls to the real `Date.now`; `Date.now()` right
after it returns `1735689600000` (2025-01-01, `DEFAULT_EPOCH`, `node/src/config.js:7`), or the
virtual day under `--det-cache`. The epoch **is** part of the cache key (same epoch reuses;
`--det-epoch=2026-06-01` does not), so the reuse is sound on the engine's own terms.

The check compares run 2 against a *plain* rerun, so making it green needs the real clock to reach
the test for fake-timer installs **and** a `clock-real` refusal — which partly undoes G-0122/G-0142.
That is a founder decision, not a cache fix. Options: (1) let the real clock through and never
reuse; (2) keep virtualizing and accept the check red with the reason written out; (3) the check's
premise is wrong, which only the founder can decide since the exam is frozen. My recommendation is
to measure (1)'s blast radius first.

## 3. Suites (MEASURED)

`cd node && node --test --test-concurrency=1 <file>`, Node 22.23.5, after `npm ci` and
`node scripts/build.js`:

| suite | tests | pass | fail |
|---|---|---|---|
| `test/verify-inputs-attacks.test.js` | 34 | 34 | 0 |
| `test/review-r055.test.js` | 8 | 8 | 0 |
| `test/cache-p041.test.js` | 36 | 36 | 0 |
| `test/policy-equivalence.test.js` | 11 | 11 | 0 |
| `test/cache.test.js` | 47 | 46 | **1** |
| **total** | **136** | **135** | **1** |

The one failure is section 2.4 (`async_hooks.AsyncResource`), not skipped and not edited.

`policy-equivalence` went from 5 tests to 11. Two changes, neither a weakening: the 500-input
generator now emits the sensor declaration every real capture carries (without one the policy
rightly stores nothing, so the generator had been producing sessions that cannot occur), and six
new tests cover the judge layer against the Rust policy directly — a clean test stored, an
unaccounted channel refused, no sensor refused, a wrong surface digest refused, an unaudited runtime
refused, and the clause-order preference. There is deliberately **no** JavaScript mirror of
`judge`, so the rule keeps one implementation.

## 4. Measurements on a real project (MEASURED)

zustand @ `3f9127f4` (the project `F-06.no-edit` itself uses), vitest 3 + jsdom 25 as the exam
installs it, 12 test files / 135 tests, Node 22.23.5, 4 vCPU shared container. Wall-clock is the
median of 3 repetitions (2 for the parallel rows); ranges in brackets.

### 4.1 Reuse share and correctness

| | value |
|---|---|
| tests reused on an unchanged checkout | **135 of 135 (100%)** |
| files reused | 8 of 12 |
| files correctly **not** reused | 4 — `not cached: outcome failed 4` (a failing outcome is never cached) |
| `--det-cache-verify` (reuse decided, **every file run anyway and compared**) | **verified 143 results, 0 differ** |
| `verify_mismatches` in `cache-summary.json` | 0 |

So **0 wrong reuses on this project, verified against a fresh full run**, and `F-06.no-edit`'s
>= 90% threshold is met with margin here (100%). That is one project, not the fleet: the share on
larger suites is UNKNOWN until section 5 runs, and the tension in 1.2 is not settled by it.

**Re-measured after the section 2 fix: identical — 135/135 tests reused in 8 files, 143 verified,
0 differ.** So routing admission through `judge()` cost zero reuse on this project. That is one
project and it does not hit `async_hooks`; the fleet cost is UNKNOWN.

### 4.2 Wall-clock, cached vs uncached, serial and parallel

| mode | plain vitest | `--det`, no cache | `--det` + warm cache |
|---|---|---|---|
| **serial** (one worker) | 5.97 s [5.68–6.16] | 7.10 s [6.81–7.20] | **3.15 s** [2.93–3.27] |
| **parallel** (4 lanes) | 2.73 s [2.68–2.78] | 3.11 s [2.98–3.23] | **1.81 s** [1.65–1.98] |

* capture overhead (`--det` vs plain, same parallelism): **+19% serial, +14% parallel** — the same
  family as the DECLARED +11.4% / +6.0% / +5.8% from `claude/node-cache-proof`.
* cached vs uncached: **−47% serial, −34% parallel**. Cold cache: 8.39 s serial, 3.69 s parallel.
* **No cached run was slower than its uncached counterpart**, so the defect condition in the brief
  does not occur here.

A correction worth recording, because I nearly reported the opposite: comparing `--det` against a
bare `npx vitest run` is **not** apples to apples. `--det` forces one worker by default, while
plain vitest defaults to multi-worker. Against that confounded baseline the warm cache looked like
a +2.6% regression; forcing plain to one worker (`--no-file-parallelism`, confirmed with
`--maxWorkers=1`) shows it is a 47% improvement. Any future measurement must pin parallelism on
both sides.

## 5. Not done, and why

* **docusaurus, TanStack query, vue-core** (the three with history) are **not attempted**. They are
  CI-scale: `harness/node_cache/specs/tanstack-query.json` needs corepack + pnpm, Node 24, a
  27-package Nx monorepo and **3 shards**, and the prior branch measured them in GitHub Actions
  (runs 44644365780, 44615968050), not locally. The brief's own rule — Actions for the matrix,
  local for one version — puts them on CI.
* **No Actions matrix run (Node 22/24/26) launched.** The exam tests an installed release artifact,
  so a matrix run needs a release build of this branch; and both it and the three projects would
  measure an engine that the decision in 2.4 is about to change. They come after that decision.
## 6. Reproduction

```bash
cd node && npm ci --no-audit --no-fund && node scripts/build.js
# minimal project: package.json {"type":"module"}, vitest.config.js include test/**/*.test.ts,
# node_modules symlinked to node/node_modules, and the FAKE_TIMERS probe above as test/ft.test.ts
DL=$(( $(date +%s)*1000 + 4000 ))
EXAM_DEADLINE=$DL node <repo>/node/bin/fenvix.js vitest run --det test/ft.test.ts   # passes
sleep 5
EXAM_DEADLINE=$DL node <repo>/node/bin/fenvix.js vitest run --det test/ft.test.ts   # still passes
EXAM_DEADLINE=$DL node_modules/.bin/vitest run test/ft.test.ts                      # fails
```
