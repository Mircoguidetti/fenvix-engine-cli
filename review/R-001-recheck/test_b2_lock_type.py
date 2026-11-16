"""B2: next failure after the fix of item 2 (threading.Lock stand-in is a type on 3.13+)."""
import sys

import pytest

CHECKS = {
    "isinstance_lock": "isinstance(threading.Lock(), threading.Lock)",
    "isinstance_allocate": "isinstance(_thread.allocate_lock(), threading.Lock)",
    "issubclass_LockType": "issubclass(_thread.LockType, threading.Lock)",
    "issubclass_type_of_lock": "issubclass(type(threading.Lock()), threading.Lock)",
    "isinstance_real_LockType": "isinstance(threading.Lock(), _thread.LockType)",
    "rlock_not_lock": "not isinstance(threading.RLock(), threading.Lock)",
    "issubclass_int": "not issubclass(int, threading.Lock)",
    "isinstance_obj": "not isinstance(object(), threading.Lock)",
    "with_ok": "(lambda l: (l.acquire(), l.release(), True)[2])(threading.Lock())",
    "condition": "threading.Condition(threading.Lock()) is not None",
}


@pytest.mark.skipif(sys.version_info < (3, 13), reason="threading.Lock is a class only from Python 3.13")
@pytest.mark.parametrize("name", sorted(CHECKS))
def test_lock_checks_match_normal(pytester, run_det, name):
    pytester.makepyfile(test_l=f"""
        import threading, _thread
        def test_check():
            assert {CHECKS[name]}
        """)
    normal = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "no:randomly")
    det, _ = run_det("-p", "no:randomly")
    assert (normal.ret, det.ret) == (0, 0), (normal.ret, det.ret, det.stdout.str()[-600:])
