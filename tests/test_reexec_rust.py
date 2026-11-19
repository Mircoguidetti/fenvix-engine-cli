"""Equivalence of ``detpy.reexec`` after its remaining logic moved to Rust (rust-hotpaths-2,
``crates/detpy-py/src/reexec.rs``, ``crates/detpy-core/src/reexec.rs``) with the Python original kept verbatim in
``tests/rust_hotpaths_ref/_ref_reexec_r2.py``: ``aslr_disabled`` (and its parse of ``/proc/self/personality``),
``_disable_aslr_for_exec`` (in a child process), ``pyc_cache_dir``, ``bytecode_active``, ``plan``, ``_argv``,
``can_reexec``, ``precompile_dirs`` and ``precompile``'s stamps file and todo/fresh decision (the driver commands it
runs and the stamps it writes, byte for byte), on generated inputs.
"""

from __future__ import annotations

import importlib.util
import io
import json
import math
import os
import random
import re
import subprocess
import sys
import sysconfig
from pathlib import Path
from types import SimpleNamespace

import pytest

from detpy import _core, reexec

REF = Path(__file__).parent / "rust_hotpaths_ref"


def _load_ref():
    spec = importlib.util.spec_from_file_location("detpy._ref_reexec_r2", REF / "_ref_reexec_r2.py")
    m = importlib.util.module_from_spec(spec)
    m.__package__ = "detpy"
    spec.loader.exec_module(m)
    m._driver_source = reexec._driver_source  # the current driver (--stdin), as the reference used it
    return m


ref = _load_ref()


def _exc(fn, *a, **k):
    try:
        return fn(*a, **k), None
    except Exception as e:  # noqa: BLE001 - compared, not handled
        return None, (type(e).__name__, str(e))


def _typed(x):
    """Values with their types (0 and False differ)."""
    if isinstance(x, dict):
        return {k: _typed(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return type(x).__name__, [_typed(v) for v in x]
    return type(x).__name__, x


# ---------------------------------------------------------------------------------------------------------------------
# personality


def test_aslr_disabled_matches_reference():
    assert reexec.aslr_disabled() == ref.aslr_disabled()


@pytest.mark.parametrize("seed", range(4))
def test_personality_parse_matches_reference(seed, monkeypatch):
    rng = random.Random(seed)
    texts = ["00000000\n", "00040000\n", "0040000", "0x40000", "0X_4_0000", " 40000 ", "-1", "+40000", "-40000",
             "fffffffffffffffffffff", "1" * 40, "", "\n", "0x", "_1", "1_", "1__0", "g", "0x0x1", "4 0", " 40000　",
             "40000\x00", "٤0000", "0b1", "1e3"]
    alphabet = "0123456789abcdefABCDEFxX_-+ \n\t"
    texts += ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 20))) for _ in range(800)]
    for t in texts:
        monkeypatch.setattr(ref, "open", lambda *a, t=t, **k: io.StringIO(t), raising=False)
        want = ref.aslr_disabled()
        got = _core.reexec_parse_personality(t)
        if t == "٤0000":  # a non-ASCII decimal digit: Python's int() accepts it, the Rust parse does not
            assert want is True and got is None
            continue
        assert got == want, repr(t)
    monkeypatch.setattr(ref, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("no /proc")), raising=False)
    assert ref.aslr_disabled() is None


