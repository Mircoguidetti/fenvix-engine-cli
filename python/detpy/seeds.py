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
    # review R-023b N5: the kernel pool through os.getrandom and OpenSSL's generator (seeded from it) are OS entropy
    # like os.urandom: observed (the "entropy" flag of the cache), and drawn from the seeded stream under --det-urandom
    if hasattr(os, "getrandom"):
        patcher.set(os, "getrandom", _core.stand_in("urandom", globals(), "os", "getrandom", wrapped=os.getrandom,
                                                     fname="urandom"))
    try:
        import ssl
    except ImportError:  # pragma: no cover - Python without ssl
        ssl = None
    if ssl is not None and hasattr(ssl, "RAND_bytes"):
        patcher.set(ssl, "RAND_bytes", _core.stand_in("urandom", globals(), "ssl", "RAND_bytes",
                                                      wrapped=ssl.RAND_bytes, fname="urandom"))
    _install_uuid1(patcher)
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


def _install_uuid1(patcher: Patcher) -> None:
    """``uuid.uuid1()`` (audit G-1524): libuuid mixes the real clock, the MAC address and a random sequence. Under
    --det it takes Python's own path with a node and a clock sequence derived from the test (and a per-test counter),
    and the virtual clock (``time.time_ns``); the last timestamp is reset at every test, so a value does not depend on
    the tests before."""
    import uuid

    real = uuid.uuid1

    def uuid1(node=None, clock_seq=None):
        st = _state.STATE
        if st.nodeid is not None:
            if node is None:
                node = (_core.derive_seed(st.config.seed, st.nodeid + "\0uuid1-node") & 0xFFFFFFFFFFFF) | 0x010000000000
            if clock_seq is None:
                _NP_COUNTER[0] += 1
                clock_seq = _core.derive_seed(st.config.seed, f"{st.nodeid}\0uuid1-seq#{_NP_COUNTER[0]}") & 0x3FFF
        return real(node, clock_seq)

    uuid1.__doc__ = real.__doc__
    patcher.set(uuid, "uuid1", uuid1)


def uninstall() -> None:
    global _urandom_rng
    _urandom_rng = None


_numpy_patched: list = []


def start_test(patcher: Patcher, nodeid: str) -> None:
    """Re-seed every generator for ``nodeid``."""
    base = _state.STATE.config.seed
    _core.seeds_reset_counter()
    _NP_COUNTER[0] = 0
    uuid = sys.modules.get("uuid")
    if uuid is not None and hasattr(uuid, "_last_timestamp"):
        uuid._last_timestamp = None  # uuid1's monotonic guard: per test, not per process
    s = _core.derive_seed(base, nodeid)
    _real_seed(random._inst, s)
    _core.sqlvirt_start_test(_core.derive_seed(base, nodeid + "\0sqlite"))  # SQLite's random() / randomblob()
    if _urandom_rng is not None:
        _real_seed(_urandom_rng, _core.derive_seed(base, nodeid + "\0urandom"))
    # Fresh temporary-name generator: names depend on the test, not on history.
    tempfile = sys.modules.get("tempfile")
    if tempfile is not None and hasattr(tempfile, "_name_sequence"):
        tempfile._name_sequence = None
    core = sys.modules.get("hypothesis.core")
    if core is not None:
        _hypothesis(patcher, core)
    _seed_numpy(patcher, s)
    _seed_libraries(s)
    _install_import_hook(patcher)


