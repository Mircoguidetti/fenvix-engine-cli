"""Level 1 for threads: no blocking point can hang a test (fix round of P-012).

Every test here runs an inner pytest under ``--det --det-threads`` in a subprocess
with a hard timeout. Each inner test is one way real suites blocked the baton
(anyio's worker pool, requests with pytest-httpbin): before the fix it hung or
raised a false ``DeadlockError``; after it, it passes, or a stuck baton becomes a
clear ``DeadlockError`` naming the threads involved.
"""

import os
import subprocess
import sys
import time

import pytest

FLAGS = ["--det", "--det-threads"]


def _run(pytester, src: str, *extra, timeout: float = 60):
    pytester.makepyfile(test_inner=src)
    t0 = time.monotonic()
    try:
        result = pytester.runpytest_subprocess(*FLAGS, "-p", "no:cacheprovider", "-W", "ignore", "-rfE", *extra,
                                               timeout=timeout)
    except pytester.TimeoutExpired:  # pragma: no cover - the failure this file guards against
        pytest.fail(f"inner run hung (> {timeout} s)")
    return result, time.monotonic() - t0


# ---------------------------------------------------------------------------
# Polling: a thread that spins on a zero-timeout poll must let the others run
# and let (virtual) time pass. anyio: ``while not started.is_set(): await checkpoint()``.
SPIN = r'''
import asyncio, queue, select, selectors, socket, threading, time

def test_selector_poll_spin_lets_a_runnable_thread_go():
    ev = threading.Event()
    t = threading.Thread(target=ev.set)
    t.start()
    sel = selectors.DefaultSelector()
    a, b = socket.socketpair()
    sel.register(a, selectors.EVENT_READ)
    while not ev.is_set():
        sel.select(0)
    t.join()
    sel.close(); a.close(); b.close()

def test_asyncio_checkpoint_spin_waits_for_a_thread():
    started = threading.Event()
    release = threading.Event()
    def worker():
        started.set()
        assert release.wait(5)
    async def main():
        t = threading.Thread(target=worker)
        t.start()
        while not started.is_set():
            await asyncio.sleep(0)
        release.set()
        await asyncio.to_thread(t.join)
    asyncio.run(main())

def test_select_poll_spin_lets_virtual_time_pass():
    ev = threading.Event()
    def sleeper():
        time.sleep(5)
        ev.set()
    t = threading.Thread(target=sleeper)
    t.start()
    while not ev.is_set():
        select.select([], [], [], 0)
    t.join()

def test_nonblocking_acquire_spin_lets_virtual_time_pass():
    lock = threading.Lock()
    def holder():
        with lock:
            time.sleep(3)
    t = threading.Thread(target=holder)
    t.start()
    while t.is_alive() and not lock.locked():
        time.sleep(0)
    while not lock.acquire(blocking=False):
        pass
    lock.release()
    t.join()

def test_queue_get_nowait_spin():
    q = queue.Queue()
    def producer():
        time.sleep(2)
        q.put(1)
    t = threading.Thread(target=producer)
    t.start()
    while True:
        try:
            assert q.get_nowait() == 1
            break
        except queue.Empty:
            pass
    t.join()

def test_sleep_zero_spin_waits_for_a_sleeper():
    ev = threading.Event()
    def sleeper():
        time.sleep(1)
        ev.set()
    t = threading.Thread(target=sleeper)
    t.start()
    while not ev.is_set():
        time.sleep(0)
    t.join()
'''


def test_zero_timeout_polls_let_threads_and_time_progress(pytester):
    result, dur = _run(pytester, SPIN, timeout=90)
    result.assert_outcomes(passed=6)
    assert dur < 60


PURE_SPIN = r'''
import threading, time

def test_pure_python_spin_on_a_flag():
    flag = []
    lock = threading.Lock()
    def w():
        with lock:  # blocks: the main thread keeps the baton
            flag.append(1)
    t = threading.Thread(target=w)
    with lock:
        t.start()
    # t is runnable now, but the main thread spins without a controlled point
    while not flag:
        pass
    t.join()
'''


def test_pure_python_spin_is_escaped_not_hung(pytester):
    """A loop with no controlled point at all (a flag read): the watchdog moves the
    spinning holder out of the scheduler, records it, and the other thread runs."""
    trace = pytester.path / "t.jsonl"
    result, _ = _run(pytester, PURE_SPIN, f"--det-trace={trace}", timeout=60)
    result.assert_outcomes(passed=1)
    assert "threads.uncontrolled" in trace.read_text()


# ---------------------------------------------------------------------------
# Outside the scheduler: an unmanaged thread (a server started before the
# scheduler, like pytest-httpbin's) serves a managed client. Its slowness is
# real time, not a deadlock, and a socket timeout is real time too.
OUTSIDE = r'''
import socket, threading, time

def _serve(srv, delay):
    while True:
        try:
            c, _ = srv.accept()
        except OSError:
            return
        with c:
            c.recv(100)
            time.sleep(delay)   # a slow handler (httpbin's /delay/N)
            c.sendall(b"pong")

def _server(delay):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    threading.Thread(target=_serve, args=(srv, delay), daemon=True, name="outside-server").start()
    return srv.getsockname()

SLOW = _server(3.0)   # started at import: before the scheduler, so unmanaged

def _ask(addr, timeout=None):
    c = socket.create_connection(addr, timeout=timeout)
    c.settimeout(timeout)
    with c:
        c.sendall(b"ping")
        return c.recv(100)

def test_blocking_recv_from_a_slow_outside_server():
    assert _ask(SLOW) == b"pong"

def test_socket_timeout_longer_than_the_outside_reply():
    assert _ask(SLOW, timeout=6.0) == b"pong"

def test_managed_thread_waits_for_the_outside_server():
    got = []
    t = threading.Thread(target=lambda: got.append(_ask(SLOW)))
    t.start()
    t.join()
    assert got == [b"pong"]
'''


