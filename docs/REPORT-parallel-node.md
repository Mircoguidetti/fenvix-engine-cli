# Parallel with proof for the JavaScript runners (row JS-07)

Branch `claude/parallel-node`, based on `claude/verifier-cli` at `bbb7a8a`.
Commits: `4fcea72` (`--det` parallel by default; the `jest -w 1` fix), `79e55ad` (serial subjects of four tests,
`docs/LIMITS.md` section 10, `prove.sh`, the Node 22/24/26 matrix).

Every number is labelled **MEASURED** (a run recorded here), **ESTIMATED** (derived), **DECLARED** (stated by a
tool or a document) or **UNKNOWN**. English only.

## 0. The one-paragraph answer

Parallel with proof works: on every real suite measured, a parallel run observed exactly what the serial run
observed, and `fenvix verify` says `IDENTICAL`. That is the guarantee the product is sold on and it holds.
Two things, however, do not support the sales claim as stated. First, **the engine's own overhead is larger than
anything parallelism wins back on a Jest suite**: plain `jest --runInBand` on one core finishes luxon in 2.93 s
where `fenvix --det` on four cores takes 10.15 s. Second, **the total CPU work grows with the lane count** — luxon
costs 14.4 s of test-file time in one lane and 59.7 s in eight — so "finishes sooner *and* costs less" is only half
true if we bill for core time. And one blocker: a first parallel run of files that share state can report failures
a serial run does not.

## 1. What was built

`node/src/parallel.js` `resolveWorkers()` previously returned 1 ("serial") when the user passed no worker option, so
every plain `--det` run was serial and the frozen exam check `JS-07.kept` failed. It now falls back to this
machine's CPUs. Precedence above that is unchanged: `--det-workers` wins, then the user's own serial request, then
the runner's own worker option. An explicit `-w 1` / `--test-concurrency=1` is now read as the serial request it is
(it previously reached the same 1 by accident, through the "said nothing" branch).

All three runners in scope share `resolveWorkers()`, so one change covers **Vitest** (`threads` and `forks`),
**Jest** (workers, and `--workerThreads`) and **node:test** (`--test-concurrency`, process isolation). Playwright
workers are Block 6's and were not touched.

The default is a default, not a promise that a run *will* be parallel. Every pre-existing refusal is untouched and
still falls back to one lane and says so: a worker shared by several files, `isolate=false`, the `vmThreads` /
`vmForks` pools, browser mode, the typecheck pool, `--det-record`, `singleThread`/`singleFork`, a custom Jest
runner, `--detectOpenHandles`, and node:test `--test-isolation=none`. **MEASURED**: `--experimental-test-isolation=none`
prints `parallel refused, serial: --test-isolation=none (every file in one process)`.

### A real bug fixed on the way

`fenvix node jest --det -w 1` ran **nothing at all**: detjs added its own `--runInBand` for one lane while the
user's `-w 1` stayed on the command line, and Jest exits with "Both --runInBand and --maxWorkers were specified,
only one is allowed". The trace recorded `0 tests` and the command still looked like it had run. `stripWorkerArgs()`
now always removes the user's worker and in-band options, parallel or not, since detjs always sets its own.
**MEASURED**: all 1116 luxon tests now run; the error string appears 0 times.

## 2. The guarantee: same outcome, same fingerprint (what §4 of the brief asked for)

**No test changed outcome between serial and parallel, anywhere.** Nothing to report as a divergence blocker.

`fenvix verify` of a one-lane trace against a four-lane trace of the same suite — the verifier of
`crates/detpy-core/src/verify.rs`, called and not reimplemented:

| project | runner / pool | tests | verdict | not proven | hazards | placement deviations |
|---|---|---|---|---|---|---|
| ufo v1.5.4 | Vitest 3 `threads` | 471 | **IDENTICAL** | 0 | 0 | 0 |
| ufo v1.5.4 | Vitest 3 `forks` | 471 | **IDENTICAL** | 0 | 0 | 0 |
| simple-statistics v7.9.3 | node:test, process isolation | 277 | **IDENTICAL** | 0 | 0 | 0 |

