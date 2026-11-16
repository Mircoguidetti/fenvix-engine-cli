# L1 study: deterministic asyncio (`--det-async`)

Status: design note plus prototype (`python/detpy/aio.py`, flag `--det-async`
on top of `--det`). CPython 3.10–3.13. Written 2026-11-16 by the L1 study
session (prompt P-006).

## 1. Where asyncio nondeterminism comes from

asyncio runs one thread and calls callbacks in exactly one place,
`BaseEventLoop._run_once`. One iteration does, in this order:

1. drop cancelled timers from the heap `_scheduled`;
2. `event_list = self._selector.select(timeout)`; `timeout` is 0 if the ready
   queue `_ready` is not empty, otherwise the time until the first timer
   (real time, `loop.time()` = `time.monotonic()`);
3. `_process_events(event_list)` appends the reader/writer callbacks of the
   ready file objects to `_ready`;
4. every timer with `when < loop.time() + clock_resolution` is moved to `_ready`;
5. the callbacks that are in `_ready` *now* are run, FIFO; callbacks they
   schedule wait for the next iteration.

Given the same inputs at the same iterations, that is deterministic: `_ready`
is a FIFO deque and `call_soon` order is a documented guarantee. All the
nondeterminism comes from *what is put into `_ready` at which iteration*:

| source | mechanism | typical flaky test |
|---|---|---|
| **ready-queue order** | FIFO itself is fixed; what varies is the iteration at which external callbacks (below) join it, so they interleave differently with task steps. `asyncio.wait`, `all_tasks()` return `set`s of tasks hashed by address. | "task B ran before A finished its setup", results read from a `set` of tasks |
| **timers and the clock** | `loop.time()` is real `time.monotonic()`. Whether a timer fires in this iteration or a later one depends on how much real CPU time the callbacks took, on scheduler preemption, GC pauses, a loaded CI runner. | `wait_for(x, timeout=0.1)` that sometimes times out; `sleep(0.01)` used as "enough time for the other task"; two timers whose order depends on work done between scheduling them |
| **I/O readiness from selectors** | `select()` returns what the kernel has ready at that instant, in kernel order (epoll: readiness order). A peer in another thread/process, the network, the loopback stack under load decide it. The number of bytes a `recv` returns also depends on timing. | server/client tests where two responses arrive in either order; "readline got half a line" |
| **thread-pool executors** | `run_in_executor` / `to_thread` / `getaddrinfo` run in worker threads; the result is posted back with `call_soon_threadsafe` whenever the worker finishes. | "job result arrived after the timeout", order of results of parallel jobs |
| **`call_soon_threadsafe`** | foreign threads append to `_ready` and write to the self-pipe at an arbitrary point between iterations. Also used by asyncio itself: executor shutdown thread, async-generator finalizers (GC), threaded child watchers (subprocess exit, 3.12+). | "event set from a thread is seen one iteration late" |
| **task cancellation** | `Task.cancel()` is itself deterministic (delivered at the next step), but most cancellations come from timeouts (`wait_for`, `asyncio.timeout`, `TaskGroup` failure fan-out), so they inherit the timer and I/O races above; `cancel()` vs. completion in the same iteration decides whether `CancelledError` or the result is seen. | "CancelledError not raised", "task finished despite cancel" |
| others | signal handlers via the self-pipe; GC finalizers of transports; `uvloop` (not a `BaseEventLoop`); trio (own scheduler) | |

## 2. What Level 0 already fixes, and what it does not

Level 0 (`--det`) fixes the test order, the seeds, `PYTHONHASHSEED`, the
filesystem listing order, the network, and the clock *of user code*
(`time.*`, `datetime.now`). It explicitly **keeps asyncio on real time**:
`clock.install` patches `BaseEventLoop.time` to the real `time.monotonic`,
because the selector waits for real and a virtual loop clock without a
scheduler would make every timeout fire immediately. So under L0:

* every row of the table above is still nondeterministic;
* worse, user code mixing `time.monotonic()` (virtual) with `asyncio.sleep`
  (real) sees inconsistent clocks: `await asyncio.sleep(10)` takes 10 real
  seconds and `time.monotonic()` advances by a few microseconds.