def test_waits_on_outside_threads_are_real_waits_not_deadlocks(pytester):
    # --det-threads-deadlock=1: before the fix, any wait over 1 s with only an
    # outside thread able to answer was declared a deadlock.
    result, _ = _run(pytester, OUTSIDE, "--det-threads-deadlock=1", "--det-threads-grace=0.5", timeout=120)
    result.assert_outcomes(passed=3)


STUCK = r'''
import socket, threading

def _silent(srv):
    c, _ = srv.accept()
    threading.Event().wait()  # never answers

SRV = socket.socket()
SRV.bind(("127.0.0.1", 0))
SRV.listen(1)
threading.Thread(target=_silent, args=(SRV,), daemon=True, name="silent-peer").start()

def test_recv_from_a_peer_that_never_answers():
    c = socket.create_connection(SRV.getsockname())
    c.recv(10)
'''


def test_a_stuck_wait_on_the_outside_becomes_a_clear_error(pytester):
    result, dur = _run(pytester, STUCK, "--det-threads-stuck=3", timeout=60)
    result.assert_outcomes(failed=1)
    text = result.stdout.str()
    assert "DeadlockError" in text
    assert "socket fd" in text and "silent-peer" in text  # names the waiter and the outside thread
    assert dur < 40


# ---------------------------------------------------------------------------
# An asynchronous exception (pytest-timeout's signal method, KeyboardInterrupt)
# raised while a managed thread waits for the baton must not corrupt the scheduler.
INTERRUPT = r'''
import signal, threading, time

class Alarm(Exception):
    pass

def _alarm(*_):
    raise Alarm()

def test_interrupted_while_waiting_for_the_baton():
    signal.signal(signal.SIGALRM, _alarm)
    stop = []
    def busy():
        n = 0
        while not stop:  # holds the baton without a controlled point
            n += 1
    t = threading.Thread(target=busy)
    signal.setitimer(signal.ITIMER_REAL, 0.3)
    try:
        t.start()   # hands the baton to the busy thread
        t.join()
    except Alarm:
        pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        stop.append(1)
    t.join()

def test_next_test_still_scheduled():
    out = []
    lock = threading.Lock()
    def w(i):
        for _ in range(3):
            with lock:
                out.append(i)
            time.sleep(0.001)
    ts = [threading.Thread(target=w, args=(i,)) for i in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(out) == [0, 0, 0, 1, 1, 1, 2, 2, 2]
'''


def test_an_interrupted_baton_wait_does_not_wedge_the_scheduler(pytester):
    result, _ = _run(pytester, INTERRUPT, timeout=60)
    result.assert_outcomes(passed=2)


# A managed thread's id is reused by the OS for a later unmanaged thread: the
# scheduler must still see the new thread as work outside the scheduler.
# (requests: test_lowlevel.py's server threads, then pytest-httpbin's server.)
HELPER = r"""
import socket, threading, time

def start_slow_server(delay):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    def serve():
        c, _ = srv.accept()
        with c:
            c.recv(100)
            time.sleep(delay)
            c.sendall(b"pong")
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()
"""

REUSE = r"""
import socket, threading
import pytest_helper_outside  # an infrastructure-like module: its threads stay unmanaged

def test_managed_threads_come_and_go():
    for _ in range(5):
        t = threading.Thread(target=lambda: None)
        t.start()
        t.join()

def test_then_an_unmanaged_server_answers_slowly():
    addr = pytest_helper_outside.start_slow_server(2.0)
    c = socket.create_connection(addr)
    with c:
        c.sendall(b"ping")
        assert c.recv(100) == b"pong"
"""


def test_reused_thread_ids_are_not_mistaken_for_managed_threads(pytester):
    pytester.makepyfile(pytest_helper_outside=HELPER)
    pytester.syspathinsert()
    result, _ = _run(pytester, REUSE, "--det-threads-deadlock=1", timeout=60)
    result.assert_outcomes(passed=2)


# The watchdog sees the scheduler idle (the holder runs outside it), then the same
# holder takes the baton back without a switch: an internal error there killed
# the watchdog thread (anyio suite: every later timer and escape stopped).
WATCHDOG = r'''
import _thread, threading, time
import detpy.threads

def test_holder_rejoins_after_an_escape():
    t = threading.Thread(target=time.sleep, args=(10,))  # a pending timer, nobody runnable
    t.start()
    raw = _thread.allocate_lock()  # not a detpy lock: waiting on it is uncontrolled
    raw.acquire()
    lock = threading.Lock()
    for _ in range(2):
        raw.acquire(timeout=0.3)  # blocked in C: the watchdog escapes the holder
        end = detpy.threads._real_monotonic() + 0.1
        while detpy.threads._real_monotonic() < end:  # rejoins, then controlled operations
            with lock:
                pass
    beats = detpy.threads.S.watchdog_beats
    raw.acquire(timeout=0.2)
    assert detpy.threads.S.watchdog_beats > beats  # the watchdog still runs
    t.join()
'''


def test_the_watchdog_survives_a_holder_that_rejoins(pytester):
    result, _ = _run(pytester, WATCHDOG, timeout=60)
    result.assert_outcomes(passed=1)
