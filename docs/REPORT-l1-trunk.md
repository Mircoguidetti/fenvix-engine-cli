# PY-07 on the trunk lineage: deterministic threads and asyncio

Block 5. Branch `claude/l1-trunk`, branched from `claude/verifier-cli` at `bbb7a8a1`.

Every number below is labelled MEASURED, ESTIMATED, DECLARED or UNKNOWN. MEASURED means this session ran it and
read the result; nothing is carried over from the earlier branches as if it had been re-measured here.

## What the row was asked for, and where it stands

| Asked for | State |
| --- | --- |
| Port the L1 asyncio and thread work onto this lineage, one implementation | Done |
| A test whose threads are deterministically scheduled becomes provable through the verdict; one whose threads are not stays NOT PROVEN | Done, both directions pinned by tests |
| Make the exam checks for PY-07 pass | Blocked on the exam's own probes, not on the engine. See "The exam" |
| Measure the provable-share movement and the slowdown | Movement demonstrated end to end on probes; the suite numbers are in flight. See "The two numbers" |

## Three things in the brief that do not exist

Reported to the coordinator before any code was written.

* Base commit `2b2f8e6a`: not a valid object in any ref, and not fetchable from the remote. Branched from the head
  of `claude/verifier-cli` instead.
* `claude/l1-trunk`: did not exist. Created.
* `crates/detpy-core/src/provable.rs`, with the accounting table `account(module, qualname)` and the single
  predicate `judge(attestation) -> Verdict`: **does not exist on any branch.** There is no `fn judge` and no
  `fn account` anywhere in the repository. On this lineage the verdict lives in
  `crates/detpy-core/src/verify.rs` (`Status::NotProven`, default-deny). That file was treated as Block 1's and
  is untouched, and it turned out that nothing in it needed to change.

`claude/l1-threads-fix` and `claude/l1-asyncio-study` share **no common ancestor** with this lineage (empty
merge-base; the trunk has 14 disjoint roots). So this is a content port, not a merge.

## provable.rs landed mid-session, and it blocks the row

MEASURED, after the three missing anchors above were reported: `crates/detpy-core/src/provable.rs` and
`python/detpy/provable.py` **now exist**. Block 1 landed them on `claude/verifier-cli` during this session, 9
commits after the branch point `bbb7a8a1`; the trunk head is `ee4d5de0`. So the brief was describing work that had
not landed yet, and the file it named is real now.

That changes the answer for this row, and not in my favour. `provable.py` takes `sys.monitoring`'s CALL event,
which fires for every callable invoked, and looks each name up in `account()`. In `provable.rs`:

```rust
fn thread_account(name: &str) -> Accounting {
    // a thread: `uncontrolled.thread`, already NOT PROVEN. Named so the report says "thread".
    "start_new_thread" | "start_joinable_thread" | "start" | ... => Accounting::Unaccounted,
```

and `Accounting::Unaccounted` is documented as "The test is NOT PROVEN." So on the current trunk head the **call**
to `threading.Thread.start` makes a test NOT PROVEN whatever the events say. The work below suppresses the
`uncontrolled.thread` *event*, which feeds `Attestation.marks`; the sensor path does not look at the marks. A
deterministically scheduled test is therefore still NOT PROVEN on that head, and nothing I can do on this side of
the line changes it.

The brief says that if `judge()` lacks something I need I must ask rather than write a second implementation, so
that is what I did. The hook already exists: `Attestation.controls` is "the `--det` controls the run had on", and
`required_controls(sensor)` already makes a per-sensor controls requirement part of the rule. The change asked of
Block 1 is that `thread_account` answer `Controlled` for `start`, `start_new_thread` and `start_joinable_thread`
**only when the run's controls contain `threads`**, and `Unaccounted` otherwise. The withdrawal path then needs no
new code at all: an escaped thread already records `uncontrolled.thread`, that lands in `Attestation.marks`, and
`judge` already turns a mark into NOT PROVEN.

My half of that contract is `meta.controls` carrying `threads` and `async`, since `judge` can only see the control
if the header names it. DECLARED: I will not suppress the sensor from this side to get a green. That would be a
second implementation of their rule, which is the one thing this row was told not to build.

## How a scheduled thread becomes provable without touching the verdict

`python/detpy/uncontrolled.py` is the only producer of the thread mark: it patches `threading.Thread.start` and
the `_thread` entry points, and records one `uncontrolled.thread` event per test. Under `--det-threads` it now
asks the scheduler whether a thread started here is one it takes, and if so records no mark. The interleaving is
then a run input like any other, recorded as the `sched.thread` choice events that the fingerprint covers. An
unchanged `verify.rs` therefore reports IDENTICAL only where the control was real, and no new verdict vocabulary
was needed.

