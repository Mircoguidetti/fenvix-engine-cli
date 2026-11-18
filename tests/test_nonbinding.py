"""T1 (django-oauth-toolkit / DRF throttling): `timer = time.time` as a class attribute.

The builtins detpy replaces do not bind as methods (builtins, bound methods); a
replacement that is a plain Python function does, and `self.timer()` then fails
with "time() takes 0 positional arguments but 1 was given" only under --det.
"""
import sys


def test_replacements_do_not_bind_as_methods(pytester, run_det):
    pytester.makepyfile(
        test_bind="""
        import os, random, threading, time, sys

        class Holder:
            timer = time.time
            mono = time.monotonic
            perf = time.perf_counter
            tns = time.time_ns
            sleeper = time.sleep
            urandom = os.urandom
            listdir = os.listdir
            scandir = os.scandir
            rnd = random.random
            randint = random.randint
            choice = random.choice
            seed = random.seed
            if sys.version_info < (3, 13):
                lock_factory = threading.Lock

        def test_called_through_an_instance():
            h = Holder()
            assert isinstance(h.timer(), float)
            assert isinstance(h.mono(), float) and isinstance(h.perf(), float) and isinstance(h.tns(), int)
            h.sleeper(0)
            assert len(h.urandom(4)) == 4
            assert isinstance(h.listdir("."), list)
            list(h.scandir("."))
            assert 0 <= h.rnd() < 1 and 1 <= h.randint(1, 3) <= 3 and h.choice([5]) == 5
            h.seed(1)
            if sys.version_info < (3, 13):
                with h.lock_factory():
                    pass

        def test_still_pickle_by_reference():
            import pickle
            assert pickle.loads(pickle.dumps(time.time)) is time.time
            assert pickle.loads(pickle.dumps(os.urandom)) is os.urandom
        """
    )
    pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "no:randomly").assert_outcomes(passed=2)
    result, _ = run_det("-p", "no:randomly")
    result.assert_outcomes(passed=2)