_CHILD = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("detpy._ref_reexec_r2", sys.argv[2])
m = importlib.util.module_from_spec(spec); m.__package__ = "detpy"; spec.loader.exec_module(m)
from detpy import reexec
before = open("/proc/self/personality").read().strip()
ok = (m if sys.argv[1] == "ref" else reexec)._disable_aslr_for_exec()
print(before, ok, open("/proc/self/personality").read().strip(), (m if sys.argv[1] == "ref" else reexec).aslr_disabled())
"""


@pytest.mark.skipif(not os.path.exists("/proc/self/personality"), reason="Linux only")
def test_disable_aslr_for_exec_matches_reference():
    out = [subprocess.run([sys.executable, "-c", _CHILD, which, str(REF / "_ref_reexec_r2.py")], capture_output=True,
                          text=True, check=True).stdout for which in ("ref", "rust")]
    assert out[0] == out[1]
    assert out[0].split()[1] == "True" and out[0].split()[3] == "True", out  # it did disable ASLR


# ---------------------------------------------------------------------------------------------------------------------
# cache directory, bytecode, plan


_ENV_VALUES = {
    "DETPY_PYC_CACHE": [None, "", "/c/pyc", "rel/c", "/c/trail/"],
    "XDG_CACHE_HOME": [None, "", "/x", "/x/", "relx", "/x/caf\udce9"],
    "HOME": [None, "", "/", "/h", "/h//", "h", "~"],
}


def _set_env(monkeypatch, combo):
    for k, v in combo.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def _combos(rng, n):
    for _ in range(n):
        yield {k: rng.choice(v) for k, v in _ENV_VALUES.items()}


def test_pyc_cache_dir_matches_reference(monkeypatch):
    rng = random.Random(3)
    seen = set()
    for combo in _combos(rng, 300):
        _set_env(monkeypatch, combo)
        for seed in ("0", "42", "random", "a/b"):
            got, want = reexec.pyc_cache_dir(seed), ref.pyc_cache_dir(seed)
            assert got == want and type(got) is type(want), combo
            seen.add(want)
    assert len(seen) > 20


def test_bytecode_active_and_plan_match_reference(monkeypatch, tmp_path):
    rng = random.Random(4)
    real = tmp_path / "cache"
    (tmp_path / "link").symlink_to(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DETPY_PYC_CACHE", str(real))
    target = ref.pyc_cache_dir("0")
    prefixes = [None, "", target, str(tmp_path / "link" / "cache" / Path(target).name), os.path.relpath(target),
                target + "/", target + "/../" + Path(target).name, str(tmp_path / "other"), "cache/missing/.."]
    flags = [SimpleNamespace(dont_write_bytecode=v) for v in (0, 1, True, False)]
    for _ in range(300):
        monkeypatch.setattr(sys, "pycache_prefix", rng.choice(prefixes))
        monkeypatch.setattr(sys, "flags", rng.choice(flags))
        if rng.random() < 0.5:
            Path(target).mkdir(parents=True, exist_ok=True)
        hs = rng.choice(["0", "1"])
        assert reexec.bytecode_active(hs) == ref.bytecode_active(hs), (sys.pycache_prefix, sys.flags)
        env_hs = rng.choice([None, "0", "1", ""])
        if env_hs is None:
            monkeypatch.delenv("PYTHONHASHSEED", raising=False)
        else:
            monkeypatch.setenv("PYTHONHASHSEED", env_hs)
        args = (hs, rng.choice([True, False, 0, 1, None, ""]), rng.choice([True, False, 0, None, "x"]))
        assert _typed(reexec.plan(*args)) == _typed(ref.plan(*args)), args
    assert _typed(reexec.plan("0", True)) == _typed(ref.plan("0", True))  # the default want_bytecode


# ---------------------------------------------------------------------------------------------------------------------
# command line and can_reexec


def test_argv_and_can_reexec_match_reference(monkeypatch):
    rng = random.Random(5)
    main = sys.modules["__main__"]
    mains = [main, None, SimpleNamespace(), SimpleNamespace(__spec__=None),
             SimpleNamespace(__spec__=SimpleNamespace(name="pytest")),
             SimpleNamespace(__spec__=SimpleNamespace(name="pytest.__main__")),
             SimpleNamespace(__spec__=SimpleNamespace(name="other"))]
    origs = ["missing", [], ["python"], ["python", "-X", "dev", "-m", "pytest", "-q"], ("py", "a")]
    argvs = [[], [""], ["prog"], ["/x/pytest", "-k", "it's"], ["", "a"]]
    for _ in range(400):
        orig = rng.choice(origs)
        if orig == "missing":
            monkeypatch.delattr(sys, "orig_argv", raising=False)
        else:
            monkeypatch.setattr(sys, "orig_argv", orig, raising=False)
        monkeypatch.setattr(sys, "argv", rng.choice(argvs))
        monkeypatch.setitem(sys.modules, "__main__", rng.choice(mains))
        monkeypatch.setattr(sys, "executable", rng.choice(["/usr/bin/python3", ""]))
        assert reexec._argv() == ref._argv()
        marker = rng.choice([None, "1", "0", ""])
        if marker is None:
            monkeypatch.delenv("DETPY_REEXEC", raising=False)
        else:
            monkeypatch.setenv("DETPY_REEXEC", marker)
        depth = rng.choice([0, 1, 2, 5])
        monkeypatch.setattr(reexec, "SESSION_DEPTH", depth)
        monkeypatch.setattr(ref, "SESSION_DEPTH", depth)
        monkeypatch.setattr(os, "name", rng.choice(["posix", "posix", "nt"]))
        got, want = reexec.can_reexec(), ref.can_reexec()
        monkeypatch.setattr(os, "name", "posix")
        assert got == want


# ---------------------------------------------------------------------------------------------------------------------
# precompile: directories, stamps, todo


def test_precompile_dirs_match_reference(monkeypatch, tmp_path):
    rng = random.Random(6)
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    (tmp_path / "f").write_text("x")
    (tmp_path / "la").symlink_to(tmp_path / "a")
    (tmp_path / "lla").symlink_to(tmp_path / "la")
    (tmp_path / "dangling").symlink_to(tmp_path / "nope")
    monkeypatch.chdir(tmp_path)
    cands = [None, "", str(tmp_path / "a"), str(tmp_path / "la"), str(tmp_path / "lla"), "a", "./b", "a/../b",
             str(tmp_path / "f"), str(tmp_path / "nope"), str(tmp_path / "dangling"), str(tmp_path / "c") + "/",
             str(tmp_path / "b")]
    for _ in range(400):
        paths = {k: rng.choice(cands) for k in ("stdlib", "purelib", "platlib") if rng.random() < 0.9}
        if rng.random() < 0.2:
            paths["data"] = str(tmp_path / "c")
        monkeypatch.setattr(sysconfig, "get_paths", lambda paths=paths: dict(paths))
        root = rng.choice(cands)
        got, want = reexec.precompile_dirs(root), ref.precompile_dirs(root)
        assert got == want, (paths, root)


class _Spy:
    def __init__(self, rc=0):
        self.calls = []
        self.rc = rc

    def __call__(self, cmd, env=None, input=None, **kw):
        self.calls.append(([c if not c.startswith('"""') else "<driver>" for c in cmd], input,
                           env["PYTHONHASHSEED"], env["PYTHONPYCACHEPREFIX"]))
        return SimpleNamespace(returncode=self.rc)