def _seed_numpy(patcher: Patcher, s: int, rnd=None) -> None:
    """numpy's global state, ``default_rng()`` and the generators built without a seed (``RandomState()``,
    ``PCG64()`` ...: audit G-1526) take seeds derived from the test. The reseed runs quietly: numpy imports
    ``numpy.random._pickle`` lazily on the first ``seed`` call and reads OS entropy there, which was recorded as an
    event of whichever test came first (audit G-0179, G-0177). ``rnd``: the numpy.random module (during its own
    import, ``numpy.random`` cannot be read from the numpy package yet)."""
    rnd = rnd if rnd is not None else sys.modules.get("numpy.random")
    if rnd is None or not hasattr(rnd, "seed"):
        return
    try:
        if not _numpy_patched and hasattr(rnd, "default_rng"):
            real = rnd.default_rng
            patcher.set(rnd, "default_rng", _core.stand_in("default_rng", real, "numpy.random", "default_rng"))
            _patch_numpy_generators(patcher, rnd)
            _numpy_patched.append(True)
        with _state.quiet():
            rnd.seed(s & 0xFFFFFFFF)
    except Exception:  # pragma: no cover - exotic numpy builds
        pass


def _derived(tag: str) -> int:
    """A seed for an unseeded generator: the test, a per-test counter (as ``Random()``), the generator's kind."""
    st = _state.STATE
    _NP_COUNTER[0] += 1
    return _core.derive_seed(st.config.seed, f"{st.nodeid or '<session>'}\0{tag}#{_NP_COUNTER[0]}")


_NP_COUNTER = [0]


class _SameType(type):
    """The stand-in classes are the original for ``isinstance`` / ``issubclass``: numpy's own instances (the global
    ``RandomState``) still pass ``isinstance(x, np.random.RandomState)`` checks (sklearn's check_random_state)."""

    def __instancecheck__(cls, inst):
        return isinstance(inst, cls._detpy_base)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, cls._detpy_base)


def _patch_numpy_generators(patcher: Patcher, rnd) -> None:
    for name in ("RandomState", "PCG64", "PCG64DXSM", "MT19937", "Philox", "SFC64"):
        base = getattr(rnd, name, None)
        if not isinstance(base, type):
            continue

        def make(base, name):
            def __init__(self, seed=None, *args, **kwargs):
                if seed is None and _state.STATE.nodeid is not None:
                    seed = _derived(name) & (0xFFFFFFFF if name == "RandomState" else (1 << 63) - 1)
                base.__init__(self, seed, *args, **kwargs)

            return _SameType(name, (base,), {"__init__": __init__, "__module__": base.__module__,
                                             "__qualname__": base.__qualname__, "__doc__": base.__doc__,
                                             "_detpy_base": base})

        try:
            patcher.set(rnd, name, make(base, name))
        except TypeError:  # pragma: no cover - a final type in some numpy build
            pass
    real_seed = rnd.seed

    def seed(seed=None):
        if seed is None and _state.STATE.nodeid is not None and not _state.is_quiet():
            seed = _derived("numpy.random.seed") & 0xFFFFFFFF
        return real_seed(seed)

    patcher.set(rnd, "seed", seed)


def _seed_libraries(s: int) -> None:
    """Global generators of other libraries, when they are loaded (audit G-1527): torch, TensorFlow, Faker (and so
    factory_boy, which draws through Faker and ``random``). JAX has no global generator (explicit keys)."""
    mods = sys.modules
    try:
        with _state.quiet():
            torch = mods.get("torch")
            if torch is not None and hasattr(torch, "manual_seed"):
                torch.manual_seed(s & 0xFFFFFFFFFFFF)
            tf = mods.get("tensorflow")
            if tf is not None and hasattr(getattr(tf, "random", None), "set_seed"):
                tf.random.set_seed(s & 0x7FFFFFFF)
            faker = mods.get("faker")
            fk = getattr(faker, "Faker", None)
            if fk is not None and hasattr(fk, "seed"):
                fk.seed(s)
    except Exception:  # pragma: no cover - a library version with another API: it keeps its own seeding
        pass


_hook_installed: list = []


