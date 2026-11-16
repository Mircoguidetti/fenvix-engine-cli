"""Level 1 prototype: deterministic asyncio scheduling (``--det-async``).

The race tests below are written so that, without the prototype, the printed
results differ between two runs (timing decides), and with it they are a pure
function of the seed. To see them fail without the prototype run::

    DETPY_ASYNC_FLAGS="--det" pytest tests/test_aio.py

(``--det`` alone: Level 0 only; the asyncio loop keeps real time and real
thread timing.)
"""

import json
import os
import sys

import pytest

FLAGS = os.environ.get("DETPY_ASYNC_FLAGS", "--det --det-async").split()
WITHOUT_PROTOTYPE = "--det-async" not in FLAGS

RACES = r'''
import asyncio, json, socket, threading, time

def emit(name, value):
    print(f"RESULT {name} {json.dumps(value)}", flush=True)

def test_executor_results():
    """Executor results: delivery order of jobs that take the same time."""
    async def main():
        loop = asyncio.get_running_loop()
        order = []
        def job(n):
            time.sleep(0.001)
            return n
        async def run(n):
            order.append(await loop.run_in_executor(None, job, n))
        await asyncio.gather(*(run(i) for i in range(6)))
        return order
    emit("executor", [asyncio.run(main()) for _ in range(15)])

def test_timeout_race():
    """Timers: a timeout that races with a chain of callbacks."""
    async def work():
        for _ in range(20):
            await asyncio.sleep(0)
        return 1
    async def main(t):
        try:
            return await asyncio.wait_for(work(), timeout=t)
        except asyncio.TimeoutError:
            return 0
    emit("timeout", [asyncio.run(main(t * 2e-5)) for t in range(1, 60)])

def test_io_readiness():
    """I/O readiness: several sockets become readable while the loop is busy."""
    async def main():
        loop = asyncio.get_running_loop()
        pairs = [socket.socketpair() for _ in range(5)]
        got = []
        for i, (a, b) in enumerate(pairs):
            a.setblocking(False)
            def cb(i=i, a=a):
                a.recv(16)
                got.append(i)
                loop.remove_reader(a)
            loop.add_reader(a, cb)
        def writer(b):
            time.sleep(0.0005)
            b.send(b"x")
        threads = [threading.Thread(target=writer, args=(b,)) for _, b in pairs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()  # the loop is blocked: all sockets are ready at the next poll
        while len(got) < len(pairs):
            await asyncio.sleep(0)
        for a, b in pairs:
            a.close()
            b.close()
        return got
    emit("io", [asyncio.run(main()) for _ in range(10)])

def test_threadsafe_callbacks():
    """call_soon_threadsafe from several threads while the loop is busy."""
    async def main():
        loop = asyncio.get_running_loop()
        got = []
        def worker(i):
            time.sleep(0.0005)
            loop.call_soon_threadsafe(got.append, i)
        threads = [threading.Thread(target=worker, args=(i,), name=f"w{i}") for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        while len(got) < 5:
            await asyncio.sleep(0)
        return got
    emit("threadsafe", [asyncio.run(main()) for _ in range(10)])

def test_job_vs_timer():
    """An executor job and a timer of (almost) the same duration."""
    async def main(d):
        loop = asyncio.get_running_loop()
        first = []
        async def timer():
            await asyncio.sleep(d)
            first.append("timer")
        async def job():
            await loop.run_in_executor(None, time.sleep, 0.001)
            first.append("job")
        await asyncio.gather(timer(), job())
        return first[0]
    emit("job_vs_timer", [asyncio.run(main(0.001 + k * 1e-5)) for k in range(-10, 10)])
'''

RACE_NAMES = ("executor", "timeout", "io", "threadsafe", "job_vs_timer")


def _run(pytester, *extra, flags=None):
    args = list(FLAGS if flags is None else flags) + ["-s", "-p", "no:cacheprovider", *extra]
    result = pytester.runpytest_subprocess(*args)
    out = {}
    for line in result.stdout.lines:
        if "RESULT " in line:
            _, name, value = line[line.index("RESULT "):].split(" ", 2)
            out[name] = json.loads(value)
    return result, out


@pytest.fixture
def races(pytester):
    pytester.makepyfile(test_races=RACES)
    return pytester


