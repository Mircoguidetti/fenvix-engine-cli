"""Review R-023b (claude/parallel-proof at a13e2dc, REPORT-2): adversarial tests of the R-023 fixes, of the
cacheability rules introduced in that round, and of absent inputs under -n.

Each test asserts the behaviour the report / design claims (same verdict as a fresh run, a test skipped only with
proof); a failing test is a finding. Tests that pass are attacks that did not get through. Some tests change
host files (/etc/hosts, /etc/resolv.conf, the interpreter's site-packages, /dev/shm) and restore them; they need
root and skip otherwise."""

import contextlib
import json
import os
import pathlib
import shutil
import socket
import struct
import subprocess
import sys
import sysconfig
import textwrap
import threading
import uuid

import pytest

pytest.importorskip("xdist")
needs_cache = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
needs_root = pytest.mark.skipif(os.geteuid() != 0, reason="changes host files")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def reused(c):
    return set(c.get("reused_ids", ()))


def three_sessions(pytester, n, change, nid, *args, truth_outcomes, record_outcomes):
    """Record (two sessions, so the entry exists whatever the first session dropped), apply ``change``, then a
    fresh run (the truth) and a cache run. The cache run must give the truth's outcomes and must not reuse ``nid``."""
    for label in ("s1", "s2"):
        r, _ = cache_run(pytester, n, label, *args)
        r.assert_outcomes(**record_outcomes)
    change()
    fresh_run(pytester, n, *args).assert_outcomes(**truth_outcomes)
    r, c = cache_run(pytester, n, "s3", *args)
    assert nid not in reused(c), f"{nid} reused after its input changed"
    r.assert_outcomes(**truth_outcomes)


NS = [pytest.param(0, id="serial"), pytest.param(2, id="n2")]


# =====================================================================================================================
# 1. F1-F6: new variants (not the review's original cases)
# =====================================================================================================================
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
def test_f1v_parallel_entry_is_not_reused_by_a_parallel_session_that_places_the_test_like_serial(pytester):
    """F1's guard refuses parallel entries to serial sessions only; a parallel session reuses parallel entries. Run 1
    (-n 2 --dist loadfile) records the victim's pass (it ran in its own worker). Run 2 (-n 1: one worker runs the
    polluter, then the victim, as serially) fails the victim when fresh, and the serial truth fails it too. Reusing
    the recorded pass gives a verdict neither the serial truth nor this run's fresh -n verdict has."""
    write(pytester, **PLACEMENT)
    fresh_run(pytester, 0, "tests").assert_outcomes(passed=1, failed=1)  # serial truth
    fresh_run(pytester, 1, "tests").assert_outcomes(passed=1, failed=1)  # fresh -n 1 truth
    cache_run(pytester, 2, "par", "--dist", "loadfile", "tests")[0].assert_outcomes(passed=2)
    r, c = cache_run(pytester, 1, "n1", "tests")
    assert "tests/test_b_victim.py::test_victim" not in reused(c)
    r.assert_outcomes(passed=1, failed=1)


