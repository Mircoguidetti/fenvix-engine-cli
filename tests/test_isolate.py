"""parallel-proof round 3, the coordinator's variant: ``--det-isolate`` (python/detpy/isolate.py).

Every test runs in a child forked from the session's snapshot: no test sees memory an earlier test left, so the
cache's carried set is empty by construction. The attacks of the carried-set rule are run again in this mode, serial
and ``-n 2``: a reused result must equal a fresh isolated run (the truth of this mode), and must never be wrong when an
input changes. Order-dependent tests (pass only after an earlier test) fail under isolation: never reused.
"""

import json
import sys
import textwrap

import pytest

pytestmark = [pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring"),
              pytest.mark.skipif(not sys.platform.startswith("linux"), reason="fork")]

from test_carried_library_memo import LIBS, ORDER_LIB, _order_project, _project  # noqa: E402


def _run(pytester, n, *args):
    out = pytester.path / f"o{n}.json"
    r = pytester.runpytest_subprocess("--det", "--det-isolate", f"--det-outcomes={out}", "-p", "no:cacheprovider",
                                      *args)
    d = json.loads(out.read_text()) if out.exists() else {}
    o = {k: (v["outcome"] if isinstance(v, dict) else v) for k, v in (d.get("outcomes") or {}).items()}
    return r, o, set((d.get("cache") or {}).get("reused_ids", ())), d


PAR = ("-n", "2", "-p", "xdist", "--dist", "loadgroup")


@pytest.mark.parametrize("mode", ["serial", "n2"])
@pytest.mark.parametrize("kind", sorted(LIBS))
def test_library_memo_under_isolation(pytester, monkeypatch, tmp_path_factory, kind, mode):
    _project(pytester, monkeypatch, tmp_path_factory, kind)
    cache = f"--det-cache={pytester.path / '.c'}"
    par = () if mode == "serial" else PAR
    r0, o0, _, d0 = _run(pytester, 0, cache, *par)
    assert o0["test_a.py::test_a"] == "passed", r0.stdout.str()
    # B alone: it loads the file itself (pass), or reads a memo nobody filled (the repository variant: fails, an
    # order-dependent test exposed)
    assert o0["test_b.py::test_b"] == ("failed" if kind == "repo" else "passed"), r0.stdout.str()
    assert d0["isolate"]["tests"] == 2 and d0["isolate"]["failed_children"] == 0
    (pytester.path / "cfg.yml").write_text("new\n")
    r1, o1, reused, _ = _run(pytester, 1, cache, *par)
    _, truth, _, _ = _run(pytester, 2)
    assert truth["test_b.py::test_b"] == "failed"
    assert {n: (o1[n], truth[n]) for n in reused if o1[n] != truth[n]} == {}, r1.stdout.str()
    assert "test_b.py::test_b" not in reused


@pytest.mark.parametrize("mode", ["serial", "n2"])
def test_unchanged_rerun_reuses_everything_in_any_placement(pytester, monkeypatch, tmp_path_factory, mode):
    _project(pytester, monkeypatch, tmp_path_factory, "lru")
    cache = f"--det-cache={pytester.path / '.c'}"
    _run(pytester, 0, cache, "-p", "xdist")  # recorded serially (xdist loaded: the same plugin set as -n)
    r1, o1, reused, _ = _run(pytester, 1, cache, *(("-p", "xdist") if mode == "serial" else PAR))
    # the key carries no earlier test: a serial record serves -n too
    assert reused == set(o1), r1.stdout.str()


def test_order_dependent_test_is_exposed_and_never_reused(pytester, monkeypatch, tmp_path_factory):
    _order_project(pytester, monkeypatch, tmp_path_factory)
    cache = f"--det-cache={pytester.path / '.c'}"
    r0, o0, _, _ = _run(pytester, 0, cache)
    assert o0 == {"test_a.py::test_a": "passed", "test_b.py::test_b": "failed"}, r0.stdout.str()
    r1, o1, reused, _ = _run(pytester, 1, cache)
    assert reused == {"test_a.py::test_a"} and o1["test_b.py::test_b"] == "failed"


@pytest.mark.parametrize("mode", ["serial", "n2"])
def test_a_file_an_earlier_test_wrote_from_a_repository_input(pytester, monkeypatch, tmp_path_factory, mode):
    # files are not isolated: A writes <tmp>/state from cfg.yml, B reads it; cfg.yml changes: B is not reused
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS"):
        monkeypatch.delenv(k, raising=False)
    state = tmp_path_factory.mktemp("out") / "state"
    pytester.makeini("[pytest]\nmarkers =\n    xdist_group: group\n")
    (pytester.path / "cfg.yml").write_text("old\n")
    pytester.makepyfile(test_a=f"""
        import pytest

        @pytest.mark.xdist_group("g")
        def test_a():
            with open("cfg.yml") as src, open({str(state)!r}, "w") as dst:
                dst.write(src.read())
        """, test_b=f"""
        import pytest

        @pytest.mark.xdist_group("g")
        def test_b():
            with open({str(state)!r}) as fh:
                assert fh.read().strip() == "old"
        """)
    cache = f"--det-cache={pytester.path / '.c'}"
    par = () if mode == "serial" else PAR
    r0, o0, _, _ = _run(pytester, 0, cache, *par)
    assert set(o0.values()) == {"passed"}, r0.stdout.str()
    (pytester.path / "cfg.yml").write_text("new\n")
    r1, o1, reused, _ = _run(pytester, 1, cache, *par)
    _, truth, _, _ = _run(pytester, 2)
    assert truth["test_b.py::test_b"] == "failed"
    assert {n: (o1[n], truth[n]) for n in reused if o1[n] != truth[n]} == {}, r1.stdout.str()
    assert "test_b.py::test_b" not in reused, r1.stdout.str()


def test_isolated_entries_are_not_offered_to_a_session_without_isolation(pytester, monkeypatch, tmp_path_factory):
    _order_project(pytester, monkeypatch, tmp_path_factory)
    cache = f"--det-cache={pytester.path / '.c'}"
    _run(pytester, 0, cache)
    out = pytester.path / "plain.json"
    pytester.runpytest_subprocess("--det", cache, f"--det-outcomes={out}", "-p", "no:cacheprovider")
    assert json.loads(out.read_text())["cache"]["reused_ids"] == []


def test_wider_scopes_are_set_up_once_in_the_parent_and_torn_down_there(pytester, monkeypatch, tmp_path_factory):
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS"):
        monkeypatch.delenv(k, raising=False)
    log = tmp_path_factory.mktemp("log") / "events"
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(test_m=f"""
        import os, pytest

        LOG = {str(log)!r}

        def note(x):
            with open(LOG, "a") as fh:
                fh.write(x + "\\n")

        @pytest.fixture(scope="module")
        def shared(tmp_path_factory):
            d = tmp_path_factory.mktemp("shared")
            note("setup")
            yield {{"dir": d, "items": []}}
            note("teardown")
            assert d.exists()

        def test_one(shared):
            shared["items"].append(1)       # a child's change: not seen by the next test
            assert shared["dir"].exists()

        def test_two(shared):
            assert shared["items"] == []
            assert shared["dir"].exists()   # the first child did not tear the module's fixture down

        def setup_module():
            note("setup_module")
        """)
    r, o, _, _ = _run(pytester, 0)
    assert o == {"test_m.py::test_one": "passed", "test_m.py::test_two": "passed"}, r.stdout.str()
    assert log.read_text().split() == ["setup_module", "setup", "teardown"]
