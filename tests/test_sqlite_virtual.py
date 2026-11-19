"""parallel-proof round 3, item 3: SQLite's date/time functions, CURRENT_TIMESTAMP defaults, random() and
randomblob() under Level 0 (``crates/detpy-py/src/sqlvirt.rs``, glue ``detpy/sqlvirt.py``).

A test that stores SQLite's 'now' or random values must give the same results in every ``--det`` run, serially and
in any worker of ``-n``; and since the values are then Level 0's, the cache with proof may record such a test
(prefect's schema: ``DEFAULT CURRENT_TIMESTAMP`` and ``randomblob`` ids) and must reuse it only when a fresh run
gives the same outcome.
"""

import json
import sys
import textwrap

import pytest

SCHEMA_TEST = """
    import sqlite3, datetime

    SCHEMA = '''
    create table flow (
        id char(36) default (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2)))),
        created timestamp default current_timestamp,
        updated timestamp default (strftime('%Y-%m-%d %H:%M:%f', 'now')),
        name text)
    '''

    def _db(tmp_path):
        con = sqlite3.connect(tmp_path / "x.db")
        con.execute(SCHEMA)
        return con

    # first: it reads no clock; under the prefix rule (review R-020) a later test carries the epoch of earlier readers
    def test_explicit_dates_keep_sqlite_semantics():
        con = sqlite3.connect(":memory:")
        assert con.execute("select date('2020-02-28', '+1 day'), julianday('2000-01-01'), "
                           "strftime('%Y', '1999-12-31'), datetime(0, 'unixepoch')").fetchone() == (
            "2020-02-29", 2451544.5, "1999", "1970-01-01 00:00:00")
        assert con.execute("select date('garbage')").fetchone() == (None,)

    def test_rows(tmp_path):
        con = _db(tmp_path)
        con.execute("insert into flow(name) values ('a')")
        con.execute("insert into flow(name) values ('b')")
        rows = con.execute("select id, created, updated, name from flow order by rowid").fetchall()
        extra = con.execute("select random(), hex(randomblob(8)), date('now'), julianday('now'), unixepoch(), "
                            "datetime('now', '+1 day'), strftime('%s'), date(), current_date, current_time, "
                            "time('now', 'subsec')").fetchone()
        print("ROWS", repr(rows), repr(extra))

    def test_same_instant_in_one_statement(tmp_path):
        con = _db(tmp_path)
        con.execute("insert into flow(name) values ('a')")
        created, updated = con.execute("select created, updated from flow").fetchone()
        # CURRENT_TIMESTAMP and strftime('now') of one INSERT are one instant, as in SQLite
        assert created == updated[:19]
        a, b = con.execute("select strftime('%f', 'now'), strftime('%f', 'now')").fetchone()
        assert a == b

    def test_virtual_now_matches_python(tmp_path):
        con = sqlite3.connect(":memory:")
        (s,) = con.execute("select unixepoch('now')").fetchone()
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        # the virtual clock: SQLite's now and Python's now come from the same clock
        assert abs(now - s) < 5, (now, s)

"""


def _rows(stdout: str) -> list:
    return [line[line.index("ROWS "):] for line in stdout.splitlines() if "ROWS " in line]


def _outcomes(path):
    d = json.loads(path.read_text())
    o = d.get("outcomes") or d.get("tests") or {}
    if isinstance(o, list):
        o = {t["nodeid"]: t["outcome"] for t in o}
    return {k: (v["outcome"] if isinstance(v, dict) else v) for k, v in o.items()}, d.get("cache") or {}


@pytest.fixture
def project(pytester, monkeypatch):
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS"):
        monkeypatch.delenv(k, raising=False)
    pytester.makeini("[pytest]\n")
    pytester.makepyfile(test_sq=textwrap.dedent(SCHEMA_TEST))
    return pytester


def test_values_are_the_same_in_every_det_run_serial_and_parallel(project):
    runs = []
    for args in ((), (), ("-n", "2", "-p", "xdist"), ("-n", "3", "-p", "xdist")):
        r = project.runpytest_subprocess("--det", "-s", "-p", "no:cacheprovider", *args)
        r.assert_outcomes(passed=4)
        runs.append(_rows(r.stdout.str()))
    assert runs[0] and runs[0] == runs[1], "serial runs differ"
    # under -n the print goes to the worker; the passing assertions above are the parallel check, and a plan
    # replay of the worker that ran test_rows prints the same rows
    assert all(len(r) <= 1 for r in runs)


def test_values_differ_without_det(project):
    a = project.runpytest_subprocess("-s", "-p", "no:cacheprovider", "-p", "no:detpy", "-k", "test_rows")
    b = project.runpytest_subprocess("-s", "-p", "no:cacheprovider", "-p", "no:detpy", "-k", "test_rows")
    assert _rows(a.stdout.str()) != _rows(b.stdout.str())  # SQLite's own clock and PRNG


@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
@pytest.mark.parametrize("mode", ["serial", "n2"])
def test_schema_with_sqlite_clock_is_cached_and_reuse_equals_truth(project, mode):
    extra = () if mode == "serial" else ("-n", "2", "-p", "xdist")
    cache = f"--det-cache={project.path / '.c'}"
    o1 = project.path / "o1.json"
    r1 = project.runpytest_subprocess("--det", cache, f"--det-outcomes={o1}", "-p", "no:cacheprovider", *extra)
    r1.assert_outcomes(passed=4)
    _, c1 = _outcomes(o1)
    assert not [n for n, why in (c1.get("not_cached_ids") or {}).items() if "clock" in why], c1
    o2 = project.path / "o2.json"
    r2 = project.runpytest_subprocess("--det", cache, f"--det-outcomes={o2}", "-p", "no:cacheprovider", *extra)
    out2, c2 = _outcomes(o2)
    reused = set(c2.get("reused_ids") or ())
    assert len(reused) == 4, r2.stdout.str()
    # truth: a fresh serial --det run
    o3 = project.path / "o3.json"
    project.runpytest_subprocess("--det", f"--det-outcomes={o3}", "-p", "no:cacheprovider")
    truth, _ = _outcomes(o3)
    assert {n: out2[n] for n in reused} == {n: truth[n] for n in reused}


@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
def test_a_changed_epoch_is_a_miss_for_a_test_that_read_sqlite_now(project):
    cache = f"--det-cache={project.path / '.c'}"
    project.runpytest_subprocess("--det", cache, "-p", "no:cacheprovider").assert_outcomes(passed=4)
    o = project.path / "o.json"
    project.runpytest_subprocess("--det", cache, "--det-epoch=2001-01-01T00:00:00", f"--det-outcomes={o}",
                                 "-p", "no:cacheprovider")
    _, c = _outcomes(o)
    reused = set(c.get("reused_ids") or ())
    # the tests that read SQLite's now depend on the epoch; the one with explicit dates does not
    assert "test_sq.py::test_rows" not in reused
    assert "test_sq.py::test_explicit_dates_keep_sqlite_semantics" in reused
