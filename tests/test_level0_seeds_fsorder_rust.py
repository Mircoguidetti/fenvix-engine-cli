"""Seeds and filesystem order in Rust (``crates/detpy-py/src/seeds.rs``, ``fsorder.rs``, ``standin.rs``) against the
Python originals (``tests/rust_hotpaths_ref/_ref_l0_seeds.py``, ``_ref_l0_fsorder.py``, ``_ref_l0_sites_norm.py``).

* whole sessions: a project drawing from every ``random`` function, seeding, ``Random()`` instances,
  ``SystemRandom``, ``randbytes``, ``os.urandom`` (with and without ``--det-urandom``), ``secrets``, ``uuid4``, numpy
  (when installed) and enumerating directories every way (``listdir`` with and without arguments, bytes paths, fds,
  ``scandir`` as context manager and iterator, ``os.walk``, ``glob`` / ``iglob`` incl. recursive, ``Path.iterdir`` /
  ``glob`` / ``rglob``, ``shutil.copytree``), run with the reference path (``-p _l0ref``, ``DETPY_L0_REF=1``) and with
  the Rust path: ``--det`` traces byte-identical, ``--det-cache`` stores, warm receipts and outcomes identical;
* the value strings, unit level: the stand-ins against the reference wrappers on the same generators and arguments,
  ``norm_path`` and ``digest_names`` against the reference functions;
* the stand-ins' disguise (names, ``__wrapped__``, ``__doc__``, binding, pickling);
* the per-call cost of both paths inside a recorded test (MEASURED, printed).
"""

from __future__ import annotations

import importlib.util
import json
import os
import pickle
import random
import re
import sys
from pathlib import Path

import pytest

REF = Path(__file__).parent / "rust_hotpaths_ref"
HAS_NUMPY = importlib.util.find_spec("numpy") is not None

