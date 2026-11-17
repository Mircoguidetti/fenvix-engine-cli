"""Deterministic thread scheduling (Level 1 prototype, ``--det-threads``).

Design: ``docs/L1-THREADS.md``. In short:

* every thread started with ``threading.Thread`` while the scheduler is active is
  *managed*; exactly one managed thread runs Python code at a time (it holds the
  *baton*);
* the running thread changes only at controlled points: lock / condition /
  event / semaphore / queue operations (all built on :class:`SchedLock`),
  ``time.sleep``, thread start / join / exit, and blocking socket / selector I/O;
* waits with a timeout and sleeps are timers on the Level 0 virtual clock: when
  no thread can run, I/O waiters are polled and the clock jumps to the earliest
  timer;
* every choice among two or more runnable threads comes from a seed (seed 0 =
  calm: run until blocked, then FIFO) and is recorded as a ``sched.thread``
  event; a deadlock raises :class:`DeadlockError` in every blocked thread;
* a watchdog thread escapes a holder that blocks in uncontrolled C code (the
  escape is recorded as ``other``/``threads.uncontrolled``).
"""

from __future__ import annotations

import _thread
import heapq
import os
import select as _select
import sys
import threading

from . import _sites, _state

_real_allocate = _thread.allocate_lock
# The scheduler's own blocking waits call the C method captured at import: tools
# that patch lock.acquire on the C type (blockbuster flags blocking calls inside an
# event loop) must not see the baton hand-over as a blocking call of the test.
_lock_acquire = _thread.LockType.acquire
_real_start_new_thread = _thread.start_new_thread
_real_join = threading.Thread.join
_real_is_alive = threading.Thread.is_alive
_get_ident = _thread.get_ident
_real_poll = getattr(_select, "poll", None)
_real_select = _select.select
_M64 = (1 << 64) - 1

RUNNABLE, BLOCKED, IOWAIT, EXTERNAL, FINISHED = "runnable", "blocked", "iowait", "external", "finished"


class DeadlockError(RuntimeError):
    """Every managed thread is blocked and nothing can wake any of them."""


class Rng:
    """SplitMix64 (same generator as detpy.aio), independent of ``random``."""

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


class Config:
    enabled = False
    seed = 0
    grace = 1.0  # real s an idle scheduler waits for external work before a timer fires
    deadlock = 5.0  # real s with only I/O waiters left before a deadlock is declared
    stuck = 60.0  # real s without progress while waiting on work outside the scheduler, then DeadlockError
    spin_escape = 1.0  # real s a holder may run without a controlled point while another thread is runnable
    spin_time = 10.0  # same, while the others only wait for time or I/O (a long computation is not a spin)
    escape_ms = 50  # real ms without progress (holder sleeping in C) before an escape
    preempt = 0  # mean user-code lines between preemptions (0 = off; exploration only)
    starve_ops = 2000  # controlled ops a holder may run while others wait, then it yields
    spin_min_ns = 1_000  # virtual time charged to a failed poll (doubles while the holder spins)
    spin_max_ns = 1_000_000


CFG = Config()


class T:
    """A managed thread."""

    __slots__ = ("idx", "key", "ident", "native", "name", "sid", "gate", "handed", "state", "wait",
                 "wait_obj", "deadline", "tseq", "timed_out", "exc", "pred", "real_deadline", "thread",
                 "budget")

    def __init__(self, idx: int, sid: str, name: str) -> None:
        self.idx = idx
        self.key = ("detpy-t", idx)
        self.ident = None
        self.native = None
        self.name = name
        self.sid = sid  # stable id: creation site + per-site counter, "main" for the test thread
        self.gate = _real_allocate()
        _lock_acquire(self.gate)
        self.handed = False
        self.state = RUNNABLE
        self.wait = ""  # what it waits for (deadlock message)
        self.wait_obj = None
        self.deadline = None
        self.tseq = 0
        self.timed_out = False
        self.exc = None
        self.pred = None
        self.real_deadline = None
        self.thread = None
        self.budget = 0


class _SchedMutex:
    """The scheduler's own lock. The calling thread is marked from before the
    acquire until the release: line preemption must not run while it holds the
    lock (code that wraps lock.acquire in Python, e.g. blockbuster, can be traced
    project code and would otherwise preempt inside the scheduler)."""

    __slots__ = ("_lock",)

    def __init__(self) -> None:
        self._lock = _real_allocate()

    def acquire(self, blocking=True, timeout=-1):
        if getattr(_tls, "holds_mu", False):
            # An asynchronous exception (a signal handler: pytest-timeout,
            # KeyboardInterrupt) left this thread's earlier hold unreleased: it
            # still owns the lock. Continue instead of deadlocking on itself.
            return True
        _tls.in_mu = True
        try:
            got = _lock_acquire(self._lock, blocking, timeout)
        except BaseException:
            _tls.in_mu = False
            raise
        if got:
            _tls.holds_mu = True
        else:
            _tls.in_mu = False
        return got

    def release(self):
        _tls.holds_mu = False
        self._lock.release()
        _tls.in_mu = False

    def locked(self):
        return self._lock.locked()


class _Sched:
    def __init__(self) -> None:
        self.mu = _SchedMutex()
        self.active = False
        self.threads: list = []  # live managed threads (finished ones are dropped)
        self.nthreads = 0
        # idents of the live managed threads (deadlock check). An ident is dropped when
        # its thread exits: the OS reuses thread ids, and a later unmanaged thread
        # (pytest-httpbin's server) must not be mistaken for a managed one.
        self.known_idents: set = set()
        self.current = None
        self.runq: list = []  # runnable threads, FIFO by the moment they became runnable
        self.timers: list = []  # heap of (deadline, seq, T, tseq)
        self.seq = 0
        self.rng = Rng(0)
        self.p_switch = 0.0
        self.ops = 0  # controlled operations (watchdog progress counter)
        self.since_switch = 0
        self.vclock = 0  # used when the Level 0 clock is off
        self.idle_since = None
        self.site_counts: dict = {}
        self.stats = {"decisions": 0, "switches": 0, "escapes": 0, "deadlocks": 0, "timer_jumps": 0,
                      "managed": 0, "spin_yields": 0, "spin_ticks": 0, "interrupted": 0}
        self.spin_ns = 0  # virtual time the next failed poll of a spinning holder charges
        self.watchdog_on = False
        self.watchdog_beats = 0  # rounds of the watchdog (tests check it still runs)
        self.exiting: list = []  # Thread objects finished for the scheduler, not yet ended


S = _Sched()
_tls = threading.local()


# ---------------------------------------------------------------------------
# Clock helpers
_CLOCKMOD: list = []


def _clockmod():
    if not _CLOCKMOD:
        from . import clock

        _CLOCKMOD.append(clock)
    return _CLOCKMOD[0]


def _clock():
    return _clockmod().CLOCK


def _ns(seconds) -> int:
    """A timeout in seconds as virtual nanoseconds, rounded up: a positive
    timeout never becomes 0 (a loop such as Condition.wait_for that recomputes
    "time left" from a float clock would otherwise spin on a 0 ns wait)."""
    ns = seconds * 1e9
    n = int(ns)
    return n + 1 if n < ns else n


def _now() -> int:
    c = _clock()
    return c.elapsed if c is not None else S.vclock


def _advance_to(t: int) -> None:
    c = _clock()
    if c is not None:
        if t > c.elapsed:
            c.advance(t - c.elapsed)
    elif t > S.vclock:
        S.vclock = t