class _SeedOnImport:
    """``sys.meta_path`` finder: when numpy.random, torch, tensorflow or faker is imported during a test (lazily,
    inside the test or a library it calls: audit G-1525), its generators are seeded for that test right after the
    module is loaded, as if it had been loaded before the test started."""

    WATCH = ("numpy.random", "torch", "tensorflow", "faker")

    def __init__(self, patcher: Patcher) -> None:
        self.patcher = patcher
        self.busy = False

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.WATCH or self.busy or _state.STATE.nodeid is None:
            return None
        import importlib.util

        self.busy = True
        try:
            spec = importlib.util.find_spec(fullname)
        finally:
            self.busy = False
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return None
        loader, hook = spec.loader, self

        class _Loader:
            def create_module(self, spec):
                return loader.create_module(spec)

            def exec_module(self, module):
                if fullname == "numpy.random":
                    # numpy seeds its global generator from OS entropy while it imports; it is reseeded right after,
                    # so that read decides nothing (audit G-0179)
                    with _state.quiet():
                        loader.exec_module(module)
                else:
                    loader.exec_module(module)
                st = _state.STATE
                if st.nodeid is not None:
                    s = _core.derive_seed(st.config.seed, st.nodeid)
                    if fullname == "numpy.random":
                        _seed_numpy(hook.patcher, s, module)
                    else:
                        _seed_libraries(s)

            def __getattr__(self, name):
                return getattr(loader, name)

        spec.loader = _Loader()
        return spec


def _install_import_hook(patcher: Patcher) -> None:
    if _hook_installed:
        return
    hook = _SeedOnImport(patcher)
    sys.meta_path.insert(0, hook)
    _hook_installed.append(hook)

    def undo() -> None:
        if hook in sys.meta_path:
            sys.meta_path.remove(hook)
        _hook_installed.clear()

    patcher._undo.append((undo, None, None))


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

    # the time spent in garbage collection (``junkdrawer.gc_cumulative_time``, subtracted from a test's run time for
    # its deadline): a ``gc.callbacks`` hook reads the clock whenever a collection runs, and when one runs depends on
    # every allocation of the process before it, so a test's clock events depended on the tests that ran before it
    # (MEASURED: a Hypothesis test alone vs after another one of its class had different fingerprints). Under --det
    # no collection time is counted (the clock is virtual: collections take no virtual time anyway)
    jd = sys.modules.get("hypothesis.internal.conjecture.junkdrawer")
    real_gc_time = getattr(jd, "gc_cumulative_time", None)
    if real_gc_time is not None:
        import gc

        def no_gc_time() -> float:
            return 0.0

        # every Hypothesis module holding the function (core, stateful, conjecture.data, ...); one imported later
        # takes the replaced one from junkdrawer
        holders = [m for n, m in list(sys.modules.items())
                   if (n == "hypothesis" or n.startswith("hypothesis.")) and m is not None
                   and getattr(m, "gc_cumulative_time", None) is real_gc_time]
        for m in holders:
            m.gc_cumulative_time = no_gc_time
        hooks = [cb for cb in list(gc.callbacks) if getattr(cb, "__module__", "") == jd.__name__]
        for cb in hooks:
            gc.callbacks.remove(cb)

        def undo_gc() -> None:
            for m in holders:
                m.gc_cumulative_time = real_gc_time
            gc.callbacks.extend(cb for cb in hooks if cb not in gc.callbacks)

        undo_steps.append(undo_gc)

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


def fixture_begin(key: str):
    """review R-023b N5: a wider-scoped fixture's setup draws from its own stream (``derive_seed(seed, "<fixture>"
    + key)``), not from the stream of whichever test requests it first; returns the states to restore."""
    base = _state.STATE.config.seed
    saved = (random._inst.getstate(), _urandom_rng.getstate() if _urandom_rng is not None else None)
    _real_seed(random._inst, _core.derive_seed(base, "<fixture>" + key))
    if _urandom_rng is not None:
        _real_seed(_urandom_rng, _core.derive_seed(base, "<fixture>" + key + "\0urandom"))
    return saved


def fixture_end(saved) -> None:
    random._inst.setstate(saved[0])
    if saved[1] is not None and _urandom_rng is not None:
        _urandom_rng.setstate(saved[1])
