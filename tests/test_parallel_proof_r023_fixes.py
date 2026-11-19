"""Tests of the review R-023 fixes beyond the reviewer's own cases (tests/test_review_r023.py).

F1: placement of entries; F2: a writer that is new in the session, the withdrawal under -n, the cross-worker wait;
F3: the previous plan of another --dist; F4: stickiness when a test is removed."""

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


@pytest.fixture
def no_outer_xdist(monkeypatch):
    # the inner sessions must not inherit an outer xdist worker's identity
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID"):
        monkeypatch.delenv(k, raising=False)


READER = """
    import os, pathlib
    def test_b_reads():
        assert pathlib.Path(os.environ["SHARED_FILE"]).read_text().strip() == "x"
    """
NEW_WRITER = """
    import os, pathlib
    def test_a_writes():
        pathlib.Path(os.environ["SHARED_FILE"]).write_text("y\\n")
    """


# -- F2: the writer is new in the session (no history), it comes before the reused reader ------------------------------
@needs_cache
@pytest.mark.parametrize("n", [0, 2])
def test_reuse_is_withdrawn_when_a_new_earlier_test_writes_its_input(pytester, tmp_path_factory, monkeypatch, n,
                                                                    no_outer_xdist):
    shared = tmp_path_factory.mktemp("outside") / "shared.txt"
    shared.write_text("x\n")
    monkeypatch.setenv("SHARED_FILE", str(shared))
    write(pytester, **{"tests/test_b_reader.py": READER})
    args = ["--dist", "loadfile"] if n else []
    cache_run(pytester, n, "s1", *args, "tests")[0].assert_outcomes(passed=1)
    _, c = cache_run(pytester, n, "s2", *args, "tests")
    assert c["reused_ids"] == ["tests/test_b_reader.py::test_b_reads"]
    # a new test, first in the serial order, now writes the reader's input
    write(pytester, **{"tests/test_a_writer.py": NEW_WRITER})
    shared.write_text("x\n")
    r, c = cache_run(pytester, n, "s3", *args, "tests")
    assert "tests/test_b_reader.py::test_b_reads" not in c["reused_ids"]
    assert c["miss_ids"]["tests/test_b_reader.py::test_b_reads"].startswith("written:")
    r.assert_outcomes(passed=1, failed=1)  # the serial result: A wrote y before B read it
    if n:
        assert "withdrawn after the run" in r.stdout.str()
    # truth
    shared.write_text("x\n")
    fresh_run(pytester, 0, "tests").assert_outcomes(passed=1, failed=1)


