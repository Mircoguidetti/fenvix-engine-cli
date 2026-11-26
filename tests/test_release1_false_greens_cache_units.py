"""Unit tests of the Python cache fixes of spec "false greens on release-1" (Phase A-fix), one per channel family,
at the layer where each fix lives. The end-to-end proof of each is its R-056 attack test
(tests/test_review_r056_pycache.py, W3 W4 W5 W8), which failed before the fix.

W3 and W4 patch process-wide state (``posix``, ``os.environ``), so they run in a child interpreter against a stub
capture: what is asserted is what the patched callables report to the capture, nothing else.
"""
import json
import os
import random
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the cache gates run on Linux")


def _child(code, where):
    """Run ``code`` from a file in ``where`` (a project's own file: user code for the capture's frame rule)."""
    script = where / "user_code.py"
    script.write_text(textwrap.dedent(code))
    p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=120, cwd=where)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_w3_posix_stat_lstat_access_are_recorded_and_import_probes_are_not(tmp_path):
    """protects=a direct ``posix.stat`` / ``lstat`` / ``access`` from user code reaches the capture's stat record
    (``_proof.Capture._patch_stat``), and a call from the import machinery does not; fails_when=``posix`` keeps the
    unwrapped builtins (release-1 6e79a62c: nothing recorded) or the import system's probes become test inputs;
    no_claim=what the capture does with the record (the Rust CaptureCore; end to end: the R-056 W3 attack tests).
    The capture is a stub with the methods the wrapper calls."""
    (tmp_path / "data.txt").write_text("abcd")
    out = _child(f"""
        import json, os, posix, sys
        sys.path.insert(0, {repr(str(tmp_path))})
        from detpy import _proof

        class Stub:
            def __init__(self):
                self.calls = []
                self._in_stat = False
            def stat_check(self, path, *a):
                self.calls.append(os.fsdecode(os.fspath(path)))
            def fields_check(self, *a): pass
            def time_check(self, *a): pass
            def flag(self, *a): pass
            def _cur(self): return 0

        cap = Stub()
        keep = [posix.stat]  # in a list: the capture rebinds module-level references to the builtin (LIMITS K3)
        _proof.Capture._patch_stat(cap)
        p = {repr(str(tmp_path / "data.txt"))}
        size = posix.stat(p).st_size
        posix.lstat(p)
        posix.access(p, posix.F_OK)
        os.symlink(p, p + ".l")
        posix.readlink(p + ".l")
        fd = posix.open(p, posix.O_RDONLY)
        fst = type(posix.fstat(fd)).__name__
        posix.close(fd)
        user = list(cap.calls)
        cap.calls.clear()
        # the import system's own probe: machinery frames under an import entry point (_find_and_load)
        g = {{"__name__": "importlib._bootstrap_external", "posix": posix, "p": p}}
        exec("def _path_stat(x):\\n    return posix.stat(x)\\n"
             "def _find_and_load(x):\\n    return _path_stat(x)\\n", g)
        g["_find_and_load"](p)
        machinery = list(cap.calls)
        cap.calls.clear()
        # the same machinery frames called by the test itself (FileFinder.find_spec): an input
        g["_path_stat"](p)
        direct_api = list(cap.calls)
        wrapped = posix.stat is not keep[0]
        for obj, name, v in reversed(cap._stat_saved):
            setattr(obj, name, v)
        print(json.dumps({{"user": user, "machinery": machinery, "direct_api": direct_api, "size": size, "wrapped": wrapped, "fstat": fst,
                          "restored": posix.stat is keep[0]}}))
    """, tmp_path)
    p = str(tmp_path / "data.txt")
    assert out["wrapped"] and out["restored"]
    assert out["size"] == 4, "the real builtin answers"
    assert out["user"] == [p, p, p, p + ".l"], out
    assert out["fstat"] == "_TimedStat", "posix.fstat on a descriptor goes through the recording wrapper"
    assert out["machinery"] == [], out
    assert out["direct_api"] == [p], "a machinery API the test calls itself is recorded"