All **MEASURED**. The order digest is identical in both runs of each pair (ufo `388b9474c6b4d161bf3d99351f8bb822`,
simple-statistics `f093e6a7f14c59e28ad85acb5a32116c`), which is the "parallel fingerprint equals the serial
fingerprint" claim, directly.

**node:test shards** (`--test-shard=K/N`, in the brief's scope but not examined by the exam) compose with lanes.
**MEASURED** on simple-statistics, each shard running 4 lanes internally: shards 1/3, 2/3 and 3/3 ran 91, 93 and 93
tests, summing to **277** — exactly the unsharded run, so no test is lost or run twice. Shard 1/3 serial against
shard 1/3 in 4 lanes verifies `IDENTICAL`, all 91 tests, 0 not proven.

**Explicit single-worker requests stay serial**, which is the branch added to `resolveWorkers()` for this change
(previously such a request reached 1 only through the "said nothing" fall-through). **MEASURED**:

| request | result |
|---|---|
| `vitest --maxWorkers=1` | serial execution |
| `vitest --no-file-parallelism` | serial execution |
| `jest -w 1` | serial execution |
| `jest --runInBand` | serial execution |
| `node-test --test-concurrency=1` | serial execution |
| `node-test --test-concurrency=2` | parallel execution in 2 lanes |

luxon (Jest) is reported separately because it does not pass cleanly in this container for reasons that have nothing
to do with the engine. **MEASURED**, failing test sets compared as sets:

| run | failing tests (of 1116) |
|---|---|
| plain `jest -w 2`, no engine | 11 |
| `fenvix --det` serial | 11 — **identical set** |
| `fenvix --det -w 2` | 11 — **identical set** |

So serial and parallel agree exactly. The 11 are environmental: with `TZ=America/New_York` plain jest fails 4, and
those 4 fail in **plain jest with no engine at all** (ICU data: output calendar, `numberingSystem`, non-breakable
spaces). The other 7 are "local zone" tests that need a real time zone; `TZ` is unset in this container.

### A divergence that is NOT parallelism, found while isolating the above

With `TZ=America/New_York` set in the environment, `--det` runs as if the zone were UTC and adds 7 failures that
plain jest does not have. `--det-tz=America/New_York` passed explicitly behaves correctly. **MEASURED**, by probe:

| run | zone the test sees | `process.env.TZ` in the test |
|---|---|---|
| plain `node --test`, `TZ=America/New_York` | America/New_York | America/New_York |
| `fenvix --det`, `TZ=America/New_York` | **UTC** | **UTC** (overwritten) |
| `fenvix --det --det-tz=America/New_York` | America/New_York | America/New_York |

`--det-help` **DECLARES** `--det-tz=ZONE|keep   time zone of the run (default: TZ when set, else UTC)`. The
measured default is UTC whether or not `TZ` is set, so behaviour and documentation disagree. Serial and parallel do
this identically, so it is not a Block 3 defect; it belongs to whoever owns the time control. Separately,
`--det-tz=America/New_York` makes one further test fail that plain jest passes
(`DateTime#toRelativeCalendar picks the correct unit with no options`), which is the expected consequence of pinning
the clock to a fixed epoch rather than a defect.

## 3. Wall clock: serial versus parallel (the number asked for first)

**MEASURED** on this container: 4 cores (`nproc` = 4, `os.availableParallelism()` = 4), whole-command wall clock,
median of 3 repetitions, `.detjs` cleared between runs. "plain" is the runner with no engine and no `--det`.

This is a **4-core** machine. The 8-to-32-core curve the product is sold on is **UNKNOWN** and cannot be measured
here; the 8-lane rows show oversubscription, not scaling. `.github/workflows/parallel-node.yml` runs the same
measurement on GitHub's runners for Node 22, 24 and 26.

### luxon 3.5.0 — Jest 29, 58 files, 1116 tests

| lanes | `fenvix --det` | speedup | plain jest | speedup | engine cost |
|---|---|---|---|---|---|
| serial | 15.79 s | 1.00x | 2.93 s | 1.00x | 5.4x |
| 2 | 13.04 s | 1.21x | 2.14 s | 1.37x | 6.1x |
| 3 | 12.07 s | 1.31x | – | – | – |
| 4 | 10.15 s | 1.56x | 1.72 s | 1.70x | 5.9x |
| 6 | **9.70 s** | **1.63x** | – | – | – |
| 8 | 10.25 s | 1.54x | 2.31 s | 1.27x | 4.4x |

### ufo v1.5.4 — Vitest 3, 13 files, 471 tests

| lanes | `fenvix --det` | speedup | plain vitest | speedup | engine cost |
|---|---|---|---|---|---|
| serial | 3.94 s | 1.00x | 2.33 s | 1.00x | 1.7x |
| 2 | 2.34 s | 1.69x | 1.64 s | 1.42x | 1.4x |
| 3 | 1.91 s | 2.06x | – | – | – |
| 4 | **1.90 s** | **2.07x** | 1.30 s | 1.79x | 1.5x |
| 6 | 1.91 s | 2.06x | – | – | – |
| 8 | 1.91 s | 2.06x | 1.23 s | 1.89x | 1.6x |

### simple-statistics v7.9.3 — node:test, 76 files, 277 tests

| lanes | `fenvix --det` | speedup | plain `node --test` | speedup | engine cost |
|---|---|---|---|---|---|
| serial | 10.63 s | 1.00x | 4.36 s | 1.00x | 2.4x |
| 2 | 6.57 s | 1.62x | 2.31 s | 1.89x | 2.8x |
| 3 | 5.24 s | 2.03x | – | – | – |
| 4 | 5.20 s | 2.04x | 1.31 s | 3.32x | 4.0x |
| 6 | **4.95 s** | **2.15x** | – | – | – |
| 8 | 4.97 s | 2.14x | 1.24 s | 3.50x | 4.0x |

### What these say

1. **Parallel does help.** 1.6x to 2.2x on 4 cores, consistently, on three different runners.
2. **The engine's overhead is larger than the parallel win on the Jest suite.** Plain `jest --runInBand` on one core
   (2.93 s) beats `fenvix --det` on four (10.15 s) by 3.5x. A customer moving luxon from GitHub's 2 cores to our 4
   would get a *slower* run unless the cache does the work instead.
3. **It is not uniform.** On ufo the engine costs 1.4-1.7x, and four lanes (1.90 s) do beat plain serial Vitest
   (2.33 s). The pitch is true on ufo and false on luxon.
4. **Plain runners scale better than we do.** node:test reaches 3.50x where we reach 2.15x.

## 4. Where scaling stops, and why

Three candidate causes were asked about. **MEASURED** for each, the longest single test and packing are *not* the
cause; the cause is fixed cost, and specifically that **the total work grows with the lane count**.

### The total work inflates with lanes

The engine reports the summed test-file time of a run. **MEASURED**:

| project | 1 lane | 2 lanes | 4 lanes | 8 lanes | work at 8 lanes |
|---|---|---|---|---|---|
| luxon (jest) | 14.44 s | 17.16 s | 24.71 s | **59.66 s** | **4.1x** |
| simple-statistics (node:test) | 5.90 s | 6.11 s | 7.69 s | 12.07 s | 2.0x |
| ufo (vitest) | 0.87 s | 1.22 s | 1.87 s | 2.44 s | 2.8x |

At 8 lanes luxon does **4.1x the CPU work** of the serial run to finish **1.6x sooner**. Every worker re-pays the
per-file cost — module graph, Babel transform, test environment, Level 0 installation — and the inflated work then
saturates 4 cores. That is the ceiling, and it is why 8 lanes is *slower* than 6 in wall clock on both luxon and
simple-statistics.

**This is the commercially important number in this report.** If we bill customers for core-seconds on our
machines, parallelism as it stands costs 2-4x the CPU to deliver 1.6-2.2x the latency. "Finishes sooner" is
supported by the data; "and costs less" is not, unless we price wall clock only.

### Not the longest test, and not bad packing

luxon, **MEASURED** from per-file durations: 58 files, durations summing to 14.73 s, longest single file 2.05 s
(`create.test.js`). A perfect packing at 4 lanes would be `max(2.05, 14.73/4)` = **3.68 s** of test-file time;
measured wall clock was 10.15 s. The scheduler is not the problem — there is 6.5 s of fixed cost it cannot divide.
The engine agrees: 0 placement deviations in every run measured, so lanes ran the plan they were given.

### Fixed start-up cost

**MEASURED**, one trivial test file, serial, median of 3 — the floor no amount of parallelism can go below:

| project | runner | floor |
|---|---|---|
| luxon | Jest | 1.78 s |
| ufo | Vitest | 0.90 s |
| simple-statistics | node:test | 0.51 s |

Jest's transform cache accounts for only part of the rest: plain `jest --runInBand --no-cache` is 4.90 s against
2.93 s cached, so ~2 s.

### Shared resources

No contention was observed on these three suites: 0 cross-worker hazards and 0 files with carried state in every
run. The shared resource that *does* bind is the 4 CPUs themselves.

### Where the engine's own overhead sits

Disabling one control at a time on luxon, `--det`, serial, 2 repetitions, **MEASURED**:

| disabled | wall clock | | disabled | wall clock |
|---|---|---|---|---|
| nothing (baseline) | 15.69 s / 16.25 s | | `fs` | 14.61 s / 14.57 s |
| **`seeds`** | **7.60 s / 7.73 s** | | `net` | 15.38 s / 15.15 s |
| `time` | 17.19 s / 17.83 s | | `isolation` | 15.14 s / 15.49 s |
| `timers` | 16.02 s / 15.73 s | | `order` | 15.71 s / 15.84 s |

**The seeds control is about 8 s of the ~13 s of engine overhead on this suite** — half the run. Not the clock,
which is the intuitive guess for a date/time library. luxon's own source and tests contain **zero** `Math.random`
calls (**MEASURED**, grep), so the cost is in the instrumentation path, not in user code drawing random numbers.
`node/src/seeds.js` calls `require('./concur').sync()` on every intercepted draw (`mathRandom`, `nonce`,
`getRandomValues`, `randomUUID`), and something on that path is hit hard by the runner's internals. Not pursued
further: `seeds.js` is Level 0 machinery, not Block 3, and it is the single biggest lever on whether "faster tests"
is true for Jest suites. It needs an owner.

## 5. Exam status (JS-07, frozen at `claude/exam`, read and not modified)

Run with the exam's own harness, not a hand-written equivalent: `exam/` extracted from `claude/exam` with
`git archive` and the sha256 of `rows_js.py`, `lib.py`, `fam.py`, `projects.py` and `run.py` checked against the
branch before running, then `python3 run.py --rows JS-07`. **3 of 4 checks pass.** Verbatim verdicts:

| check | result | the harness's own line |
|---|---|---|
| `JS-07.kept` | **PASS** | `files announced while the first file ran: 2 (per file: [2, 3, 4, 4]); engine says serial: False` |
| `JS-07.det2.ufo` | **PASS** | `summary={"runs": 2, "tests": 471, "stable": 471, "diverged": 0, "missing": 0, "outcome_unstable": 0, "order_identical": true, "reasons": {}, "not_proven": 0}` |
| `JS-07.cache2.ufo` | **PASS** | `run 2 reused 471 (needed >= 235 of 471 passing); outcomes vs plain: 13 files / 471 tests, differing files 0 []` |
| `JS-07.jest-kept` | **FAIL** | `rc=1; engine forces serial/in-band: False` |

`JS-07.jest-kept`: the parallelism half is correct and **MEASURED** — `parallel execution in 2 lanes with a fixed
plan (-w)`, and the check's `in ?band|serial|one worker` pattern does not match the output. The check also requires
`rc == 0`, and luxon exits 1 here because 4 of its tests fail in **plain jest with no engine at all** (ICU data) and
7 more need a real `TZ`. No test was skipped, quarantined or weakened to change this; it needs a runner with full
ICU and a time zone set, which the exam machines may well have.

`JS-07.jest-kept` looks **unpassable as written on this runtime, whatever the engine does**, which is a matter for
whoever owns the exam rather than for this block: the check asserts `rc == 0` over luxon's whole suite, and 4 of
luxon 3.5.0's tests fail under **plain jest 29 with no engine at all** on Node 22 with ICU 78.3 (output calendar,
`numberingSystem`, non-breakable spaces — luxon's expectations predate this ICU). An older Node or ICU would
presumably pass. Nothing in the engine can make those 4 green, and nothing should.

Two further notes on the frozen exam, for whoever owns it:

- The exam's JS-07 contains **no node:test shard or `--test-concurrency` check**, though the brief asks for them.
  node:test parallel and shards were built and proven anyway (§2), but the exam does not examine them.
- `JS-07.kept` is safe from limit P2 (§6), though not by its own doing. The probe's four files all append to one
  `EXAM_OUT` file, a genuine cross-lane write-write hazard that the engine learns and then serializes, so the probe
  reports 2 concurrent files on a fresh plan state and 1 on every subsequent run **in the same project directory**
  (**MEASURED**). The check escapes this because `lib.Ctx.clone()` does `shutil.rmtree` on the project directory
  once per `run.py` process, which takes `.detjs/plan-state.json` with it. Confirmed: a second `run.py --only
  JS-07.kept` against the same `--work` directory passes identically. So the check is reliable, and the underlying
  engine behaviour in P2 is still worth a decision.

## 6. Blockers and limits

Recorded in `docs/LIMITS.md` section 10. The first is a blocker, not a note.

### P1 (BLOCKER) — a first parallel run of files sharing state can report failures a serial run does not

**MEASURED**, from the repo's own fixture (`node/test/controls.test.js`, "isolation: parallel workers interleave"):
two files sharing `shared.log` both **pass** under `--det` serial and both **fail** under `--det` in lanes
("2 test(s) failed under --det"). The engine then reports
`CROSS-WORKER read-write shared.log: tests/x (lane 1) / tests/y (lane 2); the next plan puts them in one lane`.

The hazard is found only *after* the run, from the recorded footprints. The placement is corrected for the next run;
the first run has already reported a wrong result. `docs/PARALLEL-PROOF-DESIGN.md` (design P6) lists
"two tests writing one path never overlap" and "**0 new failures caused by the split**" as acceptance criteria, and
specifies preventing this a priori from recorded footprints — which the Python/xdist path does and the Node path
does not. There is no re-run-on-hazard mechanism in `node/src/parallel.js`.

It is a false *red*, not a false green, so the founder rule is not broken in letter; in substance it is the same
disease, an outcome decided by placement. It did not appear on any real suite measured (ufo, luxon,
simple-statistics: 0 hazards), but it is exactly the shape of a customer suite with a shared temp file, a fixed port
or one database.

**Proposed fix, not built**: when `parallel.collect()` reports a hazard, re-run the affected files in one lane and
report those outcomes. The cost is paid only when a hazard is found, the reported result is always the serial one,
and `JS-07.kept` still sees >= 2 workers. This is the brief's own instruction — "if you cannot prove a placement is
safe, run the test the safe way" — applied after the proof machinery says the placement was not safe. It needs a
decision because it changes what a run costs and means, and it touches all three runner shells.

Why the simpler answers do not work: a footprint-gated default (serial until a file's footprint is known) is the
clean default-deny answer but fails `JS-07.kept`, because the exam writes four brand-new probe files whose
footprints are unknown on the run being examined. Keeping the serial default leaves the row red.

### P2 — a together-edge never expires

Once two files are seen touching one path from two lanes, `state.together` in `.detjs/plan-state.json` keeps them in
a single lane for every later run; the entry is written and never removed. A project's parallelism therefore only
decreases and does not recover after the suite is fixed. **MEASURED** via the JS-07.kept probe (2 concurrent files
on a fresh state, 1 thereafter). Needs a decision on whether a decay or re-try is wanted.

### P3 — in lanes, a Jest `globalSetup` that runs a child process is never reused from the cache

**MEASURED**, minimal repro: a `globalSetup` doing `execFileSync('cat', ['data.txt'])` and one test file —
`--det-workers=1` reuses 1 of 1 test, `--det-workers=4` reuses 0. Isolated to that combination: no `globalSetup`
reuses fine in lanes, and a `globalSetup` without a child process reuses fine in lanes. The entry is recorded with a
worker's start-up digest and checked against the main process's, which is empty (instrumented:
`startup digest= entries=[]`), so the keys can never match (`startupDigest()` in `node/src/cache/proof.js`, compared
in `crates/detpy-core/src/proof.rs`).

**Predates this work**: reproduced on the previous commit with an explicit `--det-workers=4`. The parallel default
only makes it the out-of-the-box experience. It costs reuse, not correctness — the miss is reported honestly and
nothing is wrongly reused. `node/src/cache/` was not touched; it is shared machinery.

## 7. Tests

Run with `node --test --test-concurrency=1` in `node/`. A **true baseline** was taken for each suite by reverting
only `node/src/parallel.js` and `node/src/jest/cli.js`, so these columns compare like with like. **MEASURED**:

| suite | baseline | with this work |
|---|---|---|
| `parallel-p041.test.js` | 33 pass / 0 fail | **33 / 0** |
| `runners-p041.test.js` | 23 / 0 | **23 / 0** |
| `controls.test.js` | 16 / 0 | **16 / 0** |
| `cache.test.js` | 47 / 0 | **47 / 0** |
| `review-r055.test.js` | 8 / 0 | **8 / 0** |
| `regressions.test.js` | 7 / 0 | **7 / 0** |
| `node-p041.test.js` | 45 / 4 | **45 / 4** (4 pre-existing: native addons, no compiler here) |

Four tests took their serial baseline from a bare `--det`, which is no longer serial. Each such run now asks for
`--det-workers=1`, which is the subject the test actually tests. **No assertion was removed, relaxed or skipped,
and nothing was quarantined.** The `parallel-p041` before-hook additionally asserts the new default (lanes = CPUs),
so the default is covered in both directions.

- `controls.test.js` "isolation: parallel workers interleave" — subject is the isolation control; its two files
  genuinely interfere in lanes (limit P1).
- `controls.test.js` "order: files run in sorted order" — subject is the order files are scheduled in, not how they
  overlap in time.
- `runners-p041.test.js` "the reuse decision is made after globalSetup" (G-1290) — subject is the order of the
  decision; in lanes this suite cannot reuse at all (limit P3).
- `runners-p041.test.js` "exit without `--forceExit`" (G-2180) — the engine's own note says the behaviour under
  audit is the in-band one.

**Environment note worth keeping**: `node/node_modules` was never installed in this container, and `vitest@5` needs
`vite` as a peer dependency. Until both were installed, 35 of these tests failed for that reason alone and looked
like real breakage — including every test named "parallel fingerprints equal the serial ones". The CI workflow
installs both explicitly.

## 8. CI

`.github/workflows/parallel-node.yml`, matrix Node **22 / 24 / 26**, per the brief (local iteration was on 22):

1. build and install the engine; assert `fenvix version` reports `detjs`;
2. `node/test/parallel-p041.test.js` — plan determinism, parallel-equals-serial fingerprints, hazard reporting,
   the refusals;
3. `harness/node_parallel/prove.sh` over the exam's pinned projects for **Vitest threads**, **Vitest forks**,
   **Jest workers** and **node:test** — one lane against N lanes, then `fenvix verify`. The script exits non-zero
   unless the verdict is `IDENTICAL`, so **an outcome that differs between serial and parallel fails the build**
   rather than being reported as a note;
4. the wall-clock measurement, serial and 2/4/8 lanes, uploaded as an artifact.

Hosted-runner numbers are a direction, not a benchmark: core count and noise are not controlled there.

## 9. Open decisions

1. **P1.** Build the re-run-on-hazard fix, or accept that a first parallel run of a suite with cross-file state can
   go red and self-heal on the next run. I do not think `4fcea72` should merge without it.
2. **The seeds overhead** (~8 s of ~13 s on luxon). It decides whether "faster tests" is true for Jest suites. It
   lives in Level 0, not Block 3, and needs an owner.
3. **Core-time pricing.** Total work grows 2-4x with lanes (§4). If customers are billed for core-seconds,
   "costs less" needs re-examining, or pricing needs to be wall-clock.
4. **P2**, whether together-edges should ever expire.
5. **A bigger runner**, if the 8-to-32-core scaling curve is to be measured at all.
6. **The accounting table.** `crates/detpy-core/src/provable.rs`, `judge()` and `account(module, qualname)` — the
   rule this block was told to inherit and call — **do not exist in any ref of this repository**, and there is no
   "sensor" field in the trace header. The equivalents that do exist were used instead and not reimplemented:
   `docs/VERIFY-CONTRACT.md` as the contract, `crates/detpy-core/src/verify.rs::verify()` as the single predicate
   (called through `fenvix verify`), the `uncontrolled.*` marks and `Status::NotProven` as default-deny, and the
   header flag `env_reads_recorded` as the fail-closed capability declaration. Neither `verify.rs` nor
   `provable.rs` was edited. If `provable.rs` is work Block 1 has not landed, this needs reconciling before more is
   built on `verify.rs`.
7. The brief's base commit `2b2f8e6a` is not a valid object in this repository; `bbb7a8a` (the real remote tip of
   `claude/verifier-cli`) was used. The stale local branch was 10 commits behind at `688e4fe`.

## 10. Reproducing the numbers

```bash
# the engine, from a checkout
pip install maturin && pip install -e . --no-build-isolation
export FENVIX_HOME=$PWD                     # so detjs is found in the checkout

# the shell's own dependencies (both are needed; vitest 5 needs vite as a peer)
cd node && npm install --no-audit --no-fund --ignore-scripts --legacy-peer-deps \
        && npm install --no-save vite && cd ..

# the parallel regression tests
cd node && node --test --test-concurrency=1 test/parallel-p041.test.js && cd ..

# serial vs parallel, same outcome and same fingerprint (exits non-zero unless IDENTICAL)
harness/node_parallel/prove.sh <project-dir> vitest 4 /tmp/proof run
harness/node_parallel/prove.sh <project-dir> jest 4 /tmp/proof --ci test
harness/node_parallel/prove.sh <project-dir> node-test 4 /tmp/proof 'test/*.test.js'
```

Projects are the exam's, pinned by commit (`exam/projects.py`): ufo `0f15ddc6` (v1.5.4) with `vitest@3`,
luxon `a4044fe6` (3.5.0) with `jest@29`, simple-statistics `f9d368f4` (v7.9.3).
