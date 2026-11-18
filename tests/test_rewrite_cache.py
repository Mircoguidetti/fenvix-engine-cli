"""--det keeps pytest's assertion-rewritten test modules in its deterministic bytecode cache (``plugin.
_cache_rewritten_tests``): the second run loads them, a stale one is never used (pytest >= 9 checks the source's
hash), and the first run already executes the marshalled code that later runs load."""

import os
import subprocess
import sys
import textwrap

import pytest

rw = pytest.importorskip("_pytest.assertion.rewrite")
pytestmark = pytest.mark.skipif(b"\x03\x00\x00\x00" not in rw._read_pyc.__code__.co_consts,
                                reason="pytest without checked-hash rewritten pycs")

TEST = """
    S = {"pear", "fig", "apple", "kiwi", "plum", "lime", "date", "yuzu"}


    def test_order():
        print("ORDER", list(S))
        assert 1 + 1 == {VALUE}
    """


def _run(root, env, *extra):
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--det", "-s", "-q",
                           "--det-outcomes=" + str(root / "o.json"), *extra], cwd=root, env=env,
                          capture_output=True, text=True, timeout=300)


def _rewritten(prefix):
    return sorted(f for _r, _d, fs in os.walk(prefix) for f in fs if "-pytest-" in f)


def test_rewritten_tests_are_cached_and_checked(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n")
    src = root / "test_a.py"
    src.write_text(textwrap.dedent(TEST).replace("{VALUE}", "2"))
    (root / "conftest.py").write_text("X = 1\n")
    env = {**os.environ, "DETPY_PYC_CACHE": str(tmp_path / "pyc")}
    r1 = _run(root, env)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    names = _rewritten(tmp_path / "pyc")
    assert any(n.startswith("test_a.") for n in names) and any(n.startswith("conftest.") for n in names), names
    order1 = [x for x in r1.stdout.splitlines() if x.startswith("ORDER")]
    st = os.stat(src)
    pyc = [os.path.join(r, f) for r, _d, fs in os.walk(tmp_path / "pyc") for f in fs if f.startswith("test_a.")
           and "-pytest-" in f][0]
    written = os.stat(pyc).st_mtime_ns
    r2 = _run(root, env)
    assert r2.returncode == 0
    assert os.stat(pyc).st_mtime_ns == written  # loaded, not rewritten (a rewrite writes it again)
    assert [x for x in r2.stdout.splitlines() if x.startswith("ORDER")] == order1  # first run == loaded runs
    # a same-size edit that keeps the mtime: the rewritten pyc is stale by content, the new code runs
    src.write_text(textwrap.dedent(TEST).replace("{VALUE}", "3"))
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns))
    r3 = _run(root, env)
    assert r3.returncode == 1 and "assert (1 + 1) == 3" in r3.stdout, r3.stdout


def test_rewrite_cache_can_be_turned_off(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "test_a.py").write_text(textwrap.dedent(TEST).replace("{VALUE}", "2"))
    env = {**os.environ, "DETPY_PYC_CACHE": str(tmp_path / "pyc"), "DETPY_REWRITE_CACHE": "0"}
    assert _run(root, env).returncode == 0
    assert _rewritten(tmp_path / "pyc") == []
