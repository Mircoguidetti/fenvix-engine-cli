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

## The two numbers

### Movement, MEASURED on probes

On this container, Python 3.13.18, the exam's `executor_race` probe, 8 runs per mode:

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

## One judgment call the founder should see

Suppressing `uncontrolled.io` makes an in-process asyncio client/server pair over real loopback come out
IDENTICAL. MEASURED: no escape fires, because the loop never had to wait — the kernel always had something ready.

The defence is that the readiness sequence is recorded in the `sched.io` events (the ready-set size and the stable
ids), so a run where the real world differed diverges rather than passing for identical; and this release already
holds that an in-process listener is not an uncontrolled source (`network._note_live`: "Its own server ... is
not"). It is consistent with how `--det` already treats loopback.

What I will not do is call that certain. The verdict rests on kernel loopback timing having been **recorded**
rather than **controlled**. If the stricter line is wanted, it is one condition: keep `uncontrolled.io` whenever
the test's loop ever polled a real descriptor, and suppress it only for loops whose wake-ups are all internal
(timers, executor results, the self-pipe). That is narrower and would cost some of the movement. I have not taken
it, because the founder's rule is his to apply here.

## What runs where

`.github/workflows/l1-trunk.yml`, on a push to this branch, Python 3.12 / 3.13 / 3.14:

* `build` — the wheel. MEASURED: green on all three.
* `engine` — the engine's own suite, the regression gate for this work (it changed the Rust record hot path,
  `time.sleep` and the uncontrolled marking).
* `probes` — the PY-07 conditions. MEASURED: green on all three, with the INCONCLUSIVE notes above.
* `suites` — the measurement on anyio, requests and networkx.

No step raises a timeout to get green. A run that reaches its budget is reported as a hang.

## Tests added

`tests/test_l1_provable.py`, MEASURED 7 passed on this container (3.13.18): scheduled threads record `sched.thread`
and are not marked; threads without the option are marked; a thread blocking in C is escaped and marked again;
**a thread started by an unmanaged parent is marked** (the case the first predicate got wrong); `--det-async`
suppresses the io mark for a loop whose wake-ups are its own; a server in another process still gets
`uncontrolled.net` and `uncontrolled.child`; and either option without `--det` is an error rather than a silent
no-op.
