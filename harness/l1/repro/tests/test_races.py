"""Classic asyncio races. Every test is flaky on purpose (timing decides)."""

import asyncio
import socket
import subprocess
import sys
import threading
import time


def run(coro):
    return asyncio.run(coro)


# 1. A sleep used as synchronisation with an executor job.
def test_sleep_as_sync_with_executor():
    async def main():
        loop = asyncio.get_running_loop()
        state = {}

        def work():
            time.sleep(0.002)
            state["done"] = True

        loop.run_in_executor(None, work)
        await asyncio.sleep(0.002)  # "enough for the job"
        return state.get("done", False)

    assert run(main())


# 2. A timeout of the same order as the work it guards.
def test_tight_timeout_on_thread():
    async def main():
        return await asyncio.wait_for(asyncio.to_thread(time.sleep, 0.003), timeout=0.0032)

    run(main())


# 3. The order of results of parallel executor jobs is assumed.
def test_executor_results_in_submission_order():
    async def main():
        loop = asyncio.get_running_loop()
        out = []

        def job(i):
            time.sleep(0.001)
            return i

        async def one(i):
            out.append(await loop.run_in_executor(None, job, i))

        await asyncio.gather(*(one(i) for i in range(3)))
        return out

    assert run(main()) == [0, 1, 2]


# 4. as_completed: the first finished job is assumed to be the first submitted.
def test_as_completed_first_is_first_submitted():
    async def main():
        futs = [asyncio.ensure_future(asyncio.to_thread(lambda i=i: (time.sleep(0.001), i)[1])) for i in range(2)]
        for f in asyncio.as_completed(futs):
            return await f

    assert run(main()) == 0


# 5. A thread signals the loop; the test waits with a tight timeout.
def test_thread_signal_before_timeout():
    async def main():
        loop = asyncio.get_running_loop()
        ev = asyncio.Event()

        def worker():
            time.sleep(0.002)
            loop.call_soon_threadsafe(ev.set)

        threading.Thread(target=worker).start()
        await asyncio.wait_for(ev.wait(), timeout=0.0025)

    run(main())


# 6. Two clients connect; the server is assumed to see them in connection order.
def test_server_sees_clients_in_order():
    async def main():
        seen = []

        async def handle(reader, writer):
            seen.append((await reader.readline()).strip())
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        def client(msg):
            with socket.create_connection(("127.0.0.1", port)) as s:
                time.sleep(0.001)
                s.sendall(msg + b"\n")
                s.recv(1)

        ts = [threading.Thread(target=client, args=(m,)) for m in (b"a", b"b")]
        for t in ts:
            t.start()
            time.sleep(0.0002)  # a starts first
        while len(seen) < 2:
            await asyncio.sleep(0.001)
        for t in ts:
            await asyncio.to_thread(t.join)
        server.close()
        await server.wait_closed()
        return seen

    assert run(main()) == [b"a", b"b"]


# 7. Cancellation races with completion of an executor job.
def test_cancel_before_job_finishes():
    async def main():
        task = asyncio.ensure_future(asyncio.to_thread(time.sleep, 0.002))
        await asyncio.sleep(0.002)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return "cancelled"
        return "finished"

    assert run(main()) == "cancelled"


# 8. FIRST_COMPLETED between a job and a timer of the same duration.
def test_first_completed_job_beats_timer():
    async def main():
        job = asyncio.ensure_future(asyncio.to_thread(time.sleep, 0.002))
        timer = asyncio.ensure_future(asyncio.sleep(0.0021))
        done, pending = await asyncio.wait({job, timer}, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
        return job in done

    assert run(main())


# 9. A subprocess is assumed to answer within a short timeout.
def test_subprocess_answers_quickly():
    async def main():
        p = await asyncio.create_subprocess_exec(sys.executable, "-c", "print(1)", stdout=subprocess.PIPE)
        out, _ = await asyncio.wait_for(p.communicate(), timeout=0.05)
        return out.strip()

    assert run(main()) == b"1"


# 10. A producer thread feeds an asyncio.Queue; the consumer expects items in time.
def test_queue_fed_by_thread():
    async def main():
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()

        def producer():
            for i in range(3):
                time.sleep(0.0005)
                loop.call_soon_threadsafe(q.put_nowait, i)

        threading.Thread(target=producer).start()
        got = []
        for _ in range(3):
            got.append(await asyncio.wait_for(q.get(), timeout=0.0006))
        return got

    assert run(main()) == [0, 1, 2]


# 11. A rate limiter counts calls within a window measured with loop.time().
def test_rate_limiter_window():
    async def main():
        loop = asyncio.get_running_loop()
        calls = []
        for _ in range(5):
            calls.append(loop.time())
            await asyncio.to_thread(time.sleep, 0.0002)
        return sum(1 for c in calls if c - calls[0] < 0.001)

    assert run(main()) == 5


# 12. Two tasks append after "the same" delay computed from CPU work.
def test_ordered_appends_after_work():
    async def main():
        out = []

        async def a():
            await asyncio.to_thread(sum, range(20000))
            await asyncio.sleep(0.001)
            out.append("a")

        async def b():
            await asyncio.sleep(0.0012)
            out.append("b")

        await asyncio.gather(a(), b())
        return out

    assert run(main()) == ["a", "b"]


# 13. Readers on several sockets written by threads; order assumed.
def test_readers_see_writes_in_order():
    async def main():
        loop = asyncio.get_running_loop()
        pairs = [socket.socketpair() for _ in range(2)]
        got = []
        done = asyncio.Event()
        for i, (a, b) in enumerate(pairs):
            a.setblocking(False)

            def cb(i=i, a=a):
                a.recv(8)
                loop.remove_reader(a)
                got.append(i)
                if len(got) == 2:
                    done.set()

            loop.add_reader(a, cb)

        def writer(i, b):
            time.sleep(0.001 + 0.0001 * i)
            b.send(b"x")

        for i, (_, b) in enumerate(pairs):
            threading.Thread(target=writer, args=(i, b)).start()
        await asyncio.wait_for(done.wait(), 5)
        for a, b in pairs:
            a.close()
            b.close()
        return got

    assert run(main()) == [0, 1]


# 14. A lock handed between tasks; one task does blocking work in a thread.
def test_lock_order_with_thread_work():
    async def main():
        lock = asyncio.Lock()
        order = []

        async def holder(name, work):
            await asyncio.to_thread(time.sleep, work)
            async with lock:
                order.append(name)

        await asyncio.gather(holder("x", 0.001), holder("y", 0.001))
        return order

    assert run(main()) == ["x", "y"]