def _real_monotonic() -> float:
    return _clockmod().real_monotonic()


def _real_sleep(s: float) -> None:
    _clockmod().real_sleep(s)


# ---------------------------------------------------------------------------
# Identity
def _me():
    """The managed record of the calling thread, or None (unmanaged / inactive)."""
    if not S.active:
        return None
    return getattr(_tls, "t", None)


def managed() -> bool:
    return _me() is not None


_DETPY_DIR = os.path.dirname(os.path.abspath(__file__))


def _site() -> str:
    """Site of the first frame outside detpy: user code if any, else the first library frame."""
    try:
        f = sys._getframe(2)
    except ValueError:  # pragma: no cover
        return "<unknown>"
    first = None
    while f is not None:
        fn = f.f_code.co_filename
        if not fn.startswith(_DETPY_DIR):
            kind, norm = _sites._classify(fn)
            if kind == _sites._USER:
                return f"{norm}:{f.f_lineno}"
            if first is None and kind == _sites._STDLIB:
                first = f"{norm}:{f.f_lineno}"
        f = f.f_back
    return first or "<infra>"


def _record(op: str, value: str, source: str = "sched") -> None:
    st = _state.STATE
    rec = st.recorder
    if rec is None or st.nodeid is None:
        return
    key = getattr(_state._tls, "tkey", None) or _get_ident()
    threads = st.threads
    t = threads.get(key)
    if t is None:
        t = threads[key] = len(threads)
    rec.record(source, op, _site(), value, t)


_DEBUG = os.environ.get("DETPY_THREADS_DEBUG")


def _dbg(msg: str) -> None:
    if _DEBUG:
        line = f"[threads] {msg}\n".encode()
        if _DEBUG == "1":
            os.write(2, line)
        else:
            with open(f"{_DEBUG}.{os.getpid()}", "ab") as f:
                f.write(line)


def _record_uncontrolled(why: str) -> None:
    _dbg("uncontrolled: " + why)
    st = _state.STATE
    if st.recorder is not None and st.nodeid is not None:
        st.recorder.record("other", "threads.uncontrolled", "<threads>", why, 0)


# ---------------------------------------------------------------------------
# Core: choosing and handing over the baton. Every function named _locked_*
# runs with S.mu held.
def _locked_make_runnable(t) -> None:
    if t.state != RUNNABLE:
        t.state = RUNNABLE
        S.runq.append(t)


def _locked_wake_waiters(obj) -> None:
    for t in S.threads:
        if t.wait_obj is obj and t.state == BLOCKED:
            t.wait_obj = None
            _locked_make_runnable(t)


def _locked_poll_io() -> None:
    now = None
    for t in S.threads:
        if t.state == IOWAIT:
            ready = False
            try:
                ready = t.pred()
            except Exception:  # a closed fd: let the real call raise
                ready = True
            if not ready and t.real_deadline is not None:
                if now is None:
                    now = _real_monotonic()
                if now >= t.real_deadline:
                    t.timed_out = True
                    ready = True
            if ready:
                t.pred = None
                _locked_make_runnable(t)


def _locked_live_timer():
    """The earliest live timer as (deadline, T), dropping stale heads, or None."""
    while S.timers:
        dl, _, t, tseq = S.timers[0]
        if t.tseq != tseq or t.state not in (BLOCKED, IOWAIT) or t.deadline is None:
            heapq.heappop(S.timers)
            continue
        return dl, t
    return None


def _locked_expire_timers() -> bool:
    """Wake the threads whose timers are due at the current virtual time (no jump)."""
    now = _now()
    woke = False
    while S.timers and S.timers[0][0] <= now:
        _, _, t, tseq = heapq.heappop(S.timers)
        if t.tseq == tseq and t.state in (BLOCKED, IOWAIT) and t.deadline is not None:
            t.timed_out = True
            t.wait_obj = None
            t.pred = None
            _locked_make_runnable(t)
            woke = True
    return woke


def _locked_fire_timer() -> bool:
    """Jump the virtual clock to the earliest live timer and wake its threads."""
    while S.timers:
        dl, _, t, tseq = S.timers[0]
        if t.tseq != tseq or t.state not in (BLOCKED, IOWAIT) or t.deadline is None:
            heapq.heappop(S.timers)
            continue
        _advance_to(dl)
        S.stats["timer_jumps"] += 1
        while S.timers:
            dl2, _, t2, tseq2 = S.timers[0]
            if dl2 > dl:
                break
            heapq.heappop(S.timers)
            if t2.tseq == tseq2 and t2.state in (BLOCKED, IOWAIT) and t2.deadline is not None:
                t2.timed_out = True
                t2.wait_obj = None
                t2.pred = None
                _locked_make_runnable(t2)
        return True
    return False


def _unmanaged_threads() -> list:
    managed_idents = S.known_idents
    try:
        ts = threading.enumerate()
    except Exception:  # pragma: no cover
        return []
    return [th for th in ts if th.ident not in managed_idents and not th.name.startswith("detpy-")
            and getattr(th, "_detpy_t", None) is None]  # a managed thread still ending


def _unmanaged_alive() -> bool:
    return bool(_unmanaged_threads())


def _outside_lines() -> list:
    """What outside the scheduler could still wake a blocked managed thread."""
    out = [f"thread {t.idx} ({t.name}, started at {t.sid}) runs outside the scheduler (escaped)"
           for t in S.threads if t.state == EXTERNAL]
    for th in _unmanaged_threads():
        out.append(f"unmanaged thread {th.name!r}{' (daemon)' if th.daemon else ''}")
    from . import clock

    ext = getattr(clock, "_EXTERNAL", None)
    if ext is not None and ext.get("started"):
        out.append("a child process started by this test")
    return out


def _has(state) -> bool:
    return any(t.state == state for t in S.threads)


def _outside_activity() -> bool:
    """Something outside the managed threads may still make progress: an escaped or
    external thread, a real-time I/O wait, a child process, or an unmanaged thread."""
    for t in S.threads:
        if t.state == EXTERNAL or (t.state == IOWAIT and t.real_deadline is not None):
            return True
    from . import clock

    ext = getattr(clock, "_EXTERNAL", None)
    if ext is not None and ext.get("started"):
        return True
    return _unmanaged_alive()


def _locked_raise_deadlock(stuck_s: float = 0.0) -> None:
    blocked = [t for t in S.threads if t.state in (BLOCKED, IOWAIT)]
    lines = [f"thread {t.idx} ({t.name}, started at {t.sid}) waits for {t.wait or t.state}" for t in blocked]
    outside = _outside_lines()
    if stuck_s:
        head = (f"detpy --det-threads: deadlock: no progress for {stuck_s:g} s real time: every managed thread "
                f"is blocked and nothing outside the scheduler woke any of them (--det-threads-stuck)")
    else:
        head = "detpy --det-threads: deadlock: every managed thread is blocked"
    msg = head + "\n  " + "\n  ".join(lines)
    if outside:
        msg += "\n  outside the scheduler: " + "; ".join(outside)
    S.stats["deadlocks"] += 1
    for t in blocked:
        t.exc = DeadlockError(msg)
        t.wait_obj = None
        t.pred = None
        t.deadline = None
        _locked_make_runnable(t)
    _record_uncontrolled("deadlock")