def test_w4_reads_through_posix_environ_are_noted_like_os_environ(tmp_path):
    """protects=a read of ``posix.environ`` (bytes keys: get, [], in, iteration) is noted to the cache's environment
    record (``_proof._patch_posix_environ`` -> ``_note_env``), and ``os.environ`` keeps sharing the same dict;
    fails_when=``posix.environ`` stays the plain dict (release-1 6e79a62c: PWD read that way is in no key and no
    record) or the patch splits ``os.environ._data`` from ``posix.environ`` (a write through one not seen by the other);
    no_claim=the frame rule of ``_note_env`` (Rust: user reads only; end to end: the R-056 W4 attack test).
    ``_note_env`` is replaced by a list."""
    out = _child("""
        import json, os, posix
        from detpy import _proof

        noted = []
        _proof._note_env = noted.append
        _proof._patch_posix_environ()
        posix.environ.get(b"PWD")
        posix.environ[b"PATH"]
        b"HOME" in posix.environ
        list(posix.environ)
        after_list = len(noted)
        len(posix.environ)
        repr(posix.environ)
        posix.environ.pop(b"R1FG_ABSENT", None)
        whole = noted[after_list:]
        same = os.environ._data is posix.environ and os.environb._data is posix.environ
        os.environ["R1FG_W4"] = "x"
        seen = posix.environ.get(b"R1FG_W4")
        print(json.dumps({"noted": [n if isinstance(n, str) else n.decode() for n in noted], "same": same,
                          "whole": [n if isinstance(n, str) else n.decode() for n in whole],
                          "seen": seen.decode() if seen else None}))
    """, tmp_path)
    assert out["same"] and out["seen"] == "x"
    for name in ("PWD", "PATH", "HOME", "*"):
        assert name in out["noted"], out
    assert out["whole"] == ["*", "*", "R1FG_ABSENT"], "len, repr and pop are reads too (/review F6)"


def test_w5_the_kernel_is_part_of_the_process_key(monkeypatch):
    """protects=``process_identity`` (part of every test's key) holds the kernel (uname sysname, release, version,
    machine) and changes when the release does; fails_when=the release is in no key (release-1 6e79a62c: a cached
    result reused under another kernel, ``platform.release()``); no_claim=the digest of the whole key (Rust)."""
    import posix

    from detpy import _proof

    u = posix.uname()
    before = _proof.process_identity()
    assert before["kernel"] == [u.sysname, u.release, u.version, u.machine]

    class Fake:
        sysname, nodename, release, version, machine = u.sysname, u.nodename, "2.6.40", u.version, u.machine

    monkeypatch.setattr(posix, "uname", lambda: Fake)
    after = _proof.process_identity()
    assert after["kernel"][1] == "2.6.40"
    assert after != before


def test_w8_an_unseeded_c_generator_is_a_gap_and_controlled_ones_are_not():
    """protects=the sensor's W8 rule (``provable._unseeded_c_random``) names the construction of ``_random.Random``
    without a seed (or with None), and of a subclass that does not go through ``random.Random``, as a gap; fails_when=
    it misses the C generator (release-1 6e79a62c: reused while fresh --det runs differ) or flags the generators --det
    seeds (``random.Random``, its subclasses) or a seeded one; no_claim=the gap's effect on the cache (end to end: the
    R-056 W8 attack test) and the sensor's call-event plumbing."""
    import _random

    from detpy import provable

    missing = getattr(sys.monitoring, "MISSING")

    class OwnC(_random.Random):
        pass

    class OwnPy(random.Random):
        pass

    gap = provable._unseeded_c_random
    assert gap(_random.Random, missing) and gap(_random.Random, None) and gap(OwnC, missing)
    assert not gap(_random.Random, 42)
    assert not gap(random.Random, missing) and not gap(OwnPy, missing) and not gap(random.SystemRandom, missing)
    assert not gap(int, missing) and not gap(dict, None)
    reseed = provable._c_random_reseed
    c_gen, py_gen = _random.Random(0), random.Random(0)
    assert reseed(_random.Random.seed, c_gen), "r.seed(...) on a C generator: the method descriptor, the instance"
    assert reseed(c_gen.seed, None) and reseed(c_gen.seed, missing) and not reseed(c_gen.seed, 7)
    assert not reseed(_random.Random.seed, py_gen) and not reseed(py_gen.seed, None), "--det controls random.Random"


