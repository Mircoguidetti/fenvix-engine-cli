"""Level 1 prototype: deterministic thread scheduling (``--det-threads``).

The race tests are written so that, without the prototype, their printed results
or fingerprints differ between runs (the OS scheduler and the GIL decide), and
with it they are a pure function of the seed. To see them fail without the
prototype run::

    DETPY_THREADS_FLAGS="--det" pytest tests/test_threads.py
"""

import json
import os
import sys
import time

import pytest

FLAGS = os.environ.get("DETPY_THREADS_FLAGS", "--det --det-threads").split()
WITHOUT_PROTOTYPE = "--det-threads" not in FLAGS

RACES = r'''
import json, queue, socket, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

def emit(name, value):
    print(f"RESULT {name} {json.dumps(value)}", flush=True)

def test_sleepy_appends():
    """Threads that append between short sleeps: the interleaving is timing."""
    out = []
    def w(i):
        for k in range(4):
            out.append(i)
            time.sleep(0.0002 * (1 + (i + k) % 3))
    ts = [threading.Thread(target=w, args=(i,)) for i in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    emit("appends", out)

def test_pool_completion_order():
    """Thread pool: completion order of jobs of similar length."""
    def job(n):
        s = 0
        for i in range(2000 + 50 * (n % 4)):
            s += i
        time.sleep(0.0001)
        return n
    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(job, n) for n in range(12)]
        emit("pool", [f.result() for f in as_completed(futs)])

def test_lock_handoff():
    """Who gets a contended lock next."""
    lock = threading.Lock()
    got = []
    def w(i):
        for _ in range(5):
            with lock:
                got.append(i)
                time.sleep(0.0001)
    ts = [threading.Thread(target=w, args=(i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    emit("lock", got)

def test_queue_consumers():
    """Which consumer takes which item."""
    q = queue.Queue()
    taken = []
    def consumer(i):
        while True:
            item = q.get()
            if item is None:
                return
            taken.append((i, item))
            time.sleep(0.0001)
    ts = [threading.Thread(target=consumer, args=(i,)) for i in range(3)]
    for t in ts:
        t.start()
    for n in range(15):
        q.put(n)
    for _ in ts:
        q.put(None)
    for t in ts:
        t.join()
    emit("queue", taken)

def test_loopback_server():
    """A server thread and two client threads on loopback sockets."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    log = []
    def serve():
        for _ in range(4):
            conn, _ = srv.accept()
            data = conn.recv(64)
            log.append(data.decode())
            conn.sendall(data.upper())
            conn.close()
    def client(name):
        for k in range(2):
            c = socket.create_connection(("127.0.0.1", port))
            c.sendall(f"{name}{k}".encode())
            log.append(c.recv(64).decode())
            c.close()
    st = threading.Thread(target=serve)
    st.start()
    cs = [threading.Thread(target=client, args=(n,)) for n in "ab"]
    for c in cs:
        c.start()
    for c in cs:
        c.join()
    st.join()
    srv.close()
    emit("loopback", log)
'''


def _run(pytester, *extra, flags=None):
    """One run. Every run uses the same command line (a replay is the same command):
    object addresses, hence ``id()``-ordered sets such as ThreadPoolExecutor's
    threads, depend on it."""
    out = pytester.path / "out.json"
    if out.exists():
        out.unlink()
    args = [*(flags if flags is not None else FLAGS), *extra, f"--det-outcomes={out}", "-p", "no:cacheprovider", "-s"]
    result = pytester.runpytest_subprocess(*args)
    results = {}
    for line in result.outlines:
        if "RESULT " in line and 'print("RESULT' not in line:
            _, name, value = line[line.index("RESULT "):].split(" ", 2)
            results.setdefault(name, json.loads(value))
    data = json.loads(out.read_text()) if out.exists() else {}
    return result, results, data.get("fingerprints", {})


def test_races_are_a_function_of_the_seed(pytester):
    pytester.makepyfile(test_races=RACES)
    runs = [_run(pytester) for _ in range(3)]
    for result, _, _ in runs:
        result.assert_outcomes(passed=5)
    first = runs[0]
    for _, results, fps in runs[1:]:
        assert results == first[1]
        if not WITHOUT_PROTOTYPE:
            assert fps == first[2]


