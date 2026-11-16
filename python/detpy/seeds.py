"""Fixed seeds for ``random`` and ``numpy`` plus observation of OS entropy.

* The global ``random`` generator is re-seeded at the start of every test with
  ``derive_seed(base_seed, nodeid)``: a test draws the same numbers whatever
  its position in the run.
* ``random.Random()`` created without a seed (and ``numpy.random.default_rng()``)
  get a deterministic seed derived from the test and a per-test counter.
* ``Random`` instances created before detpy was installed (by plugins) are
  re-seeded once.
* ``os.urandom`` / ``SystemRandom`` / ``uuid4`` / ``secrets`` are *observed*
  (their output is digested into the fingerprint) but not controlled, unless
  ``--det-urandom`` is given.
"""

from __future__ import annotations

import gc
import os
import random
import sys

from . import _core, _state
from ._patch import Patcher

_real_seed = random.Random.seed
_real_urandom = os.urandom
_counter = {"n": 0}
_urandom_rng: random.Random | None = None

_NUMERIC = ("random", "uniform", "randint", "randrange", "getrandbits", "gauss", "normalvariate",
            "lognormvariate", "expovariate", "vonmisesvariate", "gammavariate", "triangular",
            "betavariate", "paretovariate", "weibullvariate", "binomialvariate")
_SEQUENCE = ("choice", "choices", "sample", "shuffle")


def _key(tag: str) -> str:
    return f"{_state.STATE.nodeid or '<session>'}\0{tag}\0{_counter['n']}"


def _seed(self, a=None, version=2):
    if a is None and not isinstance(self, random.SystemRandom):
        a = _core.derive_seed(_state.STATE.config.seed, _key("Random"))
        _counter["n"] += 1
        _state.record("random", "Random.seed(None)", str(a))
    return _real_seed(self, a, version)


def _wrap_numeric(name, fn):
    def wrapper(*args, **kwargs):
        value = fn(*args, **kwargs)
        _state.record("random", f"random.{name}", repr(value))
        return value

    wrapper.__name__ = name
    wrapper.__doc__ = fn.__doc__
    wrapper.__wrapped__ = fn
    return wrapper


def _wrap_sequence(name, fn):
    def wrapper(*args, **kwargs):
        value = fn(*args, **kwargs)
        n = len(args[0]) if args and hasattr(args[0], "__len__") else -1
        _state.record("random", f"random.{name}", f"n={n}")
        return value

    wrapper.__name__ = name
    wrapper.__doc__ = fn.__doc__
    wrapper.__wrapped__ = fn
    return wrapper


def _module_seed(fn):
    def seed(a=None, version=2):
        if a is None:
            a = _core.derive_seed(_state.STATE.config.seed, _key("random.seed"))
            _counter["n"] += 1
        _state.record("random", "random.seed", repr(a) if isinstance(a, (int, str)) else type(a).__name__)
        return fn(a, version)

    seed.__wrapped__ = fn
    return seed


def _urandom(n):
    if _urandom_rng is not None:
        data = _urandom_rng.randbytes(n)
    else:
        data = _real_urandom(n)
    _state.record("entropy", "os.urandom", f"{n}:{_core.digest(data)}")
    return data


def install(patcher: Patcher, control_urandom: bool) -> None:
    global _urandom_rng
    patcher.set(random.Random, "seed", _seed)
    inst = random._inst
    for name in _NUMERIC:
        if hasattr(random, name):
            patcher.set(random, name, _wrap_numeric(name, getattr(inst, name)))
    for name in _SEQUENCE:
        if hasattr(random, name):
            patcher.set(random, name, _wrap_sequence(name, getattr(inst, name)))
    if hasattr(inst, "randbytes"):
        rb = inst.randbytes

        def randbytes(n):
            data = rb(n)
            _state.record("random", "random.randbytes", _core.digest(data))
            return data

        patcher.set(random, "randbytes", randbytes)
    patcher.set(random, "seed", _module_seed(inst.seed))
    patcher.set(os, "urandom", _urandom)
    patcher.set(random, "_urandom", _urandom)  # SystemRandom / secrets
    if control_urandom:
        _urandom_rng = random.Random()
        _real_seed(_urandom_rng, _core.derive_seed(_state.STATE.config.seed, "<urandom>"))
    # Generators created before installation (plugins, imported libraries).
    preexisting = 0
    for obj in gc.get_objects():
        if isinstance(obj, random.Random) and not isinstance(obj, random.SystemRandom) and obj is not inst:
            _real_seed(obj, _core.derive_seed(_state.STATE.config.seed, "<preexisting>"))
            preexisting += 1
    _state.STATE.installed.append(f"random(preexisting={preexisting})")


def uninstall() -> None:
    global _urandom_rng
    _urandom_rng = None


def _numpy_default_rng(real):
    def default_rng(seed=None):
        if seed is None:
            seed = _core.derive_seed(_state.STATE.config.seed, _key("default_rng"))
            _counter["n"] += 1
            _state.record("random", "numpy.default_rng(None)", str(seed))
        return real(seed)

    default_rng.__wrapped__ = real
    return default_rng


_numpy_patched: list = []


def start_test(patcher: Patcher, nodeid: str) -> None:
    """Re-seed every generator for ``nodeid``."""
    base = _state.STATE.config.seed
    _counter["n"] = 0
    s = _core.derive_seed(base, nodeid)
    _real_seed(random._inst, s)
    if _urandom_rng is not None:
        _real_seed(_urandom_rng, _core.derive_seed(base, nodeid + "\0urandom"))
    # Fresh temporary-name generator: names depend on the test, not on history.
    tempfile = sys.modules.get("tempfile")
    if tempfile is not None and hasattr(tempfile, "_name_sequence"):
        tempfile._name_sequence = None
    np = sys.modules.get("numpy")
    if np is not None and hasattr(np, "random"):
        try:
            np.random.seed(s & 0xFFFFFFFF)
            if not _numpy_patched and hasattr(np.random, "default_rng"):
                patcher.set(np.random, "default_rng", _numpy_default_rng(np.random.default_rng))
                _numpy_patched.append(True)
        except Exception:  # pragma: no cover - exotic numpy builds
            pass


def end_test() -> None:
    """Record a digest of the final generator states (cheap, once per test)."""
    _state.record_at("random", "random.state", "<end>", _core.digest(repr(random._inst.getstate()).encode()))
    np = sys.modules.get("numpy")
    if np is not None and hasattr(np, "random"):
        try:
            st = np.random.get_state()
            _state.record_at("random", "numpy.random.state", "<end>", _core.digest(st[1].tobytes() + str(st[2]).encode()))
        except Exception:  # pragma: no cover
            pass
