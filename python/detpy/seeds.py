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
* Hypothesis (under every runner): its seed of a test without ``@seed`` or
  ``derandomize`` comes from a generator Hypothesis creates once per thread and
  draws from at every test, so a test's examples depended on how many tests
  drew before it (another order, or tests skipped by the cache, gave other
  examples). That generator is dropped at the start of every test: Hypothesis
  creates it again, seeded from the test id like every ``Random()``. The
  example database is off (``settings.database`` is None): replaying examples
  saved by earlier runs made a test's examples depend on history, and its reads
  under ``.hypothesis/`` are not inputs of the cache. Hypothesis's storage is
  off (its caches of constants and of the Unicode table are computed in every
  run) and so are its local constants (constants of every local module loaded
  so far, which made a test's examples depend on what earlier tests imported).

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
    if _urandom_rng is not None:
        _real_seed(_urandom_rng, _core.derive_seed(base, nodeid + "\0urandom"))
    # Fresh temporary-name generator: names depend on the test, not on history.
    tempfile = sys.modules.get("tempfile")
    if tempfile is not None and hasattr(tempfile, "_name_sequence"):
        tempfile._name_sequence = None
    core = sys.modules.get("hypothesis.core")
    if core is not None:
        _hypothesis(patcher, core)
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


_hypothesis_patched: list = []


def _hypothesis(patcher: Patcher, core) -> None:
    """Hypothesis under ``--det`` (module docstring): the per-thread generator of seeds is dropped at every test,
    the example database is off."""
    tl = getattr(core, "threadlocal", None)
    try:
        if tl is not None and hasattr(tl, "_hypothesis_global_random"):
            tl._hypothesis_global_random = None
        elif hasattr(core, "_hypothesis_global_random"):  # older Hypothesis: a module global
            core._hypothesis_global_random = None
    except Exception:  # pragma: no cover - an unknown Hypothesis layout: its own seeding stays
        pass
    if _hypothesis_patched:
        return
    _hypothesis_patched.append(True)
    hyp = sys.modules.get("hypothesis")
    settings = getattr(hyp, "settings", None)
    if not isinstance(settings, type) or "database" not in vars(settings):
        return
    original = vars(settings)["database"]
    # the settings class refuses assignment through its metaclass: set and restore through type's own setattr
    type.__setattr__(settings, "database", property(lambda self: None, doc="detpy --det: no example database"))
    undo_steps = [lambda: type.__setattr__(settings, "database", original)]
    # Hypothesis's storage (its caches of local constants and of the Unicode table): a cache made by an earlier
    # run changed what a run executes (read the cache, or compute it and write it): no storage, computed every run
    conf = sys.modules.get("hypothesis.configuration")
    if conf is not None and hasattr(conf, "set_hypothesis_home_dir"):
        home = vars(conf).get("__hypothesis_home_directory")
        conf.set_hypothesis_home_dir(os.path.join(os.devnull, "detpy-no-hypothesis-storage"))
        undo_steps.append(lambda: conf.set_hypothesis_home_dir(home))
    # local constants: Hypothesis biases examples with the constants of every local module loaded so far, so a
    # test's examples depended on which modules earlier tests imported and on code it never ran: none under --det
    prov = sys.modules.get("hypothesis.internal.conjecture.providers")
    real_local = getattr(prov, "_get_local_constants", None)
    if real_local is not None:
        try:
            empty = type(prov._local_constants)(
                integers=type(prov._local_constants.integers)(), floats=type(prov._local_constants.floats)(
                    key=prov.float_to_int), bytes=type(prov._local_constants.bytes)(),
                strings=type(prov._local_constants.strings)())
        except Exception:  # pragma: no cover - an unknown Hypothesis layout: its local constants stay
            empty = None
        if empty is not None:
            prov._get_local_constants = lambda: empty
            undo_steps.append(lambda: setattr(prov, "_get_local_constants", real_local))

    def undo() -> None:
        for step in reversed(undo_steps):
            step()
        _hypothesis_patched.clear()

    patcher._undo.append((undo, None, None))


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