def test_without_the_prototype_races_vary(pytester):
    """Control: with Level 0 only, timing decides (fingerprints or results differ)."""
    pytester.makepyfile(test_races=RACES)
    runs = [_run(pytester, flags=["--det"]) for _ in range(4)]
    differs = set()
    for _, results, fps in runs[1:]:
        for k in runs[0][1]:
            if results.get(k) != runs[0][1].get(k):
                differs.add(k)
        for k in runs[0][2]:
            if fps.get(k) != runs[0][2].get(k):
                differs.add(k)
    assert differs, "Level 0 alone made every race deterministic: the control is not a control"


@pytest.mark.skipif(WITHOUT_PROTOTYPE, reason="needs --det-threads")
def test_seeds_explore_interleavings(pytester):
    pytester.makepyfile(test_races=RACES)
    seen = {}
    for seed in (1, 2, 3):
        _, results, _ = _run(pytester, f"--det-threads-seed={seed}")
        seen[seed] = results
    assert len({json.dumps(r, sort_keys=True) for r in seen.values()}) > 1
    _, again, _ = _run(pytester, "--det-threads-seed=2")
    assert again == seen[2]


LOST_UPDATE = r'''
import json, threading

def test_lost_update():
    n = [0]
    def w():
        for _ in range(300):
            v = n[0]
            n[0] = v + 1
    ts = [threading.Thread(target=w) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    print("RESULT lost", json.dumps(n[0]), flush=True)
    assert n[0] == 900
'''


@pytest.mark.skipif(WITHOUT_PROTOTYPE, reason="needs --det-threads")
def test_preemption_finds_a_lost_update_and_replays_it(pytester):
    pytester.makepyfile(test_lost=LOST_UPDATE)
    result, res, _ = _run(pytester)
    result.assert_outcomes(passed=1)  # calm: switches only at controlled points
    failing = None
    for seed in range(1, 8):
        result, res, _ = _run(pytester, f"--det-threads-seed={seed}")
        if res["lost"] != 900:
            failing = (seed, res["lost"])
            break
    assert failing is not None
    seed, value = failing
    for _ in range(2):
        result, res, _ = _run(pytester, f"--det-threads-seed={seed}")
        result.assert_outcomes(failed=1)
        assert res["lost"] == value


DEADLOCK = r'''
import threading, time

def test_lock_order_inversion():
    a, b = threading.Lock(), threading.Lock()
    def x():
        with a:
            time.sleep(0.01)
            with b:
                pass
    def y():
        with b:
            time.sleep(0.01)
            with a:
                pass
    t1 = threading.Thread(target=x, name="left")
    t2 = threading.Thread(target=y, name="right")
    t1.start(); t2.start()
    t1.join(); t2.join()
'''


@pytest.mark.skipif(WITHOUT_PROTOTYPE, reason="needs --det-threads")
def test_deadlock_is_reported_not_hung(pytester):
    pytester.makepyfile(test_dead=DEADLOCK)
    t0 = time.monotonic()
    result = pytester.runpytest_subprocess(*FLAGS, "-p", "no:cacheprovider", "-W", "ignore")
    assert time.monotonic() - t0 < 30
    result.assert_outcomes(failed=1)
    text = result.stdout.str()
    assert "DeadlockError" in text
    assert "left" in text and "right" in text and "waits for lock" in text


TIMEOUTS = r'''
import threading, time

def test_waits_are_virtual():
    ev = threading.Event()
    lock = threading.Lock()
    lock.acquire()
    got = []
    def w():
        got.append(lock.acquire(timeout=30))
    t = threading.Thread(target=w)
    t0 = time.monotonic()
    t.start()
    assert ev.wait(20) is False
    t.join()
    assert got == [False]
    assert time.monotonic() - t0 >= 30  # virtual time moved by the waits
    time.sleep(100)
    assert time.monotonic() - t0 >= 130
'''