def _cache_vs_uncached(root, files, change, test_id):
    """Cold cached run, ``change(root)``, warm cached run and uncached --det: the outcomes of ``test_id``."""
    for rel, text in {"pytest.ini": "[pytest]\npythonpath = .\n", **files}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}

    def run(*args):
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-s", "-p", "no:cacheprovider", "-p",
                            "no:randomly", *args, "tests"], cwd=root, capture_output=True, text=True, env=env,
                           timeout=600)
        out = {ln.split()[1]: ln.split()[0].lower() for ln in p.stdout.splitlines()
               if ln.startswith(("PASSED ", "FAILED "))}
        return out.get(test_id), p.stdout

    cache = f"--det-cache={root / '.c'}"
    run("--det", cache)
    change(root)
    cached, log = run("--det", cache)
    uncached, _ = run("--det")
    return cached, uncached, log


def test_w3_entry_stat_through_posix_scandir_is_not_reused_after_the_file_changed(tmp_path):
    """protects=a file's size read through ``posix.scandir(d)`` entries is an input of the cached test (/review red
    team, W3 family); fails_when=the warm cached run reuses the pass after the file grew while uncached --det fails it
    (this branch before the fix: MEASURED ``reused 1 result(s) with proof``); no_claim=other ``posix`` calls than
    those named in docs and tests."""
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "data.txt").write_text("abcd")
    body = ("import posix\n\ndef test_v():\n    s = [e.stat().st_size for e in posix.scandir('d') if e.name == 'data.txt']"
            "\n    assert s == [4]\n")
    cached, uncached, log = _cache_vs_uncached(tmp_path, {"tests/test_v.py": body},
                                               lambda r: (r / "d" / "data.txt").write_text("abcdefgh"),
                                               "tests/test_v.py::test_v")
    assert uncached == "failed"
    assert cached == "failed", log[-1500:]


def test_w8_reseeding_a_c_generator_from_entropy_is_never_reused(tmp_path):
    """protects=``_random.Random(0).seed()`` (a reseed from OS entropy in C, /review security finding) makes the test
    NOT PROVEN and never reused, like an unseeded construction (founder decision W8 = refuse); fails_when=the warm
    cached run reuses it while fresh --det runs read different values (this branch before the fix: MEASURED);
    no_claim=seeds other than None (a seeded ``r.seed(42)`` called as a method is refused too: stricter, not tested)."""
    body = "import _random\n\ndef test_e():\n    r = _random.Random(0)\n    r.seed()\n    print('VALUE', r.random())\n"
    cached, _, log = _cache_vs_uncached(tmp_path, {"tests/test_e.py": body}, lambda r: None, "tests/test_e.py::test_e")
    assert cached == "passed", f"positive control: the warm run ran the test (/review testing)\n{log[-1500:]}"
    assert "not cacheable" in log, log[-1500:]
    assert not any(ln.startswith("reused 1 ") for ln in log.splitlines()), log[-1500:]


@pytest.mark.parametrize("call", ["r = _random.Random(5)\n    r.__init__()",
                                  "r = random.Random(5)\n    _random.Random.__init__(r)",
                                  "r = random.Random(5)\n    super(random.Random, r).__init__()"],
                         ids=["bound-init", "descriptor-init-on-random.Random", "super-init-on-random.Random"])
def test_w8_reinitialising_a_c_generator_from_entropy_is_never_reused(tmp_path, call):
    """protects=``__init__`` called on an existing C generator (``r.__init__()``; ``_random.Random.__init__(p)``, also on
    a ``random.Random``, which skips the seed --det controls) reseeds it from OS entropy and makes the test NOT PROVEN,
    as ``seed()`` does (founder decision W8 = refuse); fails_when=the warm cached run reuses it with proof while fresh
    --det runs read different values (this branch at f3ecbe73: MEASURED ``reused 1 result(s) with proof``, /review red
    team); no_claim=construction (``_unseeded_c_random``) and ``seed`` (the tests above)."""
    body = f"import _random, random\n\ndef test_e():\n    {call}\n    print('VALUE', r.random())\n"
    cached, _, log = _cache_vs_uncached(tmp_path, {"tests/test_e.py": body}, lambda r: None, "tests/test_e.py::test_e")
    assert cached == "passed", log[-1500:]
    assert "not cacheable" in log, log[-1500:]
    assert not any(ln.startswith("reused 1 ") for ln in log.splitlines()), log[-1500:]


