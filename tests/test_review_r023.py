"""Review R-023 (claude/parallel-proof): adversarial tests of the cache with proof under -n and of the plan.

Each test asserts the behaviour the report / design claims; a failing test is a finding."""

import json
import os
import sys
import textwrap

import pytest

pytest.importorskip("xdist")
needs_cache = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def write(pytester, **files):
    for name, text in files.items():
        p = pytester.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def cache_run(pytester, n, label, *args):
    out = pytester.path / f"out-{label}.json"
    extra = ["-n", str(n)] if n else []
    r = pytester.runpytest_subprocess(
        "--det", f"--det-cache={pytester.path / '.c'}", f"--det-outcomes={out}",
        "-p", "no:cacheprovider", "-p", "no:randomly", *extra, *args)
    data = json.loads(out.read_text()) if out.exists() else {}
    return r, data.get("cache", {})


def fresh_run(pytester, n, *args):
    extra = ["-n", str(n)] if n else []
    return pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", "-p", "no:randomly", *extra, *args)


def plan_of(pytester):
    return json.loads((pytester.path / ".detpy" / "plan.json").read_text())


# -- 1. module-level state: a result recorded under -n reused by a serial run -----------------------------------------
PLACEMENT = {
    "tests/helper.py": "STATE = []\n",
    "tests/conftest.py": "import sys, os\nsys.path.insert(0, os.path.dirname(__file__))\n",
    "tests/test_a_polluter.py": """
        import helper
        def test_pollutes(): helper.STATE.append(1)
        """,
    "tests/test_b_victim.py": """
        import helper
        def test_victim(): assert helper.STATE == []
        """,
}


@needs_cache
def test_a1_parallel_entry_of_a_placement_victim_is_not_reused_serially(pytester):
    """Design 2.5: 'until P5 ships, an entry carries placement: serial | parallel and a serial session does not reuse a
    parallel entry whose test has a recorded placement divergence'. Serially the victim fails (its polluter ran
    before it in the same process); under -n 2 --dist loadfile it runs in the other worker and passes. The passing
    result recorded under -n must not be reused by a serial session."""
    write(pytester, **PLACEMENT)
    fresh_run(pytester, 0, "tests").assert_outcomes(passed=1, failed=1)  # serial truth: the victim fails
    r, c = cache_run(pytester, 2, "par", "--dist", "loadfile", "tests")
    r.assert_outcomes(passed=2)  # placement: the victim passes in its own worker
    r, c = cache_run(pytester, 0, "ser", "tests")
    assert "tests/test_b_victim.py::test_victim" not in c.get("reused_ids", [])
    r.assert_outcomes(passed=1, failed=1)


# -- 2. cross-worker writes through channels other than open(..., "w") -------------------------------------------------
WRITERS = {
    "replace": """
        tmp = target.with_name(target.name + ".tmp"); tmp.write_text(value); os.replace(tmp, target)""",
    "rename": """
        tmp = target.with_name(target.name + ".tmp"); tmp.write_text(value); os.rename(tmp, target)""",
    "copyfile": """
        shutil.copyfile(src, target)""",
    "os_write": """
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC); os.write(fd, value.encode()); os.close(fd)""",
    "sqlite": """
        con = sqlite3.connect(str(target)); con.execute("create table if not exists t(v)"); con.execute("delete from t"); con.execute("insert into t values (?)", (value,)); con.commit(); con.close()""",
}
READERS = {
    "sqlite": """
        con = sqlite3.connect(str(p)); got = con.execute("select v from t").fetchone()[0]; con.close()""",
}
DEFAULT_READER = """
        got = p.read_text()"""


def cross_suite(kind):
    reader = READERS.get(kind, DEFAULT_READER)
    return {
        "tests/test_a_writer.py": f"""
            import os, pathlib, shutil, sqlite3
            def test_a_writes():
                target = pathlib.Path(os.environ["SHARED_FILE"])
                src = pathlib.Path(__file__).parent / "value.txt"
                value = src.read_text()
                {textwrap.dedent(WRITERS[kind]).strip()}
            """,
        "tests/test_b_reader.py": f"""
            import os, pathlib, sqlite3, time
            def test_b_reads():
                p = pathlib.Path(os.environ["SHARED_FILE"])
                for _ in range(500):  # wait (real time) for the writer in the other worker
                    try:
                        {textwrap.dedent(reader).strip()}
                        if got: break
                    except Exception:
                        pass
                    time.sleep(0.01)
                {textwrap.dedent(reader).strip()}
                assert got.strip() == "x"
            """,
        "tests/value.txt": "x\n",
    }


