"""R-003 T1 extra binding cases (not in tests/test_nonbinding.py).

Builtins stored as class attributes do not bind. Under --det each must keep
working. Run:  python -m pytest -p no:randomly -p no:cacheprovider test_t1_extra.py        (passes)
       and:  python -m pytest --det -p no:randomly -p no:cacheprovider test_t1_extra.py  (should pass too)
"""
import os
import socket
import sys
import threading
import time
import random


class Holder:
    run = os.system                       # builtin; detpy wraps with _mark_external (plain function)
    resolve = socket.gethostbyname        # builtin; detpy replaces with a plain function
    mono = time.monotonic                 # covered by their test (control)
    rnd = random.random                   # covered by their test (control)
    lock_factory = threading.Lock         # builtin before 3.13; their test only runs on 3.13 in CI


def test_os_system_as_class_attribute():
    assert Holder().run("true") == 0


def test_gethostbyname_as_class_attribute():
    assert Holder().resolve("localhost").startswith("127.")


def test_monotonic_and_random_as_class_attribute():
    h = Holder()
    assert isinstance(h.mono(), float) and 0 <= h.rnd() < 1


def test_lock_factory_as_class_attribute():
    with Holder().lock_factory():
        pass
