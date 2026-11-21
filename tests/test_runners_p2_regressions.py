"""Regressions found by the frozen exam on the runner rows (P-064, 2026-11-21), each a false divergence or a crash
on a real project, reproduced here on a small one.

* PY-06.pytest-mock.det2: modules a test rewrites (pytester's inner sessions) were cached by the first run and
  counted as cold, so the first run's ``bytecode`` run input differed from every later run's (82/82 divergent).
* PY-06.pytest-cov.det2: coverage's own data files (``.coverage.<host>.pid<N>.<random>``), created and read back by
  the run, were recorded as files read outside tests, with a different name every run (297/297 divergent).
* PY-06.time-machine: time-machine 2.x crashed the process under --det (``tests/test_clock.py`` covers the travel).
"""

from __future__ import annotations

import json
import subprocess
import sys

pytest_plugins = ["pytester"]


def _verify(t1, t2) -> dict:
    p = subprocess.run([sys.executable, "-m", "detpy", "verify", "--json", t1, t2], capture_output=True, text=True)
    return json.loads(p.stdout)


def _header(path) -> dict:
    with open(path) as f:
        return json.loads(f.readline())


def test_modules_a_test_rewrites_do_not_make_the_first_run_differ(pytester, run_det):
    (pytester.path / "t").mkdir()
    (pytester.path / "t" / "conftest.py").write_text("pytest_plugins = ['pytester']\n")
    (pytester.path / "t" / "test_inner.py").write_text(
        "def test_runs_an_inner_session(pytester):\n"
        "    pytester.makepyfile(test_x='def test_x():\\n    assert 1 + 1 == 2\\n')\n"
        "    pytester.inline_run('-p', 'no:detpy').assertoutcome(passed=1)\n")
    r1, _ = run_det("t", trace=str(pytester.path / "a.jsonl"))
    r2, _ = run_det("t", trace=str(pytester.path / "b.jsonl"))
    r1.assert_outcomes(passed=1)
    r2.assert_outcomes(passed=1)
    h1, h2 = _header(pytester.path / "a.jsonl"), _header(pytester.path / "b.jsonl")
    b1, b2 = h1["meta"]["inputs"]["bytecode"], h2["meta"]["inputs"]["bytecode"]
    assert b1 == b2, (b1, b2)
    rep = _verify(str(pytester.path / "a.jsonl"), str(pytester.path / "b.jsonl"))
    assert rep["summary"]["reasons"].get("config", 0) == 0, rep["summary"]


def test_files_the_run_creates_are_not_inputs(pytester, run_det):
    # a plugin that writes a data file named after its process and reads it back at the end, as coverage does
    pytester.makeconftest("""
        import os, sqlite3
        NAME = f".data.pid{os.getpid()}"

        def pytest_sessionstart(session):
            with open(NAME, "w") as f:
                f.write("x")
            c = sqlite3.connect(NAME + ".db")
            c.execute("create table t (a)")
            c.commit()
            c.close()

        def pytest_sessionfinish(session):
            open(NAME).read()
            c = sqlite3.connect(NAME + ".db")
            c.execute("select * from t").fetchall()
            c.close()
            os.remove(NAME)  # as coverage combines and removes its parallel data files
            os.remove(NAME + ".db")
        """)
    pytester.makepyfile(test_a="def test_a():\n    pass\n")
    run_det("test_a.py", trace=str(pytester.path / "a.jsonl"))
    run_det("test_a.py", trace=str(pytester.path / "b.jsonl"))
    for t in ("a.jsonl", "b.jsonl"):
        lines = [json.loads(x) for x in open(pytester.path / t)]
        outside = [f["path"] for x in lines for f in (x.get("files_read_outside_tests") or
                                                       x.get("meta", {}).get("files_read_outside_tests") or [])]
        assert not [p for p in outside if ".data.pid" in p], outside
    rep = _verify(str(pytester.path / "a.jsonl"), str(pytester.path / "b.jsonl"))
    assert rep["summary"]["diverged"] == 0, rep["summary"]