def test_det_async_needs_det(pytester):
    pytester.makepyfile(test_a="def test_a():\n    pass\n")
    result = pytester.runpytest_subprocess("--det-async", "-p", "no:cacheprovider")
    assert result.ret != 0
    result.stderr.fnmatch_lines(["*--det-async needs --det*"])


@pytest.mark.parametrize("seed", ["0", "3"])
def test_races_are_reproducible(races, seed):
    """Same seed, same results, in every race (fails without the prototype)."""
    r1, a = _run(races, f"--det-async-seed={seed}" if not WITHOUT_PROTOTYPE else f"--det-seed={seed}")
    r2, b = _run(races, f"--det-async-seed={seed}" if not WITHOUT_PROTOTYPE else f"--det-seed={seed}")
    r3, c = _run(races, f"--det-async-seed={seed}" if not WITHOUT_PROTOTYPE else f"--det-seed={seed}")
    assert r1.ret == 0 and r2.ret == 0 and r3.ret == 0
    assert set(a) == set(RACE_NAMES)
    differing = [n for n in RACE_NAMES if not (a[n] == b[n] == c[n])]
    assert differing == [], f"results differ between runs with the same seed: {differing}"


def test_seeds_explore_orders(races):
    """Different seeds reach different orders, each one replayable."""
    if WITHOUT_PROTOTYPE:
        pytest.fail("needs --det-async: without it there is no seed for the asyncio schedule")
    seen = {n: set() for n in RACE_NAMES}
    for seed in range(1, 7):
        _, out = _run(races, f"--det-async-seed={seed}")
        for n in RACE_NAMES:
            seen[n].add(json.dumps(out[n]))
    # The timeout race outcome is a threshold; all others are orders.
    assert all(len(v) >= 2 for v in seen.values()), {k: len(v) for k, v in seen.items()}


def test_fingerprint_names_first_diverging_choice(races, tmp_path):
    from detpy import _core

    if WITHOUT_PROTOTYPE:
        pytest.fail("needs --det-async: without it no scheduling choice is recorded")
    traces = []
    for i, seed in enumerate((1, 1, 2)):
        t = str(tmp_path / f"t{i}.jsonl")
        _run(races, f"--det-async-seed={seed}", f"--det-trace={t}", "-k", "executor")
        traces.append(t)
    same = json.loads(_core.verify(traces[:2]))
    assert same["summary"]["diverged"] == 0 and same["summary"]["stable"] == 1
    diff = json.loads(_core.verify([traces[0], traces[2]]))
    d = diff["tests"][0]["divergence"]
    assert d["reason"] == "sched"
    assert "first diverging scheduling choice" in d["description"]
    assert "executor=[" in d["description"]


