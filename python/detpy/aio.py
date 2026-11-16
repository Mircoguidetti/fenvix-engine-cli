"""Deterministic asyncio scheduling (Level 1 prototype, ``--det-async``).

Design: ``docs/L1-ASYNCIO.md``. In short, every asyncio loop that runs in the
thread of the running test gets a :class:`Scheduler` that replaces
``BaseEventLoop._run_once`` (the only place where asyncio calls callbacks) and
decides, from a seed, every point where real asyncio depends on timing:

* **time**: the loop runs on its own virtual clock. Each callback costs a
  seeded virtual duration (CPU-time model); when nothing is ready the clock
  jumps to the next deadline instead of sleeping. Timer order is therefore a
  pure function of the seed;
* **I/O readiness**: the selector is always polled without blocking; each ready
  file object is delivered in this iteration or deferred to a later one (it
  stays ready: selectors are level-triggered), and the delivered ones are put
  in a seeded order;
* **executor results** (``run_in_executor``, ``to_thread``, ``getaddrinfo``):
  the loop waits for the job to finish at the next iteration and delivers its
  result at virtual time ``submit + virtual sleeps of the job + seeded cost``,
  so the delivery point does not depend on how fast the worker thread ran;
* **call_soon_threadsafe** from foreign threads: buffered, batched over a short
  settle window and delivered in seeded order (best effort: the arrival time of
  a foreign thread is not controlled; such deliveries are recorded).

Callbacks already in the ready queue keep asyncio's FIFO guarantee: reordering
them would create executions that real asyncio cannot produce.

Every iteration that delivered an external event, fired a timer or jumped the
clock is recorded as one ``sched`` event in the test fingerprint, so the
verifier names the first diverging scheduling choice of two runs.
"""

from __future__ import annotations

import asyncio
import asyncio.base_events as _be
import asyncio.selector_events as _se
import collections
import asyncio.events as _ev
import asyncio.futures as _af
import concurrent.futures
import heapq
import os
import threading
import weakref

from . import _core, _sites, _state

NS = 1_000_000_000
_M64 = (1 << 64) - 1


class Rng:
    """SplitMix64: identical on every Python version, independent of ``random``
    (which Level 0 patches and records)."""

    __slots__ = ("s",)

    def __init__(self, seed: int) -> None:
        self.s = seed & _M64

    def next(self) -> int:
        self.s = (self.s + 0x9E3779B97F4A7C15) & _M64
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _M64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _M64
        return z ^ (z >> 31)

    def random(self) -> float:
        return (self.next() >> 11) * (1.0 / (1 << 53))

    def below(self, n: int) -> int:
        return self.next() % n if n > 0 else 0

    def shuffle(self, xs: list) -> None:
        for i in range(len(xs) - 1, 0, -1):
            j = self.below(i + 1)
            xs[i], xs[j] = xs[j], xs[i]


# ---------------------------------------------------------------------------
# Configuration (set by the plugin)
class Config:
    enabled = False
    seed = 0
    grace = 1.0  # s of real time a timer waits for foreign I/O before the clock jumps
    wait = 2.0  # s of real time the loop waits for an executor job
    settle = 0.01  # s of real time to batch foreign wake-ups


CFG = Config()

# Cost model (virtual seconds). Seed 0 is the calm profile: fixed costs, every
# ready external event delivered at once in canonical order. Other seeds explore.
CALM_COST = 5e-6
CALM_JOB = 50e-6
NOISY_COST_MEAN = 8e-6
NOISY_HICCUP_P = 0.02  # probability that a callback is "preempted"
NOISY_HICCUP_MAX = 0.005
NOISY_JOB_MEAN = 300e-6
NOISY_DEFER_P = 0.35  # probability that a ready external event waits one more iteration

_DEBUG = bool(os.environ.get("DETPY_AIO_DEBUG"))
_tl = threading.local()  # .job: the executor job running in this worker thread
_orig = {}
_loop_counter = {"nodeid": None, "n": 0}


def _real_monotonic() -> float:
    from . import clock

    return clock.real_monotonic()


def _clock():
    from . import clock

    return clock.CLOCK if "time" in _state.STATE.config.controls else None


def on_sleep(ns: int) -> None:
    """Called by the virtual ``time.sleep``: charge the sleep to the executor job."""
    job = getattr(_tl, "job", None)
    if job is not None:
        job.vsleep += ns / NS


