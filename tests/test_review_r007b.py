"""Review R-007 round 2 (FIX 4 re-check): detpy frames must stay invisible to stack
inspection of other threads, below the top frame as well.

The delivered fix (python/detpy/frames.py) hides detpy frames at the top of each
thread's stack. Under --det-threads every managed worker still has detpy's
``threads.py boot`` frame at the bottom of its stack, under threading's
``_bootstrap``. Code that walks or prints another thread's whole stack (thread dumps,
``traceback.extract_stack(sys._current_frames()[ident])``) sees a detpy frame that a
plain run and a --det run do not show. This is the defect class of R-007 FIX 4.
"""

import pytest

INNER = r'''
import sys, threading, time, traceback

def test_full_stack_of_a_worker_has_no_detpy_frame():
    started = threading.Event()
    def worker():
        started.set()
        time.sleep(0.3)
    t = threading.Thread(target=worker)
    t.start()
    started.wait()
    time.sleep(0.05)  # the worker is inside time.sleep now
    stack = traceback.extract_stack(sys._current_frames()[t.ident])
    t.join()
    detpy = [(f.filename, f.name) for f in stack if "/detpy/" in f.filename]
    assert not detpy, detpy
'''


@pytest.mark.parametrize("flags", [[], ["--det"], ["--det", "--det-threads"]], ids=["plain", "det", "det-threads"])
def test_whole_stack_of_another_thread_does_not_see_detpy(pytester, flags):
    pytester.makepyfile(test_inner=INNER)
    result = pytester.runpytest_subprocess(*flags, "-p", "no:cacheprovider", timeout=60)
    result.assert_outcomes(passed=1)
