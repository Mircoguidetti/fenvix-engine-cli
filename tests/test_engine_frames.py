"""detpy's frames are invisible to code that inspects other threads' stacks
(review R-007 FIX 4: easypy test_multiobject_logging passes in plain pytest and
failed under --det and --det-threads because the worker's top frame was detpy's)."""

import pytest

INNER = r'''
import sys, threading, time

def test_a_sleeping_thread_shows_its_own_frame():
    started = threading.Event()
    done = threading.Event()
    def worker():
        started.set()
        time.sleep(0.3)
        done.set()
    t = threading.Thread(target=worker)
    t.start()
    started.wait()
    time.sleep(0.05)  # the worker is inside time.sleep now
    frame = sys._current_frames()[t.ident]
    t.join()
    assert frame.f_code.co_name == "worker", (frame.f_code.co_filename, frame.f_code.co_name)
    for f in sys._current_frames().values():
        assert "/detpy/" not in f.f_code.co_filename
'''


@pytest.mark.parametrize("flags", [[], ["--det"], ["--det", "--det-threads"]], ids=["plain", "det", "det-threads"])
def test_stack_inspection_does_not_see_detpy(pytester, flags):
    pytester.makepyfile(test_inner=INNER)
    result = pytester.runpytest_subprocess(*flags, "-p", "no:cacheprovider", timeout=60)
    result.assert_outcomes(passed=1)