DIRLIST = {
    "tests/test_a_writer.py": """
        import os, pathlib
        def test_a_writes():
            d = pathlib.Path(os.environ["SHARED_DIR"])
            for p in d.iterdir():
                p.unlink()
            v = (pathlib.Path(__file__).parent / "value.txt").read_text().strip()
            (d / f"marker-{v}").write_text(v)
        """,
    "tests/test_b_reader.py": """
        import os, time
        def test_b_lists():
            d = os.environ["SHARED_DIR"]
            for _ in range(300):
                if os.listdir(d):
                    break
                time.sleep(0.01)
            time.sleep(0.3)
            assert sorted(os.listdir(d)) == ["marker-x"]
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_f2v_reader_of_a_directory_another_test_changes_is_not_reused(pytester, tmp_path_factory, monkeypatch, n):
    """F2 through a directory listing instead of a file's content: A replaces the entries of a directory outside the
    repository (name from value.txt), B lists it. value.txt changes; A runs and renames the marker; B's recorded
    listing matched before A ran. A fresh session 3 fails B."""
    d = tmp_path_factory.mktemp("outside")
    monkeypatch.setenv("SHARED_DIR", str(d))
    write(pytester, **DIRLIST)
    args = ["--dist", "loadfile", "--det-sleep=real", "tests"] if n else ["--det-sleep=real", "tests"]
    three_sessions(pytester, n, lambda: (pytester.path / "tests" / "value.txt").write_text("y\n"),
                   "tests/test_b_reader.py::test_b_lists", *args,
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


EXISTS = {
    "tests/test_a_writer.py": """
        import os, pathlib
        def test_a_flag():
            p = pathlib.Path(os.environ["SHARED_DIR"]) / "flag"
            if (pathlib.Path(__file__).parent / "value.txt").read_text().strip() == "y":
                p.write_text("1")
            elif p.exists():
                p.unlink()
        """,
    "tests/test_b_reader.py": """
        import os, time
        def test_b_no_flag():
            time.sleep(0.5)
            assert not os.path.exists(os.path.join(os.environ["SHARED_DIR"], "flag"))
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_f2v_absent_file_created_by_an_earlier_test_is_not_reused(pytester, tmp_path_factory, monkeypatch, n):
    """F2 with an absent input: B checks that a file does not exist; after value.txt changes, A (earlier in the serial
    order) creates it. B's recorded 'absent' matched before A ran."""
    d = tmp_path_factory.mktemp("outside")
    monkeypatch.setenv("SHARED_DIR", str(d))
    write(pytester, **EXISTS)
    args = ["--dist", "loadfile", "--det-sleep=real", "tests"] if n else ["--det-sleep=real", "tests"]

    def change():
        (pytester.path / "tests" / "value.txt").write_text("y\n")
        (d / "flag").unlink(missing_ok=True)

    for label in ("s1", "s2"):
        cache_run(pytester, n, label, *args)[0].assert_outcomes(passed=2)
    change()
    fresh_run(pytester, n, *args).assert_outcomes(passed=1, failed=1)
    (d / "flag").unlink(missing_ok=True)
    r, c = cache_run(pytester, n, "s3", *args)
    assert "tests/test_b_reader.py::test_b_no_flag" not in reused(c)
    r.assert_outcomes(passed=1, failed=1)


WORKER_FIXTURE = {
    "tests/test_w.py": """
        def test_on_gw0(worker_id): assert worker_id in ("gw0", "master")
        """,
    "tests/test_x.py": """
        def test_x1(): pass
        def test_x2(): pass
        """,
}


def plan_file(pytester, name, nid, on):
    p = json.loads((pytester.path / ".detpy" / "plan.json").read_text())
    lists = {w: [t for t in ids if t != nid] for w, ids in p["lists"].items()}
    lists.setdefault(on, []).insert(0, nid)
    p["lists"] = lists
    p["assign"] = dict(p.get("assign") or {}, **{nid: on})
    path = pytester.path / name
    path.write_text(json.dumps(p))
    return path


@needs_cache
def test_f3v_worker_id_fixture_reader_is_not_reused_when_the_plan_moves_it(pytester):
    """F3 through xdist's ``worker_id`` fixture (config.workerinput, not PYTEST_XDIST_WORKER): the deferred worker
    check sees only the variable. Recorded on gw0, the next run's plan pins the test to gw1, where it fails fresh."""
    write(pytester, **WORKER_FIXTURE)
    nid = "tests/test_w.py::test_on_gw0"
    fresh_run(pytester, 2, "tests")
    on0 = plan_file(pytester, "p0.json", nid, "gw0")
    on1 = plan_file(pytester, "p1.json", nid, "gw1")
    fresh_run(pytester, 2, f"--det-plan={on1}", "tests").assert_outcomes(passed=2, failed=1)
    cache_run(pytester, 2, "s1", f"--det-plan={on0}", "tests")[0].assert_outcomes(passed=3)
    r, c = cache_run(pytester, 2, "s2", f"--det-plan={on1}", "tests")
    assert nid not in reused(c)
    r.assert_outcomes(passed=2, failed=1)


def _plan(ids, n, previous, costs=None):
    from detpy import _core
    atoms = [_core.sched_atom_key(i, "load", None) for i in ids]
    costs = costs or [1.0] * len(ids)
    atoms = _core.sched_chunk_atoms(ids, atoms, costs, n, 8)
    p = json.loads(_core.sched_plan(ids, atoms, costs, n, previous, 0.1))
    worker = {}
    for w, lst in enumerate(p["lists"]):
        for j in lst:
            worker[ids[j]] = w
    return p, worker


@pytest.mark.parametrize("where", ["new_file_in_middle", "remove_middle_test", "add_16_tests"])
def test_f4v_plan_stays_sticky_under_other_changes(where):
    """F4 variants (binding, unit costs): a new one-test file sorting in the middle of the suite; one test removed
    from the middle of a file; 16 tests added to one file. At most 5 % of the other tests may change worker."""
    ids = [f"tests/test_{f}.py::test_{i}" for f in range(8) for i in range(48)]
    p1, w1 = _plan(ids, 4, {})
    if where == "new_file_in_middle":
        ids2 = ids[:4 * 48] + ["tests/test_3a.py::test_new"] + ids[4 * 48:]
    elif where == "remove_middle_test":
        ids2 = [i for i in ids if i != "tests/test_3.py::test_20"]
    else:
        ids2 = ids[:4 * 48] + [f"tests/test_3.py::test_new{k}" for k in range(16)] + ids[4 * 48:]
    p2, w2 = _plan(ids2, 4, p1["atom_worker"])
    common = [i for i in ids if i in w2]
    moved = sum(w1[i] != w2[i] for i in common)
    assert moved <= len(common) // 20, f"{moved} of {len(common)} existing tests changed worker (sticky={p2['sticky']})"


def test_f4v_plan_stays_sticky_when_durations_move_within_noise():
    """F4 with recorded durations: the same 384 tests, every duration moved by +-10 % (run-to-run noise). The report
    says 'from run 3 on the plan is sticky'; at most 5 % of tests may change worker."""
    import random
    ids = [f"tests/test_{f}.py::test_{i}" for f in range(8) for i in range(48)]
    rng = random.Random(7)
    base = [rng.uniform(0.01, 1.0) for _ in ids]
    p1, w1 = _plan(ids, 4, {}, base)
    noisy = [c * rng.uniform(0.9, 1.1) for c in base]
    p2, w2 = _plan(ids, 4, p1["atom_worker"], noisy)
    moved = sum(w1[i] != w2[i] for i in ids)
    assert moved <= len(ids) // 20, f"{moved} of {len(ids)} tests changed worker (sticky={p2['sticky']})"


def _fpcompare():
    sys.path.insert(0, ROOT)
    try:
        from harness.parallel_proof.fpcompare import compare
    finally:
        sys.path.remove(ROOT)
    return compare


@pytest.mark.parametrize("par", ["error", "failed+teardown-error", "passed+teardown-error"])
def test_f5v_fpcompare_counts_an_error_caused_by_the_split(par):
    """F5 variant: det_outcome reports a setup error as 'error' and a teardown error as '<x>+teardown-error'. A test
    that passes in both serial runs and errors in both parallel runs is a new failure caused by the split."""
    compare = _fpcompare()
    rec = lambda outcome: {"fingerprint": outcome, "outcome": outcome, "events": []}  # noqa: E731
    s = {"t": rec("passed")}
    p = {"t": rec(par)}
    out = compare(s, s, p, p)
    assert out["outcome_differences"] == 1
    assert out["new_failures_caused_by_split"] == ["t"]


def test_f5v_fpcompare_counts_a_serial_error_hidden_by_the_split():
    compare = _fpcompare()
    rec = lambda outcome: {"fingerprint": outcome, "outcome": outcome, "events": []}  # noqa: E731
    s = {"t": rec("error")}
    out = compare(s, s, {"t": rec("passed")}, {"t": rec("passed")})
    assert out["hidden_failures"] == ["t"]


def test_f5v_crosscheck_counts_a_test_the_run_lost():
    """crosscheck compares only the tests present in the run's outcomes: a test of the truth that the run never
    reports (lost by a crashed worker, a withdrawn hit never re-run) is not counted anywhere."""
    sys.path.insert(0, ROOT)
    try:
        from harness.parallel_proof.crosscheck import compare
    finally:
        sys.path.remove(ROOT)
    truth = {"outcomes": {"a": "passed", "b": "failed"}}
    run = {"outcomes": {"a": "passed"}, "cache": {"reused_ids": ["a"]}}
    out = compare([truth, truth], run)
    lost = [k for k, v in out.items() if "missing" in k or "lost" in k]
    assert lost and any(out[k] for k in lost), f"no field reports the lost test: {out}"


# =====================================================================================================================
# 2a. /proc, /sys, /dev reads by code that runs for every test are no longer data inputs
# =====================================================================================================================
@contextlib.contextmanager
def shm_file(text):
    p = pathlib.Path("/dev/shm") / f"detpy-r023b-{uuid.uuid4().hex}"
    p.write_text(text)
    try:
        yield p
    finally:
        p.unlink(missing_ok=True)


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2a_conftest_import_reads_dev_shm(pytester, monkeypatch, n):
    """A conftest reads a flag from /dev/shm at import (a shared-memory file a service or a previous job leaves);
    the test asserts on it. The read is in a global context, so it is dropped as an input."""
    with shm_file("x") as p:
        monkeypatch.setenv("R023B_SHM", str(p))
        write(pytester, **{
            "tests/conftest.py": """
                import os
                MODE = open(os.environ["R023B_SHM"]).read()
                """,
            "tests/test_mode.py": """
                from conftest import MODE
                def test_mode(): assert MODE == "x"
                def test_other(): pass
                """,
        })
        three_sessions(pytester, n, lambda: p.write_text("y"), "tests/test_mode.py::test_mode", "tests",
                       truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2a_any_file_read_through_proc_self_root(pytester, tmp_path_factory, monkeypatch, n):
    """/proc/self/root/<path> is the file <path>: a conftest that opens a configuration file through it (or through
    /proc/self/cwd, /dev/fd/N) reads an ordinary file that is no longer an input."""
    cfg = tmp_path_factory.mktemp("etc") / "service.conf"
    cfg.write_text("x")
    monkeypatch.setenv("R023B_CONF", "/proc/self/root" + str(cfg))
    write(pytester, **{
        "tests/conftest.py": """
            import os
            MODE = open(os.environ["R023B_CONF"]).read()
            """,
        "tests/test_mode.py": """
            from conftest import MODE
            def test_mode(): assert MODE == "x"
            def test_other(): pass
            """,
    })
    three_sessions(pytester, n, lambda: cfg.write_text("y"), "tests/test_mode.py::test_mode", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2a_pool_size_from_proc_self_status(pytester, n):
    """A conftest sizes a pool from /proc/self/status (Cpus_allowed_list: the CPU set a cgroup / taskset gives the
    job); a test asserts the pool size. Run 1-2 on CPUs {0, 1}, run 3 on CPU {0}."""
    write(pytester, **{
        "tests/conftest.py": """
            def _cpus():
                for line in open("/proc/self/status"):
                    if line.startswith("Cpus_allowed_list:"):
                        return line.split(":", 1)[1].strip()
            POOL = _cpus()
            """,
        "tests/test_pool.py": """
            from conftest import POOL
            def test_pool(): assert POOL == "0-1"
            def test_other(): pass
            """,
    })
    before = os.sched_getaffinity(0)
    if not {0, 1} <= before:
        pytest.skip("needs CPUs 0 and 1")
    try:
        os.sched_setaffinity(0, {0, 1})
        three_sessions(pytester, n, lambda: os.sched_setaffinity(0, {0}), "tests/test_pool.py::test_pool", "tests",
                       truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))
    finally:
        os.sched_setaffinity(0, before)


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2a_between_tests_hook_reads_dev_shm_into_the_environment(pytester, monkeypatch, n):
    """The 'between tests' context: a pytest_runtest_setup hook copies a /dev/shm flag into os.environ; the test
    reads the variable (an input by name, whose value the session itself set: not compared)."""
    with shm_file("x") as p:
        monkeypatch.setenv("R023B_SHM", str(p))
        write(pytester, **{
            "tests/conftest.py": """
                import os
                def pytest_runtest_setup(item):
                    os.environ["R023B_MODE"] = open(os.environ["R023B_SHM"]).read()
                """,
            "tests/test_mode.py": """
                import os
                def test_mode(): assert os.environ["R023B_MODE"] == "x"
                def test_other(): pass
                """,
        })
        three_sessions(pytester, n, lambda: p.write_text("y"), "tests/test_mode.py::test_mode", "tests",
                       truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


# =====================================================================================================================
# 2b. loopback host-name lookups keyed by the resolver files
# =====================================================================================================================
@contextlib.contextmanager
def replaced(path, text):
    p = pathlib.Path(path)
    old = p.read_bytes()
    try:
        p.write_text(text)
        yield p
    finally:
        p.write_bytes(old)


class FakeDNS:
    """A UDP DNS server on 127.0.0.1:53: answers A queries with 127.0.0.1 when ``answer`` is set, NXDOMAIN otherwise
    (AAAA and the rest: NOERROR, no answer)."""

    def __init__(self):
        self.answer = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 53))
        self.sock.settimeout(0.2)
        self.stop = False
        self.t = threading.Thread(target=self.serve, daemon=True)
        self.t.start()

    def serve(self):
        while not self.stop:
            try:
                q, addr = self.sock.recvfrom(512)
            except (TimeoutError, OSError):
                continue
            tid = q[:2]
            i = 12
            while q[i]:
                i += q[i] + 1
            qend = i + 5
            qtype = struct.unpack(">H", q[i + 1:i + 3])[0]
            question = q[12:qend]
            if not self.answer:
                hdr = tid + struct.pack(">HHHHH", 0x8183, 1, 0, 0, 0)
                self.sock.sendto(hdr + question, addr)
            elif qtype == 1:
                hdr = tid + struct.pack(">HHHHH", 0x8180, 1, 1, 0, 0)
                rr = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + socket.inet_aton("127.0.0.1")
                self.sock.sendto(hdr + question + rr, addr)
            else:
                hdr = tid + struct.pack(">HHHHH", 0x8180, 1, 0, 0, 0)
                self.sock.sendto(hdr + question, addr)

    def close(self):
        self.stop = True
        self.t.join()
        self.sock.close()


LOOKUP = {
    "tests/test_lookup.py": """
        import socket
        def test_name_does_not_resolve():
            try:
                socket.getaddrinfo("ip6-localhost", 80, socket.AF_INET, socket.SOCK_STREAM)
            except socket.gaierror:
                return
            raise AssertionError("ip6-localhost resolved")
        def test_other(): pass
        """,
}


@needs_root
@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2b_loopback_name_answered_by_dns_is_not_reused(pytester, n):
    """``ip6-localhost`` is one of the names the rule treats as answered by the resolver files. Where /etc/hosts does
    not list it (this container, many images), glibc asks the DNS server of /etc/resolv.conf (nsswitch 'files dns').
    The four recorded files do not change; the DNS answer does."""
    if "ip6-localhost" in pathlib.Path("/etc/hosts").read_text():
        pytest.skip("/etc/hosts lists ip6-localhost here")
    dns = FakeDNS()
    try:
        with replaced("/etc/resolv.conf", "nameserver 127.0.0.1\noptions timeout:1 attempts:1\n"):
            write(pytester, **LOOKUP)

            def change():
                dns.answer = True

            three_sessions(pytester, n, change, "tests/test_lookup.py::test_name_does_not_resolve", "tests",
                           truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))
    finally:
        dns.close()


