"""pytest-xdist under ``--det`` (docs/PARALLEL-PROOF-DESIGN.md, build steps P1-P3): per-worker traces merged by the
controller, a fixed plan (``DetScheduling``), the cache with proof decided once in the controller with the
cross-worker write rule."""

import json
import os
import sys
import textwrap

import pytest

from conftest import load_trace

pytest.importorskip("xdist")
needs_cache = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def write(pytester, **files):
    for name, text in files.items():
        p = pytester.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


SUITE = {
    "tests/test_a.py": """
        import random, time
        def test_a1(): assert random.random() < 2
        def test_a2(): time.time()
        def test_a3(): random.randint(0, 9)
        """,
    "tests/test_b.py": """
        import random
        import pytest
        class TestB:
            def test_b1(self): random.random()
            def test_b2(self): pass
        @pytest.mark.parametrize("x", range(6))
        def test_p(x): random.random()
        """,
    "tests/test_c.py": """
        import os
        import pytest
        @pytest.mark.xdist_group("db")
        def test_g1(): pass
        def test_c1(): pass
        def test_worker(worker_id, testrun_uid):
            assert os.environ.get("PYTEST_XDIST_WORKER", "master") == worker_id
            if worker_id != "master":
                assert os.environ["PYTEST_XDIST_TESTRUNUID"] == testrun_uid
            print("UID", testrun_uid)
        """,
    "tests/test_d.py": """
        import pytest
        @pytest.mark.xdist_group("db")
        def test_g2(): pass
        @pytest.mark.xdist_group("db")
        def test_g3(): pass
        """,
}
N_SUITE = 16


def run(pytester, *args, trace="trace.jsonl", outcomes=None):
    extra = [f"--det-outcomes={pytester.path / outcomes}"] if outcomes else []
    r = pytester.runpytest_subprocess("--det", f"--det-trace={pytester.path / trace}", "-p", "no:cacheprovider",
                                      "-p", "no:randomly", *extra, *args)
    return r


def plan_of(pytester):
    return json.loads((pytester.path / ".detpy" / "plan.json").read_text())


# -- P1: traces ------------------------------------------------------------------------------------------------------
def test_one_trace_per_worker_and_a_merged_trace(pytester):
    write(pytester, **SUITE)
    r = run(pytester, "-n", "2", "tests")
    r.assert_outcomes(passed=N_SUITE)
    for w in ("gw0", "gw1"):
        h, t, f = load_trace(pytester.path / f"trace.{w}.jsonl")
        assert h["meta"]["worker"] == w and f is not None
        assert len(h["order"]) == N_SUITE  # every worker collects the whole suite
    h, tests, footer = load_trace(pytester.path / "trace.jsonl")
    assert len(tests) == N_SUITE and footer["n_tests"] == N_SUITE  # today: header-only "collection failed"
    assert {t["worker"] for t in tests.values()} == {"gw0", "gw1"}
    assert h["meta"]["merged"] and h["meta"]["plan"]["workers"] == 2
    # merged lines follow the serial order
    assert [n for n in h["order"] if n in tests] == list(tests)
    assert [t["index"] for t in tests.values()] == list(range(N_SUITE))


def test_merged_fingerprints_equal_serial_ones(pytester):
    write(pytester, **SUITE)
    run(pytester, "tests", trace="serial.jsonl").assert_outcomes(passed=N_SUITE)
    run(pytester, "-n", "3", "tests", trace="par.jsonl").assert_outcomes(passed=N_SUITE)
    _, s, _ = load_trace(pytester.path / "serial.jsonl")
    hp, p, _ = load_trace(pytester.path / "par.jsonl")
    assert {k: v["fingerprint"] for k, v in s.items() if k != "tests/test_c.py::test_worker"} == \
        {k: v["fingerprint"] for k, v in p.items() if k != "tests/test_c.py::test_worker"}
    # detpy verify: same order header, no divergence except the test that reads its worker id
    rep = json.loads(__import__("detpy._core", fromlist=["x"]).verify(
        [str(pytester.path / "serial.jsonl"), str(pytester.path / "par.jsonl")]))
    assert rep["summary"]["order_identical"]