# ---------------------------------------------------------------------------
# Labels: stable, address-free names for what a choice delivered.
_TASK_IDS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_TASK_N = {"n": 0}


def _task_id(task) -> int:
    """Per-test ordinal of a task, by first appearance in a scheduling choice."""
    n = _TASK_IDS.get(task)
    if n is None:
        _TASK_N["n"] += 1
        n = _TASK_IDS[task] = _TASK_N["n"]
    return n


def _coro_label(task) -> str:
    try:
        coro = task.get_coro()
    except Exception:
        return "task"
    name = getattr(coro, "__qualname__", None) or type(coro).__name__
    frame = getattr(coro, "cr_frame", None) or getattr(coro, "gi_frame", None) or getattr(coro, "ag_frame", None)
    where = f"{name}:{frame.f_lineno}" if frame is not None else name
    try:
        return f"#{_task_id(task)} {where}"
    except TypeError:
        return where


def _fn_label(cb) -> str:
    import functools

    while isinstance(cb, functools.partial):
        cb = cb.func
    owner = getattr(cb, "__self__", None)
    if isinstance(owner, asyncio.Task):
        return "task " + _coro_label(owner)
    name = getattr(cb, "__qualname__", None) or getattr(cb, "__name__", None) or type(cb).__name__
    proto = getattr(owner, "_protocol", None) if owner is not None else None
    if proto is not None:
        name += f"({type(proto).__name__})"
    return name


def _handle_label(h) -> str:
    cb, args = h._callback, h._args or ()
    for a in args:
        if isinstance(a, asyncio.Future):
            for item in (getattr(a, "_callbacks", None) or ()):
                c = item[0] if isinstance(item, tuple) else item
                if isinstance(getattr(c, "__self__", None), asyncio.Task):
                    return f"{_fn_label(cb)}->task {_coro_label(c.__self__)}"
    return _fn_label(cb)


def _io_label(key, mask) -> str:
    reader, writer = key.data if isinstance(key.data, tuple) else (None, None)
    parts = []
    if mask & 1 and reader is not None:
        parts.append("r:" + _fn_label(reader._callback))
    if mask & 2 and writer is not None:
        parts.append("w:" + _fn_label(writer._callback))
    return f"io fd{key.fd} " + ("|".join(parts) or f"mask={mask}")


# ---------------------------------------------------------------------------
class Job:
    __slots__ = ("n", "label", "submit_vt", "vsleep", "cf", "afut", "due", "interactive", "events", "sid")

    def __init__(self, n: int, label: str, submit_vt: float) -> None:
        self.n = n
        self.label = label
        self.submit_vt = submit_vt
        self.vsleep = 0.0  # virtual seconds the job slept (charged by the virtual time.sleep)
        self.cf = None  # concurrent.futures.Future of the job
        self.afut = None  # asyncio future handed to the caller
        self.due = None  # virtual delivery time, known once the job finished
        self.interactive = False
        self.events: list = []  # events recorded by the worker thread while it ran the job
        self.sid = ""  # stable id: run_in_executor call site + counter