def _locked_candidates(me, inline: bool):
    """Runnable threads, after polling I/O and (inline only) firing timers or
    detecting a deadlock. Returns [] when the decision is left to the watchdog."""
    _locked_poll_io()
    S.runq = [t for t in S.runq if t.state == RUNNABLE]
    if S.runq or not inline:
        return S.runq
    if _outside_activity() or _has(IOWAIT):
        # Idle: the watchdog waits for the outside world (or for the kernel to
        # deliver data already sent: Nagle, delayed ACKs), then fires timers.
        return S.runq
    # Nothing outside the managed threads can change anything: time jumps, or
    # nobody can ever be woken.
    if S.timers and _locked_fire_timer():
        S.runq = [t for t in S.runq if t.state == RUNNABLE]
        if S.runq:
            return S.runq
    _locked_raise_deadlock()
    return S.runq


def _locked_choose(me, cands):
    """Pick the next thread among the candidates; record real choices."""
    n = len(cands)
    if n == 1:
        return cands[0]
    S.stats["decisions"] += 1
    if CFG.seed == 0:
        # Calm: the running thread continues if it can, otherwise FIFO.
        i = cands.index(me) if me is not None and me in cands else 0
    else:
        i = S.rng.below(n)
    chosen = cands[i]
    if _DEBUG:
        _dbg(f"choose {i} of {[t.idx for t in cands]} rng={S.rng.s} by {getattr(me, 'idx', None)} "
             f"tid={_get_ident() == getattr(S.current, 'ident', None)}")
    order = sorted(cands, key=lambda t: t.idx)
    _record("sched.thread", f"{order.index(chosen)}/{n}:{chosen.sid}")
    return chosen


def _locked_hand(me, nxt) -> None:
    """Give the baton to ``nxt`` (None: idle, the watchdog takes over)."""
    if nxt is not None:
        S.runq.remove(nxt)
    S.current = nxt
    if nxt is not me:
        S.since_switch = 0
        S.spin_ns = 0
        S.stats["switches"] += 1
    if _DEBUG:
        _dbg(f"hand {getattr(me, 'idx', None)} -> {getattr(nxt, 'idx', None)} at {_site()} "
             f"({getattr(me, 'state', None)} {getattr(me, 'wait', '')}) runq={[t.idx for t in S.runq]} "
             f"states={[(t.idx, t.state) for t in S.threads]}")
    if nxt is None:
        S.idle_since = _real_monotonic()
        return
    S.idle_since = None
    if nxt is not me and not nxt.handed:
        nxt.handed = True
        nxt.gate.release()


def _wait_gate(me) -> None:
    """Wait (no lock held) until the baton is handed to ``me``."""
    try:
        _lock_acquire(me.gate)
    except BaseException:
        _interrupted(me)
        raise
    me.handed = False
    if S.exiting:
        _reap()


def _interrupted(me) -> None:
    """An asynchronous exception (a signal handler: pytest-timeout's signal method,
    KeyboardInterrupt) ended ``me``'s wait for the baton. The exception must
    propagate, so ``me`` keeps running: as the holder if the baton reached it
    meanwhile, otherwise outside the scheduler until its next controlled point."""
    S.mu.acquire()
    try:
        S.stats["interrupted"] += 1
        if me.handed:  # the gate was opened for us: consume it, we hold the baton
            _lock_acquire(me.gate, False)
            me.handed = False
        me.tseq += 1  # drop its timer
        me.deadline = None
        me.wait_obj = None
        me.pred = None
        if S.current is me:
            me.state = RUNNABLE
            return
        if me in S.runq:
            S.runq.remove(me)
        me.state = EXTERNAL
        _record_uncontrolled(f"thread {me.idx} ({me.name}) interrupted while waiting for the baton")
    finally:
        S.mu.release()


def _reap() -> None:
    """Wait until threads that finished for the scheduler have really ended.

    A finished thread still runs interpreter teardown (its frames, thread state,
    ``threading._active`` entry) after handing the baton on; letting it do so
    while the next thread runs makes memory reuse, and so object addresses, id()
    order and garbage collection timing, depend on the OS. The baton holder waits
    for it first (short; the outcome does not depend on timing)."""
    while S.exiting:
        th = S.exiting.pop(0)
        try:
            _real_join(th, 2.0)
            if _real_is_alive(th):
                _record_uncontrolled(f"thread {th.name} still ending after 2 s")
        except Exception:  # pragma: no cover
            pass


def _switch(me) -> None:
    """``me`` holds S.mu and the baton, and has set its state (RUNNABLE to yield,
    BLOCKED/IOWAIT to block). Hand the baton over and wait until it comes back."""
    yielding = me.state == RUNNABLE
    if yielding and me not in S.runq:
        S.runq.append(me)
    cands = _locked_candidates(me, inline=True)
    # Calm: a yielding thread continues; a thread that blocked (even if a timer
    # jump woke it at once) lets the longest-waiting runnable thread go first.
    nxt = _locked_choose(me if yielding else None, cands) if cands else None
    if nxt is me:
        S.runq.remove(me)
        S.current = me
        S.mu.release()
        return
    _locked_hand(me, nxt)
    S.mu.release()
    if S.active:
        _wait_gate(me)


_HEADROOM = 60  # frames kept free below the recursion limit for the scheduler itself


def _near_recursion_limit() -> bool:
    try:
        sys._getframe(150)  # cheap common case: a shallow stack
        sys._getframe(sys.getrecursionlimit() - _HEADROOM)
    except ValueError:
        return False
    return True


def _check_depth() -> None:
    """A RecursionError inside the scheduler (while it holds its lock or has changed a
    thread's state) would wedge every thread: raise it before entering instead."""
    if _near_recursion_limit():
        raise RecursionError("maximum recursion depth exceeded")


def _enter(me) -> None:
    """Start of every controlled operation of a managed thread: rejoin if escaped."""
    S.ops += 1
    if me.state == EXTERNAL:
        _rejoin(me)


def _rejoin(me) -> None:
    S.mu.acquire()
    if not S.active:
        S.mu.release()
        return
    if S.current is None:
        me.state = RUNNABLE
        S.current = me
        S.idle_since = None
        S.mu.release()
        if S.exiting:
            _reap()
        return
    _locked_make_runnable(me)
    S.mu.release()
    _wait_gate(me)


def _point(me) -> None:
    """A controlled point where the running thread may be switched out (exploration,
    or a holder that ran too long while others wait)."""
    if S.current is not me:
        return  # not the baton holder (exiting, escaped): never consume a seeded choice
    S.since_switch += 1
    if not S.runq:
        if not (CFG.seed and S.since_switch & 31 == 0 and _has(IOWAIT)):
            return
    _check_depth()
    if CFG.seed:
        if _DEBUG:
            _dbg(f"point {me.idx} at {_site()}")
        if S.rng.random() >= S.p_switch and S.since_switch < CFG.starve_ops:
            return
    elif S.since_switch < CFG.starve_ops:
        return
    S.mu.acquire()
    if not S.active or S.current is not me:
        S.mu.release()
        return
    me.state = RUNNABLE
    if CFG.seed == 0 or S.since_switch >= CFG.starve_ops:
        # Yield to the others: put ``me`` last.
        S.runq.append(me)
        cands = _locked_candidates(me, inline=True)
        nxt = cands[0] if cands else me
        if len(cands) > 1:
            S.stats["decisions"] += 1
            order = sorted(cands, key=lambda t: t.idx)
            _record("sched.thread", f"{order.index(nxt)}/{len(cands)}:{nxt.sid}")
        if nxt is me:
            S.runq.remove(me)
            S.mu.release()
            return
        _locked_hand(me, nxt)
        S.mu.release()
        _wait_gate(me)
    else:
        _switch(me)
    _after_wake(me)