def test_merge_is_byte_identical_from_the_same_worker_traces(pytester):
    from detpy import _core

    write(pytester, **SUITE)
    run(pytester, "-n", "2", "tests").assert_outcomes(passed=N_SUITE)
    h, _, _ = load_trace(pytester.path / "trace.jsonl")
    plan = plan_of(pytester)
    workers = [(w, str(pytester.path / f"trace.{w}.jsonl"), ids) for w, ids in plan["lists"].items()]
    outs = []
    for i in range(2):
        out = pytester.path / f"m{i}.jsonl"
        _core.merge_traces(h["order"], workers, json.dumps(h["meta"], sort_keys=True), plan["digest"], str(out))
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]
    assert outs[0] == (pytester.path / "trace.jsonl").read_bytes()


def test_no_warning_under_filterwarnings_error(pytester):
    # today: detpy's "xdist is not supported" UserWarning became an INTERNALERROR (pydantic-ai, prefect)
    write(pytester, **SUITE)
    pytester.makeini("[pytest]\nfilterwarnings = error\n")
    r = run(pytester, "-n", "2", "tests")
    assert r.ret == 0, r.stdout.str()
    r.assert_outcomes(passed=N_SUITE)


def test_a_killed_worker_leaves_missing_tests_and_its_replacement_runs_the_rest(pytester):
    write(pytester, **{"tests/test_k.py": """
        import os
        def test_1(): pass
        def test_2(): pass
        def test_crash(): os._exit(3)
        def test_4(): pass
        def test_5(): pass
        """})
    r = run(pytester, "-n", "1", "--dist", "loadfile", "tests")
    out = r.stdout.str()
    assert "replacing crashed worker" in out
    r.assert_outcomes(passed=4, failed=1)
    h, tests, footer = load_trace(pytester.path / "trace.jsonl")
    assert set(tests) == {f"tests/test_k.py::test_{i}" for i in (1, 2, 4, 5)}
    assert footer["missing"] == ["tests/test_k.py::test_crash"]
    # the replacement worker ran the rest of the dead worker's list, in order
    assert tests["tests/test_k.py::test_4"]["worker"] == "gw1"
    assert h["meta"]["parallel"]["crashed"] == [["gw0", "tests/test_k.py::test_crash"]]


# -- P2: the fixed plan ----------------------------------------------------------------------------------------------
def test_two_runs_give_the_same_per_worker_lists_and_fingerprints(pytester):
    write(pytester, **SUITE)
    lists, fps = [], []
    for i in range(2):
        run(pytester, "-n", "3", "tests", trace=f"t{i}.jsonl").assert_outcomes(passed=N_SUITE)
        lists.append(plan_of(pytester)["lists"])
        _, t, _ = load_trace(pytester.path / f"t{i}.jsonl")
        fps.append({k: (v["fingerprint"], v["worker"]) for k, v in t.items()})
    assert lists[0] == lists[1]
    assert fps[0] == fps[1]


def test_worker_lists_are_subsequences_of_the_serial_order(pytester):
    write(pytester, **SUITE)
    run(pytester, "-n", "3", "tests").assert_outcomes(passed=N_SUITE)
    h, _, _ = load_trace(pytester.path / "trace.jsonl")
    pos = {n: i for i, n in enumerate(h["order"])}
    for ids in plan_of(pytester)["lists"].values():
        assert [pos[n] for n in ids] == sorted(pos[n] for n in ids)


def test_loadgroup_groups_stay_on_one_worker_and_ids_stay_serial(pytester):
    write(pytester, **SUITE)
    run(pytester, "-n", "3", "--dist", "loadgroup", "tests").assert_outcomes(passed=N_SUITE)
    plan = plan_of(pytester)
    where = {n: w for w, ids in plan["lists"].items() for n in ids}
    group = ["tests/test_c.py::test_g1", "tests/test_d.py::test_g2", "tests/test_d.py::test_g3"]
    assert len({where[n] for n in group}) == 1
    _, tests, _ = load_trace(pytester.path / "trace.jsonl")
    assert not any("@" in n for n in tests)  # xdist's "@group" suffix is not applied under --det


@pytest.mark.parametrize("dist,unit", [("loadscope", lambda n: n.rsplit("::", 1)[0]),
                                       ("loadfile", lambda n: n.split("::")[0])])