@pytest.mark.skipif(WITHOUT_PROTOTYPE, reason="needs --det-threads")
def test_timeouts_and_sleeps_are_virtual(pytester):
    pytester.makepyfile(test_to=TIMEOUTS)
    t0 = time.monotonic()
    result = pytester.runpytest_subprocess(*FLAGS, "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)
    assert time.monotonic() - t0 < 20  # real time: no 30 s wait


ESCAPE = r'''
import _thread, threading, time

def test_uncontrolled_lock_escapes():
    raw = _thread.allocate_lock()  # not a detpy lock: blocking on it is uncontrolled
    raw.acquire()
    done = []
    def holder():
        time.sleep(0.01)
        raw.release()
    def waiter():
        raw.acquire()
        done.append(1)
    t1 = threading.Thread(target=waiter)
    t2 = threading.Thread(target=holder)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert done == [1]
'''


@pytest.mark.skipif(WITHOUT_PROTOTYPE, reason="needs --det-threads")
def test_escape_hatch_for_uncontrolled_blocking(pytester):
    pytester.makepyfile(test_esc=ESCAPE)
    trace = pytester.path / "t.jsonl"
    result = pytester.runpytest_subprocess(*FLAGS, f"--det-trace={trace}", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)
    assert "threads.uncontrolled" in trace.read_text()


LOCK_TYPES = r'''
import threading, queue

def test_lock_types():
    l = threading.Lock()
    assert isinstance(l, threading.Lock) or not isinstance(threading.Lock, type)
    r = threading.RLock()
    with r:
        with r:
            pass
    c = threading.Condition()
    with c:
        assert not c.wait(0.01)
    s = threading.Semaphore(2)
    assert s.acquire() and s.acquire() and not s.acquire(timeout=0.01)
    b = threading.Barrier(2, timeout=5)
    t = threading.Thread(target=b.wait)
    t.start()
    b.wait()
    t.join()
    q = queue.SimpleQueue()
    q.put(1)
    assert q.get(timeout=1) == 1
    tm = threading.Timer(5.0, lambda: None)
    tm.start()
    tm.cancel()
    tm.join()
'''


@pytest.mark.skipif(WITHOUT_PROTOTYPE, reason="needs --det-threads")
def test_threading_api_keeps_working(pytester):
    pytester.makepyfile(test_api=LOCK_TYPES)
    result = pytester.runpytest_subprocess(*FLAGS, "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)


def test_det_threads_needs_det(pytester):
    pytester.makepyfile(test_x="def test_x():\n    pass\n")
    result = pytester.runpytest_subprocess("--det-threads", "-p", "no:cacheprovider")
    assert "--det-threads needs --det" in result.stderr.str()


FUTURE_ORDER = r'''
import json
from concurrent.futures import Future, as_completed, wait
from concurrent.futures._base import _AcquireFutures

def test_future_order():
    # Free every other future and allocate new ones: the new ones reuse the
    # freed memory, so creation order and address order disagree.
    fs = [Future() for _ in range(64)]
    keep = fs[1::2]
    del fs
    fs = keep + [Future() for _ in range(32)]
    for f in fs:
        f.set_result(None)
    order = {id(f): i for i, f in enumerate(fs)}
    seen = [order[id(f)] for f in as_completed(fs)]
    done, _ = wait(fs)
    seen_wait = [order[id(f)] for f in done]
    locked = [order[id(f)] for f in _AcquireFutures(list(reversed(fs))).futures]
    print("RESULT futures", json.dumps([seen, seen_wait, locked]), flush=True)
    # as_completed yields already finished futures from the end of its list
    monotone = lambda xs: xs == sorted(xs) or xs == sorted(xs, reverse=True)
    assert monotone(seen) and monotone(seen_wait) and locked == sorted(locked)
'''


@pytest.mark.skipif(WITHOUT_PROTOTYPE, reason="needs --det-threads")
def test_futures_follow_creation_order_not_addresses(pytester):
    """as_completed/wait iterate sets of futures and _AcquireFutures sorts them by
    id(): under --det-threads all three follow the creation order."""
    pytester.makepyfile(test_fut=FUTURE_ORDER)
    result = pytester.runpytest_subprocess(*FLAGS, "-p", "no:cacheprovider", "-s")
    result.assert_outcomes(passed=1)


EXIT_TEARDOWN = r'''
import threading
from concurrent.futures import ThreadPoolExecutor

def test_many_short_pools():
    out = []
    lock = threading.Lock()
    def job(i):
        with lock:
            out.append(i)
        return i
    for r in range(15):
        with ThreadPoolExecutor(3) as ex:
            list(ex.map(job, range(6)))
    print("RESULT pools", len(out), flush=True)
'''


@pytest.mark.skipif(WITHOUT_PROTOTYPE, reason="needs --det-threads")
def test_thread_exit_is_serialised(pytester):
    """Threads that end while others run: their teardown must not shift the
    seeded choices (an exiting thread used to consume the seeded stream)."""
    pytester.makepyfile(test_exit=EXIT_TEARDOWN)
    fps = set()
    for _ in range(6):
        _, _, fp = _run(pytester, "--det-threads-seed=3")
        fps.add(json.dumps(fp, sort_keys=True))
    assert len(fps) == 1