def _after_wake(me) -> None:
    exc = me.exc
    if exc is not None:
        me.exc = None
        raise exc


def _block(me, state: str, what: str, obj=None, timeout_ns=None, pred=None, real_timeout=None) -> bool:
    """Block ``me`` until woken; returns False if it timed out. S.mu is held on entry
    and released on return."""
    me.state = state
    me.wait = what
    me.wait_obj = obj
    me.pred = pred
    me.timed_out = False
    me.tseq += 1
    me.real_deadline = None if real_timeout is None else _real_monotonic() + real_timeout
    if timeout_ns is not None:
        me.deadline = _now() + max(0, timeout_ns)
        S.seq += 1
        heapq.heappush(S.timers, (me.deadline, S.seq, me, me.tseq))
    else:
        me.deadline = None
    _switch(me)
    me.deadline = None
    me.wait = ""
    _after_wake(me)
    return not me.timed_out


# ---------------------------------------------------------------------------
# Public helpers for the other controls
def sleep(ns: int) -> bool:
    """Virtual sleep of a managed thread. Returns False if the caller is not managed."""
    me = _me()
    if me is None:
        return False
    _enter(me)
    _check_depth()
    S.mu.acquire()
    if not S.active:
        S.mu.release()
        return False
    if ns <= 0:
        S.mu.release()
        _yield(me, spin=True)
        return True
    _block(me, BLOCKED, f"sleep({ns / 1e9:g}s)", timeout_ns=ns)
    return True


def _yield(me, spin: bool = False) -> None:
    S.mu.acquire()
    if not S.active or S.current is not me:
        S.mu.release()
        return
    me.state = RUNNABLE
    S.runq.append(me)
    cands = _locked_candidates(me, inline=True)
    if spin:
        if len(cands) == 1 and _locked_live_timer() is not None:
            # A spinning holder and nobody else can run: in a real run time would
            # pass while it spins. Charge this poll some virtual time (doubling
            # while the spin lasts) and wake the threads whose timers are due.
            S.spin_ns = min(max(CFG.spin_min_ns, 2 * S.spin_ns), CFG.spin_max_ns)
            _advance_to(_now() + S.spin_ns)
            S.stats["spin_ticks"] += 1
            if _locked_expire_timers():
                S.runq.remove(me)
                S.runq.append(me)  # the woken threads go first
                cands = S.runq = [t for t in S.runq if t.state == RUNNABLE]
        if len(cands) > 1:
            S.stats["spin_yields"] += 1
    # A yield gives the others a turn: the yielding thread goes last.
    if CFG.seed:
        nxt = cands[S.rng.below(len(cands))] if len(cands) > 1 else cands[0]
    else:
        nxt = cands[0]
    if len(cands) > 1:
        S.stats["decisions"] += 1
        order = sorted(cands, key=lambda t: t.idx)
        _record("sched.thread", f"{order.index(nxt)}/{len(cands)}:{nxt.sid}")
    if nxt is me:
        S.runq.remove(me)
        S.mu.release()
        return
    _locked_hand(me, nxt)
    S.mu.release()
    _wait_gate(me)
    _after_wake(me)


def poll_miss(me=None) -> None:
    """A zero-timeout poll of a managed thread found nothing: ``select(0)``, a failed
    non-blocking acquire, ``Event.is_set()`` false, ``Queue.get_nowait()`` empty.
    A loop of such polls waits for another thread or for time to pass (anyio:
    ``while not started.is_set(): await checkpoint()``), so the runnable threads go
    first (calm: the poller goes last) and, if none can run, the poll is charged
    virtual time so that due timers fire. Nothing happens when no other managed
    thread is waiting for anything."""
    if me is None:
        me = _me()
        if me is None:
            return
    if S.current is not me or not (S.runq or S.timers or _has(IOWAIT)):
        return
    _check_depth()
    _yield(me, spin=True)


def io_wait(pred, timeout=None, what="I/O", real_time=False) -> bool:
    """Wait until ``pred()`` is true (polled at controlled points) or ``timeout``
    seconds pass (virtual, or real if ``real_time``). Returns False on timeout.
    Callers check :func:`managed` first."""
    me = _me()
    if me is None:
        raise RuntimeError("io_wait outside a managed thread")
    _enter(me)
    try:
        if pred():
            _point(me)
            return True
    except Exception:
        return True
    if timeout is not None and timeout <= 0:
        return False
    _check_depth()
    S.mu.acquire()
    if not S.active:
        S.mu.release()
        return pred()
    if real_time:
        return _block(me, IOWAIT, what, pred=pred, real_timeout=timeout)
    return _block(me, IOWAIT, what, pred=pred, timeout_ns=None if timeout is None else _ns(timeout))


class external:
    """Context manager: the calling managed thread leaves the scheduler (the code
    inside may block in C or wait for something outside the process); it rejoins
    when the block ends. Rejoining while another thread runs is recorded as
    uncontrolled."""

    __slots__ = ("me",)

    def __enter__(self):
        me = self.me = _me()
        if me is None:
            return self
        _enter(me)
        S.mu.acquire()
        if not S.active or S.current is not me:
            S.mu.release()
            self.me = None
            return self
        me.state = EXTERNAL
        cands = _locked_candidates(me, inline=False)
        nxt = _locked_choose(None, cands) if cands else None
        _locked_hand(me, nxt)
        S.mu.release()
        return self

    def __exit__(self, *exc):
        me = self.me
        if me is None or not S.active:
            return False
        S.mu.acquire()
        if S.current is None:
            me.state = RUNNABLE
            S.current = me
            S.idle_since = None
            S.mu.release()
            return False
        _record_uncontrolled(f"rejoin of thread {me.idx} while thread {S.current.idx} runs")
        _locked_make_runnable(me)
        S.mu.release()
        _wait_gate(me)
        return False