The claim is withdrawn the moment it stops being true:

* a managed thread that blocks in C code, spins without reaching a scheduling point, or runs outside the
  scheduler is **escaped** by the watchdog; the scheduler records `threads.uncontrolled` (where it lost control)
  and calls `uncontrolled.mark_thread_escaped`, which records the ordinary `uncontrolled.thread` the verifier
  reads. The test is NOT PROVEN again, exactly as without the option.
* `--det-async` is symmetric: the scheduler chooses the order ready I/O is delivered in and records each choice as
  `sched.io`, so `uncontrolled.io` is suppressed while it drives the loop; a wake-up it had to take from the real
  world is recorded as `asyncio.uncontrolled` and marks the test through `mark_io_escaped`.
* every path that cannot answer answers with the mark. The predicates return False on any exception, and False
  means "mark it".

`uncontrolled.net` and `uncontrolled.child` are untouched. MEASURED: with both options on, a test whose asyncio
peer is a server in another process still records `uncontrolled.net` and `uncontrolled.child`. The live-socket
bucket (12% of tests by the earlier measurement) is not in this row and this change does not claim it.

### One correctness bug found reviewing my own change

`will_manage` first answered "the scheduler is active". What actually decides is `_wrap_start_thread`: a thread is
adopted only when the thread **starting** it is itself managed. A thread started by an unmanaged thread (a pool
worker that existed before the test, a finalizer running inside the scheduler's critical section) is not taken,
and the first predicate would have suppressed its mark anyway — a test reported identical on a control we do not
have. It now asks `_me()`, the same question the gate asks. `tests/test_l1_provable.py` pins that case.

## The seams: what the trunk had moved since the L1 branches

`threads.py`, `aio.py` and `frames.py` come over unchanged. What differs is how they reach the engine.

* **`_state.record` and the quiet flag are Rust here.** The two per-thread values L1 kept in a `threading.local`
  join the quiet flag as Rust thread-locals (`l0_set_tkey`, `l0_set_event_buffer`): a stable event key for a
  managed thread, because the OS hands out a thread ident again once a thread ends and a later thread would take
  the finished one's event column, making the trace differ between runs over nothing the test did; and the
  executor-job event buffer, so a job's events land where the loop delivers its result rather than wherever the
  pool happened to run it. Mirrored in `tests/rust_hotpaths_ref/_ref_l0_state.py`, which the equivalence test
  compares against byte for byte.
* **`time.sleep` is Rust here**, where L1 hooked a Python `_on_sleep`. L1's branchy logic stays verbatim in Python
  (`clock._sleep_l1`) behind one atomic (`clock_set_l1_hooks`). With no L1 option the Rust path is what it was,
  which is what keeps the slowdown honest for the tests that have no threads.
* **Both schedulers install from `_level0.install_controls`**, not the pytest plugin, so the unittest, django,
  doctest and nose2 runners get them too.
* **`--det-threads-real-urandom` is not ported.** On this lineage OS entropy is controlled by default under
  `--det`, so the flag would do nothing; `--det-entropy=observe` is the way to keep real entropy. DECLARED: if a
  gap probe expects the flag to exist, this is why it does not.
* `ThreadEntry`, `LineTracer` and `LineMonitor` are not yet ported to this lineage's `_core`. All three use sites
  are guarded by `try: from ._core import ... except ImportError` with Python fallbacks, and the two tracers only
  engage for exploring seeds (`CFG.seed and CFG.preempt`), not for the calm seed 0 that `--det-threads` uses by
  default. UNKNOWN: the cost of the Python fallback for exploring seeds on this lineage.

## One thing I broke and had to repair

Commit `9ccac5fc`, whose message says it is a report change, also reverted five files to the trunk baseline —
`_level0.py`, `_state.py`, `clock.py`, `plugin.py`, `uncontrolled.py`, 209 deletions. That is the entire
Python-side integration of this port: the two options, the config, the installs, the per-test hooks, the
provability decision, the Rust-backed `_state` helpers and the clock sleep hook. At that commit
`fenvix python --help` listed neither `--det-threads` nor `--det-async`.

Cause: `git checkout <ref> -- <paths>`, which I used to put the trunk's own Python in place while proving the
anyio hang was not mine, **stages** what it checks out. The index still held those five files when I committed
what I believed was only a report. The later `git checkout HEAD -- python/detpy/` then restored the damaged
versions, which concealed it. It surfaced only because a patch anchor that an earlier commit had added was
missing from the file.

Repaired by restoring all five from `cc3a9479` and verifying them byte-identical to it. `threads.py`, `aio.py` and
`frames.py` were never staged and were untouched. The matrix results reported here are unaffected: they ran on
`89d076e8`, which predates the bad commit. Recorded because a reader comparing commits would otherwise find the
port appearing and disappearing with no explanation.

## Why the numbers below are believable: three bugs in my own harness

Found by running the harness on a real suite before trusting it, not by it failing.

* The movement counter compared each test's status against `"identical"`. `fenvix verify --json` gives
  `verify.rs`'s `Status` in kebab-case — `stable | diverged | missing | input-differs | not-proven` — and `stable`
  is the proof the report prints as IDENTICAL. Nothing ever equalled `"identical"`, so "tests moved" and "proofs
  lost" were pinned at zero and the proven share read 0.0 whatever the runs did.
* The first `--det` run of an environment compiles the standard library and site-packages under
  `PYTHONHASHSEED=0` into a shared cache. MEASURED: 5.4 s of a 5.4 s run. Whichever mode ran first carried that
  one-off, and the slowdown read **-66%**. There is now a discarded warm-up run.
* The first suites job that reached the measurement finished anyio in 5 seconds and reported a tidy "0 moved, 0
  lost, 0 broken". The corpus records no test dependencies for anyio, so nearly every test errored at import:
  three modes of nothing, which compare equal. Nothing in the harness objected.

**All three were wrong in the flattering direction.** That is the single most useful thing to know about these
numbers, and the reason the guards below exist rather than being left to care.

So the harness now refuses to report a job it could not run: `suites.py` installs what a suite's own tests need
and runs `--collect-only` as a gate (MEASURED: anyio collects 2490 tests where it had been measuring
approximately none), and `measure.py` marks a result invalid and exits nonzero on pytest rc 2, 3, 4 or 5
(interrupted, internal error, usage, nothing collected), on a run that reached its budget, on a missing
`fenvix verify` report, or when no test was in both modes. Every transition is reported by name, so a move to
`diverged` cannot hide inside "not proven any more".

## Speed: the first thing this control does is make a suite faster

MEASURED on this container, Python 3.13.18, anyio `tests/test_synchronization.py -k asyncio`, 2 rounds per mode
after a discarded warm-up: `--det` median 3.37 s, Level 1 median 2.20 s — **Level 1 ran 35-40% FASTER than
`--det`** (-40% on the run reported below, -35% on the second). The reason is structural, not noise: under
`--det` alone an asyncio loop forces `time.sleep` to wait for real, because the loop keeps real time and its
deadlines must see the sleep; under `--det-async` the scheduler owns the loop's time and the sleeps stop waiting.

Stated honestly in both directions: on that same selection **no movement was available**, because all 165 tests
were already `stable` under `--det` — nothing was NOT PROVEN to begin with. The speed figure does not hide that,
and the absence of movement there does not hide the speed figure.

## The two numbers

### Movement, MEASURED on probes

On this container, Python 3.13.18, the exam's `executor_race` probe, 8 runs per mode. **MEASURED at the
branch point `bbb7a8a1`, before `provable.rs` landed** — it is evidence that the mechanism works, not a
claim about the current trunk, and it will be re-measured once Block 1's clause and their `marshal.load`
classification fix are in:

| | outcome | `fenvix verify` |
| --- | --- | --- |
| `--det` (Level 0 only) | passed in all 8 | **NOT PROVEN**, rc 1, reason `thread` |
| `--det --det-threads --det-async` | passed in all 8, one fingerprint | **IDENTICAL**, rc 0 |

That is the movement this row exists for, demonstrated end to end: the same test, NOT PROVEN before and IDENTICAL
after, with the verdict code unchanged.

The reverse direction, also MEASURED: a worker thread blocking in C on `os.read` of an empty pipe is escaped, both
`threads.uncontrolled` and `uncontrolled.thread` are recorded, and `fenvix verify` of 4 such runs does not report
it identical (rc 1).

### Movement and slowdown on real suites

IN FLIGHT. `harness/l1_trunk/measure.py` runs each suite `--runs` times per mode, compares the runs of a mode with
`fenvix verify --json`, and reports the per-test status transition in **both** directions plus the wall time. It
counts, as first-class numbers rather than footnotes: tests that moved to IDENTICAL, tests that **lost** a proof,
and tests the schedulers **break** (one outcome in every `--det` run, a different one in every L1 run). The corpus
is the L1 study's own (`harness/l1_trunk/threads-corpus.json`, 26 suites pinned by commit), carried over unchanged
so these numbers can be compared with the ones that study reported.

UNKNOWN until those jobs land: the provable-share movement and the slowdown on real suites. They are what the row
is judged on and they are not in hand yet. Nothing here should be read as if they were.

## A hang on the trunk, found while measuring, and not this row's

MEASURED on this container, anyio at the pinned corpus commit, `pytest tests/test_from_thread.py -k asyncio`:

| mode | result |
| --- | --- |
| plain pytest | 87 passed in 2.0 s |
| `--det` | **HANGS** — 10 min elapsed, 1 s of CPU, single-threaded, sleeping |
| `--det --det-threads --det-async` | completes in 3 s |

Verified not to be this work before reporting it: the trunk's own `_level0.py`, `_state.py`, `clock.py`,
`plugin.py` and `uncontrolled.py` were restored from `claude/verifier-cli`, the three new modules moved aside, and
the hang reproduced identically; `frames.install`, the one change here that touches plain `--det`, was ruled out
separately; the working tree was then checked clean against HEAD. Reported as a hang rather than given a longer
budget.

Assigned to Block 2 by the coordinator with that reproduction. Level 1 happens to unblock it, which is not a fix
and is not claimed as one.

## Three tests I reported Level 1 as breaking: the claim is withdrawn

MEASURED, same selection, `--det --det-threads --det-async`: 3 failed, 84 passed, 1 error, against 87 passed
plain. All three are `TestBlockingPortal::test_from_async`, parametrised `[asyncio-trio]`, `[asyncio+eager-trio]`
and `[trio-asyncio]`, failing with `RuntimeError: This portal is not running`.

I reported that as a defect of this port, with a diagnosis (anyio's blocking portal runs a **trio** loop in a
worker thread; trio's primitives are not scheduling points this scheduler can see, so the portal thread is
starved) and a fix (route `trio.run` through `threads._wrap_outside_run`, as uvloop already is). **Both were
wrong, and the comparison I drew them from was invalid.**

What settles it is a minimal probe — a worker thread that calls `trio.run` on a coroutine appending to a list:

| mode | result |
| --- | --- |
| plain pytest | 1 passed |
| `--det` | **1 failed** — `assert [] == [1]`: the coroutine never ran |
| `--det --det-threads` | 1 failed, the same way |

So trio in a worker thread is already broken by **Level 0 alone**, with no Level 1 option. The three anyio
failures are almost certainly that same Level 0 defect, surfacing only once `--det-threads` lifts the `--det`
hang that was hiding the rest of the file.

The invalid step was mine: I compared Level 1 against **plain pytest** (87 passed) because `--det` hangs on that
file and could not provide a baseline. "Passes plain, fails under L1" says nothing about what L1 broke when
`--det` breaks it too. The right baseline was unavailable, and I should have said so instead of attributing it.

The `trio.run` wrap is kept, but **not as a fix and not claimed as one**. MEASURED: it does not change the anyio
result (3 failed / 84 passed with and without it). It is kept because a thread running a trio loop genuinely is
not controlled by this scheduler, so it should leave the scheduler and the test should be marked — MEASURED, it
records `threads.uncontrolled` and `uncontrolled.thread`, which is the honest answer rather than a scheduler
recording `sched.*` events around a loop whose scheduling it does not own.

Handed to Block 2 with the hang, as the same family: trio under `--det` is a Level 0 defect.

## The exam

MEASURED, and this is the finding that needs a decision rather than more work from me.

`exam/results.json` on the frozen `claude/exam` records PY-07 as `status: FAIL`, `n_checks: 0`, `n_passed: 0`,
`legs: {}`, and all 13 of its gaps as `no_check_ran`. The row has never been examined: before this work the
options did not exist, so nothing ran.

`PY-07.options` is now satisfied. MEASURED: `--det-threads` and `--det-async` appear in `fenvix python --help`, on
3.12, 3.13 and 3.14.

The other two probe checks have a precondition the engine cannot supply. Both require a **real race to occur** in
8 plain runs:

* `PY-07.probe-stable` computes `ok = exercised and all(one outcome under the options)`, where `exercised` means
  each probe showed at least 2 distinct outcomes in 8 plain runs.
* `PY-07.verify-honest` returns False outright when the 8 `--det` runs agree ("the race was not exercised, nothing
  to judge").

MEASURED on GitHub-hosted `ubuntu-24.04`, Python 3.13, 8 runs each (the same runner class `exam.yml` uses): the
thread race showed **1** distinct outcome, and the executor race showed **1**. Both INCONCLUSIVE. Under the
options both were stable with a single fingerprint — the half of the check that tests the engine passes. MEASURED
on this container: the executor race does show 2 outcomes in 8 plain runs, so that probe is not impossible, just
host-dependent. The thread race is worse than unlucky: MEASURED, **0 failures in 40 plain runs** on this
container, so it is not that 8 runs were too few. The lost update does not happen here at all, even with
`sys.setswitchinterval(1e-6)` and 400,000 increments across two threads.

So on the exam's own runners, PY-07 as frozen is likely to report INCONCLUSIVE for `probe-stable` and
`verify-honest`, and the exam counts INCONCLUSIVE as not passed. That is a property of the probes, not of this
work, and I will not pretend otherwise:

* I did not change the exam. It is frozen and it is the authority.
* I did not relax `harness/l1_trunk/probes.py` to call an unexercised probe green. It reports INCONCLUSIVE as
  INCONCLUSIVE.
* DECLARED: I will not report PY-07 green on an INCONCLUSIVE probe. A check that could not observe the thing it
  is checking has not passed.

**For the founder.** Three ways out, none of which I can take alone: run the exam's PY-07 leg on a runner where
the races do occur; let the exam's probe-stable treat "stable under the options, race not exercised" as a
separate, named outcome rather than a failure (an exam change, his call); or accept the row on the evidence that
does exist — the measured movement above, the escape behaviour, and the tests that pin both directions.

Separately: `exam.yml` is not on the repository's default branch, so GitHub does not offer it as a manual
dispatch; only a push to `claude/exam` triggers it, and it installs a `release-1.yml` engine artifact rather than
a branch. Running PY-07 against this work therefore needs a `release-1.yml` run on `claude/l1-trunk` and then
either a push to `claude/exam`'s own `rerun.json` or someone with that authority. I have not pushed to the exam
branch.

## The io line: settled strict, and what it costs

Suppressing `uncontrolled.io` makes an in-process asyncio client/server pair over real loopback come out
IDENTICAL. MEASURED: no escape fires, because the loop never had to wait — the kernel always had something ready.

The defence is that the readiness sequence is recorded in the `sched.io` events (the ready-set size and the stable
ids), so a run where the real world differed diverges rather than passing for identical; and this release already
holds that an in-process listener is not an uncontrolled source (`network._note_live`: "Its own server ... is
not"). It is consistent with how `--det` already treats loopback.

I wrote that I was "not comfortable calling it certain", and the coordinator ruled that this settles it without
going to the founder, because the founder's rule already covers it: never a green on a doubt, and speed never
buys an exception. Recording the readiness sequence is a good defence and it is not the same thing as controlling
it; "defensible" is not the bar.

**So the strict line is taken.** `uncontrolled.io` is kept whenever the test's loop ever watched a descriptor that
is not the loop's own wake-up pipe, and suppressed only for loops whose wake-ups are all internal — timers,
executor results, the self-pipe. The loopback pair above therefore stays NOT PROVEN. Loopback goes on the list of
channels to cover later rather than being claimed now.

UNKNOWN: the movement this costs on real suites. It will be reported as a number, not as a remark.

## What runs where

`.github/workflows/l1-trunk.yml`, on a push to this branch, Python 3.12 / 3.13 / 3.14:

* `build` — the wheel. MEASURED: green on all three.
* `engine` — **GATE.** The engine's own suite, the regression gate for this work (it changed the Rust record hot
  path, `time.sleep` and the uncontrolled marking). `fail-fast: true`, per the founder's rule that a red gate ends
  the run: there is nothing to learn from the other versions once one says the port broke something.
* `probes` — **MEASUREMENT.** The PY-07 conditions. `fail-fast: false`: what a probe does on 3.14 is evidence even
  when 3.12 is red, and these report INCONCLUSIVE rather than passing or failing where the host does not race.
  MEASURED: green on all three, with the INCONCLUSIVE notes above.
* `suites` — **MEASUREMENT.** The two numbers, over hours. `fail-fast: false` and `cancel-in-progress: false`: one
  suite failing must not throw the others away, and a later push must not cancel them.

No step raises a timeout to get green. A run that reaches its budget is reported as a hang.

## Tests added

`tests/test_l1_provable.py`, MEASURED 7 passed on this container (3.13.18): scheduled threads record `sched.thread`
and are not marked; threads without the option are marked; a thread blocking in C is escaped and marked again;
**a thread started by an unmanaged parent is marked** (the case the first predicate got wrong); `--det-async`
suppresses the io mark for a loop whose wake-ups are its own; a server in another process still gets
`uncontrolled.net` and `uncontrolled.child`; and either option without `--det` is an error rather than a silent
no-op.
