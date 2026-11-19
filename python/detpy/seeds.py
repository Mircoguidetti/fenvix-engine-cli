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

The recording stand-ins (``random.random`` ... ``random.shuffle``, ``random.randbytes``, ``random.seed``,
``random.Random.seed``, ``os.urandom`` / ``random._urandom``, ``numpy.random.default_rng``) and the per-test counter
of derived seeds are Rust (``_core.stand_in``, ``crates/detpy-py/src/seeds.rs``): a draw runs no detpy Python frame.
The Python original is ``tests/rust_hotpaths_ref/_ref_l0_seeds.py``.
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
_urandom_rng: random.Random | None = None  # read by the os.urandom stand-in (--det-urandom)

_NUMERIC = ("random", "uniform", "randint", "randrange", "getrandbits", "gauss", "normalvariate",
            "lognormvariate", "expovariate", "vonmisesvariate", "gammavariate", "triangular",
            "betavariate", "paretovariate", "weibullvariate", "binomialvariate")
_SEQUENCE = ("choice", "choices", "sample", "shuffle")

# Random.seed(self, a=None, version=2): a seed derived from the test and the counter when ``a`` is None.
_seed = _core.stand_in("random_seed", globals(), "random", "seed", qualname="Random.seed", doc=_real_seed.__doc__,
                       wrapped=_real_seed, fname="_seed")
# os.urandom(n) (random._urandom: SystemRandom, secrets), from _urandom_rng under --det-urandom.
_urandom = _core.stand_in("urandom", globals(), "os", "urandom", wrapped=_real_urandom)


def install(patcher: Patcher, control_urandom: bool) -> None:
    global _urandom_rng
    patcher.set(random.Random, "seed", _seed)
    inst = random._inst
    for name in _NUMERIC:
        if hasattr(random, name):
            fn = getattr(inst, name)
            patcher.set(random, name, _core.stand_in("numeric", fn, "random", name, doc=fn.__doc__))
    for name in _SEQUENCE:
        if hasattr(random, name):
            fn = getattr(inst, name)
            patcher.set(random, name, _core.stand_in("sequence", fn, "random", name, doc=fn.__doc__))
    if hasattr(inst, "randbytes"):
        patcher.set(random, "randbytes", _core.stand_in("randbytes", inst.randbytes, "random", "randbytes"))
    patcher.set(random, "seed", _core.stand_in("module_seed", inst.seed, "random", "seed"))
    patcher.set(os, "urandom", _urandom)
    patcher.set(random, "_urandom", _core.stand_in("urandom", globals(), "random", "_urandom", wrapped=_real_urandom,
                                                   fname="urandom"))
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


_numpy_patched: list = []


def start_test(patcher: Patcher, nodeid: str) -> None:
    """Re-seed every generator for ``nodeid``."""
    base = _state.STATE.config.seed
    _core.seeds_reset_counter()
    s = _core.derive_seed(base, nodeid)
    _real_seed(random._inst, s)
    _core.sqlvirt_start_test(_core.derive_seed(base, nodeid + "\0sqlite"))  # SQLite's random() / randomblob()
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
                real = np.random.default_rng
                patcher.set(np.random, "default_rng", _core.stand_in("default_rng", real, "numpy.random", "default_rng"))
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
