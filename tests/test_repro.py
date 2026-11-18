"""detpy repro: search, minimisation (polluter / state setter), bundle, replay proof."""
import json
from pathlib import Path

from detpy import repro

PROJECT = """
import os
CACHE = {}
def test_setter():
    os.environ["DETPY_REPRO_FLAG"] = "1"
def test_a(): pass
def test_b(): pass
def test_brittle():
    assert os.environ.get("DETPY_REPRO_FLAG") == "1"
def test_c(): pass
def test_writer():
    CACHE["k"] = 1
def test_d(): pass
def test_victim():
    assert "k" not in CACHE
def test_e(): pass
"""


def _runner(pytester):
    import os
    pytester.makepyfile(test_p=PROJECT)
    pytester.makeini("[pytest]\n")
    return repro.Runner(cwd=Path(pytester.path), workdir=Path(pytester.path) / ".work",
                        pytest_args=["-p", "no:randomly"], timeout=300)


def test_ddmin_keeps_order_and_is_minimal():
    need = {3, 7}
    got = repro.ddmin(list(range(10)), lambda sub: need <= set(sub))
    assert got == [3, 7]
    assert repro.ddmin(list(range(10)), lambda sub: 5 in sub) == [5]


def test_order_for_matches_the_plugin_shuffle():
    ids = [f"t::{i}" for i in range(20)]
    assert repro.order_for(ids, "fixed") == ids
    assert sorted(repro.order_for(ids, "3")) == sorted(ids) and repro.order_for(ids, "3") != ids


def test_repro_names_the_polluter_and_replays(pytester, monkeypatch):
    runner = _runner(pytester)
    out = Path(pytester.path) / "bundles"
    b = repro.reproduce(runner, "test_p.py::test_victim", seeds=5, confirm=3, out_dir=out)
    assert b["status"] == "reproduced", b
    assert b["polluters"] == ["test_p.py::test_writer"]
    assert b["order"] == ["test_p.py::test_writer", "test_p.py::test_victim"]
    assert b["replay"] == {"runs": 3, "fails": 3, "fingerprints": b["replay"]["fingerprints"],
                           "identical_fingerprint": True}
    assert len(b["replay"]["fingerprints"]) == 1
    bundle = Path(b["bundle"])
    assert json.loads((bundle / "bundle.json").read_text())["test"] == "test_p.py::test_victim"
    assert (bundle / "order.txt").read_text().splitlines() == b["order"]
    monkeypatch.chdir(pytester.path)
    again = repro.replay(bundle, 2, runner.python)
    assert again["fails"] == 2 and again["identical_fingerprint"] and again["matches_bundle"]


def test_repro_names_the_state_setter_of_a_brittle_test(pytester):
    runner = _runner(pytester)
    b = repro.reproduce(runner, "test_p.py::test_brittle", seeds=20, confirm=2, out_dir=None)
    assert b["status"] == "reproduced", b
    assert b["kind"] == "brittle" and b["setters"] == ["test_p.py::test_setter"]
    assert b["order"] == ["test_p.py::test_brittle"] and b["config"] != "fixed"


def test_repro_reports_not_found_for_a_stable_test(pytester):
    runner = _runner(pytester)
    b = repro.reproduce(runner, "test_p.py::test_a", seeds=2, confirm=2)
    assert b["status"] == "not-found" and b["configs_searched"] == 3


ORDER_FIRST = """
import os
def test_needs_flag():
    assert os.environ.get("DETPY_REPRO_FLAG2") == "1"
def test_f1(): pass
def test_f2(): pass
def test_sets_flag():
    os.environ["DETPY_REPRO_FLAG2"] = "1"
def test_f3(): pass
"""


def test_standalone_repro_names_the_setter_when_the_fixed_order_fails(pytester):
    """E6 (review R-003): the target fails in the fixed order (its setter runs
    after it); the standalone command must still search a passing order and name
    the setter, as the explore path does."""
    pytester.makepyfile(test_q=ORDER_FIRST)
    pytester.makeini("[pytest]\n")
    runner = repro.Runner(cwd=Path(pytester.path), workdir=Path(pytester.path) / ".work",
                          pytest_args=["-p", "no:randomly"], timeout=300)
    b = repro.reproduce(runner, "test_q.py::test_needs_flag", seeds=20, confirm=2)
    assert b["status"] == "reproduced" and b["config"] == "fixed", b
    assert b["kind"] == "brittle" and b["setters"] == ["test_q.py::test_sets_flag"], b