PROJECT = {
    "pkg/__init__.py": "",
    "pkg/draws.py": '''
import random

AT_IMPORT = random.Random().random()            # collection context: a derived seed, not recorded


def numeric():
    vals = [random.random(), random.uniform(1, 2), random.randint(0, 100), random.randrange(10),
            random.randrange(0, 100, 7), random.getrandbits(40), random.gauss(0, 1), random.normalvariate(0, 1),
            random.lognormvariate(0, 1), random.expovariate(2), random.vonmisesvariate(1, 2),
            random.gammavariate(2, 3), random.triangular(), random.betavariate(2, 3), random.paretovariate(2),
            random.weibullvariate(1, 2), random.uniform(a=1, b=3), random.gauss()]
    if hasattr(random, "binomialvariate"):
        vals.append(random.binomialvariate(10, 0.3))
    return vals
''',
    "conftest.py": '''
import os
import random

import pytest

if os.environ.get("FAKE_URANDOM") == "1":
    # deterministic "OS entropy" (both paths read seeds._real_urandom at call time): whole traces comparable
    import detpy.seeds as _seeds

    _n = [0]

    def _fake_urandom(n):
        _n[0] += 1
        return bytes((_n[0] * 31 + i * 7) & 255 for i in range(n))

    _seeds._real_urandom = _fake_urandom


@pytest.fixture
def drawn():
    yield random.random()                       # fixture setup draw
    random.choice([1, 2, 3])                    # teardown draw
''',
    "test_random.py": '''
import os
import random
import secrets
import sys
import time
import uuid

import pytest

from pkg import draws


def test_numeric(drawn):
    print("VAL", draws.numeric(), drawn)


def test_sequence():
    xs = list(range(20))
    random.shuffle(xs)
    print("VAL", random.choice(xs), random.choices(xs, k=3), random.sample(xs, 4), xs, random.choice("abc"),
          random.sample(population=xs, k=2), random.choices(range(5), weights=[1] * 5, k=2),
          random.choice(iter_seq := (7, 8)), iter_seq)
    with pytest.raises(IndexError):
        random.choice([])
    with pytest.raises(TypeError):
        random.choice(x for x in [1])          # no __len__: n=-1 is never recorded (the draw raised)


def test_seeding():
    random.seed()
    a = random.random()
    random.seed(None)
    random.seed(42)
    b = random.random()
    random.seed("text")
    random.seed(b"bytes")
    random.seed(3.5)
    random.seed(True)
    random.seed(a=7, version=2)
    r1, r2, r3 = random.Random(), random.Random(), random.Random(5)
    r1.seed()
    r1.seed(None)
    r1.seed(a=None, version=2)
    random.Random.seed(r2)

    class Sub(random.Random):
        pass

    s = Sub()
    print("VAL", a, b, r1.random(), r2.random(), r3.random(), s.random(), draws.AT_IMPORT, time.monotonic())


def test_entropy():
    sr = random.SystemRandom()
    sr.seed()                                   # a no-op on SystemRandom (not derived)
    random.Random.seed(sr)                      # SystemRandom: not derived, not recorded
    print("VAL", sr.random(), sr.randint(0, 9), sr.randbytes(5), os.urandom(8), os.urandom(0), random.randbytes(6),
          secrets.token_hex(4), secrets.randbelow(100), secrets.choice("xyz"), uuid.uuid4(), uuid.uuid4().hex)
    print("VAL", len(os.urandom(size := 3)), size)


def test_failing_draw():
    assert random.random() < 0
''',
    "test_numpy.py": '''
import pytest

np = pytest.importorskip("numpy")


def test_np():
    rng = np.random.default_rng()
    print("VAL", np.random.rand(), rng.random(), np.random.default_rng(seed=None).integers(10),
          np.random.default_rng(5).random(), np.random.randint(0, 10, 3).tolist())
''',
    "test_fs.py": '''
import glob
import os
import pathlib
import shutil
import time

NAMES = ["zeta", "Alpha", "mid", "beta", "_x", "0num", "omega", "kappa", "caf\\u00e9"]


def make(root):
    for n in NAMES:
        (root / n).mkdir()
        (root / n / "f.txt").write_text(n)
        (root / n / "sub").mkdir()
        (root / n / "sub" / "g.py").write_text(n)
    return sorted(NAMES)


def test_listdir(tmp_path, monkeypatch):
    exp = make(tmp_path)
    monkeypatch.chdir(tmp_path)
    fd = os.open(tmp_path, os.O_RDONLY)
    try:
        by_fd = os.listdir(fd)
    finally:
        os.close(fd)
    print("VAL", os.listdir(tmp_path) == exp, os.listdir(), os.listdir("."), os.listdir("zeta"),
          os.listdir(path="mid/sub"), os.listdir(os.fsencode(tmp_path)), os.listdir(b"zeta"), by_fd,
          os.listdir(str(tmp_path) + "/./zeta/../mid//"), os.listdir(pathlib.PurePath("beta")), time.monotonic())


def test_scandir(tmp_path, monkeypatch):
    exp = make(tmp_path)
    with os.scandir(tmp_path) as it:
        a = [e.name for e in it]
    b = [e.name for e in os.scandir(str(tmp_path))]
    it = os.scandir(tmp_path / "zeta")
    first = next(it)
    it.close()
    monkeypatch.chdir(tmp_path)
    c = [e.name for e in os.scandir()]
    d = [e.name for e in os.scandir(b"mid")]
    print("VAL", a == exp, b, first.name, c, d)


def test_walk_and_copytree(tmp_path):
    (tmp_path / "src").mkdir()
    make(tmp_path / "src")
    print("VAL", [(os.path.relpath(t, tmp_path), d, f) for t, d, f in os.walk(tmp_path)])
    shutil.copytree(tmp_path / "src", tmp_path / "dst")
    print("VAL", [os.path.relpath(t, tmp_path) for t, _, _ in os.walk(tmp_path / "dst", topdown=False)])
    shutil.rmtree(tmp_path / "dst")


def test_glob(tmp_path, monkeypatch):
    make(tmp_path)
    monkeypatch.chdir(tmp_path)
    print("VAL", [os.path.relpath(p, tmp_path) for p in glob.glob(str(tmp_path / "*" / "f.txt"))],
          glob.glob("**/*.py", recursive=True), glob.glob("*", root_dir=tmp_path / "mid"),
          glob.glob(pathname="z*"), list(glob.iglob("**", recursive=True)), list(glob.iglob(b"*/sub")),
          glob.glob("nothing-*"), glob.glob(""))


def test_pathlib(tmp_path):
    make(tmp_path)
    print("VAL", [p.name for p in tmp_path.iterdir()], [str(p.relative_to(tmp_path)) for p in tmp_path.glob("*/f.txt")],
          [str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.py")],
          [str(p.relative_to(tmp_path)) for p in (tmp_path / "zeta").glob("**/*")],
          [p.name for p in pathlib.Path("does-not-exist-here").glob("*")])
    g = tmp_path.glob("*")                      # lazy: nothing listed before the first next()
    (tmp_path / "late").mkdir()
    print("VAL", [p.name for p in g])
''',
}


