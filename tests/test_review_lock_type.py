"""R-001 review: failing test on fenvix-engine-cli 0aef0ae (copy into tests/; uses tests/conftest.py).

Why it matters: c776b6f replaces threading.Lock with a factory function under --det. From Python
3.13 threading.Lock is a class, so `isinstance(x, threading.Lock)` is legal code that passes
normally and raises TypeError under --det: a false failure introduced by an L0 fix. (Libraries
that build validators from the type, e.g. pydantic arbitrary types, are a plausible but unverified
extension of the same problem.)
"""
import sys

import pytest


@pytest.mark.skipif(sys.version_info < (3, 13), reason="threading.Lock is a class only from Python 3.13")
def test_threading_lock_stays_a_type_under_det(pytester, run_det):
    pytester.makepyfile(
        test_l="""
        import threading
        def test_lock_is_a_lock():
            assert isinstance(threading.Lock(), threading.Lock)
        """
    )
    pytester.runpytest_subprocess("-p", "no:cacheprovider").assert_outcomes(passed=1)
    result, _ = run_det("-p", "no:randomly")
    # Fails on 0aef0ae: TypeError: isinstance() arg 2 must be a type, a tuple of types, or a union
    result.assert_outcomes(passed=1)