@needs_cache
@pytest.mark.parametrize("kind", sorted(WRITERS))
def test_a2_cross_worker_write_channels_are_never_reused(pytester, tmp_path_factory, monkeypatch, kind):
    """The report's 1.4.5 attack (A writes a file outside the repository in worker 0, B reads it in worker 1) with
    the write done through other channels than open(): the reader must not be reused after value.txt changes."""
    shared = tmp_path_factory.mktemp("outside") / "shared.dat"
    monkeypatch.setenv("SHARED_FILE", str(shared))
    write(pytester, **cross_suite(kind))
    for label in ("s1", "s2"):
        r, c = cache_run(pytester, 2, label, "--dist", "loadfile", "--det-sleep=real", "tests")
        r.assert_outcomes(passed=2)
    lists = plan_of(pytester)["assign"]
    assert lists["tests/test_a_writer.py::test_a_writes"] != lists["tests/test_b_reader.py::test_b_reads"]
    (pytester.path / "tests" / "value.txt").write_text("y\n")
    shared.unlink()
    r, c = cache_run(pytester, 2, "s3", "--dist", "loadfile", "--det-sleep=real", "tests")
    assert "tests/test_b_reader.py::test_b_reads" not in set(c.get("reused_ids", ()))
    r.assert_outcomes(passed=1, failed=1)


