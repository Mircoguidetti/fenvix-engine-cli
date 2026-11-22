"""Review R-023c fixes (E1-E8): the cases the review's own file (tests/test_review_r023c.py, merged unchanged) does not
cover, and the precision each fix keeps. Each test runs the cache and compares with what a fresh run gives."""

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


def cache_run(pytester, label, *args, store=".c"):
    out = pytester.path / f"out-{label}.json"
    r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / store}", f"--det-outcomes={out}",
                                      "-p", "no:cacheprovider", "-p", "no:randomly", *args)
    data = json.loads(out.read_text()) if out.exists() else {}
    return r, data.get("cache", {})


def reused(c):
    return set(c.get("reused_ids", ()))


@pytest.fixture
def clean_xdist_env(monkeypatch):
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "DETPY_CACHE_SHARED"):
        monkeypatch.delenv(k, raising=False)


# -- E6: the shared store under -n ---------------------------------------------------------------------------------
@needs_cache
def test_e6_machine_two_under_n_runs_the_adopted_writer_with_its_reader(pytester, tmp_path_factory, monkeypatch,
                                                                        clean_xdist_env):
    """Machine 1 runs the suite serially (A writes a spool file, B consumes it: the edge (A, B) is recorded) and pushes.
    Machine 2, with an empty local store and -n 2, adopts A's entry together with its edge: A is not reused while B
    runs, and the plan runs the two on one worker in the serial order (the together edge), so B finds the file."""
    spool = tmp_path_factory.mktemp("spool")
    monkeypatch.setenv("R023C_SPOOL", str(spool))
    write(pytester, **{
        "tests/test_a_writer.py": """
            import os, pathlib
            def test_a_writes():
                pathlib.Path(os.environ["R023C_SPOOL"], "job").write_text("payload\\n")
            """,
        "tests/test_b_consumer.py": """
            import os, pathlib
            def test_b_consumes():
                p = pathlib.Path(os.environ["R023C_SPOOL"], "job")
                assert p.read_text() == "payload\\n"
                p.unlink()
            """})
    shared = f"--det-cache-shared={pytester.path / '.shared'}"
    for label in ("m1a", "m1b"):
        cache_run(pytester, label, shared, "tests", store=".job1")[0].assert_outcomes(passed=2)
    for label in ("m2a", "m2b"):
        r, c = cache_run(pytester, label, shared, "tests", "-n", "2", store=f".job2{label}")
        r.assert_outcomes(passed=2)
        assert "tests/test_a_writer.py::test_a_writes" not in reused(c)


# -- E1: a mkdir of an existing directory --------------------------------------------------------------------------
@needs_cache
def test_e1_makedirs_of_an_existing_temporary_root_is_a_kind_input_not_a_write(pytester):
    """os.makedirs(..., exist_ok=True) of a directory that exists writes nothing: the test stays cacheable (its kind
    check of the directory is an input), as a fresh run of it does not depend on any other test."""
    write(pytester, **{"tests/test_mk.py": """
        import os, tempfile
        def test_makedirs_tmp():
            os.makedirs(tempfile.gettempdir(), exist_ok=True)
            assert os.path.isdir(tempfile.gettempdir())
        def test_after():
            assert os.path.isdir("/tmp")
        """})
    cache_run(pytester, "s1", "tests")[0].assert_outcomes(passed=2)
    r, c = cache_run(pytester, "s2", "tests")
    r.assert_outcomes(passed=2)
    assert reused(c) == {"tests/test_mk.py::test_makedirs_tmp", "tests/test_mk.py::test_after"}


# -- E2/E4: what stays reusable, what is keyed ---------------------------------------------------------------------
@needs_cache
def test_e2_shutil_copy2_into_a_temporary_directory_stays_reusable(pytester):
    """shutil.copystat (copy2, copytree) reads the source's times to set them on the copy: it decides nothing, so a
    test that copies is still reused; its read of the source's content is its input."""
    write(pytester, **{"tests/src.txt": "a\n", "tests/test_cp.py": """
        import os, shutil
        def test_copy(tmp_path):
            shutil.copy2(os.path.join(os.path.dirname(__file__), "src.txt"), tmp_path / "dst.txt")
            assert (tmp_path / "dst.txt").read_text() == "a\\n"
        """})
    cache_run(pytester, "s1", "tests")[0].assert_outcomes(passed=1)
    r, c = cache_run(pytester, "s2", "tests")
    assert reused(c) == {"tests/test_cp.py::test_copy"}
    (pytester.path / "tests" / "src.txt").write_text("b\n")
    r, c = cache_run(pytester, "s3", "tests")
    r.assert_outcomes(failed=1)
    assert reused(c) == set()