def test_scopes_and_files_are_atoms(pytester, dist, unit):
    write(pytester, **SUITE)
    run(pytester, "-n", "3", "--dist", dist, "tests").assert_outcomes(passed=N_SUITE)
    seen = {}
    for w, ids in plan_of(pytester)["lists"].items():
        for n in ids:
            assert seen.setdefault(unit(n), w) == w


def test_testrun_uid_is_derived_and_stable(pytester):
    write(pytester, **SUITE)
    uids = []
    for i in range(2):
        # output options differ between the runs: the uid does not
        run(pytester, "-n", "2", "tests", trace=f"u{i}.jsonl", outcomes=f"o{i}.json").assert_outcomes(passed=N_SUITE)
        uids.append(plan_of(pytester)["testrunuid"])
    assert uids[0] == uids[1] and len(uids[0]) == 32
    # a different seed gives another uid
    run(pytester, "-n", "2", "--det-seed=3", "tests").assert_outcomes(passed=N_SUITE)
    assert plan_of(pytester)["testrunuid"] != uids[0]


def test_plan_worker_replays_one_worker_serially(pytester):
    write(pytester, **SUITE)
    run(pytester, "-n", "2", "tests").assert_outcomes(passed=N_SUITE)
    plan_path = pytester.path / "plan-copy.json"
    plan_path.write_text((pytester.path / ".detpy" / "plan.json").read_text())
    plan = json.loads(plan_path.read_text())
    _, par, _ = load_trace(pytester.path / "trace.jsonl")
    for w, ids in plan["lists"].items():
        r = run(pytester, f"--det-plan={plan_path}", f"--det-plan-worker={w}", "tests", trace=f"replay-{w}.jsonl")
        r.assert_outcomes(passed=len(ids))
        h, rep, _ = load_trace(pytester.path / f"replay-{w}.jsonl")
        assert list(rep) == ids
        # same fingerprints as in the parallel run, the worker-identity test included
        assert {k: v["fingerprint"] for k, v in rep.items()} == {k: par[k]["fingerprint"] for k in ids}


def test_plan_replays_the_assignment_under_n(pytester):
    write(pytester, **SUITE)
    run(pytester, "-n", "3", "tests").assert_outcomes(passed=N_SUITE)
    first = plan_of(pytester)
    saved = pytester.path / "p.json"
    saved.write_text(json.dumps(first))
    (pytester.path / ".detpy" / "plan.json").unlink()
    (pytester.path / ".detpy" / "durations.json").unlink()
    run(pytester, "-n", "3", f"--det-plan={saved}", "tests").assert_outcomes(passed=N_SUITE)
    again = plan_of(pytester)
    assert again["lists"] == first["lists"] and again["replayed"]


def test_serial_run_is_unchanged_without_n(pytester):
    write(pytester, **SUITE)
    run(pytester, "tests").assert_outcomes(passed=N_SUITE)
    h, tests, footer = load_trace(pytester.path / "trace.jsonl")
    assert "plan" not in h["meta"] and "merged" not in h["meta"]
    assert all("worker" not in t for t in tests.values())
    assert set(footer) == {"type", "n_tests", "order_digest"}
    assert not (pytester.path / ".detpy" / "plan.json").exists()


# -- P3: the cache with proof across workers ---------------------------------------------------------------------------
def cache_run(pytester, n, label, *args):
    out = pytester.path / f"out-{label}.json"
    rc = pytester.path / f"rc-{label}.jsonl"
    extra = ["-n", str(n)] if n else []
    r = pytester.runpytest_subprocess(
        "--det", f"--det-cache={pytester.path / '.c'}", f"--det-cache-receipts={rc}", f"--det-outcomes={out}",
        f"--det-trace={pytester.path / ('t-' + label + '.jsonl')}", "-p", "no:cacheprovider", "-p", "no:randomly",
        *extra, *args)
    data = json.loads(out.read_text()) if out.exists() else {}
    return r, data.get("cache", {}), rc


