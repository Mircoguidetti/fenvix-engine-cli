"""Point 2: fixed seeds for random, numpy and PYTHONHASHSEED."""

import importlib.util

import pytest

HAS_NUMPY = importlib.util.find_spec("numpy") is not None


def values(result, tag):
    return [line.split(tag, 1)[1].strip() for line in result.outlines if tag in line]


RANDOM_TESTS = """
import random, os
def test_a():
    print("VAL-a", random.random(), random.randint(0, 10**9))
def test_b():
    print("VAL-b", random.random(), random.Random().random())
def test_hash():
    print("VAL-hash", hash("detpy"), list({"x", "y", "z", "w"}), os.environ.get("PYTHONHASHSEED"))
"""


def test_random_and_hash_seed_are_fixed(pytester, run_det):
    pytester.makepyfile(test_r=RANDOM_TESTS)
    r1, t1 = run_det("-s")
    r2, _ = run_det("-s")
    assert t1[0]["meta"]["bytecode"] == "precompiled"
    assert t1[0]["meta"]["precompile_s"] >= 0
    for tag in ("VAL-a", "VAL-b", "VAL-hash"):
        v1, v2 = values(r1, tag), values(r2, tag)
        assert v1 and v1 == v2, tag
    assert values(r1, "VAL-hash")[0].endswith(" 0")  # PYTHONHASHSEED=0 after re-exec


def test_values_do_not_depend_on_position(pytester, run_det):
    pytester.makepyfile(test_r=RANDOM_TESTS)
    full, _ = run_det("-s")
    alone, _ = run_det("-s", "test_r.py::test_b")
    shuffled, _ = run_det("-s", "--det-seed=0")  # same seed, other order code path
    assert values(full, "VAL-b") == values(alone, "VAL-b") == values(shuffled, "VAL-b")


def test_seed_changes_values(pytester, run_det):
    pytester.makepyfile(test_r=RANDOM_TESTS)
    a, _ = run_det("-s", "--det-seed=1")
    b, _ = run_det("-s", "--det-seed=2")
    assert values(a, "VAL-a") != values(b, "VAL-a")
    assert values(b, "VAL-hash")[0].endswith(" 2")


def test_no_reexec_reports_unfixed_hash_seed(pytester, run_det, monkeypatch):
    pytester.makepyfile(test_r="def test_x(): pass")
    monkeypatch.setenv("PYTHONHASHSEED", "123")
    r, t = run_det("--det-no-reexec")
    assert t[0]["meta"]["hashseed"] == "123"
    assert "not fixed" in t[0]["meta"]["reexec"]
    r.stdout.fnmatch_lines(["*PYTHONHASHSEED=123 (PYTHONHASHSEED not fixed*"])


def test_random_events_are_recorded(pytester, run_det):
    pytester.makepyfile(test_r=RANDOM_TESTS)
    _, (_, tests, _) = run_det()
    ops = [e["o"] for e in tests["test_r.py::test_a"]["events"]]
    assert ops[:2] == ["random.random", "random.randint"]
    assert "random.state" in ops
    b_ops = [e["o"] for e in tests["test_r.py::test_b"]["events"]]
    assert "Random.seed(None)" in b_ops
    site = tests["test_r.py::test_a"]["events"][0]["at"]
    assert site == "test_r.py:3"


@pytest.mark.skipif(not HAS_NUMPY, reason="numpy not installed")
def test_numpy_is_seeded(pytester, run_det):
    pytester.makepyfile(
        test_np="""
        import numpy as np
        def test_np():
            print("VAL-np", np.random.rand(), np.random.default_rng().random())
        """
    )
    a, _ = run_det("-s")
    b, _ = run_det("-s")
    assert values(a, "VAL-np") and values(a, "VAL-np") == values(b, "VAL-np")


def test_without_det_nothing_is_fixed(pytester):
    pytester.makepyfile(test_r=RANDOM_TESTS)
    a = pytester.runpytest_subprocess("-s", "-p", "no:cacheprovider")
    b = pytester.runpytest_subprocess("-s", "-p", "no:cacheprovider")
    assert values(a, "VAL-a") != values(b, "VAL-a")


SET_MODULE = "def order():\n    return list({'x', 'y', 'z', 'w'})\n"


def test_precompiled_bytecode_makes_first_run_agree(pytester, run_det):
    """A set literal's order depends on whether its module was compiled from
    source or loaded from a .pyc. With the deterministic precompilation every
    run (the first one included) loads the same bytecode."""
    pytester.makepyfile(setmod=SET_MODULE, test_s="import setmod\ndef test_s():\n    print('VAL-set', setmod.order())\n")
    runs = [values(run_det("-s")[0], "VAL-set") for _ in range(3)]
    assert runs[0] and runs[0] == runs[1] == runs[2]


def test_without_precompilation_the_first_run_can_differ(pytester, run_det):
    pytester.makepyfile(setmod=SET_MODULE, test_s="import setmod\ndef test_s():\n    print('VAL-set', setmod.order())\n")
    runs = [values(run_det("-s", "--det-disable=bytecode")[0], "VAL-set") for _ in range(3)]
    assert runs[1] == runs[2]
    assert runs[0] != runs[1]  # compiled from source vs loaded from the .pyc written by run 1