def _write(root: Path, files: dict) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


@pytest.fixture
def ref_env(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(REF), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep))


def _run(pytester, mode: str, *args, urandom: bool = True):
    os.environ["DETPY_L0_REF"] = "1" if mode == "ref" else "0"
    os.environ["FAKE_URANDOM"] = "0" if urandom else "1"
    try:
        flags = ("--det-urandom",) if urandom else ()
        r = pytester.runpytest_subprocess("--det", *flags, "-p", "no:cacheprovider", "-s", "-p", "_l0ref", *args)
    finally:
        del os.environ["DETPY_L0_REF"], os.environ["FAKE_URANDOM"]
    out = r.stdout.str()
    assert "Traceback" not in out.split("short test summary")[0] or "assert random.random() < 0" in out, out[-3000:]
    return r


def _vals(r) -> list:
    return [line[line.index("VAL "):] for line in r.stdout.lines if "VAL " in line]


def test_reference_plugin_installs_seeds_and_fsorder(pytester, ref_env):
    pytester.makepyfile(test_x="import os, random, detpy.seeds as s, detpy.fsorder as f\ndef test_x():\n"
                               "    print('REF', type(random.random).__name__, type(os.urandom).__name__, "
                               "type(os.listdir).__name__, s.__file__.endswith('seeds.py'), hasattr(s, '_wrap_numeric'))\n")
    ref = _run(pytester, "ref")
    new = _run(pytester, "new")
    assert "REF random urandom listdir True True" in ref.stdout.str()
    assert "REF stand_in stand_in listdir True False" in new.stdout.str()


