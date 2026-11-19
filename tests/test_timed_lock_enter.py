"""parallel-proof round 3, item 8: pydantic-ai's flaky verdict under ``--det``.

``test_one_capability_serves_runs_on_several_event_loops_and_threads`` failed in one of three ``--det -n 4`` runs (and,
MEASURED locally, in 3 of 15 serial ``--det`` runs, 0 of 15 plain) with blockbuster's ``BlockingError('Blocking call to
lock.acquire')``. Traceback: ``pydantic_ai/_uuid.py`` ``uuid7`` -> ``with _lock_v7:`` -> detpy's ``_TimedLock.__enter__``
-> ``acquire`` -> blockbuster's wrapper. ``_lock_v7`` is a module-level ``threading.Lock()`` created under ``--det``,
so it is Level 0's ``_TimedLock``. A plain ``with lock:`` enters through the lock type's ``__enter__`` slot, which
blockbuster does not wrap; ``_TimedLock.__enter__`` called the Python-visible ``acquire``, which it does. blockbuster
raises only when the acquire would block (``lock.locked()``): with the test's four threads contending for the lock,
which happens by timing. Fix: ``_TimedLock.__enter__`` enters the real lock through its ``__enter__`` (a ``with`` has
no timeout, so there is nothing for the virtual clock to do).
"""

import threading

from detpy.clock import _TimedLock


class _Spy:
    """A lock whose ``acquire`` must not be called by ``with`` (blockbuster's view of ``_thread.lock.acquire``)."""

    def __init__(self):
        self.real = threading._allocate_lock()  # the real lock type, whatever Level 0 patched
        self.acquire_calls = 0

    def acquire(self, *a, **k):
        self.acquire_calls += 1
        return self.real.acquire(*a, **k)

    def release(self):
        self.real.release()

    def __enter__(self):
        return self.real.__enter__()

    def __exit__(self, *exc):
        return self.real.__exit__(*exc)

    def locked(self):
        return self.real.locked()


def test_with_a_timed_lock_enters_through_the_real_enter_not_acquire():
    spy = _Spy()
    lock = _TimedLock(spy)
    with lock:
        assert spy.locked()
    assert not spy.locked()
    assert spy.acquire_calls == 0
    # an explicit acquire (which may carry a timeout) still goes through acquire
    assert lock.acquire(timeout=0.01)
    lock.release()
    assert spy.acquire_calls == 1


def test_timed_lock_with_statement_still_excludes_other_threads():
    lock = _TimedLock(threading._allocate_lock())
    seen = []

    def worker(i):
        for _ in range(200):
            with lock:
                seen.append(i)
                seen.append(i)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(seen[k] == seen[k + 1] for k in range(0, len(seen), 2))