def receipts(path):
    return [json.loads(line) for line in open(path) if line.strip()]


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
            assert p.read_text().strip() == "x"
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
def test_cross_worker_write_is_never_reused(pytester, tmp_path_factory, monkeypatch):
    """1.4.5 reproduced: A (worker 0) writes a file outside the repository from value.txt, B (worker 1) reads it.
    On the old engine B was cached in session 2 and reused as passed in session 3 although value.txt changed."""
    shared = tmp_path_factory.mktemp("outside") / "shared.txt"
    monkeypatch.setenv("SHARED_FILE", str(shared))
    write(pytester, **CROSS)
    for label in ("s1", "s2"):
        r, c, _ = cache_run(pytester, 2, label, "--dist", "loadfile", "--det-sleep=real", "tests")
        r.assert_outcomes(passed=2)
    assert "tests/test_b_reader.py::test_b_reads" not in set(c.get("reused_ids", ()))
    assert "another worker" in c["not_cached_detail_by_id"]["tests/test_b_reader.py::test_b_reads"] \
        if "not_cached_detail_by_id" in c else True
    (pytester.path / "tests" / "value.txt").write_text("y\n")
    shared.unlink()
    r, c, _ = cache_run(pytester, 2, "s3", "--dist", "loadfile", "--det-sleep=real", "tests")
    assert "tests/test_b_reader.py::test_b_reads" not in set(c.get("reused_ids", ()))
    r.assert_outcomes(passed=1, failed=1)  # B runs and fails, as serially


@needs_cache
def test_serial_and_parallel_sessions_take_the_same_decisions(pytester):
    write(pytester, **SUITE)
    r, c, _ = cache_run(pytester, 0, "cold", "tests")
    r.assert_outcomes(passed=N_SUITE)
    _, ser, rc_ser = cache_run(pytester, 0, "warm-serial", "tests")
    _, par, rc_par = cache_run(pytester, 2, "warm-par", "tests")
    assert set(ser["reused_ids"]) - {"tests/test_c.py::test_worker"} == set(par["reused_ids"])
    # the test that reads its worker id is not reused from a serial entry under -n (its value differs)
    assert "tests/test_c.py::test_worker" not in par["reused_ids"]
    assert len(par["reused_ids"]) == N_SUITE - 1
    # receipts come from the controller and cover every test
    assert len(receipts(rc_par)) == N_SUITE


@needs_cache
def test_a_store_written_under_n_serves_a_serial_run_and_receipts_are_stable(pytester):
    write(pytester, **SUITE)
    r, c, _ = cache_run(pytester, 2, "cold", "tests")
    r.assert_outcomes(passed=N_SUITE)
    assert c["recorded"] == N_SUITE and c["ran"] == N_SUITE
    _, w1, rc1 = cache_run(pytester, 2, "w1", "tests")
    _, w2, rc2 = cache_run(pytester, 2, "w2", "tests")
    assert len(w1["reused_ids"]) == N_SUITE
    assert receipts(rc1) == receipts(rc2)
    _, ser, _ = cache_run(pytester, 0, "serial", "tests")
    # every entry recorded by a worker is offered to a serial run; the worker-id reader runs again
    assert set(ser["reused_ids"]) == {f for f in w1["reused_ids"] if f != "tests/test_c.py::test_worker"}


@needs_cache
def test_verification_sample_is_the_same_in_two_parallel_runs(pytester):
    write(pytester, **SUITE)
    cache_run(pytester, 2, "cold", "tests")[0].assert_outcomes(passed=N_SUITE)
    v = []
    for label in ("v1", "v2"):
        r, c, _ = cache_run(pytester, 2, label, "--det-cache-verify=0.5", "tests")
        r.assert_outcomes(passed=N_SUITE)
        v.append(sorted(c["verified_ids"]))
        assert not c["verify_mismatches"]
    assert v[0] == v[1] and v[0]


@needs_cache
def test_cache_summary_and_trace_under_n(pytester):
    write(pytester, **SUITE)
    r, c, _ = cache_run(pytester, 2, "cold", "tests")
    out = r.stdout.str()
    assert "decided once in the controller" in out
    assert not list((pytester.path / ".c" / "shards").glob("*.json"))  # merged and removed
    r, c, _ = cache_run(pytester, 2, "warm", "tests")
    r.assert_outcomes(passed=N_SUITE)
    h, tests, _ = load_trace(pytester.path / "t-warm.jsonl")
    # everything reused by the controller, the worker-id reader too (same worker as in its recorded run)
    assert tests == {} and len(c["reused_ids"]) == N_SUITE
    assert h["meta"]["plan"]["hits"] == N_SUITE