@pytest.mark.parametrize("urandom", [True, False], ids=["det-urandom", "os-urandom"])
def test_traces_match_reference(pytester, ref_env, urandom):
    _write(pytester.path, PROJECT)
    traces, vals = {}, {}
    for i, mode in enumerate(("ref", "new", "ref", "new")):
        t = pytester.path / f"trace-{mode}-{i}.jsonl"
        r = _run(pytester, mode, f"--det-trace={t}", urandom=urandom)
        # the header's precompile duration is the only wall-clock value in a trace
        traces.setdefault(mode, []).append(re.sub(rb'"precompile_s":[0-9.]+,', b"", t.read_bytes()))
        vals.setdefault(mode, []).append(_vals(r))
    assert traces["ref"][0] == traces["ref"][1]
    assert traces["new"][0] == traces["new"][1]
    lines_ref = traces["ref"][0].decode().splitlines()
    lines_new = traces["new"][0].decode().splitlines()
    assert len(lines_ref) == len(lines_new)
    for a, b in zip(lines_ref, lines_new):
        assert a == b
    assert traces["ref"][0] == traces["new"][0]
    assert vals["ref"][0] == vals["new"][0] and len(vals["new"][0]) >= 12
    events = [json.loads(x) for x in lines_new if '"type":"test"' in x]
    ops = {e["o"] for t in events for e in t.get("events", [])}
    expected = {"random.random", "random.uniform", "random.randint", "random.randrange", "random.getrandbits",
                "random.gauss", "random.normalvariate", "random.lognormvariate", "random.expovariate",
                "random.vonmisesvariate", "random.gammavariate", "random.triangular", "random.betavariate",
                "random.paretovariate", "random.weibullvariate", "random.choice", "random.choices", "random.sample",
                "random.shuffle", "random.seed", "Random.seed(None)", "random.randbytes", "os.urandom",
                "os.listdir", "os.scandir", "glob.glob", "glob.iglob", "Path.iterdir", "Path.glob", "Path.rglob"}
    if HAS_NUMPY:
        expected.add("numpy.default_rng(None)")
    assert expected <= ops, expected - ops
    sites = {e["at"] for t in events for e in t.get("events", [])}
    assert any(s.startswith("pkg/draws.py:") for s in sites)
    values = {e["v"] for t in events for e in t.get("events", []) if e["o"] in ("os.listdir", "os.scandir")}
    assert any(v.startswith("<fd>|") for v in values) and any(v.startswith("<basetemp>/") for v in values), values


def test_cache_matches_reference(pytester, ref_env):
    _write(pytester.path, PROJECT)
    out = {}
    for mode in ("ref", "new"):
        cache = pytester.path / f".cache-{mode}"
        _run(pytester, mode, f"--det-cache={cache}", f"--det-outcomes={pytester.path / f'o-{mode}-c.json'}")
        # the run id (time and pid) and the measured durations are the only wall-clock values of a store
        store = re.sub(rb'"(run|duration)":("[^"]*"|[0-9.e-]+)', b"", (cache / "proof-cache.json").read_bytes())
        _run(pytester, mode, f"--det-cache={cache}", f"--det-outcomes={pytester.path / f'o-{mode}-w.json'}")
        receipts = [re.sub(r'"(run|duration)": ("[^"]*"|[0-9.e-]+)', "", x)
                    for x in (cache / "receipts.jsonl").read_text().splitlines()]
        oc = json.loads((pytester.path / f"o-{mode}-c.json").read_text())
        ow = json.loads((pytester.path / f"o-{mode}-w.json").read_text())
        out[mode] = (store, receipts, oc.get("outcomes"), ow.get("outcomes"),
                     {k: (oc.get("cache") or {}).get(k) for k in ("reused", "ran", "recorded", "not_cached")},
                     {k: (ow.get("cache") or {}).get(k) for k in ("reused", "ran", "recorded", "not_cached")})
    ref, new = out["ref"], out["new"]
    assert ref[0] == new[0]                      # the store, byte for byte
    assert ref[1] == new[1]                      # warm receipts
    assert ref[2:] == new[2:]
    assert new[5]["reused"], new[5]


# -- unit level: the value strings -----------------------------------------------------------------------------------


def _ref_module(name: str, file: str):
    """A reference module loaded under another name (its relative imports resolve to the real detpy modules)."""
    spec = importlib.util.spec_from_file_location(f"detpy._ref_{name}", REF / file)
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "detpy"
    spec.loader.exec_module(m)
    return m


class _Events:
    """A recorder object (the record path calls its ``record`` method) collecting the events of one test."""

    def __init__(self) -> None:
        self.events: list = []

    def record(self, source, op, site, value, thread=0):
        self.events.append((source, op, site, value, thread))


@pytest.fixture
def capture():
    from detpy import _state

    st = _state.STATE
    saved = (st.recorder, st.nodeid, st.threads)
    rec = _Events()
    st.recorder, st.nodeid = rec, "unit::test"
    _state.reset_threads()
    try:
        yield rec
    finally:
        st.recorder, st.nodeid, st.threads = saved


