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


ENTROPY = r'''
import threading, uuid

def test_worker_draws_entropy():
    out = []
    t = threading.Thread(target=lambda: out.append(str(uuid.uuid4())))
    t.start()
    t.join()
    print("UUID", out[0])
'''


def _fingerprint(pytester, *flags):
    import json

    out = pytester.path / "o.json"
    result = pytester.runpytest_subprocess(*flags, f"--det-outcomes={out}", "-p", "no:cacheprovider", "-s", timeout=60)
    result.assert_outcomes(passed=1)
    fps = json.loads(out.read_text())["fingerprints"]
    return next(iter(fps.values()))


def test_det_threads_implies_deterministic_entropy(pytester):
    """--det-threads alone gives one fingerprint for a test whose worker thread
    draws entropy (R-007 FIX 1: it needed --det-urandom too)."""
    pytester.makepyfile(test_inner=ENTROPY)
    runs = {_fingerprint(pytester, "--det", "--det-threads") for _ in range(3)}
    assert len(runs) == 1
    # the opt-out keeps real entropy
    real = {_fingerprint(pytester, "--det", "--det-threads", "--det-threads-real-urandom") for _ in range(2)}
    assert len(real) == 2
