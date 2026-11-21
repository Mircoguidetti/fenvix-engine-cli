"""What --det-threads / --det-async may and may not claim (PY-07).

The rule in one line: a test whose threads the scheduler controls throughout becomes provable, and a test where
it loses control of a thread stays NOT PROVEN. Never the other way round. These tests pin both directions,
including the cases where the scheduler is active but does *not* take a thread: those must keep the mark, because
suppressing it there would claim a control we do not have.
"""

import json

L1 = ("--det-threads", "--det-async")


def ops(rec) -> list:
    return [e["o"] for e in rec["events"]]


def one_test(trace) -> dict:
    _, tests, _ = trace
    assert len(tests) == 1, sorted(tests)
    return next(iter(tests.values()))


THREADS = '''
import threading


def test_threads():
    out = []

    def work(i):
        out.append(i)
    ts = [threading.Thread(target=work, args=(i,)) for i in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out) == [0, 1, 2]
'''


def test_scheduled_threads_are_a_run_input(pytester, run_det):
    """With --det-threads the scheduler records its choices and the test is not marked."""
    pytester.makepyfile(test_probe=THREADS)
    result, trace = run_det(*L1, "test_probe.py")
    result.assert_outcomes(passed=1)
    o = ops(one_test(trace))
    assert "sched.thread" in o, o
    assert "uncontrolled.thread" not in o, o


def test_threads_without_the_option_are_marked(pytester, run_det):
    """Level 0 alone observes threads without controlling them: the mark must stay."""
    pytester.makepyfile(test_probe=THREADS)
    result, trace = run_det("test_probe.py")
    result.assert_outcomes(passed=1)
    o = ops(one_test(trace))
    assert "uncontrolled.thread" in o, o
    assert "sched.thread" not in o, o


ESCAPE = '''
import os, threading


def test_escape():
    r, w = os.pipe()
    got = []

    def worker():
        got.append(os.read(r, 4))     # blocks in C, where the scheduler cannot see it
    t = threading.Thread(target=worker)
    t.start()
    os.write(w, b"ping")
    t.join()
    os.close(r)
    os.close(w)
    assert got == [b"ping"]
'''


def test_escaped_thread_is_marked_again(pytester, run_det):
    """A thread that blocks in C is escaped: the scheduler says so and the test is NOT PROVEN after all."""
    pytester.makepyfile(test_probe=ESCAPE)
    result, trace = run_det(*L1, "test_probe.py")
    result.assert_outcomes(passed=1)
    o = ops(one_test(trace))
    assert "threads.uncontrolled" in o, o  # the scheduler's own record of where it lost control
    assert "uncontrolled.thread" in o, o  # and the mark the verifier reads


# A thread that existed before the test is not managed, so a thread *it* starts is not managed either
# (``threads._wrap_start_thread``: it adopts a thread only when the thread starting it is itself managed). The
# test must keep the mark: this is the case a predicate of "the scheduler is active" alone would get wrong.
UNMANAGED_PARENT = '''
import threading

ready = threading.Event()
go = threading.Event()
done = threading.Event()
seen = []


def _pool_worker():
    """Started at import, before any test: unmanaged for the whole session."""
    ready.set()
    go.wait(30)

    def child():
        seen.append(1)
    t = threading.Thread(target=child)   # started by an unmanaged thread
    t.start()
    t.join()
    done.set()


_T = threading.Thread(target=_pool_worker, daemon=True)
_T.start()
ready.wait(30)


def test_unmanaged_parent_starts_a_thread():
    go.set()
    assert done.wait(30)
    assert seen == [1]
'''


def test_thread_started_by_an_unmanaged_thread_is_marked(pytester, run_det):
    pytester.makepyfile(test_probe=UNMANAGED_PARENT)
    result, trace = run_det(*L1, "test_probe.py")
    result.assert_outcomes(passed=1)
    o = ops(one_test(trace))
    assert "uncontrolled.thread" in o, o


ASYNC_INTERNAL = '''
import asyncio


def test_internal_loop():
    out = []

    async def main():
        await asyncio.sleep(0)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, out.append, 1)
    asyncio.run(main())
    assert out == [1]
'''


def test_scheduled_loop_io_is_a_run_input(pytester, run_det):
    """--det-async chooses the delivery order of the loop's own wake-ups and records it: no io mark."""
    pytester.makepyfile(test_probe=ASYNC_INTERNAL)
    result, trace = run_det(*L1, "test_probe.py")
    result.assert_outcomes(passed=1)
    o = ops(one_test(trace))
    assert "uncontrolled.io" not in o, o


OUTPROC = '''
import asyncio, subprocess, sys


def test_outproc_peer():
    code = ("import socket;s=socket.socket();s.bind(('127.0.0.1',0));s.listen(1);"
            "print(s.getsockname()[1],flush=True);c,_=s.accept();c.sendall(b'HI');c.close()")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    port = int(p.stdout.readline().strip())
    got = []

    async def main():
        r, w = await asyncio.open_connection("127.0.0.1", port)
        got.append(await r.read(10))
        w.close()
    asyncio.run(main())
    p.wait()
    assert got == [b"HI"]
'''


def test_a_server_outside_the_process_is_still_uncontrolled(pytester, run_det):
    """L1 does not control a live socket: that bucket keeps its mark, whatever the schedulers do."""
    pytester.makepyfile(test_probe=OUTPROC)
    result, trace = run_det(*L1, "test_probe.py")
    result.assert_outcomes(passed=1)
    o = ops(one_test(trace))
    assert "uncontrolled.net" in o, o
    assert "uncontrolled.child" in o, o


def test_the_options_need_det(pytester):
    """--det-threads / --det-async without --det is an error, not a silent no-op (audit G-1532)."""
    pytester.makepyfile(test_probe="def test_x():\n    pass\n")
    for flag in ("--det-threads", "--det-async"):
        r = pytester.runpytest_subprocess(flag, "-p", "no:cacheprovider", "test_probe.py")
        assert r.ret != 0, flag
        assert "needs --det" in (r.stdout.str() + r.stderr.str()), flag