@needs_cache
def test_e4_st_mode_through_os_stat_is_keyed(pytester):
    write(pytester, **{"tests/run.sh": "#!/bin/sh\n", "tests/test_mode.py": """
        import os, stat
        P = os.path.join(os.path.dirname(__file__), "run.sh")
        def test_executable_bit():
            assert os.stat(P).st_mode & stat.S_IXUSR
        """})
    os.chmod(pytester.path / "tests" / "run.sh", 0o755)
    cache_run(pytester, "s1", "tests")[0].assert_outcomes(passed=1)
    assert reused(cache_run(pytester, "s2", "tests")[1]) == {"tests/test_mode.py::test_executable_bit"}
    os.chmod(pytester.path / "tests" / "run.sh", 0o644)
    r, c = cache_run(pytester, "s3", "tests")
    r.assert_outcomes(failed=1)
    assert reused(c) == set()


# -- E7: precision of the predecessor rule -------------------------------------------------------------------------
@needs_cache
def test_e7_an_earlier_test_the_running_one_cannot_reach_stays_reused(pytester):
    """Two test files that import nothing and share no file: the second one's carried set holds no test of the first
    (Entry::needs is empty), so when it runs the first stays reused. It runs because a data file it reads changed,
    not its code (an edit of a test file makes its stored needs stale: review R-052, every earlier test runs)."""
    write(pytester, **{
        "tests/test_x.py": "def test_x():\n    assert 1\n",
        "tests/test_y.py": "def test_y():\n    assert open('tests/data.txt').read()\n",
        "tests/data.txt": "1\n",
    })
    cache_run(pytester, "s1", "tests")[0].assert_outcomes(passed=2)
    assert reused(cache_run(pytester, "s2", "tests")[1]) == {"tests/test_x.py::test_x", "tests/test_y.py::test_y"}
    (pytester.path / "tests" / "data.txt").write_text("2\n")
    r, c = cache_run(pytester, "s3", "tests")
    r.assert_outcomes(passed=2)
    assert reused(c) == {"tests/test_x.py::test_x"}


@needs_cache
def test_e7_a_running_test_that_reaches_the_library_node_runs_its_predecessors(pytester):
    """A test that imports a module (the library node) may consume state any earlier test left: when it runs, the
    earlier tests of its process run before it too (a fresh run's order)."""
    write(pytester, **{
        "tests/test_p.py": "import json\n\ndef test_p():\n    assert json\n",
        "tests/test_q.py": "import json\n\ndef test_q():\n    assert json\n",
    })
    cache_run(pytester, "s1", "tests")[0].assert_outcomes(passed=2)
    (pytester.path / "tests" / "test_q.py").write_text("import json\n\ndef test_q():\n    assert json.dumps(1)\n")
    r, c = cache_run(pytester, "s2", "tests")
    r.assert_outcomes(passed=2)
    assert reused(c) == set()


@needs_cache
def test_e7_isolation_needs_no_predecessor(pytester):
    """Under --det-isolate each test runs in its own child: no in-process state reaches it, its predecessors stay
    reused."""
    write(pytester, **{
        "tests/test_p.py": "import json\n\ndef test_p():\n    assert json\n",
        "tests/test_q.py": "import json\n\ndef test_q():\n    assert json\n",
    })
    cache_run(pytester, "s1", "tests", "--det-isolate")[0].assert_outcomes(passed=2)
    (pytester.path / "tests" / "test_q.py").write_text("import json\n\ndef test_q():\n    assert json.dumps(1)\n")
    r, c = cache_run(pytester, "s2", "tests", "--det-isolate")
    r.assert_outcomes(passed=2)
    assert reused(c) == {"tests/test_p.py::test_p"}


# -- pytest-benchmark: the whole environment -----------------------------------------------------------------------
@needs_cache
@pytest.mark.benchmark_plugin
def test_pytest_benchmark_makes_every_test_carry_the_whole_environment(pytester, monkeypatch):
    """pytest-benchmark's pytest_configure calls platform.architecture(): it iterates os.environ and spawns `file`,
    whose environment reads are not observed. Every test then depends on the whole environment: a variable no test
    reads invalidates them all (sound; the cost of the plugin, measured here)."""
    pytest.importorskip("pytest_benchmark")
    write(pytester, **{"tests/test_n.py": "def test_n():\n    assert 1\n"})
    monkeypatch.delenv("R023C_UNREAD", raising=False)
    cache_run(pytester, "s1", "tests")[0].assert_outcomes(passed=1)
    assert reused(cache_run(pytester, "s2", "tests")[1]) == {"tests/test_n.py::test_n"}
    monkeypatch.setenv("R023C_UNREAD", "1")
    assert reused(cache_run(pytester, "s3", "tests")[1]) == set()