# ---------------------------------------------------------------------------
# The scheduler-aware lock
class SchedLock:
    """``threading.Lock`` under --det-threads: a real lock plus scheduling.

    Managed threads never block on the real lock: they wait in the scheduler and
    retry, with virtual timeouts. Unmanaged threads (and everything once the
    scheduler is off) use the real lock directly.
    """

    __slots__ = ("_real", "_nwait", "__weakref__")

    def __init__(self) -> None:
        self._real = _real_allocate()
        self._nwait = 0

    def acquire(self, blocking=True, timeout=-1):
        me = _me()
        if me is None:
            got = self._real.acquire(blocking, timeout)
            if not got and blocking and timeout is not None and timeout > 0:
                c = _clock()
                if c is not None:
                    c.advance(int(timeout * 1e9))
            return got
        _enter(me)
        _point(me)
        if self._real.acquire(False):
            return True
        if not blocking or timeout == 0:
            poll_miss(me)  # a non-blocking acquire in a loop is a spin
            return False
        _check_depth()
        if timeout is not None and timeout >= 0:
            deadline = _now() + _ns(timeout)
        else:
            deadline = None
        while True:
            S.mu.acquire()
            if not S.active:
                S.mu.release()
                rem = -1 if deadline is None else max(0.0, (deadline - _now()) / 1e9)
                return self._real.acquire(True, rem)
            if self._real.acquire(False):  # released meanwhile (e.g. by an unmanaged thread)
                S.mu.release()
                return True
            rem = None if deadline is None else deadline - _now()
            if rem is not None and rem <= 0:
                S.mu.release()
                return False
            self._nwait += 1
            try:
                ok = _block(me, BLOCKED, f"lock {self._name()}", obj=self, timeout_ns=rem)
            finally:
                self._nwait -= 1
            if self._real.acquire(False):
                return True
            if not ok:
                return False

    def release(self):
        if (self._nwait or S.runq) and _me() is not None:
            _check_depth()
        self._real.release()
        if self._nwait:
            S.mu.acquire()
            _locked_wake_waiters(self)
            if S.current is None and S.runq and S.active:
                # Released by an unmanaged or escaped thread while the scheduler idles.
                cands = _locked_candidates(None, inline=False)
                if cands:
                    _locked_hand(None, _locked_choose(None, cands))
            S.mu.release()
        me = _me()
        if me is not None and S.current is me:
            _point(me)

    def locked(self):
        return self._real.locked()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()

    acquire_lock = acquire
    release_lock = release
    locked_lock = locked

    def _at_fork_reinit(self):
        self._real = _real_allocate()

    def _name(self) -> str:
        return f"0x{id(self):x}"

    def __repr__(self):
        return f"<{'locked' if self._real.locked() else 'unlocked'} detpy.threads.SchedLock object>"


def _new_lock(*args, **kwargs):
    return SchedLock()


class _LockTypeMeta(type):
    """Stand-in for the ``threading.Lock`` type (3.13+): isinstance keeps working."""

    def __instancecheck__(cls, obj):
        real = cls.__wrapped__
        return isinstance(obj, real) or isinstance(obj, SchedLock) or type(obj).__name__ == "_TimedLock"

    def __subclasscheck__(cls, sub):
        return sub is cls or sub is SchedLock or issubclass(sub, cls.__wrapped__)

    def __repr__(cls):
        return repr(cls.__wrapped__)


def _lock_standin(real):
    from ._patch import nonbinding

    if isinstance(real, type):
        ns = {"__new__": lambda cls, *a, **k: SchedLock(), "__wrapped__": real, "__module__": real.__module__,
              "__qualname__": real.__qualname__, "__doc__": real.__doc__, "__slots__": ()}
        return _LockTypeMeta(real.__name__, (), ns)
    return nonbinding(_new_lock, "threading", "Lock")


def _new_rlock(*args, **kwargs):
    return threading._PyRLock(*args, **kwargs)


# ---------------------------------------------------------------------------
# Threads
def _locked_register(sid: str, name: str):
    t = T(S.nthreads, sid, name)
    S.nthreads += 1
    S.threads.append(t)
    S.stats["managed"] += 1
    return t


def _child_sid() -> str:
    site = _site()
    n = S.site_counts.get(site, 0) + 1
    S.site_counts[site] = n
    return f"{site}#{n}"


_INFRA_MODULES = ("_pytest", "pytest", "pluggy", "xdist", "execnet", "coverage", "pytest_cov", "detpy")


def _started_by_infra() -> bool:
    """True if the first frame outside detpy and the standard library belongs to
    test infrastructure (pytest, its plugins): such threads stay unmanaged."""
    f = sys._getframe(2)
    while f is not None:
        fn = f.f_code.co_filename
        if not fn.startswith(_DETPY_DIR):
            kind, _ = _sites._classify(fn)
            if kind == _sites._INFRA:
                return True
            if kind == _sites._USER:
                top = str(f.f_globals.get("__name__", "")).split(".", 1)[0]
                return top in _INFRA_MODULES or top.startswith("pytest_")
        f = f.f_back
    return True


def _wrap_start_thread(real):
    def start_thread(function, *args, **kwargs):
        me = _me()
        if me is None or _started_by_infra():
            return real(function, *args, **kwargs)
        _enter(me)
        _check_depth()
        thread_obj = getattr(_tls, "starting", None)
        _tls.starting = None
        name = getattr(thread_obj, "name", "thread")
        S.mu.acquire()
        t = _locked_register(_child_sid(), name)
        t.thread = thread_obj
        t.state = "starting"
        S.mu.release()
        if thread_obj is not None:
            thread_obj._detpy_t = t

        def boot(*a, **k):
            _tls.t = t
            _state._tls.tkey = t.key
            t.ident = _get_ident()
            try:
                t.native = threading.get_native_id()
            except AttributeError:  # pragma: no cover
                t.native = None
            S.known_idents.add(t.ident)
            if S.active:
                _wait_gate(t)
                _after_wake(t)
                if CFG.seed and CFG.preempt:
                    _install_tracer(t)
            try:
                return function(*a, **k)
            finally:
                if CFG.seed and CFG.preempt:
                    sys.settrace(None)
                _exit(t)

        try:
            res = real(boot, *args, **kwargs)
        except BaseException:
            S.mu.acquire()
            t.state = FINISHED
            S.mu.release()
            raise
        S.mu.acquire()
        _locked_make_runnable(t)
        S.mu.release()
        _point(me)
        return res

    start_thread.__wrapped__ = real
    return start_thread


def _exit(t) -> None:
    # From here on the thread is outside the scheduler (teardown code may still
    # take locks): it must neither wait for the baton nor consume seeded choices.
    _tls.t = None
    S.mu.acquire()
    if t.thread is not None and S.active:
        S.exiting.append(t.thread)
    was_holder = S.current is t
    t.state = FINISHED
    S.known_idents.discard(t.ident)
    t.wait_obj = None
    _locked_wake_waiters(t)
    try:
        S.threads.remove(t)
    except ValueError:  # pragma: no cover
        pass
    if S.active and (was_holder or S.current is None):
        cands = _locked_candidates(None, inline=was_holder)
        nxt = _locked_choose(None, cands) if cands else None
        _locked_hand(t, nxt)
    S.mu.release()


def _wrap_thread_start(real):
    def start(self):
        me = _me()
        if me is not None:
            try:
                if not self._started.is_set() and not isinstance(self._started._cond._lock, SchedLock):
                    self._started = threading.Event()  # created before --det-threads: make it controlled
            except AttributeError:  # pragma: no cover
                pass
            _tls.starting = self
        try:
            return real(self)
        finally:
            _tls.starting = None

    start.__wrapped__ = real
    return start


def _wrap_join(real):
    def join(self, timeout=None):
        me = _me()
        t = getattr(self, "_detpy_t", None)
        if me is not None and t is not None and t is not me:
            _enter(me)
            _check_depth()
            S.mu.acquire()
            if S.active and t.state != FINISHED:
                ok = _block(me, BLOCKED, f"join of thread {t.idx} ({t.name})", obj=t,
                            timeout_ns=None if timeout is None else _ns(max(0, timeout)))
                if not ok:
                    return None
            else:
                S.mu.release()
            # Finished for the scheduler: the real thread is ending; wait for it
            # (short, and its result does not depend on timing).
            return real(self)
        if me is not None and t is None and self is not threading.current_thread():
            with external():  # an unmanaged thread: wait outside the scheduler
                return real(self, timeout)
        return real(self, timeout)

    join.__wrapped__ = real
    return join