What L0 gives L1 for free: a fixed hash seed (so `set` iteration of strings is
stable), ASLR off (task addresses, hence `set`-of-task order, are more often
equal across runs, but not guaranteed), the per-test seed derivation
(`derive_seed(seed, nodeid)`), the virtual clock to keep consistent with, the
event sink and the verifier.

## 3. The seeded scheduler

`--det-async` gives every asyncio loop *run by the thread of the running test*
a `Scheduler` that replaces `_run_once`. Each choice point where real asyncio
depends on timing is decided by a SplitMix64 generator seeded with
`derive_seed(seed, nodeid + loop index)`:

| choice point | real asyncio | `--det-async` |
|---|---|---|
| loop clock | real monotonic | virtual: each callback costs a seeded duration (CPU-time model: exponential, mean 8 µs, 2% "hiccups" up to 5 ms; seed 0 = fixed 5 µs); when nothing is ready the clock **jumps** to the next deadline instead of sleeping. Jumps are mirrored into the L0 clock so `time.monotonic()` agrees. |
| which timers fire this iteration | real time elapsed | pure function of the virtual clock, hence of the seed |
| I/O readiness | `select(timeout)` blocks; kernel order | `select(0)` every iteration (never blocks while work is pending). Each ready file object is delivered now or **deferred** to a later iteration (p = 0.35 per iteration; it stays ready because selectors are level-triggered); delivered ones are put in canonical order (fd) then shuffled. Seed 0: all, in fd order. |
| executor results | posted by the worker whenever it finishes | `run_in_executor` keeps the `concurrent.futures.Future`; at the next iteration the loop **waits for the job** and schedules its delivery at virtual time `submit + virtual sleeps of the job + seeded cost`; the delivery is a timer-like event, so "job vs. timer" and "job A vs. job B" are decided by virtual durations and the seed, not by thread speed. The worker's own events (e.g. its `time.sleep`) are buffered and recorded at the delivery point. |
| `call_soon_threadsafe` from foreign threads | appended at arrival | buffered; when the loop has to wait for real it batches arrivals over a settle window (10 ms, extended by each new arrival); the batch is merged **FIFO per posting thread** (causal order kept), threads interleaved by the seed |
| idle loop with timers and live foreign sources (threads, child processes) | sleeps on the selector until the timer | waits for real up to `min(delay, --det-async-grace)` (1 s) for foreign I/O, then jumps. A wake-up in that window is recorded (`grace-wakeup`) because its timing is not controlled. |
| `shutdown_default_executor` | joins in a helper thread, 300 s timeout race | joined in the loop thread |

What is **not** reordered: callbacks already in `_ready`. FIFO is an asyncio API
guarantee; reordering it would produce executions CPython can never produce and
therefore false failures. The seed explores only the freedom real asyncio has:
*when* external events arrive relative to each other and to timers, and how
long callbacks take.

Seed 0 is the **calm profile** (fixed costs, everything ready delivered at
once): the default of `--det-async` alone, meant to make a suite reproducible
without exploring. Seeds ≥ 1 explore (`--det-async-seed=N`, default
`--det-seed`).

### Recording, fingerprint, verifier (shared event vocabulary)

Every choice is one event in the shared vocabulary (fenvix-brain-cli
ARCHITECTURE.md, "Shared event vocabulary"; encoding version 2):

| op | when | chosen index / set size |
|---|---|---|
| `sched.io` | a ready file object is delivered | index in the canonical (fd-ordered) set of ready objects still undelivered, including the deferred ones |
| `sched.ready` | a foreign `call_soon_threadsafe` callback is delivered | index in the canonical order of the batch still undelivered |
| `sched.executor` | an executor result is delivered | `0/n`, n = results due together (order = virtual completion time) |
| `sched.timer` | a timer fires | `0/n`, n = timers due together (order = deadline) |

value = `<chosen index>/<set size>:<stable id>`; the stable id is the creation
site of the callback (first user frame when the timer, reader/writer, executor
job or threadsafe call was created; `path:line` relative to the root) plus a
per-site counter, e.g. `sched.io 1/3:tests/test_x.py:39#2`. The event's site is
the same creation site. Points whose timing the scheduler does not control are
recorded as `other` events `asyncio.uncontrolled` (`grace-wakeup`,
`blocked-wakeup`, `executor-unsettled=<job>`). Events of executor workers are
recorded at the delivery point of their job, so worker threads do not perturb
the fingerprint. The Rust core has `Source::Sched` (tag 9), `Reason::Sched`,
`ENCODING_VERSION = 2` and refuses to compare traces of different encodings.
`detpy verify` reports, e.g.:

```
NOT-COVERED test_races.py::test_io_threads  [sched]
    runs 0 vs 1: event #4: first diverging scheduling choice: sched.io 1/3:test_races.py:39#2 @ test_races.py:39  <>  sched.io 2/3:test_races.py:39#3 @ test_races.py:39
```

## 4. Mapping onto Node's event loop (design only)

The Node L1 can reuse the same model and the same vocabulary; only the
interception points differ. Node's loop is libuv plus V8's microtask queue:

```
timers -> pending callbacks -> idle/prepare -> poll (I/O) -> check (setImmediate) -> close callbacks
          after every macrotask callback: process.nextTick queue, then the promise (microtask) queue, until both are empty
```

| asyncio concept (this prototype) | Node / libuv equivalent | choice point and `sched` op |
|---|---|---|
| `_ready` FIFO of callbacks scheduled by callbacks | `process.nextTick` queue and promise jobs (microtasks): FIFO, drained completely after each macrotask | **not a choice** (FIFO is guaranteed by the language, like `call_soon`). Exactly as here, reordering them would create impossible executions. |
| microtasks vs. macrotasks | V8 microtask checkpoint vs. libuv phases | the order is fixed by the spec; `sched.microtask` is reserved for the one real freedom: *which macrotask* runs next when several are runnable (e.g. `setImmediate` vs. an expired `setTimeout(0)` scheduled from the main module, whose order depends on loop start time) |
| timers + virtual clock with jumps | timers phase (`setTimeout`/`setInterval`, libuv timer heap, `uv_now` updated once per iteration) | `sched.timer`: virtual `uv_now` with the same cost model and jumps; timers due together fire in deadline order (`0/n`) |
| I/O readiness, deferral, seeded order | poll phase (epoll/kqueue), `pending callbacks` phase for deferred I/O errors | `sched.io`: poll with timeout 0, deliver or defer each ready handle, seeded order among delivered |
| executor jobs (`run_in_executor`) | libuv threadpool (`fs.*`, `dns.lookup`, `crypto.pbkdf2`, `zlib`), worker threads' `postMessage` | `sched.executor`: wait for the work request, deliver its completion at `submit + virtual duration + seeded cost` |
| foreign `call_soon_threadsafe` | `uv_async_send` from other threads (worker_threads messages, N-API thread-safe functions) | `sched.ready`: batch, FIFO per sender, seeded interleaving |
| `call_soon` from the loop | `setImmediate` (check phase) | FIFO within the check phase; the choice is check-before/after-timers only at loop start |
| `shutdown_default_executor` race | process exit with pending handles (`unref`ed timers) | deterministic drain at test end |

Where to intercept in Node: timers and `setImmediate` in JS (the
`internal/timers` lists, or a loader that wraps the globals as the Node L0
already does for `Date`), `process.hrtime`/`performance.now` for the clock;
I/O and the threadpool are in C (libuv), so a Node L1 that controls `sched.io`
and `sched.executor` needs either a patched `libuv` (a custom Node build or a
`LD_PRELOAD` shim of `uv_run`/`uv__io_poll`/`uv_queue_work`) or, at JS level,
wrappers of `fs`/`net`/`dns` callbacks that defer delivery through the
scheduler (cheaper, partial: native addons and streams' internal reads escape
it). The Rust core needs nothing new: the same `Source::Sched` ops and value
format, stable ids from source-mapped `.ts` sites.

## 5. Approaches compared