def _tree(root: Path, rng: random.Random) -> list:
    libs = []
    for i in range(rng.randint(1, 3)):
        lib = root / f"lib{i}"
        (lib / f"pkg{i}").mkdir(parents=True)
        (lib / f"pkg{i}" / "__init__.py").write_text(f"X = {i}\n")
        (lib / f"m{i}.py").write_text("Y = {1, 2}\n")
        if rng.random() < 0.5:
            (lib / f"dist{i}-1.0.dist-info").mkdir()
            (lib / f"dist{i}-1.0.dist-info" / "RECORD").write_text("r\n")
        libs.append(str(lib))
    proj = root / "proj"
    (proj / "pkg").mkdir(parents=True)
    (proj / "pkg" / "a.py").write_text("A = 1\n")
    (proj / ".git").mkdir()
    (proj / ".git" / "h.py").write_text("H = 1\n")
    return libs + [str(proj)]


_STAMPS = [None, "", "{}", "garbage", '{"a": "b"}', '{"x": 1, "y": [1.5, null, true], "z": {"k": "v", "k": "w"}}',
           '{"\\ud83d\\ude00": "\\udce9", "big": 123456789012345678901234567890, "f": 1e400, "n": NaN}',
           "﻿{}", '{"a": 1,}']


@pytest.mark.parametrize("seed", range(12))
def test_precompile_stamps_and_todo_match_reference(seed, monkeypatch, tmp_path):
    rng = random.Random(seed)
    results = []
    for mod in (ref, reexec):
        r2 = random.Random(seed)
        base = tmp_path / mod.__name__
        dirs = _tree(base, r2)
        root = r2.choice([dirs[-1], dirs[-1] + "/", None, str(base / "missing")])
        if r2.random() < 0.3:
            dirs.insert(0, dirs[0])  # a directory twice
        if r2.random() < 0.3 and root is not None:
            dirs.append(os.path.relpath(dirs[-1]))
        monkeypatch.setattr(mod, "precompile_dirs", lambda rootdir, dirs=dirs: list(dirs))
        monkeypatch.setenv("DETPY_PYC_CACHE", str(base / "pyc"))
        prefix = mod.pyc_cache_dir("0")
        os.makedirs(prefix, exist_ok=True)
        stamps = Path(prefix) / "stamps-v3.json"
        initial = r2.choice(_STAMPS)
        if initial is not None:
            stamps.write_text(initial.replace("LIB0", dirs[0]))
        seq = []
        for step in range(4):
            spy = _Spy(rc=r2.choice([0, 0, 0, 1]))
            monkeypatch.setattr(subprocess, "run", spy)
            mod.precompile("0", root)
            seq.append(([(c, d, hs, p.replace(str(base), "<base>")) for c, d, hs, p in
                         [(_rel(c, base), _rel_data(d, base), hs, p) for c, d, hs, p in spy.calls]],
                        stamps.read_bytes().replace(os.fsencode(str(base)), b"<base>") if stamps.exists() else None))
            # change things between the runs: a new library entry, an edited project file, a stale stamp
            what = r2.choice(["lib", "proj", "none", "stamp"])
            if what == "lib":
                (Path(dirs[0]) / f"new{step}.py").write_text("N = 1\n")
            elif what == "proj":
                (Path(dirs[-1]) / "pkg" / "a.py").write_text(f"A = {step + 2}\n")
            elif what == "stamp" and stamps.exists():
                try:
                    data = json.loads(stamps.read_text())
                except ValueError:
                    data = None
                if isinstance(data, dict) and data:
                    data[next(iter(data))] = "stale"
                    stamps.write_text(json.dumps(data))
        results.append(_canonical_digests(seq))
    assert results[0] == results[1]