def _wrap_is_alive(real):
    def is_alive(self):
        t = getattr(self, "_detpy_t", None)
        me = _me()
        if me is not None and t is not None:
            _enter(me)
            _point(me)
            if t.state == FINISHED:
                return False
            if t.state != "starting":
                if _polled_by_user():
                    poll_miss(me)  # while t.is_alive(): ... spins until t ends
                    if t.state == FINISHED:
                        return False
                return True
        return real(self)

    is_alive.__wrapped__ = real
    return is_alive


# ---------------------------------------------------------------------------
# Preemption in user code (exploration only)
_USER_CODE: dict = {}


def _is_project_code(code) -> bool:
    hit = _USER_CODE.get(code)
    if hit is None:
        fn = code.co_filename
        if fn.startswith(_DETPY_DIR):
            hit = False
        else:
            kind, norm = _sites._classify(fn)
            hit = kind == _sites._USER and not norm.startswith(("<", "/", "~"))
        _USER_CODE[code] = hit
    return hit


def _new_budget() -> int:
    return 1 + S.rng.below(2 * CFG.preempt)


def _install_tracer(t) -> None:
    """Line preemption in project code (exploration). The trace function is
    ``detpy._core.LineTracer``, a C callable: a Python trace function runs at the
    depth of the traced code, so near the recursion limit the test's RecursionError
    was raised inside it, one frame early (structlog test_recursive checks the last
    frame of a recursion traceback). The Python fallback below is used only with an
    older compiled core."""

    def on_budget():
        nb = _new_budget()
        if (S.active and S.current is t and S.runq and not getattr(_tls, "in_mu", False)
                and not _near_recursion_limit()):
            _preempt(t)
        return nb

    try:
        from ._core import LineTracer
    except ImportError:  # pragma: no cover - older compiled core
        LineTracer = None
    if LineTracer is not None:
        sys.settrace(LineTracer(_USER_CODE, _is_project_code, on_budget, _new_budget()))
        return
    t.budget = _new_budget()

    def line(frame, event, arg):
        if event == "line":
            t.budget -= 1
            if t.budget <= 0:
                try:
                    t.budget = on_budget()
                except RecursionError:
                    t.budget = 1
        return line

    def call(frame, event, arg):
        if event == "call":
            try:
                hit = _is_project_code(frame.f_code)
            except RecursionError:
                return None
            if hit:
                return line
        return None

    sys.settrace(call)


def _preempt(me) -> None:
    S.mu.acquire()
    if not S.active or S.current is not me:
        S.mu.release()
        return
    me.state = RUNNABLE
    _switch(me)
    _after_wake(me)


# ---------------------------------------------------------------------------
# I/O: sockets, selectors, select
def _fd_ready(fd: int, write: bool = False) -> bool:
    if fd is None or fd < 0:
        return True
    if _real_poll is not None:
        p = _real_poll()
        p.register(fd, (_select.POLLOUT if write else _select.POLLIN) | _select.POLLERR | _select.POLLHUP)
        return bool(p.poll(0))
    r, w, _ = _real_select([] if write else [fd], [fd] if write else [], [], 0)
    return bool(r or w)


def _sock_wait(sock, write=False) -> None:
    """Before a blocking socket call of a managed thread: wait in the scheduler."""
    try:
        to = sock.gettimeout()
    except Exception:
        return
    if to == 0.0:
        return
    fd = sock.fileno()
    if fd < 0:
        return
    if not io_wait(lambda: _fd_ready(fd, write), to, what=f"socket fd {fd} {'writable' if write else 'readable'}"):
        import socket

        raise socket.timeout("timed out")


def _wrap_sock_read(real):
    def method(self, *args, **kwargs):
        if _me() is not None:
            _sock_wait(self)
        return real(self, *args, **kwargs)

    method.__wrapped__ = real
    method.__name__ = getattr(real, "__name__", "method")
    return method


_STDLIB_CALLERS = frozenset(("threading", "queue", "concurrent.futures.thread", "concurrent.futures._base",
                             "concurrent.futures.process", "logging", "logging.handlers"))


def _polled_by_user() -> bool:
    """The poll comes from code under test, not from the standard library's own
    bookkeeping (Thread.start checks its _started event)."""
    try:
        return sys._getframe(2).f_globals.get("__name__") not in _STDLIB_CALLERS
    except ValueError:  # pragma: no cover
        return False


def _wrap_event_is_set(real):
    def is_set(self):
        r = real(self)
        if not r and S.active:
            me = _me()
            if me is not None and S.current is me and _polled_by_user():
                poll_miss(me)
        return r

    is_set.__wrapped__ = real
    return is_set


def _wrap_queue_get(real):
    def get(self, block=True, timeout=None):
        try:
            return real(self, block, timeout)
        except Exception as e:
            if (S.active and type(e).__name__ == "Empty"
                    and (not block or (timeout is not None and timeout <= 0))):
                me = _me()
                if me is not None and S.current is me:
                    poll_miss(me)
            raise

    get.__wrapped__ = real
    return get


def _ssl_ready(sock) -> bool:
    try:
        if sock.pending():
            return True
    except Exception:
        return True
    return _fd_ready(sock.fileno())


def _wrap_ssl_loop(real, kind: str):
    """SSL reads and handshakes: run non-blocking and wait in the scheduler on
    SSLWantRead/WantWrite, so a TLS peer in another managed thread can progress."""
    import ssl

    def method(self, *args, **kwargs):
        if _me() is None:
            return real(self, *args, **kwargs)
        try:
            to = self.gettimeout()
        except Exception:
            return real(self, *args, **kwargs)
        if to == 0.0 or self.fileno() < 0:
            return real(self, *args, **kwargs)
        if kind == "read" and getattr(self, "_sslobj", None) is None:
            return real(self, *args, **kwargs)  # plain socket mode before the handshake
        deadline = None if to is None else _now() + _ns(to)
        self.settimeout(0.0)
        try:
            while True:
                try:
                    return real(self, *args, **kwargs)
                except ssl.SSLWantReadError:
                    want_write = False
                except ssl.SSLWantWriteError:
                    want_write = True
                rem = None if deadline is None else (deadline - _now()) / 1e9
                if rem is not None and rem <= 0:
                    import socket

                    raise socket.timeout("timed out")
                fd = self.fileno()
                pred = (lambda: _fd_ready(fd, True)) if want_write else (lambda: _ssl_ready(self) or _fd_ready(fd))
                if not io_wait(pred, rem, what=f"TLS fd {fd}"):
                    import socket

                    raise socket.timeout("timed out")
        finally:
            try:
                self.settimeout(to)
            except Exception:
                pass

    method.__wrapped__ = real
    return method


def _in_event_loop() -> bool:
    aio = sys.modules.get("asyncio")
    if aio is None:
        return False
    try:
        return aio._get_running_loop() is not None
    except Exception:  # pragma: no cover
        return False