def _same_site(f, *args, **kwargs):
    return f(*args, **kwargs)                    # one call line for both paths: identical sites


def test_seed_stand_ins_match_reference_wrappers(capture):
    from detpy import _core

    ref = _ref_module("seeds", "_ref_l0_seeds.py")
    args = {"random": (), "uniform": (1, 5), "randint": (0, 10 ** 30), "randrange": (3, 99, 4), "getrandbits": (70,),
            "gauss": (), "normalvariate": (2, 3), "lognormvariate": (0, 1), "expovariate": (), "vonmisesvariate": (1, 1),
            "gammavariate": (2, 2), "triangular": (0, 1, 0.2), "betavariate": (1, 3), "paretovariate": (3,),
            "weibullvariate": (2, 2), "binomialvariate": (20, 0.5)}
    for name in ref._NUMERIC:
        if not hasattr(random, name):
            continue
        a, b = random.Random(7), random.Random(7)
        old = ref._wrap_numeric(name, getattr(a, name))
        new = _core.stand_in("numeric", getattr(b, name), "random", name, doc=getattr(b, name).__doc__)
        for _ in range(3):
            assert repr(_same_site(old, *args[name])) == repr(_same_site(new, *args[name]))
    for name, call in (("choice", ([4, 5, 6],)), ("choices", (range(9),)), ("sample", ([1, 2, 3, 4], 2)),
                       ("shuffle", ([1, 2, 3],)), ("choice", ("xyz",))):
        a, b = random.Random(3), random.Random(3)
        old = ref._wrap_sequence(name, getattr(a, name))
        new = _core.stand_in("sequence", getattr(b, name), "random", name)
        assert _same_site(old, *call) == _same_site(new, *call)
        assert _same_site(old, population=[1, 2, 3], k=1) == _same_site(new, population=[1, 2, 3], k=1) \
            if name == "sample" else True
    ev = capture.events
    assert len(ev) % 2 == 0 and ev
    for i in range(0, len(ev), 2):
        assert ev[i] == ev[i + 1]
    assert ("random", "random.sample", ev[-1][2], "n=-1", 0) in ev   # population= keyword: n=-1
    assert ("random", "random.choice", ev[-1][2], "n=3", 0) in ev


def test_seed_counter_and_keys_match_reference(capture):
    from detpy import _core, _state, seeds

    ref = _ref_module("seeds", "_ref_l0_seeds.py")
    for nodeid in ("unit::test", None, ""):
        _state.STATE.nodeid = nodeid
        ref._counter["n"] = 0
        _core.seeds_reset_counter()
        # the Random.seed stand-in derives the same seeds as the reference _seed, counter included
        a, b = random.Random(1), random.Random(1)
        for _ in range(3):
            for tag in ("Random", "random.seed", "default_rng"):
                assert ref._key(tag) == _core.seeds_key(tag)
            _same_site(ref._seed, a)
            _same_site(seeds._seed, b)
            assert a.random() == b.random()
            assert ref._counter["n"] == _core.seeds_counter()
        sa, sb = ref._module_seed(a.seed), _core.stand_in("module_seed", b.seed, "random", "seed")
        for arg in (None, 5, "x", b"y", 2.5, True):
            _same_site(sa, arg)
            _same_site(sb, arg)
            assert a.random() == b.random() and ref._counter["n"] == _core.seeds_counter()
    _state.STATE.nodeid = "unit::test"
    ev = capture.events
    assert ev and all(ev[i] == ev[i + 1] for i in range(0, len(ev), 2))
    assert {e[3] for e in ev if e[1] == "random.seed"} >= {"5", "'x'", "bytes", "float", "True"}