def test_w8_reinit_rule_names_init_on_a_c_generator_and_not_the_controlled_path():
    """protects=``provable._c_random_reseed`` names ``__init__`` like ``seed``: the C descriptor on any C generator
    (a ``random.Random`` too: nothing in ``random`` or detpy calls it), a bound C ``__init__`` without a fixed seed;
    fails_when=it misses them (this branch at f3ecbe73) or flags ``random.Random``'s own Python ``__init__`` (which
    calls the seed --det controls) or a fixed seed; no_claim=the call-event plumbing (end to end: the test above)."""
    import _random

    from detpy import provable

    missing = getattr(sys.monitoring, "MISSING")
    reseed = provable._c_random_reseed
    c_gen, py_gen = _random.Random(0), random.Random(0)
    assert reseed(_random.Random.__init__, c_gen) and reseed(_random.Random.__init__, py_gen)
    assert reseed(c_gen.__init__, None) and reseed(c_gen.__init__, missing) and not reseed(c_gen.__init__, 7)
    assert not reseed(py_gen.__init__, None) and not reseed(py_gen.__init__, missing), "--det controls random.Random"
    sup = super(random.Random, py_gen).__init__  # the C slot bound to a random.Random (cycle 2 /review: still open)
    assert reseed(sup, missing) and reseed(sup, None) and not reseed(sup, 7)
    assert not reseed(dict.__init__, {}) and not reseed({}.__init__, None)


def test_reversed_posix_environ_is_a_whole_environment_read(tmp_path):
    """protects=``reversed(posix.environ)`` (the C ``dict.__reversed__`` slot, which calls none of the recorded
    methods) is noted as a read of the whole environment, like ``list(posix.environ)``; fails_when=it lists every
    variable name unrecorded (this branch at f3ecbe73, /review security and adversarial); no_claim=``dict.get(posix.
    environ, k)`` called on the base class (an explicit bypass of the subclass)."""
    out = _child("""
        import json, posix
        from detpy import _proof

        noted = []
        _proof._note_env = noted.append
        _proof._patch_posix_environ()
        names = list(reversed(posix.environ))
        print(json.dumps({"noted": [n if isinstance(n, str) else n.decode() for n in noted], "n": len(names)}))
    """, tmp_path)
    assert out["n"] > 0 and "*" in out["noted"], out


def test_import_machinery_api_called_by_a_test_is_an_input(tmp_path):
    """protects=a test that builds ``importlib.machinery.FileFinder`` on a directory outside sys.path and asks it for a
    module is rerun when the directory gains that module (founder decision 2026-11-25: close the import-machinery
    bypass for APIs a test calls itself); fails_when=the stat probes through ``_bootstrap_external`` pass as the
    import system's own and the cached pass is reused while uncached --det fails (this branch at 44069221: MEASURED);
    no_claim=``import`` statements and importlib.util.find_spec (recorded by the module-lookup finder, unchanged)."""
    (tmp_path / "lib2").mkdir()
    body = ("import importlib.machinery as M, os\n\ndef test_v():\n"
            "    f = M.FileFinder(os.path.abspath('lib2'), (M.SourceFileLoader, ['.py']))\n"
            "    assert f.find_spec('opt') is None\n")
    cached, uncached, log = _cache_vs_uncached(tmp_path, {"tests/test_v.py": body},
                                               lambda r: (r / "lib2" / "opt.py").write_text("X = 1\n"),
                                               "tests/test_v.py::test_v")
    assert uncached == "failed"
    assert cached == "failed", log[-1500:]