def _canonical_digests(seq):
    """dir_stamp digests renamed by first appearance: the two trees hold other inodes and mtimes, the same history."""
    names = {}

    def sub(m):
        return b"<d%d>" % names.setdefault(m.group(0), len(names))

    return [(calls, None if st is None else re.sub(rb"[0-9a-f]{64}", sub, st)) for calls, st in seq]


def _rel(cmd, base):
    return [c.replace(str(base), "<base>") for c in cmd]


def _rel_data(data, base):
    return None if data is None else data.replace(os.fsencode(str(base)), b"<base>")


def test_precompile_stamps_file_that_is_not_an_object(monkeypatch, tmp_path):
    """The one documented difference: a stamps file holding another JSON value raised AttributeError in the
    original (the session failed); it now counts as no stamps."""
    lib = tmp_path / "lib"
    lib.mkdir()
    for mod in (ref, reexec):
        monkeypatch.setattr(mod, "precompile_dirs", lambda rootdir: [str(lib)])
        monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / mod.__name__))
        prefix = mod.pyc_cache_dir("0")
        os.makedirs(prefix)
        (Path(prefix) / "stamps-v3.json").write_text("[1, 2]")
        monkeypatch.setattr(subprocess, "run", _Spy())
    with pytest.raises(AttributeError):
        ref.precompile("0", None)
    reexec.precompile("0", None)
    stamps = json.loads((Path(reexec.pyc_cache_dir("0")) / "stamps-v3.json").read_text())
    assert stamps == {str(lib): _core.dir_stamp(str(lib))}


def _random_json(rng, depth=0):
    r = rng.random()
    if depth > 3 or r < 0.35:
        return rng.choice([None, True, False, 0, -0, 1, -17, 2**70, -(2**64), 1.5, -0.0, 1e-7, 1e22, 3.141592653589793,
                           float("inf"), float("-inf"), float("nan"), "", "a", "é", "😀", "\udce9", "\ud83d", "q\"\\/\n\t\x01\x7f",
                           " "])
    if r < 0.7:
        return {rng.choice(["a", "b", "é", "😀", "\udce9", "", "k"]) + str(rng.randint(0, 3)): _random_json(rng, depth + 1)
                for _ in range(rng.randint(0, 4))}
    return [_random_json(rng, depth + 1) for _ in range(rng.randint(0, 4))]


def _python_stamps(raw: bytes) -> str | None:
    """What the original wrote back for a stamps file and no directories: json.dump of {**json.load(f)}."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return None
    return json.dumps({**data})


def test_stamps_json_read_and_write_match_python_json(tmp_path):
    rng = random.Random(11)
    path = tmp_path / "stamps.json"
    checked = 0
    for i in range(3000):
        obj = {"/usr/lib/python3": "ab12", **{f"k{j}": _random_json(rng) for j in range(rng.randint(0, 4))}}
        if rng.random() < 0.2:
            obj = _random_json(rng)
        text = json.dumps(obj, ensure_ascii=rng.random() < 0.5, indent=rng.choice([None, 0, 2]),
                          separators=rng.choice([None, (",", ":"), (" , ", " : ")]))
        if rng.random() < 0.15:  # a repeated key
            text = text.replace("{", '{"k0": "first", ', 1) if text.startswith("{") and len(text) > 2 else text
        if rng.random() < 0.15 and text:  # corruption
            k = rng.randrange(len(text))
            text = text[:k] + rng.choice(["", "x", "\\", '"', ",", "\x00", " "]) + text[k + 1:]
        raw = text.encode("utf-8", "surrogatepass")
        path.write_bytes(raw)
        want = _python_stamps(raw)
        if want is None:
            continue
        got = _core.reexec_precompile_plan([], None, str(path))[2].dumps()
        assert got == want, text
        checked += 1
    assert checked > 2000