def test_entropy_stand_ins_match_reference(capture):
    from detpy import _core, seeds

    ref = _ref_module("seeds", "_ref_l0_seeds.py")
    for rng_seed in (None, 11):
        if rng_seed is None:
            ref._urandom_rng = seeds._urandom_rng = None
            ref._real_urandom = seeds._real_urandom = lambda n: bytes(range(n))
        else:
            ref._urandom_rng, seeds._urandom_rng = random.Random(rng_seed), random.Random(rng_seed)
        try:
            for n in (0, 1, 16, True):
                assert _same_site(ref._urandom, n) == _same_site(seeds._urandom, n)
            assert _same_site(ref._urandom, n=3) == _same_site(seeds._urandom, n=3)
        finally:
            seeds._urandom_rng = None
            seeds._real_urandom = os.urandom
    a, b = random.Random(4), random.Random(4)
    real_rb = a.randbytes

    def ref_randbytes(n):  # verbatim body of the reference's closure in install()
        data = real_rb(n)
        ref._state.record("random", "random.randbytes", ref._core.digest(data))
        return data

    new_rb = _core.stand_in("randbytes", b.randbytes, "random", "randbytes")
    assert _same_site(ref_randbytes, 9) == _same_site(new_rb, 9)
    ev = capture.events
    assert ev and all(ev[i] == ev[i + 1] for i in range(0, len(ev), 2))
    assert ("entropy", "os.urandom") == ev[0][:2] and ev[0][3].startswith("0:")
    assert any(e[3].startswith("True:") for e in ev)


@pytest.mark.skipif(not HAS_NUMPY, reason="numpy not installed")
def test_default_rng_stand_in_matches_reference(capture):
    import numpy as np

    from detpy import _core

    ref = _ref_module("seeds", "_ref_l0_seeds.py")
    old = ref._numpy_default_rng(np.random.default_rng)
    new = _core.stand_in("default_rng", np.random.default_rng, "numpy.random", "default_rng")
    ref._counter["n"] = 0
    _core.seeds_reset_counter()
    for kw in ({}, {"seed": None}, {"seed": 3}):
        assert _same_site(old, **kw).random() == _same_site(new, **kw).random()
    assert _same_site(old, None).random() == _same_site(new, None).random()
    ev = capture.events
    assert len(ev) == 6 and all(ev[i] == ev[i + 1] for i in range(0, len(ev), 2))


def test_float_repr_matches_python():
    """The numeric stand-ins render a float with a long decimal expansion in Rust (shortest round-trip digits in
    CPython's layout); ties (short expansions) go to the interpreter's repr."""
    import math
    import struct

    from detpy import _core

    rnd = random.Random(5)
    xs = [0.0, -0.0, 1.0, -1.5, 1e16, 1e15, 9999999999999998.0, 1e-4, 1e-5, 5e-324, 1.7976931348623157e308,
          2.2250738585072014e-308, 0.1, 1 / 3, 2.0 ** 53 + 2, 1e22, 1e23, math.nan, math.inf, -math.inf,
          903003408581556.2, 2012746371511900.2]
    for e in range(-1074, 1024, 7):
        p = math.ldexp(1.0, e)
        xs += [p, math.nextafter(p, 0), math.nextafter(p, math.inf)]
    for i in range(200_000):
        k = i % 5
        if k == 0:
            xs.append(struct.unpack("<d", rnd.getrandbits(64).to_bytes(8, "little"))[0])
        elif k == 1:
            xs.append(rnd.random() * 10 ** rnd.randint(-30, 30))
        elif k == 2:
            xs.append(float(rnd.randint(-10 ** 18, 10 ** 18)) / 10 ** rnd.randint(0, 20))
        elif k == 3:
            xs.append(round(rnd.uniform(-1e6, 1e6), rnd.randint(0, 12)))
        else:
            xs.append(rnd.gauss(0, 1))
    assert [repr(x) for x in xs] == [_core.seeds_float_repr(x) for x in xs]
    assert sum(map(_core.seeds_float_repr_is_rust, xs)) > len(xs) * 0.8
    assert not _core.seeds_float_repr_is_rust(903003408581556.2)  # an exact tie: Python's half-even digits