def _wrap_selector_select(real):
    def select(self, timeout=None):
        if _me() is None:
            return real(self, timeout)
        if timeout is not None and timeout <= 0:
            me = _me()
            _enter(me)
            r = real(self, 0)
            if not r:
                poll_miss(me)  # an event loop with nothing ready, or a polling loop
            return r
        from . import aio

        real_time = _in_event_loop() and not aio.CFG.enabled  # asyncio keeps real time under Level 0
        box = []

        def pred():
            r = real(self, 0)
            if r:
                box.append(r)
            return bool(r)

        if io_wait(pred, timeout, what="selector", real_time=real_time):
            return real(self, 0)
        if real_time and timeout:
            # Same rule as Level 0 (clock._wrap_selector_select): an event-loop wait
            # that times out advances the virtual clock by its timeout (asyncio.sleep).
            c = _clock()
            if c is not None:
                c.advance(-(-int(timeout * 1e9) // 1_000_000) * 1_000_000)
        return []

    select.__wrapped__ = real
    return select


def _select_select(rlist, wlist, xlist, timeout=None):
    me = _me()
    if me is None:
        return _real_select(rlist, wlist, xlist, timeout)
    if timeout is not None and timeout <= 0:
        _enter(me)
        r = _real_select(rlist, wlist, xlist, 0)
        if not (r[0] or r[1] or r[2]):
            poll_miss(me)
        return r
    box = []

    def pred():
        r = _real_select(rlist, wlist, xlist, 0)
        if r[0] or r[1] or r[2]:
            box.append(r)
            return True
        return False

    if io_wait(pred, timeout, what="select()", real_time=_in_event_loop()):
        return _real_select(rlist, wlist, xlist, 0)
    return ([], [], [])


# ---------------------------------------------------------------------------
# Watchdog: escapes, idle duty (timers while external work is pending), slow deadlocks
def _task_state(native) -> str:
    if native is None:
        return "?"
    try:
        with open(f"/proc/self/task/{native}/stat", "rb") as f:
            data = f.read()
        return data[data.rindex(b")") + 2:data.rindex(b")") + 3].decode()
    except Exception:
        return "?"


def _watchdog() -> None:
    """The scheduler's watchdog thread. An error in one round must not stop it: without
    it nobody fires timers for an idle scheduler or escapes a stuck holder."""
    while True:
        try:
            _watchdog_loop()
            return
        except Exception as e:  # pragma: no cover - defensive
            _dbg(f"watchdog error: {e!r}")
            try:
                if S.mu.locked() and getattr(_tls, "holds_mu", False):
                    S.mu.release()
            except Exception:
                pass


def _watchdog_loop() -> None:
    last_ops = -1
    last_cur = None
    last_switches = -1
    stalled_since = None
    held_since = None
    while True:
        _real_sleep(0.005)
        S.watchdog_beats += 1
        if not S.active:
            S.watchdog_on = False
            return
        S.mu.acquire()
        try:
            if not S.active:
                S.watchdog_on = False
                return
            cur = S.current
            if cur is None:
                stalled_since = held_since = None
                _idle_duty()
                continue
            now = _real_monotonic()
            if cur is not last_cur or S.stats["switches"] != last_switches or held_since is None:
                last_cur, last_switches, last_ops = cur, S.stats["switches"], S.ops
                stalled_since, held_since = None, now
                continue
            others = S.runq or _locked_live_timer() is not None or _has(IOWAIT)
            if not others:
                last_ops, stalled_since, held_since = S.ops, None, now
                continue
            if S.ops != last_ops:
                # The holder makes controlled operations but keeps the baton while
                # others wait only for time (a spin on something that is not a
                # poll, e.g. qsize()): after a long while, let time pass (uncontrolled).
                last_ops, stalled_since = S.ops, None
                if not S.runq and now - held_since >= CFG.spin_time and _locked_fire_timer():
                    _record_uncontrolled(f"timer fired while thread {cur.idx} ({cur.name}) kept the baton "
                                         f"for {now - held_since:.1f} s")
                    held_since = now
                continue
            if stalled_since is None:
                stalled_since = now
                continue
            stalled_ms = (now - stalled_since) * 1000
            if stalled_ms < CFG.escape_ms:
                continue
            state = _task_state(cur.native)
            if state in ("S", "D"):
                why = "blocked outside the scheduler"
            elif stalled_ms >= (CFG.spin_escape if S.runq else CFG.spin_time) * 1000:
                # Running Python (or C) code with no controlled point for a long
                # time while others wait: a spin on a plain variable. Without an
                # escape it would never let the thread it waits for run.
                why = f"running {stalled_ms / 1000:.1f} s without a controlled point"
            else:
                continue
            cur.state = EXTERNAL
            S.stats["escapes"] += 1
            _record_uncontrolled(f"escape of thread {cur.idx} ({cur.name}) {why}")
            cands = _locked_candidates(None, inline=False)
            nxt = _locked_choose(None, cands) if cands else None
            _locked_hand(None, nxt)
            stalled_since = None
        finally:
            S.mu.release()


def _idle_duty() -> None:
    """S.mu held, nobody holds the baton."""
    cands = _locked_candidates(None, inline=False)
    if cands:
        _locked_hand(None, _locked_choose(None, cands))
        return
    outside = _outside_activity()
    io = _has(IOWAIT)
    idle = _real_monotonic() - (S.idle_since or _real_monotonic())
    timer = _locked_live_timer()
    if timer is not None:
        left = max(0.0, (timer[0] - _now()) / 1e9)
        if outside:
            limit = CFG.grace
            if timer[1].state == IOWAIT:
                # A socket timeout while work outside the scheduler (an unmanaged
                # server thread, a child process, an escaped thread) may answer:
                # that answer comes in real time, so the timeout is real time too.
                limit = max(limit, left)
        elif io:
            # Only I/O waiters: give data in flight as much real time as the
            # virtual time to the next timer (at most the grace), as a real run would.
            limit = min(CFG.grace, left)
        else:
            limit = 0.0
        if idle >= limit:
            if _locked_fire_timer():
                if outside:
                    _record_uncontrolled("timer fired while outside work was pending")
                cands = [t for t in S.runq if t.state == RUNNABLE]
                if cands:
                    _locked_hand(None, _locked_choose(None, cands))
        return
    blocked = any(t.state in (BLOCKED, IOWAIT) for t in S.threads)
    if not blocked:
        return
    if any(t.state == IOWAIT and t.real_deadline is not None for t in S.threads):
        return  # a real-time wait (event-loop select) ends by itself
    if _has(EXTERNAL) or (outside and io):
        # Waiting for work outside the scheduler (an escaped thread, an unmanaged
        # server, a child process): a real wait, as in a plain run, but bounded so
        # that a test never hangs.
        limit = CFG.stuck
    elif outside or io:
        limit = CFG.deadlock
    else:
        limit = 0.0
    if idle >= limit:
        _locked_raise_deadlock(stuck_s=limit if limit == CFG.stuck else 0.0)
        cands = [t for t in S.runq if t.state == RUNNABLE]
        if cands:
            _locked_hand(None, cands[0])


class _InsertionOrderedSet(set):
    """A set that iterates in insertion order (ThreadPoolExecutor._threads): the
    order a set of threads is joined in would otherwise follow their addresses."""

    def __init__(self, *args):
        super().__init__(*args)
        self._order = list(super().__iter__())

    def add(self, x):
        if x not in self:
            self._order.append(x)
        super().add(x)

    def discard(self, x):
        if x in self:
            self._order.remove(x)
        super().discard(x)

    def remove(self, x):
        super().remove(x)
        self._order.remove(x)

    def clear(self):
        super().clear()
        self._order = []

    def pop(self):
        if not self._order:
            raise KeyError("pop from an empty set")
        x = self._order.pop(0)
        super().discard(x)
        return x

    def __iter__(self):
        return iter(list(self._order))


def _virtual_monotonic() -> float:
    """Monotonic seconds on the scheduler's clock (no event recorded: standard
    library bookkeeping, not an observation by the code under test)."""
    if S.active:
        return _now() / 1e9
    return _real_monotonic()


_FUTURE_SEQ = [0]


def _wrap_future_init(real):
    def __init__(self, *args, **kwargs):
        real(self, *args, **kwargs)
        if S.active:
            _FUTURE_SEQ[0] += 1
            self._detpy_seq = _FUTURE_SEQ[0]

    __init__.__wrapped__ = real
    return __init__


def _future_hash(self):
    seq = getattr(self, "_detpy_seq", None)
    return object.__hash__(self) if seq is None else seq


def _future_key(f):
    seq = getattr(f, "_detpy_seq", None)
    return (1, id(f)) if seq is None else (0, seq)


def _acquire_futures_init(self, futures):
    self.futures = sorted(futures, key=_future_key)


def _wrap_pool_init(real):
    def __init__(self, *args, **kwargs):
        real(self, *args, **kwargs)
        if _me() is not None and isinstance(getattr(self, "_threads", None), set):
            self._threads = _InsertionOrderedSet(self._threads)

    __init__.__wrapped__ = real
    return __init__


# ---------------------------------------------------------------------------
# Installation
_PATCHED = {"on": False}


def install(patcher, seed: int, grace: float, deadlock: float, preempt: int, stuck: float = 60.0) -> None:
    import queue
    import selectors
    import socket

    CFG.enabled = True
    CFG.seed = seed
    CFG.grace = grace
    CFG.deadlock = deadlock
    CFG.stuck = max(stuck, deadlock)
    CFG.preempt = preempt if seed else 0
    S.rng = Rng(seed)
    S.p_switch = (0.02, 0.1, 0.3, 0.6)[Rng(seed ^ 0x5EED).below(4)] if seed else 0.0
    patcher.set(threading, "_allocate_lock", _new_lock)
    patcher.set(threading, "Lock", _lock_standin(getattr(threading.Lock, "__wrapped__", threading.Lock)))
    patcher.set(threading, "RLock", _new_rlock)
    patcher.set(threading, "_CRLock", None)
    for name in ("_start_new_thread", "_start_joinable_thread"):
        if hasattr(threading, name):
            patcher.set(threading, name, _wrap_start_thread(getattr(threading, name)))
    # Libraries that wrap thread creation (easypy's threadtree) capture
    # _thread.start_new_thread at import and install their own
    # threading._start_new_thread: patch the low-level entry points too.
    for name in ("start_new_thread", "start_new", "start_joinable_thread"):
        if hasattr(_thread, name):
            patcher.set(_thread, name, _wrap_start_thread(getattr(_thread, name)))
    patcher.set(threading.Thread, "start", _wrap_thread_start(threading.Thread.start))
    patcher.set(threading.Thread, "join", _wrap_join(threading.Thread.join))
    patcher.set(threading.Thread, "is_alive", _wrap_is_alive(threading.Thread.is_alive))
    patcher.set(threading.Event, "is_set", _wrap_event_is_set(threading.Event.is_set))
    patcher.set(queue.Queue, "get", _wrap_queue_get(queue.Queue.get))
    if hasattr(queue, "_PySimpleQueue"):
        patcher.set(queue._PySimpleQueue, "get", _wrap_queue_get(queue._PySimpleQueue.get))
    if hasattr(queue, "_PySimpleQueue"):
        patcher.set(queue, "SimpleQueue", queue._PySimpleQueue)
    for name in ("recv", "recv_into", "recvfrom", "recvfrom_into", "accept"):
        if name in vars(socket.socket) or hasattr(socket.socket, name):
            patcher.set(socket.socket, name, _wrap_sock_read(getattr(socket.socket, name)))
    try:
        import ssl

        for name, kind in (("recv", "read"), ("recv_into", "read"), ("read", "read"),
                           ("do_handshake", "handshake")):
            if name in vars(ssl.SSLSocket):
                patcher.set(ssl.SSLSocket, name, _wrap_ssl_loop(vars(ssl.SSLSocket)[name], kind))
    except ImportError:  # pragma: no cover
        pass
    for name in ("SelectSelector", "PollSelector", "EpollSelector", "DevpollSelector", "KqueueSelector"):
        cls = getattr(selectors, name, None)
        if cls is not None and "select" in vars(cls):
            patcher.set(cls, "select", _wrap_selector_select(vars(cls)["select"]))
    patcher.set(_select, "select", _select_select)
    import concurrent.futures.thread as _cft

    patcher.set(_cft.ThreadPoolExecutor, "__init__", _wrap_pool_init(_cft.ThreadPoolExecutor.__init__))
    # The standard library keeps its own reference to the real monotonic clock
    # (threading._time, queue.time): Condition.wait_for, Barrier, Semaphore and
    # Queue.get compute "time left" with it. Their waits are virtual under the
    # scheduler, so the time left must be virtual too, or a timed-out wait is
    # retried with the same time left forever (a Barrier timeout never fires).
    if hasattr(threading, "_time"):
        patcher.set(threading, "_time", _virtual_monotonic)
    if callable(getattr(queue, "time", None)):
        patcher.set(queue, "time", _virtual_monotonic)
    import concurrent.futures._base as _cfb

    # Futures hash by address: wait()/as_completed() iterate sets of futures and
    # _AcquireFutures locks them in id() order, so which future is seen first (and
    # where the caller blocks) would follow the heap layout. Give every future
    # created under the scheduler a creation number and use it instead.
    patcher.set(_cfb.Future, "__init__", _wrap_future_init(_cfb.Future.__init__))
    patcher.set(_cfb.Future, "__hash__", _future_hash)
    if hasattr(_cfb, "_AcquireFutures"):
        patcher.set(_cfb._AcquireFutures, "__init__", _acquire_futures_init)
    from . import clock

    patcher.set(clock, "_sched_sleep", sleep)
    patcher.set(clock, "_sched_managed", managed)
    _PATCHED["on"] = True


def activate() -> None:
    """Start scheduling: the calling (test) thread becomes managed thread 0."""
    if not CFG.enabled or S.active:
        return
    S.mu.acquire()
    main = _locked_register("main", threading.current_thread().name)
    main.ident = _get_ident()
    try:
        main.native = threading.get_native_id()
    except AttributeError:  # pragma: no cover
        pass
    main.state = RUNNABLE
    S.known_idents.add(main.ident)
    S.current = main
    S.active = True
    S.mu.release()
    _tls.t = main
    if not S.watchdog_on:
        S.watchdog_on = True
        _real_start_new_thread(_watchdog, ())


def start_test() -> None:
    S.site_counts = {}
    me = _me()
    if me is not None and CFG.seed and CFG.preempt and me.idx == 0:
        _install_tracer(me)


def end_test() -> None:
    me = _me()
    if me is not None and CFG.seed and CFG.preempt and me.idx == 0:
        sys.settrace(None)


def uninstall() -> None:
    """Stop scheduling; every managed thread continues as a plain thread."""
    if not CFG.enabled:
        return
    S.mu.acquire()
    S.active = False
    for t in S.threads:
        if t.state != FINISHED and t is not S.current and not t.handed:
            t.handed = True
            try:
                t.gate.release()
            except RuntimeError:  # pragma: no cover
                pass
    S.current = None
    S.runq = []
    S.timers = []
    S.mu.release()
    _tls.t = None
    CFG.enabled = False
    _PATCHED["on"] = False


def stats() -> dict:
    return dict(S.stats)