| | A. custom loop + event loop policy | **B. instrument `BaseEventLoop` internals** (chosen) | C. selector shim |
|---|---|---|---|
| what it is | a new `AbstractEventLoop` (or `SelectorEventLoop` subclass) installed with `set_event_loop_policy` / `loop_factory` | replace `_run_once`, `time`, `call_soon_threadsafe`, `run_in_executor`, `run_forever`, `shutdown_default_executor` on the class, active only on loops run by the test thread | wrap `loop._selector` so `select()` returns events in a seeded order and never blocks |
| loops covered | only loops created through the policy: misses `asyncio.new_event_loop()` with an explicit class, `asyncio.Runner(loop_factory=...)`, pytest-asyncio's own loop fixtures in some versions, tornado/aiohttp test utilities that create loops directly, session-scoped loops created before the plugin | every `BaseEventLoop` whatever created it (asyncio.run, Runner, pytest-asyncio, anyio's asyncio backend, tornado ≥ 5, aiohttp test utils); loops created before the test are re-based onto virtual time when first run | every selector loop, but only the I/O dimension |
| choice points controlled | all, if the loop is written from scratch | all (timers, I/O, executors, threadsafe, clock) | I/O order only; timers, executors, threadsafe and the clock stay real |
| fidelity | a re-implementation drifts from CPython semantics (exception handling, debug mode, slow-callback logging, eager tasks 3.12+, `_asyncgen` hooks) | the original methods do all the work except the iteration itself; `_run_once` is ~60 lines and identical in structure 3.10–3.13 | high, but too little control |
| fragility | public API only | private attributes (`_ready`, `_scheduled`, `_selector`, `_process_events`, `_read_from_self`, `_clock_resolution`, `TimerHandle._when`): stable 3.10–3.13, must be re-checked per CPython release (3.14 has not been checked) | private `_selector` |
| `isinstance` / identity | loop class changes | unchanged | unchanged |
| effort | high | medium | low |

**Choice: B.** It is the only approach that both reaches every loop a real
test suite creates (pytest-asyncio, anyio, asyncio.run, tornado) and controls
every choice point, while reusing CPython's own handle/transport machinery so
semantics do not drift. The selector work of C is folded into B (non-blocking
polling and seeded delivery inside `_run_once`). The cost is a dependency on
private internals; it is contained in one module and covered by tests on
3.10–3.13 in CI. A (a custom loop) remains the right shape for *uvloop users*
later (uvloop is not a `BaseEventLoop`), via a policy that swaps uvloop for a
scheduled selector loop under `--det-async`.

## 6. Limits of the prototype

* **Foreign threads are not scheduled.** Callbacks and I/O caused by
  threads the test starts itself are delivered in seeded order *within a
  batch*, but which batch they fall into depends on real time (settle window).
  These deliveries are visible in the fingerprint. Deterministic thread
  switching is the other half of L1 (bytecode-count scheduling) and is not
  part of this study.
* **Executor jobs that wait for the loop** (`run_coroutine_threadsafe(...).result()`
  inside a job, asgiref-style bridges) cannot be waited for: the loop detects a
  post from another thread while waiting and falls back to delivery at arrival
  (`executor-unsettled`, recorded). A job running longer than
  `--det-async-wait` (2 s real) falls back the same way.
* **Child processes and the real network** are external: an idle loop waits
  for them up to `--det-async-grace` real seconds per timer before jumping, so a
  slow subprocess plus a short timeout behaves as in reality (flaky), and is
  recorded as `grace-wakeup`.
* **Byte chunking** of stream reads is not controlled (what one `recv` returns).
* **`set`s of tasks** (`asyncio.wait`) iterate in address order; L0's
  ASLR-off makes that stable in practice but it is not guaranteed.
* **uvloop and trio** are not covered (not `BaseEventLoop`).
* CPython only; 3.14 not checked.

## 7. Files

* `python/detpy/aio.py` — scheduler, patched loop methods.
* `python/detpy/plugin.py` — `--det-async`, `--det-async-seed`, `--det-async-grace`,
  `--det-async-wait`, `--det-async-settle`.
* `python/detpy/clock.py` — virtual sleeps of executor jobs are charged to the job.
* `python/detpy/_state.py` — per-thread event buffer (executor jobs).
* `crates/detpy-core/src/{event,verify}.rs` — `Source::Sched`, `Reason::Sched`.
* `tests/test_aio.py` — race tests (fail without the prototype:
  `DETPY_ASYNC_FLAGS="--det" pytest tests/test_aio.py`), exploration,
  fingerprint, no-false-failure checks.