def test_w8_a_c_generator_seeded_by_an_object_hash_is_a_gap():
    """protects=``_random.Random(obj)`` and ``r.seed(obj)`` on a C generator with a seed whose hash may be an address
    (any type but int, bool, float, str, bytes: ``_random`` seeds from ``hash(obj)``) are a gap (founder decision
    2026-11-25); fails_when=only None counts as unseeded (this branch at 44069221); no_claim=the Python
    ``random.Random`` (it refuses such seed types itself: TypeError)."""
    import _random

    from detpy import provable

    missing = getattr(sys.monitoring, "MISSING")
    gap, reseed = provable._unseeded_c_random, provable._c_random_reseed
    for seed in (object(), (1, 2), frozenset({1})):
        assert gap(_random.Random, seed), seed
        assert reseed(_random.Random(0).seed, seed), seed
    for seed in (0, 7, True, 1.5, "s", b"b"):
        assert not gap(_random.Random, seed), seed
        assert not reseed(_random.Random(0).seed, seed), seed
    assert gap(_random.Random, missing) and gap(_random.Random, None)


def test_a_stat_in_another_thread_is_recorded_while_one_thread_is_inside_the_record(tmp_path):
    """protects=while thread A is inside the capture's stat record (stat_check), thread B's ``posix.stat`` and
    ``os.stat`` are still recorded (founder decision 2026-11-25: the in-record flag was the capture's, shared by every
    thread); fails_when=B's reads pass unrecorded because A holds the flag (release-1 and this branch at 44069221);
    no_claim=the capture's own locking in Rust."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    out = _child(f"""
        import json, os, posix, sys, threading
        from detpy import _proof

        inside, release = threading.Event(), threading.Event()

        class Stub:
            def __init__(self):
                self.calls = []
            def stat_check(self, path, *a):
                name = os.fsdecode(os.fspath(path))
                self.calls.append(name)
                if name.endswith("a.txt"):
                    inside.set()
                    release.wait(10)
            def fields_check(self, *a): pass
            def time_check(self, *a): pass
            def flag(self, *a): pass
            def _cur(self): return 0

        cap = Stub()
        _proof.Capture._patch_stat(cap)
        a, b = {repr(str(tmp_path / "a.txt"))}, {repr(str(tmp_path / "b.txt"))}
        t = threading.Thread(target=lambda: posix.stat(a))
        t.start()
        inside.wait(10)
        posix.stat(b)
        os.stat(b)
        release.set()
        t.join(10)
        for obj, name, v in reversed(cap._stat_saved):
            setattr(obj, name, v)
        print(json.dumps({{"calls": cap.calls}}))
    """, tmp_path)
    b = str(tmp_path / "b.txt")
    assert out["calls"].count(b) == 2, out


@pytest.mark.parametrize("build", ["list(map(_random.Random, [None]))[0]", "functools.partial(_random.Random)()",
                                   "type.__call__(_random.Random)"],
                         ids=["map", "functools.partial", "type.__call__"])
def test_w8_a_c_generator_built_from_c_code_is_never_reused(tmp_path, build):
    """protects=an unseeded C generator constructed where C code calls the type (``map``, ``functools.partial``,
    ``type.__call__``: no CALL event names ``_random.Random``) is the W8 gap, NOT PROVEN and never reused (founder
    decision 2026-11-25, /plan-eng-review D1 = A: ``_random.Random`` is replaced with a controlled subclass while the
    sensor runs); fails_when=the warm cached run reuses it with proof while fresh --det runs read different values
    (this branch at 3c9d2b09: MEASURED for map, /review red team for all three); no_claim=the class reached through
    ``random.Random.__mro__`` or bound before the sensor started (docs/LIMITS.md section 10)."""
    body = f"import _random, functools\n\ndef test_e():\n    r = {build}\n    print('VALUE', r.random())\n"
    cached, _, log = _cache_vs_uncached(tmp_path, {"tests/test_e.py": body}, lambda r: None, "tests/test_e.py::test_e")
    assert cached == "passed", log[-1500:]
    assert "not cacheable" in log, log[-1500:]
    assert not any(ln.startswith("reused 1 ") for ln in log.splitlines()), log[-1500:]


def test_w8_a_seeded_c_generator_stays_reusable_through_the_controlled_class(tmp_path):
    """protects=positive control of the controlled ``_random.Random``: a generator seeded with an int, built directly
    and through ``map``, is reused with proof, and ``type(r) is _random.Random`` and ``isinstance`` still hold for the
    test; fails_when=the controlled class's own reseed through the C slot is reported as a gap (a false red), or it
    breaks the type the test sees; no_claim=other seed types (``_entropy_or_address_seed``: the unit tests above)."""
    body = ("import _random\n\ndef test_e():\n    a = _random.Random(5)\n    b = list(map(_random.Random, [5]))[0]\n"
            "    assert type(a) is _random.Random and isinstance(b, _random.Random)\n"
            "    assert a.random() == b.random()\n    print('VALUE', a.random())\n")
    cached, uncached, log = _cache_vs_uncached(tmp_path, {"tests/test_e.py": body}, lambda r: None,
                                               "tests/test_e.py::test_e")
    assert uncached == "passed" and cached == "passed", log[-1500:]
    assert any(ln.startswith("reused 1 ") for ln in log.splitlines()), log[-1500:]


@pytest.mark.parametrize("call", ["posix.statvfs('.').f_bavail", "posix.fstatvfs(0).f_bavail"],
                         ids=["statvfs", "fstatvfs"])
def test_posix_statvfs_is_recorded_like_os_statvfs(tmp_path, call):
    """protects=a disk measurement read through ``posix.statvfs`` / ``posix.fstatvfs`` (the builtins ``os.statvfs`` is,
    reached without ``os``) is recorded in the trace like ``os.statvfs`` (osstate control, /review red team, W3 family,
    4bd560da); fails_when=``posix`` keeps the unwrapped builtin and the read leaves no record (release-1 24962a94),
    so a test whose outcome depends on free space compares equal across runs; no_claim=what the verifier does with
    the record (the existing os.statvfs tests)."""
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_v.py").write_text(f"import posix\n\ndef test_v():\n    assert {call} >= 0\n")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS",)}
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--det",
                        "tests"], cwd=tmp_path, capture_output=True, text=True, env=env, timeout=600)
    assert p.returncode == 0, p.stdout[-1500:] + p.stderr[-1500:]
    trace = (tmp_path / ".detpy" / "trace.jsonl").read_text()
    name = call.split("(")[0].replace("posix.", "os.")
    assert f'"{name}"' in trace, trace[-2000:]


def test_the_controlled_class_keeps_isinstance_and_issubclass_of_the_c_type(tmp_path):
    """protects=under --det user code sees ``_random.Random`` as the C type for ``isinstance`` / ``issubclass``: a
    ``random.Random`` (whose base is the original C type), a ``SystemRandom`` and a generator built before the sensor
    are instances, ``random.Random`` is a subclass; a user's own subclass of ``_random.Random`` keeps ordinary checks;
    fails_when=the controlled subclass answers only for its own instances (this branch at 3b08fa26: all False under
    --det, True without it -- /review Step 4.7 QA, capture 002); no_claim=``type(x) is _random.Random`` for a generator
    built before the sensor started (docs/LIMITS.md section 10)."""
    (tmp_path / "pytest.ini").write_text("[pytest]\npythonpath = .\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_t.py").write_text(
        "import _random, random\n\n"
        "def test_t():\n"
        "    assert isinstance(random.Random(0), _random.Random)\n"
        "    assert isinstance(random.SystemRandom(), _random.Random)\n"
        "    assert issubclass(random.Random, _random.Random) and issubclass(_random.Random, _random.Random)\n"
        "    assert isinstance(_random.Random(1), _random.Random) and type(_random.Random(1)) is _random.Random\n"
        "    assert not isinstance(1, _random.Random) and not issubclass(int, _random.Random)\n"
        "    class R(_random.Random):\n        pass\n"
        "    assert isinstance(R(2), R) and isinstance(R(2), _random.Random)\n"
        "    assert not isinstance(_random.Random(2), R) and not isinstance(random.Random(0), R)\n"
        "    assert not issubclass(random.Random, R)\n")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS",)}
    for args in ([], ["--det"]):
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", *args,
                            "tests"], cwd=tmp_path, capture_output=True, text=True, env=env, timeout=600)
        assert p.returncode == 0, f"{args}\n{p.stdout[-2000:]}"