# ---------------------------------------------------------------------------
# Ordinary asyncio code must keep working (no false failures) with any seed.
SEMANTICS = r'''
import asyncio, subprocess, sys, threading, time
import pytest

def run(coro):
    return asyncio.run(coro)

def test_streams_server_and_client():
    async def main():
        async def handle(r, w):
            data = await r.readline()
            w.write(data.upper())
            await w.drain()
            w.close()
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        results = []
        async def client(i):
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(f"hello {i}\n".encode())
            await w.drain()
            results.append(await r.readline())
            w.close()
        await asyncio.gather(*(client(i) for i in range(5)))
        server.close()
        await server.wait_closed()
        return sorted(results)
    assert run(main()) == [f"HELLO {i}\n".encode() for i in range(5)]

def test_subprocess_with_timeout():
    async def main():
        p = await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(0.2); print('ok')",
                                                 stdout=subprocess.PIPE)
        out, _ = await asyncio.wait_for(p.communicate(), timeout=30)
        return out.strip(), p.returncode
    assert run(main()) == (b"ok", 0)

def test_to_thread_and_executor():
    async def main():
        a = await asyncio.to_thread(sum, range(10))
        b = await asyncio.get_running_loop().run_in_executor(None, time.sleep, 0.01)
        return a, b
    assert run(main()) == (45, None)

def test_job_calls_back_into_loop():
    async def double(x):
        await asyncio.sleep(0.01)
        return 2 * x
    async def main():
        loop = asyncio.get_running_loop()
        def job():
            return asyncio.run_coroutine_threadsafe(double(21), loop).result(timeout=10)
        return await loop.run_in_executor(None, job)
    assert run(main()) == 42

def test_timeouts_and_cancellation():
    async def main():
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.sleep(10), timeout=0.01)
        t = asyncio.ensure_future(asyncio.sleep(10))
        await asyncio.sleep(0)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        t0 = time.monotonic()
        await asyncio.sleep(3600)  # virtual: does not wait
        assert time.monotonic() - t0 >= 3600
    run(main())

def test_queue_producer_consumer():
    async def main():
        q = asyncio.Queue(maxsize=2)
        got = []
        async def producer():
            for i in range(20):
                await q.put(i)
                await asyncio.sleep(0.001)
            await q.put(None)
        async def consumer():
            while (x := await q.get()) is not None:
                got.append(x)
        await asyncio.gather(producer(), consumer())
        return got
    assert run(main()) == list(range(20))

def test_thread_sets_event_through_loop():
    async def main():
        loop = asyncio.get_running_loop()
        ev = asyncio.Event()
        threading.Thread(target=lambda: (time.sleep(0.05), loop.call_soon_threadsafe(ev.set))).start()
        await asyncio.wait_for(ev.wait(), timeout=5)
        return True
    assert run(main())

def test_getaddrinfo():
    async def main():
        return await asyncio.get_running_loop().getaddrinfo("127.0.0.1", 80)
    assert run(main())

def test_gather_many_sleepers():
    async def sleeper(i):
        await asyncio.sleep(0.01 * (i % 5))
        return i
    async def main():
        return await asyncio.gather(*(sleeper(i) for i in range(100)))
    assert run(main()) == list(range(100))
'''

SEMANTICS_311 = r'''
import asyncio, pytest

def test_taskgroup_and_timeout():
    async def main():
        async with asyncio.TaskGroup() as tg:
            ts = [tg.create_task(asyncio.sleep(0.01, result=i)) for i in range(5)]
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.05):
                await asyncio.sleep(1)
        return [t.result() for t in ts]
    assert asyncio.run(main()) == list(range(5))
'''

PLUGINS = r'''
import asyncio, pytest

@pytest.mark.asyncio
async def test_pytest_asyncio():
    await asyncio.sleep(0.01)
    assert asyncio.get_running_loop().time() > 0

@pytest.mark.anyio
async def test_anyio_asyncio_backend():
    import anyio
    with anyio.fail_after(5):
        await anyio.sleep(0.01)

@pytest.fixture
def anyio_backend():
    return "asyncio"
'''


@pytest.mark.parametrize("seed", ["0", "1", "2", "5"])
def test_ordinary_asyncio_code_passes(pytester, seed):
    if WITHOUT_PROTOTYPE:
        pytest.skip("checks the prototype for false failures (sleep(3600) would really wait)")
    pytester.makepyfile(test_semantics=SEMANTICS)
    if sys.version_info >= (3, 11):
        pytester.makepyfile(test_semantics311=SEMANTICS_311)
    result = pytester.runpytest_subprocess(*FLAGS, f"--det-seed={seed}", "-p", "no:cacheprovider")
    outcomes = result.parseoutcomes()
    assert outcomes.get("failed", 0) == 0 and outcomes.get("error", 0) == 0, result.stdout.str()[-3000:]


def test_pytest_asyncio_and_anyio(pytester):
    if WITHOUT_PROTOTYPE:
        pytest.skip("checks the prototype for false failures")
    pytest.importorskip("pytest_asyncio")
    pytest.importorskip("anyio")
    pytester.makepyfile(test_plugins=PLUGINS)
    result = pytester.runpytest_subprocess(*FLAGS, "--det-seed=4", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=2)


def test_header_reports_seed(pytester):
    if WITHOUT_PROTOTYPE:
        pytest.skip("header only shown with --det-async")
    pytester.makepyfile(test_a="def test_a():\n    pass\n")
    result = pytester.runpytest_subprocess(*FLAGS, "--det-async-seed=7", "-p", "no:cacheprovider")
    result.stdout.fnmatch_lines(["*--det-async (Level 1 prototype): asyncio scheduler seed 7 (exploring)*"])
