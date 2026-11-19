"""``python -m detpy ward``: controls and adversarial cases (the shared table as ward tests, plus ward's own: module
and global fixtures reading files, parameterised tests)."""

from __future__ import annotations

import sys
import textwrap

import pytest

from runners_cases import CASES, PRELUDE, check_case, run_case
from runners_util import run, write

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
pytest.importorskip("ward")


def wd(root, *args, **kw):
    return run("ward", root, "test", "--path", "tests", *args, **kw)


MODULE = """
import random, time
from ward import test, each

@test("clock")
def _():
    t0 = time.time()
    time.sleep(3)
    assert time.time() - t0 >= 3

@test("random")
def _():
    print(random.random())

@test("param {x}")
def _(x=each(1, 2, 3)):
    assert x > 0
"""


def test_two_det_runs_give_identical_fingerprints(tmp_path):
    root = tmp_path / "p"
    write(root, {"tests/test_w.py": MODULE})
    a = wd(root, cache=False)
    b = wd(root, cache=False)
    assert len(a.outcomes) == 5 and set(a.outcomes.values()) == {"passed"}, a
    assert a.fingerprints == b.fingerprints
    assert "tests/test_w.py::param {x}[2]" in a.outcomes


def test_seeded_shuffle_is_reproducible(tmp_path):
    root = tmp_path / "p"
    write(root, {f"tests/test_m{m}.py": "from ward import test\n" + "".join(
        f"\n@test('t{t}')\ndef _():\n    pass\n" for t in range(6)) for m in range(3)})
    s5 = wd(root, cache=False, det_args=["--det-seed=5"])
    s5b = wd(root, cache=False, det_args=["--det-seed=5"])
    s6 = wd(root, cache=False, det_args=["--det-seed=6"])
    assert len(s5.order) == 18 and s5.order == s5b.order and s5.order != s6.order


def test_controls_are_active_inside_ward_tests(tmp_path):
    root = tmp_path / "p"
    write(root, {"tests/test_c.py": """
        import os, time
        from ward import test

        @test("clock")
        def _():
            assert int(time.time()) == 1893456000

        @test("hash seed")
        def _():
            assert os.environ.get("PYTHONHASHSEED") == "0"
        """})
    r = wd(root, cache=False, det_args=["--det-epoch=2030-01-01T00:00:00"])
    assert set(r.outcomes.values()) == {"passed"} and len(r.outcomes) == 2, r


def _module(c) -> str:
    body = textwrap.indent(c["body"], " " * 4)
    return (PRELUDE + c["prelude"] + "from ward import test\n\n\n@test('control')\ndef _():\n    assert 1 + 1 == 2\n\n\n"
            "@test('case')\ndef _():\n" + body + "\n")


@pytest.mark.parametrize("c", CASES, ids=[c["name"] for c in CASES])
def test_wrong_reuse(tmp_path, c):
    root = tmp_path / "p"
    (root / "tests").mkdir(parents=True)
    first, second = run_case(c, lambda r, env: wd(r, env=env, safe_path=True, det_args=["--det-urandom"]), root,
                             lambda r, c: (r / "tests" / "test_case.py").write_text(_module(c)), root / "tests")
    check_case(c, first, second, "tests/test_case.py::case", "tests/test_case.py::control")


def test_module_and_global_fixture_reads_are_inputs_of_their_users(tmp_path):
    root = tmp_path / "p"
    write(root, {"mod.txt": "1\n", "glob.txt": "1\n", "tests/test_f.py": """
        from ward import fixture, test, Scope

        @fixture(scope=Scope.Global)
        def g():
            return open("glob.txt").read()

        @fixture(scope=Scope.Module)
        def m(gv=g):
            return open("mod.txt").read() + gv

        @test("uses module fixture")
        def _(v=m):
            assert v == "1\\n1\\n"

        @test("uses global fixture only")
        def _(v=g):
            assert v == "1\\n"

        @test("plain")
        def _():
            pass
        """})
    wd(root)
    assert len(wd(root).reused) == 3
    write(root, {"mod.txt": "2\n"})
    r = wd(root)
    assert r.outcomes["tests/test_f.py::uses module fixture"] == "failed", r
    assert r.reused == {"tests/test_f.py::uses global fixture only", "tests/test_f.py::plain"}, r
    write(root, {"mod.txt": "1\n", "glob.txt": "2\n"})
    r = wd(root)
    assert r.outcomes["tests/test_f.py::uses global fixture only"] == "failed", r
    assert r.outcomes["tests/test_f.py::uses module fixture"] == "failed", r
    assert r.reused == {"tests/test_f.py::plain"}, r