@needs_root
@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2b_hosts_file_change_is_seen(pytester, n):
    """Control: the same test, the answer changed through /etc/hosts (a recorded file): not reused."""
    if "ip6-localhost" in pathlib.Path("/etc/hosts").read_text():
        pytest.skip("/etc/hosts lists ip6-localhost here")
    old = pathlib.Path("/etc/hosts").read_text()
    with replaced("/etc/hosts", old):
        write(pytester, **LOOKUP)
        three_sessions(pytester, n,
                       lambda: pathlib.Path("/etc/hosts").write_text(old + "127.0.0.1 ip6-localhost\n"),
                       "tests/test_lookup.py::test_name_does_not_resolve", "tests",
                       truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2b_hostaliases_changes_a_loopback_lookup(pytester, tmp_path_factory, monkeypatch, n):
    """glibc's resolver reads HOSTALIASES (a file named by an environment variable the test never reads through
    os.environ) for single-label names that reach DNS: ``ip6-loopback`` -> an alias. Not one of the four files."""
    if "ip6-loopback" in pathlib.Path("/etc/hosts").read_text():
        pytest.skip("/etc/hosts lists ip6-loopback here")
    aliases = tmp_path_factory.mktemp("res") / "aliases"
    aliases.write_text("")
    monkeypatch.setenv("HOSTALIASES", str(aliases))
    write(pytester, **{
        "tests/test_lookup.py": """
            import socket
            def test_name_does_not_resolve():
                try:
                    socket.getaddrinfo("ip6-loopback", 80, socket.AF_INET, socket.SOCK_STREAM)
                except socket.gaierror:
                    return
                raise AssertionError("ip6-loopback resolved")
            def test_other(): pass
            """,
    })
    # does this libc honour HOSTALIASES for the name at all? (probe outside detpy)
    aliases.write_text("ip6-loopback localhost\n")
    try:
        socket.getaddrinfo("ip6-loopback", 80, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror:
        pytest.skip("HOSTALIASES not honoured for this name here")
    finally:
        aliases.write_text("")
    three_sessions(pytester, n, lambda: aliases.write_text("ip6-loopback localhost\n"),
                   "tests/test_lookup.py::test_name_does_not_resolve", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


# =====================================================================================================================
# 2c. connections to the xdist controller's listener are infrastructure
# =====================================================================================================================
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


CONTROLLER_SERVER = {
    "tests/conftest.py": """
        import os, pathlib, socket, threading
        PORT = int(os.environ["R023B_PORT"])
        SRC = pathlib.Path(__file__).parent / "value.txt"

        def pytest_configure(config):
            if hasattr(config, "workerinput"):
                return
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", PORT))
            srv.listen(16)

            def serve():
                while True:
                    c, _ = srv.accept()
                    c.sendall(SRC.read_bytes())
                    c.close()
            threading.Thread(target=serve, daemon=True).start()
        """,
    "tests/test_client.py": """
        import os, socket
        def test_value_from_the_controller():
            s = socket.create_connection(("127.0.0.1", int(os.environ["R023B_PORT"])))
            data = b""
            while True:
                b = s.recv(100)
                if not b:
                    break
                data += b
            assert data.strip() == b"x"
        def test_other(): pass
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
def test_2c_data_served_by_a_controller_listener_is_an_input(pytester, monkeypatch):
    """A conftest's pytest_configure runs in the xdist controller too (the controller runs conftest code, not only
    plugins): here it serves the content of value.txt on a loopback port. A test in a worker reads it. value.txt
    changes: a fresh -n run fails the test."""
    monkeypatch.setenv("R023B_PORT", str(free_port()))
    write(pytester, **CONTROLLER_SERVER)
    three_sessions(pytester, 2, lambda: (pytester.path / "tests" / "value.txt").write_text("y\n"),
                   "tests/test_client.py::test_value_from_the_controller", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


CONTROLLER_RELAY = {
    "tests/conftest.py": """
        import os, socket, threading
        PORT = int(os.environ["R023B_PORT"])

        def pytest_configure(config):
            if hasattr(config, "workerinput"):
                return
            box = []
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", PORT))
            srv.listen(16)

            def serve():
                while True:
                    c, _ = srv.accept()
                    msg = c.recv(100)
                    if msg.startswith(b"put "):
                        box.append(msg[4:])
                        c.sendall(b"ok")
                    else:
                        c.sendall(box[-1] if box else b"")
                    c.close()
            threading.Thread(target=serve, daemon=True).start()
        """,
    "tests/test_a_put.py": """
        import os, pathlib, socket
        def test_a_puts():
            v = (pathlib.Path(__file__).parent / "value.txt").read_bytes().strip()
            s = socket.create_connection(("127.0.0.1", int(os.environ["R023B_PORT"])))
            s.sendall(b"put " + v)
            s.recv(10)
        """,
    "tests/test_b_get.py": """
        import os, socket, time
        def test_b_gets():
            for _ in range(300):
                s = socket.create_connection(("127.0.0.1", int(os.environ["R023B_PORT"])))
                s.sendall(b"get")
                v = s.recv(100)
                if v:
                    break
                time.sleep(0.01)
            assert v == b"x"
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
def test_2c_cross_worker_state_through_a_controller_listener(pytester, monkeypatch):
    """Test A (worker 0) sends value.txt's content to a store the controller's conftest serves; test B (worker 1)
    reads it: a cross-worker data flow that the cross-worker write rule never sees (no file is written). value.txt
    changes: A runs, B is reused."""
    monkeypatch.setenv("R023B_PORT", str(free_port()))
    write(pytester, **CONTROLLER_RELAY)
    three_sessions(pytester, 2, lambda: (pytester.path / "tests" / "value.txt").write_text("y\n"),
                   "tests/test_b_get.py::test_b_gets", "--dist", "loadfile", "--det-sleep=real", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


# =====================================================================================================================
# 2d. the controller decides with the workers' start environment (snapshot at pytest_xdist_setupnodes)
# =====================================================================================================================
TXENV = {
    "tests/test_env.py": """
        import os
        def test_mode_unset(): assert os.environ.get("R023B_TXMODE") is None
        def test_other(): pass
        """,
}


@needs_cache
def test_2d_variable_set_by_the_tx_spec_is_seen(pytester):
    """xdist's ``--tx popen//env:NAME=VALUE`` sets a variable in every worker (and ``--tx`` is not part of the
    configuration digest). The controller's snapshot does not have it; the workers do."""
    write(pytester, **TXENV)
    nid = "tests/test_env.py::test_mode_unset"
    for label in ("s1", "s2"):
        cache_run(pytester, 2, label, "tests")[0].assert_outcomes(passed=2)
    tx = ["--tx", "2*popen//env:R023B_TXMODE=on", "--dist", "load"]
    pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", "-p", "no:randomly", *tx,
                                  "tests").assert_outcomes(passed=1, failed=1)
    r, c = cache_run(pytester, 0, "s3", *tx, "tests")
    assert nid not in reused(c)
    r.assert_outcomes(passed=1, failed=1)


@needs_cache
def test_2d_variable_set_by_a_worker_only_hook_from_a_recorded_file(pytester, tmp_path_factory, monkeypatch):
    """Control: a worker-only pytest_configure sets a variable from an ordinary file outside the repository; the
    file read is a start-up input of the worker."""
    f = tmp_path_factory.mktemp("cfg") / "mode"
    f.write_text("x")
    monkeypatch.setenv("R023B_FILE", str(f))
    write(pytester, **{
        "tests/conftest.py": """
            import os
            def pytest_configure(config):
                if hasattr(config, "workerinput"):
                    os.environ["R023B_MODE"] = open(os.environ["R023B_FILE"]).read()
            """,
        "tests/test_env.py": """
            import os
            def test_mode(): assert os.environ.get("R023B_MODE") == "x"
            def test_other(): pass
            """,
    })
    three_sessions(pytester, 2, lambda: f.write_text("y"), "tests/test_env.py::test_mode", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


# =====================================================================================================================
# 2e. --det-urandom
# =====================================================================================================================
@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2e_os_getrandom_is_entropy(pytester, n):
    """os.getrandom (getrandom(2), the same kernel pool as os.urandom) is neither controlled nor observed: a test
    that draws from it is cached without --det-urandom, which the design forbids for OS entropy."""
    write(pytester, **{
        "tests/test_rand.py": """
            import os
            def test_draw(): assert len(os.getrandom(8)) == 8
            def test_other(): pass
            """,
    })
    for label in ("s1", "s2"):
        cache_run(pytester, n, label, "tests")[0].assert_outcomes(passed=2)
    r, c = cache_run(pytester, n, "s3", "tests")
    assert "tests/test_rand.py::test_draw" not in reused(c), "a test that drew OS entropy was reused"


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2e_ssl_rand_bytes_is_entropy(pytester, n):
    """ssl.RAND_bytes (OpenSSL's generator, seeded from the kernel): same class as os.getrandom."""
    write(pytester, **{
        "tests/test_rand.py": """
            import ssl
            def test_draw(): assert len(ssl.RAND_bytes(8)) == 8
            def test_other(): pass
            """,
    })
    for label in ("s1", "s2"):
        cache_run(pytester, n, label, "tests")[0].assert_outcomes(passed=2)
    r, c = cache_run(pytester, n, "s3", "tests")
    assert "tests/test_rand.py::test_draw" not in reused(c), "a test that drew OS entropy was reused"


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2e_dev_urandom_read_at_import_is_entropy(pytester, n):
    """/dev/urandom opened by a conftest at import: a /dev read in a global context, dropped by the new rule (and not
    os.urandom, so not the 'entropy' flag either). The test's verdict depends on the bytes; without --det-urandom
    it must not be cached."""
    write(pytester, **{
        "tests/conftest.py": """
            TOKEN = open("/dev/urandom", "rb").read(8)
            """,
        "tests/test_rand.py": """
            from conftest import TOKEN
            def test_token(): assert len(TOKEN) == 8
            def test_other(): pass
            """,
    })
    for label in ("s1", "s2"):
        cache_run(pytester, n, label, "tests")[0].assert_outcomes(passed=2)
    r, c = cache_run(pytester, n, "s3", "tests")
    assert "tests/test_rand.py::test_token" not in reused(c), "a test that read OS entropy was reused"


SESSION_TOKEN = {
    "tests/conftest.py": """
        import os, pytest
        @pytest.fixture(scope="session")
        def token():
            return int.from_bytes(os.urandom(8), "big")
        """,
    "tests/test_b_user.py": """
        def test_b_token(token): assert token == EXPECTED
        """,
}


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2e_session_fixture_entropy_depends_on_the_first_requesting_test(pytester, n):
    """Under --det-urandom the stream is re-seeded per test from the node id. A session fixture's bytes come from the
    stream of the test that first requests it. A new test that sorts first and requests the fixture changes the
    value a later, unchanged test sees; nothing that test reads has changed."""
    files = dict(SESSION_TOKEN)
    files["tests/test_b_user.py"] = files["tests/test_b_user.py"].replace("EXPECTED", "-1")
    write(pytester, **files)
    args = ["--det-urandom", "-p", "no:xdist"] if not n else ["--det-urandom", "--dist", "loadfile"]

    def probe():
        r = fresh_run(pytester, n, *args, "tests")
        out = r.stdout.str()
        import re
        m = re.search(r"assert (\d+) == -1", out)
        assert m, out
        return int(m.group(1))

    v1 = probe()
    first = {"tests/test_a_first.py": "def test_a_first(token): pass\n"}
    write(pytester, **first)
    v2 = probe()
    (pytester.path / "tests" / "test_a_first.py").unlink()
    if v1 == v2:
        pytest.skip("the first requester does not change the value here")
    files["tests/test_b_user.py"] = SESSION_TOKEN["tests/test_b_user.py"].replace("EXPECTED", str(v1))
    write(pytester, **files)
    nid = "tests/test_b_user.py::test_b_token"
    for label in ("s1", "s2"):
        cache_run(pytester, n, label, *args, "tests")[0].assert_outcomes(passed=1)
    write(pytester, **first)
    fresh_run(pytester, n, *args, "tests").assert_outcomes(passed=1, failed=1)
    r, c = cache_run(pytester, n, "s3", *args, "tests")
    assert nid not in reused(c)
    r.assert_outcomes(passed=1, failed=1)


# =====================================================================================================================
# 3. absent inputs, serially and under -n
# =====================================================================================================================
@needs_cache
@pytest.mark.parametrize("n", NS)
def test_3_failed_optional_import_later_satisfied(pytester, n):
    write(pytester, **{
        "tests/test_opt.py": """
            try:
                import r023b_optional
            except ImportError:
                r023b_optional = None
            def test_without_optional(): assert r023b_optional is None
            def test_other(): pass
            """,
    })
    three_sessions(pytester, n, lambda: write(pytester, **{"tests/r023b_optional.py": "X = 1\n"}),
                   "tests/test_opt.py::test_without_optional", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_3_new_conftest(pytester, n):
    write(pytester, **{
        "tests/sub/test_x.py": """
            def test_x(): pass
            """,
        "tests/test_y.py": """
            def test_y(): pass
            """,
    })
    three_sessions(pytester, n, lambda: write(pytester, **{"tests/sub/conftest.py": """
                       import pytest
                       @pytest.fixture(autouse=True)
                       def boom():
                           raise RuntimeError("new conftest")
                       """}),
                   "tests/sub/test_x.py::test_x", "tests",
                   truth_outcomes=dict(passed=1, errors=1), record_outcomes=dict(passed=2))


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_3_path_exists_of_a_file_created_later(pytester, n):
    write(pytester, **{
        "tests/test_exists.py": """
            import os
            def test_no_override():
                assert not os.path.exists(os.path.join(os.path.dirname(__file__), "override.cfg"))
            def test_other(): pass
            """,
    })
    three_sessions(pytester, n, lambda: write(pytester, **{"tests/override.cfg": "1\n"}),
                   "tests/test_exists.py::test_no_override", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_3_namespace_package_gains_init(pytester, n):
    write(pytester, **{
        "tests/r023b_ns/mod.py": "V = 1\n",
        "tests/test_ns.py": """
            import r023b_ns.mod
            import r023b_ns
            def test_namespace(): assert getattr(r023b_ns, "FLAG", None) is None
            def test_other(): pass
            """,
    })
    three_sessions(pytester, n, lambda: write(pytester, **{"tests/r023b_ns/__init__.py": "FLAG = 1\n"}),
                   "tests/test_ns.py::test_namespace", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


@needs_root
@needs_cache
@pytest.mark.parametrize("n", NS)
def test_3_new_pth_file(pytester, tmp_path_factory, n):
    """A .pth file added to the interpreter's site-packages (a package install that only adds a path) makes an
    optional import succeed."""
    extra = tmp_path_factory.mktemp("extra")
    (extra / "r023b_pthmod.py").write_text("X = 1\n")
    pth = pathlib.Path(sysconfig.get_paths()["purelib"]) / f"r023b-{uuid.uuid4().hex[:8]}.pth"
    write(pytester, **{
        "tests/test_pth.py": """
            try:
                import r023b_pthmod
            except ImportError:
                r023b_pthmod = None
            def test_without(): assert r023b_pthmod is None
            def test_other(): pass
            """,
    })
    try:
        three_sessions(pytester, n, lambda: pth.write_text(str(extra) + "\n"), "tests/test_pth.py::test_without",
                       "tests", truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))
    finally:
        pth.unlink(missing_ok=True)


def make_zip(path, files):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_3_zipimport_member_appears(pytester, n):
    """An optional import from a zip on sys.path (zipimport): the zip gains the module."""
    (pytester.path / "tests").mkdir()
    make_zip(pytester.path / "tests" / "deps.zip", {"other.py": ""})
    write(pytester, **{
        "tests/conftest.py": """
            import os, sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "deps.zip"))
            """,
        "tests/test_zip.py": """
            try:
                import r023b_zmod
            except ImportError:
                r023b_zmod = None
            def test_without(): assert r023b_zmod is None
            def test_other(): pass
            """,
    })
    three_sessions(pytester, n,
                   lambda: make_zip(pytester.path / "tests" / "deps.zip", {"other.py": "", "r023b_zmod.py": "X = 1\n"}),
                   "tests/test_zip.py::test_without", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_3_zipimport_member_changes(pytester, n):
    (pytester.path / "tests").mkdir()
    make_zip(pytester.path / "tests" / "deps.zip", {"r023b_zmod.py": "V = 1\n"})
    write(pytester, **{
        "tests/conftest.py": """
            import os, sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "deps.zip"))
            """,
        "tests/test_zip.py": """
            import r023b_zmod
            def test_v(): assert r023b_zmod.V == 1
            def test_other(): pass
            """,
    })
    three_sessions(pytester, n, lambda: make_zip(pytester.path / "tests" / "deps.zip", {"r023b_zmod.py": "V = 2\n"}),
                   "tests/test_zip.py::test_v", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


def build_so(path, value):
    src = path.with_suffix(".c")
    src.write_text(f"int value(void) {{ return {value}; }}\n")
    subprocess.run(["cc", "-shared", "-fPIC", "-o", str(path), str(src)], check=True)
    src.unlink()


needs_cc = pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")


@needs_cc
@needs_cache
@pytest.mark.parametrize("n", NS)
def test_3_ctypes_library_changes(pytester, n):
    (pytester.path / "tests").mkdir()
    build_so(pytester.path / "tests" / "libr023b.so", 1)
    write(pytester, **{
        "tests/test_lib.py": """
            import ctypes, os
            LIB = ctypes.CDLL(os.path.join(os.path.dirname(__file__), "libr023b.so"))
            def test_value(): assert LIB.value() == 1
            def test_other(): pass
            """,
    })
    three_sessions(pytester, n, lambda: build_so(pytester.path / "tests" / "libr023b.so", 2),
                   "tests/test_lib.py::test_value", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


@needs_cc
@needs_cache
@pytest.mark.parametrize("n", NS)
def test_3_ctypes_library_appears(pytester, n):
    write(pytester, **{
        "tests/test_lib.py": """
            import ctypes, os
            try:
                LIB = ctypes.CDLL(os.path.join(os.path.dirname(__file__), "libr023b.so"))
            except OSError:
                LIB = None
            def test_without(): assert LIB is None
            def test_other(): pass
            """,
    })
    three_sessions(pytester, n, lambda: build_so(pytester.path / "tests" / "libr023b.so", 1),
                   "tests/test_lib.py::test_without", "tests",
                   truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))


ABSENT_SPLIT = {
    "tests/test_a_maker.py": """
        import os, pathlib
        def test_a_makes():
            if (pathlib.Path(__file__).parent / "value.txt").read_text().strip() == "y":
                pathlib.Path(os.environ["SHARED_DIR"], "flag").write_text("1")
        """,
    "tests/test_b_checker.py": """
        import os, time
        def test_b_checks():
            time.sleep(0.5)
            assert not os.path.exists(os.path.join(os.environ["SHARED_DIR"], "flag"))
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
def test_3_absent_input_across_worker_shards(pytester, tmp_path_factory, monkeypatch):
    """Worker-split stores: B (worker 1) records 'flag absent'; A (worker 0) creates the flag in the session where
    value.txt changes. The merge sees A's shard write only for paths that existed; B's absent input is in another
    shard. A fresh -n run fails B; the cache run must not reuse B."""
    d = tmp_path_factory.mktemp("outside")
    monkeypatch.setenv("SHARED_DIR", str(d))
    write(pytester, **ABSENT_SPLIT)
    args = ["--dist", "loadfile", "--det-sleep=real", "tests"]
    for label in ("s1", "s2"):
        cache_run(pytester, 2, label, *args)[0].assert_outcomes(passed=2)
    (pytester.path / "tests" / "value.txt").write_text("y\n")
    fresh_run(pytester, 2, *args).assert_outcomes(passed=1, failed=1)
    (d / "flag").unlink()
    r, c = cache_run(pytester, 2, "s3", *args)
    assert "tests/test_b_checker.py::test_b_checks" not in reused(c)
    r.assert_outcomes(passed=1, failed=1)


class ValueServer:
    """A loopback TCP server of this (outer) process: sends ``value`` to every client."""

    def __init__(self, host, port):
        self.value = b"x"
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind((host, port))
        self.srv.listen(16)
        self.srv.settimeout(0.2)
        self.stop = False
        self.t = threading.Thread(target=self.serve, daemon=True)
        self.t.start()

    def serve(self):
        while not self.stop:
            try:
                c, _ = self.srv.accept()
            except (TimeoutError, OSError):
                continue
            c.sendall(self.value)
            c.close()

    def close(self):
        self.stop = True
        self.t.join()
        self.srv.close()


SAME_PORT = {
    "tests/conftest.py": """
        import os, socket, xdist  # noqa: F401
        PORT = int(os.environ["R023B_PORT"])
        def pytest_configure(config):
            if hasattr(config, "workerinput"):
                return
            # a listener of the session's own process (a plugin's status server, say): it serves nothing here
            srv = socket.socket()
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", PORT))
            srv.listen(1)
            config._r023b_srv = srv
        """,
    "tests/test_client.py": """
        import os, socket
        def test_value_from_another_process():
            s = socket.create_connection(("127.0.0.2", int(os.environ["R023B_PORT"])))
            data = s.recv(100)
            assert data == b"x"
        def test_other(): pass
        """,
}


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_2c_listener_match_ignores_the_address(pytester, monkeypatch, n):
    """own_listener matches a connect by port and 'loopback' only, not by address: the session process (serially)
    or the controller (-n) listens on 127.0.0.1:P; another process serves data on 127.0.0.2:P. A test that reads
    from 127.0.0.2:P is treated as talking to its own session and cached. Under -n this is the new controller rule."""
    port = free_port()
    monkeypatch.setenv("R023B_PORT", str(port))
    srv = ValueServer("127.0.0.2", port)
    try:
        write(pytester, **SAME_PORT)
        three_sessions(pytester, n, lambda: setattr(srv, "value", b"y"),
                       "tests/test_client.py::test_value_from_another_process", "tests",
                       truth_outcomes=dict(passed=1, failed=1), record_outcomes=dict(passed=2))
    finally:
        srv.close()


CONSUMED = {
    "tests/test_a_writer.py": """
        import os, pathlib
        def test_a_writes():
            v = (pathlib.Path(__file__).parent / "value.txt").read_text()
            pathlib.Path(os.environ["SHARED_FILE"]).write_text(v)
        """,
    "tests/test_b_reader.py": """
        import os, pathlib, time
        def test_b_consumes():
            p = pathlib.Path(os.environ["SHARED_FILE"])
            for _ in range(300):
                if p.exists() and p.read_text():
                    break
                time.sleep(0.01)
            v = p.read_text()
            p.unlink()  # the reader cleans up (a queue, a spool directory, a lock file)
            assert v.strip() == "x"
        """,
    "tests/value.txt": "x\n",
}


@needs_cache
@pytest.mark.parametrize("n", NS)
def test_f2v_reused_writer_whose_output_is_gone(pytester, tmp_path_factory, monkeypatch, n):
    """F2's persistence keeps a written path 'while the path exists'. A writes a file outside the repository, B reads
    and removes it. At save the path is gone, so the writer is forgotten; next session A (unchanged) is reused and
    writes nothing, B runs and finds no file. A fresh session passes both."""
    shared = tmp_path_factory.mktemp("outside") / "spool.txt"
    monkeypatch.setenv("SHARED_FILE", str(shared))
    write(pytester, **CONSUMED)
    args = ["--dist", "loadfile", "--det-sleep=real", "tests"] if n else ["--det-sleep=real", "tests"]
    fresh_run(pytester, n, *args).assert_outcomes(passed=2)
    for label in ("s1", "s2", "s3"):
        r, c = cache_run(pytester, n, label, *args)
        r.assert_outcomes(passed=2)