class Scheduler:
    def __init__(self, loop) -> None:
        self.loop = loop
        self.thread_id = threading.get_ident()
        clk = _clock()
        self.vt = clk.mono_ns(clk.elapsed) / NS if clk is not None else 1000.0
        self.synced_vt = self.vt  # loop time already reflected in the Level 0 clock
        self.lock = threading.Lock()
        self.pool: list = []  # (handle, thread name) posted by other threads
        self.jobs: dict = {}  # job number -> Job (running)
        self.done_jobs: list = []  # heap of (due, n, job)
        self.job_n = 0
        self.iteration = 0
        self.nodeid = None
        self.rng = Rng(0)
        self.noisy = False
        self.index = 0
        self.wakeup = threading.Condition(self.lock)
        self.ids = weakref.WeakKeyDictionary()  # handle -> stable id
        self.io_ids: dict = {}  # (fd, "r"|"w") -> stable id of the registration
        self.site_n = collections.Counter()
        self._reset_for_test()
        # Timers scheduled before the scheduler was attached used real time.
        offset = self.vt - _real_monotonic()
        if loop._scheduled:
            for h in loop._scheduled:
                h._when += offset
            heapq.heapify(loop._scheduled)

    # -- per test ---------------------------------------------------------
    def _reset_for_test(self) -> None:
        nodeid = _state.STATE.nodeid
        if _loop_counter["nodeid"] != nodeid:
            _loop_counter["nodeid"], _loop_counter["n"] = nodeid, 0
        self.index = _loop_counter["n"]
        _loop_counter["n"] += 1
        self.nodeid = nodeid
        self.rng = Rng(_core.derive_seed(CFG.seed, f"{nodeid or '<session>'}\0asyncio\0{self.index}"))
        self.noisy = CFG.seed != 0
        self.iteration = 0
        self.site_n = collections.Counter()
        _TASK_IDS.clear()
        _TASK_N["n"] = 0

    # -- time -------------------------------------------------------------
    def cost(self) -> float:
        if not self.noisy:
            return CALM_COST
        r = self.rng
        c = -NOISY_COST_MEAN * _log1m(r.random())
        if r.random() < NOISY_HICCUP_P:
            c += r.random() * NOISY_HICCUP_MAX
        return c

    def job_cost(self) -> float:
        if not self.noisy:
            return CALM_JOB
        return -NOISY_JOB_MEAN * _log1m(self.rng.random())

    def jump_to(self, when: float) -> float:
        delta = when - self.vt
        if delta <= 0:
            return 0.0
        self.vt = when
        clk = _clock()
        if clk is not None:
            # time.monotonic() sees the sleep (and the callbacks' virtual cost) too.
            clk.advance(int((self.vt - self.synced_vt) * NS))
            self.synced_vt = self.vt
        return delta

    # -- threads ------------------------------------------------------------
    def post(self, handle) -> None:
        """Buffer a callback posted from another thread."""
        name = threading.current_thread().name
        with self.lock:
            self.pool.append((handle, name))
            self.wakeup.notify_all()

    def job_finished(self) -> None:
        """Done-callback of an executor job (runs in the worker thread)."""
        with self.lock:
            self.wakeup.notify_all()
        try:
            self.loop._write_to_self()  # wake the loop if it blocks on the selector
        except Exception:
            pass

    def _take_pool(self) -> list:
        with self.lock:
            items, self.pool = self.pool, []
        return items

    def _external_possible(self) -> bool:
        """Can something outside this thread still wake the loop up?"""
        if self.jobs:
            return True
        me = threading.current_thread()
        for t in threading.enumerate():
            if t is me or t.name.startswith("detpy-"):
                continue
            if t.name.startswith(("asyncio_", "ThreadPoolExecutor-")) and not self.jobs:
                continue  # idle executor workers
            if t.daemon and t.name.startswith(("pytest_timeout", "Dummy-")):
                continue
            return True
        try:
            return os.waitid(os.P_ALL, 0, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None
        except (ChildProcessError, OSError, AttributeError):
            return False

    # -- the loop iteration ----------------------------------------------------
    def run_once(self) -> None:
        loop = self.loop
        if _state.STATE.nodeid != self.nodeid:
            self._reset_for_test()
        self.iteration += 1
        _purge_cancelled(loop)
        rec = []  # what this iteration delivered, for the fingerprint
        jump = 0.0

        self._settle_jobs(rec)
        io = self._poll(0)
        foreign = self._foreign()
        due_timers, due_jobs = self._due()
        busy = bool(loop._ready) or loop._stopping or due_timers or due_jobs

        if not busy and not io and not foreign:
            # Idle: deliver whatever comes first, deterministically when possible.
            nxt = self._next_deadline()
            if nxt is not None:
                if self._external_possible():
                    io, foreign = self._wait_real(min(max(nxt - self.vt, 0.0), CFG.grace))
                    if io or foreign:
                        rec.append("grace-wakeup")
                if not io and not foreign:
                    jump = self.jump_to(nxt)
                    due_timers, due_jobs = self._due()
            else:
                io, foreign = self._wait_real(None)
                rec.append("blocked-wakeup")

        if _DEBUG:
            import sys
            print(f"[aio] it={self.iteration} ready={len(loop._ready)} io={len(io)} fg={len(foreign)} "
                  f"timers={due_timers} jobs={[j.n for _, _, j in due_jobs]} pend={sorted(j.n for j in self.jobs.values())} "
                  f"done={[(round(d, 6), n) for d, n, _ in self.done_jobs]} vt={self.vt:.6f} rec={rec}", file=sys.stderr)
        # Choose which ready external events are delivered now and in which order.
        io_now, io_later = self._choose(io, busy or due_timers or due_jobs)
        fg_now = self._merge(foreign)
        # Deliver, recording each choice in the shared vocabulary:
        # op sched.*, value "<chosen index>/<set size>:<stable id>".
        for why in rec:  # points whose timing is not controlled (see docs/L1-ASYNCIO.md)
            _state.record_at("other", "asyncio.uncontrolled", f"<loop {self.index}>", why)
        if io_now:
            remaining = sorted(io_now + io_later, key=lambda x: (x[1].fd, x[2]))
            for x in io_now:
                i = remaining.index(x)
                self._choice("sched.io", i, len(remaining), self._io_id(x[1], x[2]))
                remaining.pop(i)
            loop._process_events([(k, m) for (_, k, m) in io_now])
        if fg_now:
            batch = list(fg_now)
            canon = sorted(batch, key=lambda h: self.ids.get(h, ""))
            for h in fg_now:
                i = canon.index(h)
                self._choice("sched.ready", i, len(canon), self.ids.get(h) or "<thread>#?")
                canon.pop(i)
                loop._ready.append(h)
        for k, (_, _, job) in enumerate(due_jobs):
            self._choice("sched.executor", 0, len(due_jobs) - k, job.sid)
            loop._ready.append(_ev.Handle(_deliver_job, (job,), loop, None))
            for ev in job.events:  # events of the worker thread, at a deterministic point
                _state.record_at(ev[0], ev[1], ev[2], ev[3])
        end_time = self.vt + loop._clock_resolution
        fired = []
        while loop._scheduled and loop._scheduled[0]._when < end_time:
            h = heapq.heappop(loop._scheduled)
            h._scheduled = False
            loop._ready.append(h)
            if not h._cancelled:
                fired.append(h)
        for k, h in enumerate(fired):
            self._choice("sched.timer", 0, len(fired) - k, self.ids.get(h) or "<asyncio>:" + _handle_label(h))

        ntodo = len(loop._ready)
        for _ in range(ntodo):
            h = loop._ready.popleft()
            if h._cancelled:
                continue
            if loop._debug:
                try:
                    loop._current_handle = h
                    t0 = self.vt
                    h._run()
                    self.vt += self.cost()
                    if self.vt - t0 >= loop.slow_callback_duration:
                        _be.logger.warning("Executing %s took %.3f seconds", _be._format_handle(h), self.vt - t0)
                finally:
                    loop._current_handle = None
            else:
                h._run()
                self.vt += self.cost()
        h = None

    # -- stable ids and recording -------------------------------------------
    def stable_id(self, depth: int) -> str:
        """Creation site of a callback (first user frame) plus a per-site counter."""
        site = _site_of(depth + 1)
        with self.lock:
            self.site_n[site] += 1
            n = self.site_n[site]
        return f"{site}#{n}"

    def _io_id(self, key, mask) -> str:
        kind = "r" if mask & 1 else "w"
        return self.io_ids.get((key.fd, kind)) or f"<asyncio>:{_io_label(key, mask)}"

    def _choice(self, op: str, chosen: int, size: int, sid: str) -> None:
        site = sid.rsplit("#", 1)[0]
        _state.record_at("sched", op, site, f"{chosen}/{size}:{sid}")

    # -- pieces --------------------------------------------------------------
    def _poll(self, timeout) -> list:
        loop = self.loop
        events = loop._selector.select(timeout)
        ssock = getattr(loop, "_ssock", None)
        sfd = ssock.fileno() if ssock is not None else -1
        out = []
        for key, mask in events:
            if key.fd == sfd:
                loop._read_from_self()  # wake-up byte: drain, nothing to deliver
                continue
            out.append((_io_label(key, mask), key, mask))
        out.sort(key=lambda x: (x[1].fd, x[2]))  # canonical order (fd), then the seed decides
        return out

    def _foreign(self) -> list:
        return self._take_pool()

    def _merge(self, foreign: list) -> list:
        """Order of foreign call_soon_threadsafe callbacks: FIFO per posting thread
        (causal order), threads interleaved by the seed (calm: by thread name)."""
        if not foreign:
            return []
        by_thread: dict = {}
        for h, name in foreign:
            by_thread.setdefault(name, []).append(h)
        queues = [by_thread[k] for k in sorted(by_thread)]
        if not self.noisy or len(queues) == 1:
            return [h for q in queues for h in q]
        out = []
        while queues:
            i = self.rng.below(len(queues))
            out.append(queues[i].pop(0))
            if not queues[i]:
                queues.pop(i)
        return out

    def _settle_jobs(self, rec: list) -> None:
        """Wait for every running executor job and give it a virtual delivery time."""
        if not self.jobs:
            return
        for n in sorted(self.jobs):
            job = self.jobs[n]
            if job.afut.cancelled():
                # asyncio drops the result of a cancelled future: nothing to deliver.
                job.cf.cancel()
                del self.jobs[n]
                continue
            if job.interactive:
                if job.cf.done():
                    self._finish(job)
                continue
            if not job.cf.done() and not self._wait_job(job):
                job.interactive = True
                rec.append(f"executor-unsettled={job.label}")
                continue
            self._finish(job)

    def _wait_job(self, job) -> bool:
        """Block until the job finished; give up if it talks to the loop or takes too long."""
        deadline = _real_monotonic() + CFG.wait
        with self.lock:
            while not job.cf.done():
                if self.pool:
                    return False  # a thread posted to the loop: the job may be waiting for it
                left = deadline - _real_monotonic()
                if left <= 0:
                    return False
                self.wakeup.wait(min(left, 0.05))
        return True

    def _finish(self, job) -> None:
        del self.jobs[job.n]
        if job.interactive:
            job.due = self.vt
        else:
            job.due = max(self.vt, job.submit_vt + job.vsleep + self.job_cost())
        heapq.heappush(self.done_jobs, (job.due, job.n, job))

    def _due(self):
        loop = self.loop
        end = self.vt + loop._clock_resolution
        timers = bool(loop._scheduled) and loop._scheduled[0]._when < end
        jobs = []
        while self.done_jobs and self.done_jobs[0][0] < end:
            jobs.append(heapq.heappop(self.done_jobs))
        return timers, jobs

    def _next_deadline(self):
        loop = self.loop
        cands = []
        if loop._scheduled:
            cands.append(loop._scheduled[0]._when)
        if self.done_jobs:
            cands.append(self.done_jobs[0][0])
        return min(cands) if cands else None

    def _wait_real(self, timeout):
        """Block on the selector for real (foreign I/O or threads), then batch."""
        io = self._poll(timeout)
        foreign = self._foreign()
        if (io or foreign) and CFG.settle > 0 and self._external_possible():
            # Let near-simultaneous wake-ups land, so their order is chosen by the seed.
            # Every new arrival extends the window (up to 10 windows).
            from .clock import real_sleep

            start = _real_monotonic()
            end = start + CFG.settle
            while True:
                now = _real_monotonic()
                if now >= end:
                    break
                real_sleep(min(0.0005, end - now))  # ready fds stay ready: do not spin on select
                more = self._poll(0)
                seen = {(k.fd, m) for (_, k, m) in io}
                new = [x for x in more if (x[1].fd, x[2]) not in seen]
                fresh = self._foreign()
                if new or fresh:
                    io.extend(new)
                    foreign.extend(fresh)
                    end = min(_real_monotonic() + CFG.settle, start + 10 * CFG.settle)
            io.sort(key=lambda x: (x[1].fd, x[2]))
        return io, foreign

    def _choose(self, io: list, busy) -> tuple:
        if not io:
            return [], []
        if not self.noisy:
            return io, []
        now, later = [], []
        for x in io:
            (later if busy and self.rng.random() < NOISY_DEFER_P else now).append(x)
        if not now and not busy:
            now.append(later.pop(self.rng.below(len(later))))
        self.rng.shuffle(now)
        return now, later


_SITE_CACHE: dict = {}


def _classify_file(filename: str):
    """(kind, display path) with string operations only.

    The loop thread must not call os/os.path here: tools such as blockbuster
    (used by anyio's test suite) flag any blocking call made inside a running
    event loop, and realpath/abspath are such calls.
    """
    hit = _SITE_CACHE.get(filename)
    if hit is not None:
        return hit
    kind, shown = "user", filename
    if filename.startswith("<"):
        kind = "stdlib" if filename.startswith("<frozen") else "user"
    elif any(filename.startswith(p) for p in _PREFIXES["infra"]):
        kind = "infra"
    else:
        for d in _PREFIXES["site"]:
            if filename.startswith(d + "/"):
                shown = "<site>/" + filename[len(d) + 1:]
                break
        else:
            if any(filename.startswith(d + "/") for d in _PREFIXES["stdlib"]):
                kind = "stdlib"
            elif _PREFIXES["root"] and filename.startswith(_PREFIXES["root"] + "/"):
                shown = filename[len(_PREFIXES["root"]) + 1:]
    res = (kind, shown.replace("\\", "/"))
    _SITE_CACHE[filename] = res
    return res


_PREFIXES: dict = {"infra": (), "site": (), "stdlib": (), "root": None}


def refresh_prefixes(rootdir) -> None:
    """Computed outside the loop (filesystem calls allowed here)."""
    std, site, infra = _sites._dirs()
    extra = set()
    for d in list(std) + list(site):
        extra.add(os.path.abspath(d))
    _PREFIXES["stdlib"] = tuple(sorted({*std, *(os.path.abspath(d) for d in std)}, key=len, reverse=True))
    _PREFIXES["site"] = tuple(sorted({*site, *(os.path.abspath(d) for d in site)}, key=len, reverse=True))
    _PREFIXES["infra"] = tuple(infra) + (os.path.dirname(os.path.abspath(__file__)),)
    _PREFIXES["root"] = rootdir.rstrip("/") if rootdir else None
    _SITE_CACHE.clear()


def _site_of(depth: int) -> str:
    import sys

    try:
        f = sys._getframe(depth + 1)
    except ValueError:
        return "<asyncio>"
    while f is not None:
        kind, shown = _classify_file(f.f_code.co_filename)
        if kind == "user":
            return f"{shown}:{f.f_lineno}"
        if kind == "infra":
            return "<asyncio>"
        f = f.f_back
    return "<asyncio>"


def _log1m(u: float) -> float:
    import math

    return math.log1p(-u) if u < 1.0 else -40.0


def _purge_cancelled(loop) -> None:
    sched = loop._scheduled
    n = len(sched)
    if n > _be._MIN_SCHEDULED_TIMER_HANDLES and loop._timer_cancelled_count / n > _be._MIN_CANCELLED_TIMER_HANDLES_FRACTION:
        keep = []
        for h in sched:
            if h._cancelled:
                h._scheduled = False
            else:
                keep.append(h)
        heapq.heapify(keep)
        loop._scheduled = keep
        loop._timer_cancelled_count = 0
    else:
        while sched and sched[0]._cancelled:
            loop._timer_cancelled_count -= 1
            h = heapq.heappop(sched)
            h._scheduled = False


# ---------------------------------------------------------------------------
# Patched BaseEventLoop methods
def _sched(loop):
    return loop.__dict__.get("_detpy_sched")


def _attach(loop) -> None:
    if not CFG.enabled or "_detpy_sched" in loop.__dict__:
        return
    st = _state.STATE
    if st.nodeid is None or threading.get_ident() != st.test_thread:
        return  # loops of other threads and outside tests keep real scheduling
    if not hasattr(loop, "_selector") or not isinstance(loop, _be.BaseEventLoop):
        return
    loop.__dict__["_detpy_sched"] = Scheduler(loop)


def _run_once(self):
    s = self.__dict__.get("_detpy_sched")
    if s is None:
        return _orig["_run_once"](self)
    return s.run_once()


def _run_forever(self):
    _attach(self)
    return _orig["run_forever"](self)


def _time(self):
    s = self.__dict__.get("_detpy_sched")
    if s is None:
        return _real_monotonic()
    return s.vt


def _call_soon_threadsafe(self, callback, *args, context=None):
    s = self.__dict__.get("_detpy_sched")
    if s is None or threading.get_ident() == s.thread_id:
        return _orig["call_soon_threadsafe"](self, callback, *args, context=context)
    self._check_closed()
    handle = _ev.Handle(callback, args, self, context)
    if handle._source_traceback:
        del handle._source_traceback[-1]
    s.ids[handle] = s.stable_id(1)
    s.post(handle)
    self._write_to_self()
    return handle


def _deliver_job(job) -> None:
    if not job.afut.done():
        _af._copy_future_state(job.cf, job.afut)


class _JobRunner:
    """Runs the job in the worker thread and charges its virtual sleeps."""

    __slots__ = ("job", "func")

    def __init__(self, job, func) -> None:
        self.job, self.func = job, func

    def __call__(self, *args):
        prev = getattr(_tl, "job", None)
        _tl.job = self.job
        prev_buf = _state.set_event_buffer(self.job.events)
        try:
            return self.func(*args)
        finally:
            _tl.job = prev
            _state.set_event_buffer(prev_buf)


def _run_in_executor(self, executor, func, *args):
    """Like BaseEventLoop.run_in_executor, but the scheduler delivers the result.

    asyncio chains the job's concurrent future to the asyncio future with
    call_soon_threadsafe, i.e. at whatever moment the worker thread finishes.
    Here the scheduler waits for the job and copies its state at a virtual time
    that depends only on the job's virtual sleeps and the seed.
    """
    s = self.__dict__.get("_detpy_sched")
    if s is None or threading.get_ident() != s.thread_id:
        return _orig["run_in_executor"](self, executor, func, *args)
    self._check_closed()
    if self._debug:
        self._check_callback(func, "run_in_executor")
    if executor is None:
        executor = self._default_executor
        if hasattr(self, "_check_default_executor"):
            self._check_default_executor()
        if executor is None:
            executor = concurrent.futures.ThreadPoolExecutor(thread_name_prefix="asyncio")
            self._default_executor = executor
    s.job_n += 1
    job = Job(s.job_n, f"{_fn_label(func)}#{s.job_n}", s.vt)
    job.sid = s.stable_id(1)
    threaded = isinstance(executor, concurrent.futures.ThreadPoolExecutor)
    job.cf = executor.submit(_JobRunner(job, func) if threaded else func, *args)
    job.afut = self.create_future()
    s.jobs[job.n] = job
    job.cf.add_done_callback(lambda _cf: s.job_finished())
    return job.afut


async def _shutdown_default_executor(self, *args, **kwargs):
    """Join the default executor in the loop thread.

    asyncio joins it in a helper thread and waits for its call_soon_threadsafe
    under a 300 s timeout: a race between a foreign thread and a timer, decided
    by real time. Jobs of a scheduled loop were already delivered, so joining
    here is short and deterministic.
    """
    if self.__dict__.get("_detpy_sched") is None:
        return await _orig["shutdown_default_executor"](self, *args, **kwargs)
    self._executor_shutdown_called = True
    executor = self._default_executor
    if executor is not None:
        executor.shutdown(wait=True)


def _call_at(self, when, callback, *args, context=None):
    timer = _orig["call_at"](self, when, callback, *args, context=context)
    s = self.__dict__.get("_detpy_sched")
    if s is not None:
        s.ids[timer] = s.stable_id(1)
    return timer


def _io_patch(name, kind):
    def method(self, fd, callback, *args):
        res = _orig[name](self, fd, callback, *args)
        s = self.__dict__.get("_detpy_sched")
        if s is not None:
            try:
                fileno = fd if isinstance(fd, int) else fd.fileno()
            except Exception:
                return res
            s.io_ids[(fileno, kind)] = s.stable_id(1)
        return res

    method.__name__ = name
    return method


def install(patcher, seed: int, grace: float, wait: float, settle: float, rootdir=None) -> None:
    refresh_prefixes(rootdir)
    CFG.enabled = True
    CFG.seed = seed
    CFG.grace, CFG.wait, CFG.settle = grace, wait, settle
    B = _be.BaseEventLoop
    for name, fn in (("_run_once", _run_once), ("run_forever", _run_forever), ("time", _time),
                     ("call_soon_threadsafe", _call_soon_threadsafe), ("run_in_executor", _run_in_executor),
                     ("shutdown_default_executor", _shutdown_default_executor)):
        _orig[name] = B.__dict__[name] if name != "time" else (lambda self: _real_monotonic())
        patcher.set(B, name, fn)
    _orig["call_at"] = B.__dict__["call_at"]
    patcher.set(B, "call_at", _call_at)
    S = _se.BaseSelectorEventLoop
    for name, kind in (("_add_reader", "r"), ("_add_writer", "w")):
        _orig[name] = S.__dict__[name]
        patcher.set(S, name, _io_patch(name, kind))
    from . import clock

    clock._on_sleep = on_sleep


def uninstall() -> None:
    CFG.enabled = False
    from . import clock

    clock._on_sleep = None