# -- F2: the reader waits for its writer on another worker -------------------------------------------------------------
SLOW_WRITER = {
    "tests/test_a_writer.py": """
        import os, pathlib, time
        def test_a_writes():
            time.sleep(0.5)  # real time (--det-sleep=real): the reader in the other worker would be first
            src = pathlib.Path(__file__).parent / "value.txt"
            pathlib.Path(os.environ["SHARED_FILE"]).write_text(src.read_text())
        """,
    "tests/test_b_reader.py": """
        import os, pathlib
        def test_b_reads():
            assert pathlib.Path(os.environ["SHARED_FILE"]).read_text().strip() == "x"
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
def test_reader_waits_for_its_writer_on_another_worker(pytester, tmp_path_factory, monkeypatch, no_outer_xdist):
    shared = tmp_path_factory.mktemp("outside") / "shared.txt"
    shared.write_text("x\n")
    monkeypatch.setenv("SHARED_FILE", str(shared))
    write(pytester, **SLOW_WRITER)
    args = ["--dist", "loadfile", "--det-sleep=real", "tests"]
    cache_run(pytester, 2, "s1", *args)[0].assert_outcomes(passed=2)
    p = plan_of(pytester)
    assert p["assign"]["tests/test_a_writer.py::test_a_writes"] != p["assign"]["tests/test_b_reader.py::test_b_reads"]
    (pytester.path / "tests" / "value.txt").write_text("y\n")
    # s2: A runs again (its input changed) on the other worker; B waits for it and reads its y, as serially
    r, c = cache_run(pytester, 2, "s2", *args)
    p = plan_of(pytester)
    assert p["assign"]["tests/test_a_writer.py::test_a_writes"] != p["assign"]["tests/test_b_reader.py::test_b_reads"]
    assert p["waits"] == {"tests/test_b_reader.py::test_b_reads": ["tests/test_a_writer.py::test_a_writes"]}
    r.assert_outcomes(passed=1, failed=1)
    assert "waited for a writer on another worker" in r.stdout.str()
    # s3: B (its reader) runs again, so A is not reused (review R-023b N8: a reused writer would not write the file
    # its reader expects); A runs on the other worker and B waits for it, as in s2
    r, c = cache_run(pytester, 2, "s3", *args)
    assert c["reused_ids"] == []
    assert plan_of(pytester)["waits"] == {"tests/test_b_reader.py::test_b_reads": ["tests/test_a_writer.py::test_a_writes"]}
    r.assert_outcomes(passed=1, failed=1)
    fresh_run(pytester, 0, "--det-sleep=real", "tests").assert_outcomes(passed=1, failed=1)  # truth
    assert not list((pytester.path / ".detpy" / "barrier").glob("*"))  # cleaned up


# -- F1: one worker's list replayed serially records parallel results --------------------------------------------------
@needs_cache
def test_plan_worker_replay_records_parallel_entries(pytester, no_outer_xdist):
    write(pytester, **{"tests/test_x.py": "def test_1(): pass\ndef test_2(): pass\n"})
    fresh_run(pytester, 2, "tests").assert_outcomes(passed=2)
    plan = pytester.path / "plan-copy.json"
    plan.write_text((pytester.path / ".detpy" / "plan.json").read_text())
    wid = next(w for w, ids in plan_of(pytester)["lists"].items() if ids)
    cache_run(pytester, 0, "replay", f"--det-plan={plan}", f"--det-plan-worker={wid}", "tests")
    store = json.loads((pytester.path / ".c" / "proof-cache.json").read_text())
    assert store["tests"] and all(e.get("placement") == "parallel" for e in store["tests"].values())
    _, c = cache_run(pytester, 0, "serial", "tests")
    assert c["reused_ids"] == []


# -- F3: the previous plan of another --dist is not used ---------------------------------------------------------------
def test_previous_plan_of_another_dist_is_ignored(pytester, no_outer_xdist):
    write(pytester, **{"tests/test_x.py": "def test_1(): pass\n", "tests/test_y.py": "def test_2(): pass\n"})
    fresh_run(pytester, 2, "tests").assert_outcomes(passed=2)
    fresh_run(pytester, 2, "--dist", "loadfile", "tests").assert_outcomes(passed=2)
    assert plan_of(pytester)["previous_ignored"] == "another --dist"
    fresh_run(pytester, 2, "--dist", "loadfile", "tests").assert_outcomes(passed=2)
    assert plan_of(pytester)["previous_ignored"] == "" and plan_of(pytester)["sticky"]


# -- F4: removing a test keeps the others in place ---------------------------------------------------------------------
def test_removing_one_test_keeps_the_others_placement(pytester, no_outer_xdist):
    files = {f"tests/test_{f}.py": "".join(f"def test_{i}(): pass\n" for i in range(48)) for f in range(8)}
    write(pytester, **files)
    for _ in range(2):
        fresh_run(pytester, 4, "tests").assert_outcomes(passed=384)
    a1 = plan_of(pytester)["assign"]
    write(pytester, **{"tests/test_3.py": "".join(f"def test_{i}(): pass\n" for i in range(48) if i != 20)})
    fresh_run(pytester, 4, "tests").assert_outcomes(passed=383)
    a2 = plan_of(pytester)["assign"]
    moved = sum(a1[i] != a2[i] for i in a2)
    assert moved <= len(a2) // 20, f"{moved} of {len(a2)} tests changed worker"