# -- 3. a write from a hook context (between tests) in another worker ---------------------------------------------------
HOOK = {
    "tests/conftest.py": """
        import os, pathlib
        def pytest_runtest_teardown(item):
            if item.name == "test_a_marker":
                src = pathlib.Path(__file__).parent / "value.txt"
                pathlib.Path(os.environ["SHARED_FILE"]).write_text(src.read_text())
        """,
    "tests/test_a_writer.py": """
        def test_a_marker(): pass
        """,
    "tests/test_b_reader.py": """
        import os, pathlib, time
        def test_b_reads():
            p = pathlib.Path(os.environ["SHARED_FILE"])
            for _ in range(500):
                if p.exists() and p.read_text():
                    break
                time.sleep(0.01)
            assert p.read_text().strip() == "x"
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
@pytest.mark.parametrize("n", [0, 2])
def test_a3_write_from_a_hook_after_another_test_is_never_reused(pytester, tmp_path_factory, monkeypatch, n):
    """A conftest hook writes, after test A, the content of value.txt to a file outside the repository; B reads it.
    value.txt changes, the outside file keeps its old content (nothing deletes it): B must not be reused. A fresh
    run of the third session fails B (serially and under -n)."""
    shared = tmp_path_factory.mktemp("outside") / "shared.txt"
    monkeypatch.setenv("SHARED_FILE", str(shared))
    write(pytester, **HOOK)
    args = ["--dist", "loadfile"] if n else []
    for label in ("s1", "s2"):
        r, c = cache_run(pytester, n, label, *args, "--det-sleep=real", "tests")
        r.assert_outcomes(passed=2)
    (pytester.path / "tests" / "value.txt").write_text("y\n")
    r, c = cache_run(pytester, n, "s3", *args, "--det-sleep=real", "tests")
    assert "tests/test_b_reader.py::test_b_reads" not in set(c.get("reused_ids", ()))
    r.assert_outcomes(passed=1, failed=1)


# -- 4. the report's own cross-worker attack without deleting the outside file ----------------------------------------
CROSS = {
    "tests/test_a_writer.py": """
        import os, pathlib
        def test_a_writes():
            pathlib.Path(os.environ["SHARED_FILE"]).write_text((pathlib.Path(__file__).parent / "value.txt").read_text())
        """,
    "tests/test_b_reader.py": """
        import os, pathlib, time
        def test_b_reads():
            p = pathlib.Path(os.environ["SHARED_FILE"])
            for _ in range(500):  # wait (real time) for the writer in the other worker
                if p.exists() and p.read_text():
                    break
                time.sleep(0.01)
            time.sleep(0.3)  # let a writer of this session finish
            assert p.read_text().strip() == "x"
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
@pytest.mark.parametrize("n", [0, 2])
def test_a4_reader_of_another_tests_file_is_not_reused_when_the_file_survives(pytester, tmp_path_factory, monkeypatch, n):
    """tests/test_parallel_proof.py::test_cross_worker_write_is_never_reused deletes the outside file before
    session 3, so B's recorded content no longer matches and B misses for that reason. Without the deletion: in
    session 2 A is reused (not run, so it writes nothing), B runs and is recorded with no writer in the session; in
    session 3 value.txt changes, A runs and writes 'y', B is reused as passed. A fresh session 3 fails B."""
    shared = tmp_path_factory.mktemp("outside") / "shared.txt"
    monkeypatch.setenv("SHARED_FILE", str(shared))
    write(pytester, **CROSS)
    args = ["--dist", "loadfile"] if n else []
    for label in ("s1", "s2"):
        r, c = cache_run(pytester, n, label, *args, "--det-sleep=real", "tests")
        r.assert_outcomes(passed=2)
    (pytester.path / "tests" / "value.txt").write_text("y\n")
    r, c = cache_run(pytester, n, "s3", *args, "--det-sleep=real", "tests")
    assert "tests/test_b_reader.py::test_b_reads" not in set(c.get("reused_ids", ()))
    r.assert_outcomes(passed=1, failed=1)


@pytest.mark.parametrize("n", [0, 2])
def test_a4_truth_session_3_fails_b(pytester, tmp_path_factory, monkeypatch, n):
    """The truth for a4: the same three sessions without the cache; session 3 fails B."""
    shared = tmp_path_factory.mktemp("outside") / "shared.txt"
    monkeypatch.setenv("SHARED_FILE", str(shared))
    write(pytester, **CROSS)
    args = ["--dist", "loadfile"] if n else []
    fresh_run(pytester, n, *args, "--det-sleep=real", "tests").assert_outcomes(passed=2)
    (pytester.path / "tests" / "value.txt").write_text("y\n")
    fresh_run(pytester, n, *args, "--det-sleep=real", "tests").assert_outcomes(passed=1, failed=1)


# -- 5. a test that reads its worker id, run on another worker by --det-plan -------------------------------------------
WORKER = {
    "tests/test_w.py": """
        import os
        def test_on_gw0(): assert os.environ.get("PYTEST_XDIST_WORKER") in ("gw0", None)
        """,
    "tests/test_x.py": """
        def test_x1(): pass
        def test_x2(): pass
        """,
}


def plan_file(pytester, name, on):
    p = plan_of(pytester)
    nid = "tests/test_w.py::test_on_gw0"
    lists = {w: [t for t in ids if t != nid] for w, ids in p["lists"].items()}
    lists.setdefault(on, []).insert(0, nid)
    p["lists"] = lists
    p["assign"] = dict(p.get("assign") or {}, **{nid: on})
    path = pytester.path / name
    path.write_text(json.dumps(p))
    return path


@needs_cache
def test_a5_worker_reader_is_not_reused_when_the_plan_moves_it(pytester):
    """The controller checks PYTEST_XDIST_WORKER against the test's worker in the *previous* plan. --det-plan pins
    the test to gw1 for this run (a fresh run fails it there); its result recorded on gw0 must not be reused."""
    write(pytester, **WORKER)
    fresh_run(pytester, 2, "tests")  # writes .detpy/plan.json
    on0 = plan_file(pytester, "p0.json", "gw0")
    on1 = plan_file(pytester, "p1.json", "gw1")
    fresh_run(pytester, 2, f"--det-plan={on1}", "tests").assert_outcomes(passed=2, failed=1)  # truth on gw1
    r, c = cache_run(pytester, 2, "s1", f"--det-plan={on0}", "tests")  # recorded on gw0; plan.json: gw0
    r.assert_outcomes(passed=3)
    r, c = cache_run(pytester, 2, "s2", f"--det-plan={on1}", "tests")
    assert "tests/test_w.py::test_on_gw0" not in c.get("reused_ids", [])
    r.assert_outcomes(passed=2, failed=1)


# -- 6. stickiness of the plan when one test is added ------------------------------------------------------------------
def _plan(ids, n, previous):
    from detpy import _core
    atoms = [_core.sched_atom_key(i, "load", None) for i in ids]
    costs = [1.0] * len(ids)
    atoms = _core.sched_chunk_atoms(ids, atoms, costs, n, 8)
    p = json.loads(_core.sched_plan(ids, atoms, costs, n, previous, 0.1))
    worker, preds = {}, {}
    for w, lst in enumerate(p["lists"]):
        for k, j in enumerate(lst):
            worker[ids[j]] = w
            preds[ids[j]] = tuple(ids[x] for x in lst[:k])
    return p, worker, preds


def test_a6_adding_one_test_keeps_the_other_tests_placement():
    """Report P2: 'sticky (previous atom -> worker kept ...)', chunk boundaries 'from the collection only' so 'the
    chunks (and the sticky plan over them) stay put from run to run'. 384 tests in 8 files on 4 workers, then one
    test appended at the end of the last file: the chunk cap goes from 12 to 13, every chunk key after the first of
    each file changes, and most existing tests change worker and in-process predecessors (placement)."""
    ids = [f"tests/test_{f}.py::test_{i}" for f in range(8) for i in range(48)]
    p1, w1, pr1 = _plan(ids, 4, {})
    p2, w2, pr2 = _plan(ids + ["tests/test_7.py::test_new"], 4, p1["atom_worker"])
    moved = sum(w1[i] != w2[i] for i in ids)
    lost = sum(pr1[i] != pr2[i] for i in ids)
    assert p2["sticky"]  # the plan says it is sticky ...
    assert moved <= len(ids) // 20, f"{moved} of {len(ids)} existing tests changed worker"  # ... it is not
    assert lost <= len(ids) // 20, f"{lost} of {len(ids)} existing tests changed in-process predecessors"


def test_a6_pytester_adding_one_test_moves_existing_tests(pytester):
    files = {f"tests/test_{f}.py": "".join(f"def test_{i}(): pass\n" for i in range(48)) for f in range(8)}
    write(pytester, **files)
    for _ in range(2):
        fresh_run(pytester, 4, "tests").assert_outcomes(passed=384)
    a1 = plan_of(pytester)["assign"]
    with open(pytester.path / "tests" / "test_7.py", "a") as f:
        f.write("def test_new(): pass\n")
    fresh_run(pytester, 4, "tests").assert_outcomes(passed=385)
    a2 = plan_of(pytester)["assign"]
    moved = sum(a1[i] != a2[i] for i in a1)
    assert moved <= len(a1) // 20, f"{moved} of {len(a1)} existing tests changed worker"


# -- 7. fpcompare: a failure hidden in the second parallel run only ----------------------------------------------------
def test_a7_fpcompare_counts_a_failure_hidden_in_either_parallel_run():
    """'0 hidden failures' comes from harness/parallel_proof/fpcompare.py: a test that fails in both serial runs and
    passes in one parallel run is hidden. The check looks at the first parallel run only."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    try:
        from harness.parallel_proof.fpcompare import compare
    finally:
        sys.path.remove(root)
    rec = lambda outcome: {"fingerprint": "f", "outcome": outcome, "events": []}  # noqa: E731
    s = {"t": rec("failed")}
    hidden = compare(s, s, {"t": rec("failed")}, {"t": rec("passed")})
    assert hidden["outcome_differences"] == 1
    assert hidden["hidden_failures"] == ["t"]


# -- 8. an environment variable set by a test in another worker --------------------------------------------------------
ENVSET = {
    "tests/test_a_sets.py": """
        import os
        def test_sets(): os.environ["DETPY_R023_FLAG"] = "1"
        """,
    "tests/test_b_reads_env.py": """
        import os
        def test_reads(): assert os.environ.get("DETPY_R023_FLAG") is None
        """,
}


@needs_cache
def test_a8_env_set_by_a_test_in_another_worker_is_not_reused_serially(pytester):
    """The environment is a recorded input (by name). Serially B sees the variable A set and fails; under -n 2
    --dist loadfile B runs in the other worker, sees no variable and passes; the entry (env: variable absent) matches
    a serial session's start environment, so the serial session reuses it."""
    write(pytester, **ENVSET)
    fresh_run(pytester, 0, "tests").assert_outcomes(passed=1, failed=1)
    cache_run(pytester, 2, "par", "--dist", "loadfile", "tests")[0].assert_outcomes(passed=2)
    r, c = cache_run(pytester, 0, "ser", "tests")
    assert "tests/test_b_reads_env.py::test_reads" not in c.get("reused_ids", [])
    r.assert_outcomes(passed=1, failed=1)