def test_stand_in_disguise(monkeypatch):
    import inspect

    from detpy import _core, seeds
    from detpy._patch import Patcher, binds_as_method

    r = random.Random(1)
    s = _core.stand_in("numeric", r.random, "random", "random", doc=r.random.__doc__)
    assert (s.__name__, s.__qualname__, s.__module__, s.__doc__) == ("random", "random", "random", r.random.__doc__)
    assert s.__wrapped__ == r.random and repr(s) == "<built-in function random>"
    assert not binds_as_method(s)
    monkeypatch.setattr(random, "random", s)
    monkeypatch.setattr(random.Random, "seed", seeds._seed)
    monkeypatch.setattr(os, "urandom", seeds._urandom)
    assert pickle.loads(pickle.dumps(s)) is s           # by reference, like the builtin
    assert pickle.loads(pickle.dumps(seeds._seed)) is seeds._seed
    assert pickle.loads(pickle.dumps(seeds._urandom)) is seeds._urandom

    class Holder:
        draw = s
        seed = seeds._seed

    assert 0 <= Holder().draw() < 1 and Holder.draw is s
    assert binds_as_method(seeds._seed) and Holder.seed is seeds._seed
    assert seeds._seed.__wrapped__ is seeds._real_seed and inspect.signature(seeds._seed) == \
        inspect.signature(seeds._real_seed)
    with pytest.raises(TypeError, match=r"urandom\(\) takes 1 positional argument but 2 were given"):
        seeds._urandom(1, 2)
    with pytest.raises(TypeError, match=r"_seed\(\) missing 1 required positional argument: 'self'"):
        seeds._seed()
    with pytest.raises(TypeError, match=r"seed\(\) got an unexpected keyword argument 'b'"):
        _core.stand_in("module_seed", r.seed, "random", "seed")(b=1)
    # patched on a module, a stand-in is set as is (not wrapped again by nonbinding)
    p = Patcher()
    mod = type(sys)("m")
    mod.f = len
    p.set(mod, "f", s)
    assert mod.f is s
    p.undo_all()


# -- timing ----------------------------------------------------------------------------------------------------------


@pytest.mark.skipif(sys.version_info < (3, 12), reason="timing only")
def test_rust_stand_ins_are_faster_than_the_reference(pytester, ref_env):
    """Not an equivalence check: the per-call cost of both paths inside a recorded test (MEASURED, printed)."""
    pytester.makepyfile(test_t='''
import os, random


def test_t(tmp_path):
    from detpy.clock import real_perf_counter as clock
    for i in range(5):
        (tmp_path / str(i)).touch()
    seq = list(range(10))
    best = {}
    for _ in range(3):
        n = 20000
        t0 = clock()
        for _ in range(n):
            random.random()
        t1 = clock()
        for _ in range(n):
            random.choice(seq)
        t2 = clock()
        for _ in range(n // 4):
            os.listdir(tmp_path)
        t3 = clock()
        for label, dt in (("random", (t1 - t0) / n), ("choice", (t2 - t1) / n), ("listdir", (t3 - t2) / (n // 4))):
            best[label] = min(best.get(label, dt), dt)
    for label, dt in best.items():
        print("NSPERCALL", label, round(dt * 1e9))
''')
    res = {}
    for mode in ("ref", "new"):
        r = _run(pytester, mode, "--det-max-events=100")
        for line in r.stdout.lines:
            if "NSPERCALL" in line:
                _, label, ns = line[line.index("NSPERCALL"):].split()[:3]
                res.setdefault(label, {})[mode] = int(ns)
    print("ns per call in a test (best of 3):", res)
    assert res["random"]["new"] < res["random"]["ref"] and res["choice"]["new"] < res["choice"]["ref"]
