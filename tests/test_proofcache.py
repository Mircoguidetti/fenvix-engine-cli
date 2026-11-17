"""Cache with proof (``--det-cache``): a result is reused only when every input it used is unchanged."""

import json
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


@pytest.fixture
def run_cache(pytester):
    counter = {"n": 0}

    def run(*args):
        counter["n"] += 1
        out = pytester.path / f"out{counter['n']}.json"
        r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.cachedir'}",
                                          f"--det-outcomes={out}", "-p", "no:cacheprovider", *args)
        data = json.loads(out.read_text()) if out.exists() else {}
        c = data.get("cache", {})
        return r, set(c.get("reused_ids", ())), data

    return run


def ids(*names, mod="test_m.py"):
    return {f"{mod}::{n}" for n in names}


def project(pytester, **files):
    pytester.makeini("[pytest]\n")
    pytester.mkpydir("pkg")
    for name, text in files.items():
        p = pytester.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        import textwrap
        p.write_text(textwrap.dedent(text))


MOD = """
LIMIT = 10

def f(x):
    return x + 1

def g(x):
    return x * 2
"""

TESTS = """
from pkg import mod

def test_f():
    assert mod.f(1) == 2

def test_g():
    assert mod.g(2) == 4

def test_limit():
    assert mod.LIMIT == 10
"""


def test_unchanged_suite_is_reused_with_a_receipt(pytester, run_cache):
    project(pytester, **{"pkg/mod.py": MOD, "test_m.py": TESTS})
    r, reused, _ = run_cache()
    r.assert_outcomes(passed=3)
    assert reused == set()
    r, reused, data = run_cache("-v")
    r.assert_outcomes(passed=3)
    assert reused == ids("test_f", "test_g", "test_limit")
    r.stdout.fnmatch_lines(["*reused 3 result(s) with proof, ran 0*", "REUSED test_m.py::test_f key=*"])
    receipts = [json.loads(line) for line in (pytester.path / ".cachedir" / "receipts.jsonl").read_text().splitlines()]
    f = next(x for x in receipts if x["nodeid"] == "test_m.py::test_f")
    assert f["reused"] and len(f["key"]) == 32 and f["n_units"] >= 2 and f["n_skeleton"] >= 1


def test_function_change_reruns_only_the_tests_that_executed_it(pytester, run_cache):
    project(pytester, **{"pkg/mod.py": MOD, "test_m.py": TESTS})
    run_cache()
    (pytester.path / "pkg/mod.py").write_text(MOD.replace("return x * 2", "return 2 * x"))
    r, reused, data = run_cache()
    assert reused == ids("test_f", "test_limit")
    assert data["cache"]["miss_ids"]["test_m.py::test_g"].startswith("code: pkg/mod.py::g")


def test_comment_and_formatting_changes_keep_the_results(pytester, run_cache):
    project(pytester, **{"pkg/mod.py": MOD, "test_m.py": TESTS})
    run_cache()
    (pytester.path / "pkg/mod.py").write_text(MOD.replace("return x * 2", "return x*2  # doubled"))
    _, reused, _ = run_cache()
    assert reused == ids("test_f", "test_g", "test_limit")


def test_module_level_change_reruns_every_test_that_had_the_module_loaded(pytester, run_cache):
    # test_limit reads a constant: no line of mod.py runs during the test (the pygments 7c196150 case)
    project(pytester, **{"pkg/mod.py": MOD, "test_m.py": TESTS})
    run_cache()
    (pytester.path / "pkg/mod.py").write_text(MOD.replace("LIMIT = 10", "LIMIT = 11"))
    r, reused, _ = run_cache()
    assert reused == set()
    r.assert_outcomes(passed=2, failed=1)


def test_function_run_at_import_time_is_an_input_of_every_reader(pytester, run_cache):
    # TABLE is built by helpers.build() while test_a imports pkg.table; test_b only reads it
    project(pytester, **{
        "pkg/helpers.py": "def build():\n    return [1, 2, 3]\n",
        "pkg/table.py": "from pkg import helpers\nTABLE = helpers.build()\n",
        "test_m.py": """
            def test_a():
                from pkg import table
                assert len(table.TABLE) == 3

            def test_b():
                import pkg.table
                assert pkg.table.TABLE[0] == 1
            """,
    })
    run_cache()
    _, reused, _ = run_cache()
    assert reused == ids("test_a", "test_b")
    (pytester.path / "pkg/helpers.py").write_text("def build():\n    return [0, 2, 3]\n")
    r, reused, _ = run_cache()
    assert reused == set()
    r.assert_outcomes(passed=1, failed=1)


def test_data_file_change_reruns_its_reader(pytester, run_cache):
    project(pytester, **{"test_m.py": """
        import os
        HERE = os.path.dirname(__file__)

        def test_data():
            with open(os.path.join(HERE, "data.txt")) as fh:
                assert fh.read() == "hello"

        def test_other():
            assert True
        """, "data.txt": "hello"})
    run_cache()
    (pytester.path / "data.txt").write_text("world")
    r, reused, data = run_cache()
    assert reused == ids("test_other")
    assert data["cache"]["miss_ids"]["test_m.py::test_data"].startswith("data: data.txt")
    r.assert_outcomes(passed=1, failed=1)


def test_import_time_read_of_a_test_module_serves_only_its_own_tests(pytester, run_cache):
    # test_a.py reads version.txt while it is imported; test_b.py does not import test_a
    project(pytester, **{
        "pkg/lib.py": "import os\nHERE = os.path.dirname(__file__)\n"
                      "def conf():\n    return open(os.path.join(HERE, 'conf.txt')).read()\nCONF = conf()\n",
        "pkg/conf.txt": "1",
        "version.txt": "1.0",
        "test_a.py": """
            import os
            VERSION = open(os.path.join(os.path.dirname(__file__), "version.txt")).read()

            def test_version():
                assert VERSION == "1.0"
            """,
        "test_b.py": """
            from pkg import lib

            def test_b():
                assert lib.CONF == "1"
            """,
    })
    run_cache()
    _, reused, _ = run_cache()
    assert reused == ids("test_version", mod="test_a.py") | ids("test_b", mod="test_b.py")
    (pytester.path / "version.txt").write_text("2.0")
    r, reused, data = run_cache()
    assert reused == ids("test_b", mod="test_b.py")
    assert data["cache"]["miss_ids"]["test_a.py::test_version"].startswith("data: version.txt")
    r.assert_outcomes(passed=1, failed=1)
    # a repository module's import-time read stays an input of every test
    (pytester.path / "version.txt").write_text("1.0")
    run_cache()
    (pytester.path / "pkg/conf.txt").write_text("2")
    r, reused, _ = run_cache()
    assert reused == set()
    r.assert_outcomes(passed=1, failed=1)


def test_read_write_open_is_an_input(pytester, run_cache):
    # review R-002 error 1: a fixture opened read-write (sqlite, "r+") was dropped from the inputs
    import sqlite3

    db = pytester.path / "fixture.db"
    con = sqlite3.connect(db)
    con.execute("create table t (v integer)")
    con.execute("insert into t values (1)")
    con.commit()
    con.close()
    project(pytester, **{"test_m.py": """
        import os, sqlite3
        HERE = os.path.dirname(__file__)

        def test_sqlite():
            con = sqlite3.connect(os.path.join(HERE, "fixture.db"))
            assert con.execute("select v from t").fetchone() == (1,)
            con.close()

        def test_rplus():
            with open(os.path.join(HERE, "counter.txt"), "r+") as fh:
                assert fh.read() == "1"
        """, "counter.txt": "1"})
    run_cache()
    _, reused, _ = run_cache()
    assert reused == ids("test_sqlite", "test_rplus")
    con = sqlite3.connect(db)
    con.execute("update t set v = 2")
    con.commit()
    con.close()
    (pytester.path / "counter.txt").write_text("2")
    r, reused, _ = run_cache()
    assert reused == set()
    r.assert_outcomes(failed=2)


def test_environment_variable_read_is_an_input_and_unread_ones_are_not(pytester, run_cache, monkeypatch):
    # review R-002 error 2
    project(pytester, **{"test_m.py": """
        import os

        def test_flag():
            assert os.environ.get("DETPY_T_FLAG", "0") == "0"

        def test_other():
            assert True
        """})
    monkeypatch.delenv("DETPY_T_FLAG", raising=False)
    run_cache()
    monkeypatch.setenv("DETPY_T_UNREAD", "x")
    _, reused, _ = run_cache()
    assert reused == ids("test_flag", "test_other")
    monkeypatch.setenv("DETPY_T_FLAG", "1")
    r, reused, data = run_cache()
    assert reused == ids("test_other")
    assert data["cache"]["miss_ids"]["test_m.py::test_flag"] == "env: environment variable DETPY_T_FLAG"
    r.assert_outcomes(passed=1, failed=1)


def test_runtime_identity_change_reruns_everything(pytester, run_cache):
    # review R-002 note N2: the installed distributions are part of the runtime identity
    project(pytester, **{"test_m.py": "def test_a():\n    assert True\n"})
    run_cache()
    d = pytester.path / "detpy_fake_dist-1.0.dist-info"
    d.mkdir()
    (d / "METADATA").write_text("Metadata-Version: 2.1\nName: detpy-fake-dist\nVersion: 1.0\n")
    (d / "RECORD").write_text("")
    _, reused, data = run_cache()
    assert reused == set()
    assert data["cache"]["miss_ids"]["test_m.py::test_a"].startswith("runtime:")


def test_cached_failure_is_never_reused(pytester, run_cache):
    # review R-002 note N4
    project(pytester, **{"test_m.py": "def test_bad():\n    assert False\n\ndef test_good():\n    pass\n"})
    run_cache()
    r, reused, data = run_cache()
    assert reused == ids("test_good")
    r.assert_outcomes(passed=1, failed=1)
    assert data["cache"]["miss_ids"]["test_m.py::test_bad"].startswith("new")


def test_network_connection_and_subprocess_are_never_cached(pytester, run_cache, outside_server):
    # review R-002 error 3: a test that reaches a service it did not start (here on loopback) cannot be proven.
    # Step 1 narrowed two rules, each with its own tests: a connection to a server this very process listens on is
    # in-process computation (test_own_loopback_server_* in test_proofcache_follow.py), and a subprocess is
    # followed (its program, files and environment become inputs) unless --det-cache-no-follow.
    project(pytester, **{"test_m.py": f"""
        import socket, subprocess, sys

        def test_loopback():
            c = socket.create_connection(("127.0.0.1", {outside_server}))
            c.close()

        def test_spawn():
            subprocess.run([sys.executable, "-c", "pass"], check=True)

        def test_plain():
            pass
        """})
    run_cache("--det-cache-no-follow")
    _, reused, data = run_cache("--det-cache-no-follow")
    assert reused == ids("test_plain")
    nc = data["cache"]["not_cached_ids"]
    assert nc["test_m.py::test_loopback"] == "network connection"
    assert nc["test_m.py::test_spawn"] == "subprocess"


@pytest.fixture
def outside_server():
    """A loopback HTTP server the tested process tree did not start (stands for a proxy or an external service)."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_external_service_through_a_loopback_proxy_is_never_cached(pytester, run_cache, monkeypatch,
                                                                    outside_server):
    # review R-002b: HTTP(S)_PROXY on loopback reaches the outside; "loopback only" proves nothing
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{outside_server}")
    monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{outside_server}")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    project(pytester, **{"test_m.py": """
        import urllib.request

        def test_external():
            with urllib.request.urlopen("http://service.example/", timeout=10) as r:
                assert r.read() == b"ok"

        def test_plain():
            pass
        """})
    # Level 0 treats the configured proxy as the outside and blocks it: the failure is never reused
    run_cache()
    r, reused, data = run_cache()
    r.assert_outcomes(passed=1, failed=1)
    assert reused == ids("test_plain")
    assert data["cache"]["not_cached_ids"]["test_m.py::test_external"] == "outcome failed"
    # without the proxy the same loopback port is "localhost" to Level 0 and the test passes, but a service the
    # test process tree did not start is outside too: a connection, loopback or not, is never cached
    for var in ("HTTP_PROXY", "http_proxy"):
        monkeypatch.delenv(var)
    (pytester.path / "test_m.py").write_text((pytester.path / "test_m.py").read_text().replace(
        "http://service.example/", f"http://127.0.0.1:{outside_server}/"))
    run_cache()
    r, reused, data = run_cache()
    r.assert_outcomes(passed=2)
    assert reused == ids("test_plain")
    assert data["cache"]["not_cached_ids"]["test_m.py::test_external"] == "network connection"


def test_name_lookup_and_c_level_sockets_are_never_cached(pytester, run_cache, outside_server):
    # a socket opened by a C extension raises no audit event: one still open when its test or fixture ends counts
    project(pytester, **{"test_m.py": f"""
        import ctypes, socket, struct

        import pytest

        KEEP = []

        def test_lookup():
            assert socket.getaddrinfo("localhost", 80)

        def test_numeric_address_is_not_a_lookup():
            assert socket.getaddrinfo("127.0.0.1", 80)

        @pytest.fixture(scope="module")
        def c_connection():
            libc = ctypes.CDLL(None, use_errno=True)
            fd = libc.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
            addr = struct.pack("=H", socket.AF_INET) + struct.pack(">H", {outside_server}) + bytes([127, 0, 0, 1]) + bytes(8)
            assert libc.connect(fd, addr, len(addr)) == 0, ctypes.get_errno()
            KEEP.append(fd)
            return fd

        def test_c_socket(c_connection):
            assert c_connection > 0

        def test_c_socket_again(c_connection):
            assert c_connection > 0
        """})
    run_cache()
    r, reused, data = run_cache()
    r.assert_outcomes(passed=4)
    assert reused == ids("test_numeric_address_is_not_a_lookup")
    nc = data["cache"]["not_cached_ids"]
    assert nc["test_m.py::test_lookup"] == "host name lookup"
    assert nc["test_m.py::test_c_socket"] == "network socket opened outside Python (C extension)"
    assert nc["test_m.py::test_c_socket_again"] == "network socket opened outside Python (C extension)"


@pytest.mark.skipif(not __import__("os").path.exists("/etc/ld.so.cache"), reason="needs ldconfig")
def test_find_library_at_import_time_is_not_a_subprocess(pytester, run_cache):
    # ctypes.util.find_library runs `ldconfig -p` (ifaddr, uuid, ... at import time): its input is the linker cache
    project(pytester, **{"test_m.py": """
        import ctypes.util

        LIBC = ctypes.util.find_library("c")

        def test_libc():
            assert LIBC
        """})
    run_cache()
    r, reused, data = run_cache()
    r.assert_outcomes(passed=1)
    assert reused == ids("test_libc")


def test_clock_reader_depends_on_the_epoch(pytester, run_cache):
    project(pytester, **{"test_m.py": """
        import time

        def test_clock():
            assert time.time() > 0

        def test_no_clock():
            pass
        """})
    run_cache("--det-epoch=2025-01-01T00:00:00")
    _, reused, _ = run_cache("--det-epoch=2025-01-01T00:00:00")
    assert reused == ids("test_clock", "test_no_clock")
    _, reused, data = run_cache("--det-epoch=2025-06-01T00:00:00")
    assert reused == ids("test_no_clock")
    assert data["cache"]["miss_ids"]["test_m.py::test_clock"].startswith("clock")


def test_os_entropy_is_cached_only_when_controlled(pytester, run_cache):
    project(pytester, **{"test_m.py": "import uuid\n\ndef test_uuid():\n    assert uuid.uuid4()\n"})
    run_cache()
    _, reused, data = run_cache()
    assert reused == set()
    assert data["cache"]["not_cached_ids"]["test_m.py::test_uuid"].startswith("os entropy")
    run_cache("--det-urandom")
    _, reused, _ = run_cache("--det-urandom")
    assert reused == ids("test_uuid")


def test_skip_and_xfail_are_reused_with_their_reports(pytester, run_cache):
    project(pytester, **{"test_m.py": """
        import pytest

        @pytest.mark.skip(reason="not here")
        def test_skip_mark():
            pass

        def test_skip_call():
            pytest.skip("inside")

        @pytest.mark.xfail(reason="known")
        def test_xfail():
            assert False
        """})
    r, _, _ = run_cache("-rsx")
    r.assert_outcomes(skipped=2, xfailed=1)
    r, reused, _ = run_cache("-rsx")
    assert reused == ids("test_skip_mark", "test_skip_call", "test_xfail")
    r.assert_outcomes(skipped=2, xfailed=1)
    r.stdout.fnmatch_lines(["*SKIPPED*not here*", "*SKIPPED*inside*", "*XFAIL*known*"])


def test_new_test_in_one_module_keeps_the_other_modules(pytester, run_cache):
    project(pytester, **{"test_a.py": "def test_a1():\n    pass\n", "test_b.py": "def test_b1():\n    pass\n"})
    run_cache()
    (pytester.path / "test_a.py").write_text("def test_a1():\n    pass\n\ndef test_a2():\n    pass\n")
    _, reused, _ = run_cache()
    assert reused == {"test_b.py::test_b1"}


def test_conftest_fixture_change_reruns_only_its_directory(pytester, run_cache):
    project(pytester, **{
        "sub1/conftest.py": "import pytest\n\n@pytest.fixture\ndef val():\n    return 1\n",
        "sub1/test_s1.py": "def test_s1(val):\n    assert val == 1\n",
        "sub2/conftest.py": "import pytest\n\n@pytest.fixture\ndef other():\n    return 2\n",
        "sub2/test_s2.py": "def test_s2(other):\n    assert other == 2\n",
    })
    run_cache()
    (pytester.path / "sub1/conftest.py").write_text(
        "import pytest\n\nX = 1\n\n@pytest.fixture\ndef val():\n    return 1\n")
    _, reused, _ = run_cache()
    assert reused == {"sub2/test_s2.py::test_s2"}
    # a new hook in a conftest can act on every test
    (pytester.path / "sub1/conftest.py").write_text(
        "import pytest\n\nX = 1\n\ndef pytest_runtest_setup(item):\n    pass\n\n"
        "@pytest.fixture\ndef val():\n    return 1\n")
    _, reused, _ = run_cache()
    assert reused == set()


def test_reading_a_file_another_test_wrote_is_not_cached(pytester, run_cache):
    project(pytester, **{"test_m.py": """
        import os
        P = os.path.join(os.path.dirname(__file__), "shared.txt")

        def test_writer():
            with open(P, "w") as fh:
                fh.write("x")

        def test_reader():
            with open(P) as fh:
                assert fh.read() == "x"
        """})
    run_cache()
    _, reused, data = run_cache()
    assert "test_m.py::test_reader" not in reused
    assert data["cache"]["not_cached_ids"]["test_m.py::test_reader"].startswith("reads a file another test")


def test_verify_runs_reusable_tests_and_compares(pytester, run_cache):
    project(pytester, **{"pkg/mod.py": MOD, "test_m.py": TESTS})
    run_cache()
    r, reused, data = run_cache("--det-cache-verify=1.0")
    assert reused == set()
    assert sorted(data["cache"]["verified_ids"]) == sorted(ids("test_f", "test_g", "test_limit"))
    assert data["cache"]["verify_mismatches"] == []
    r.stdout.fnmatch_lines(["*verified 3 reusable result(s) by running them: 0 mismatch(es)*"])


def test_det_cache_requires_det(pytester):
    pytester.makepyfile("def test_a():\n    pass\n")
    r = pytester.runpytest_subprocess(f"--det-cache={pytester.path / 'c'}")
    r.stderr.fnmatch_lines(["*--det-cache needs --det*"])


def test_refusal_names_the_program_and_the_context(pytester, run_cache):
    # step 1: a refusal says what caused it and where (r5: every home-assistant and pylint test was "subprocess")
    project(pytester, **{"pkg/spawner.py": """
        import subprocess, sys

        subprocess.run([sys.executable, "-c", "pass"], check=True)
        """, "test_m.py": """
        import pkg.spawner

        def test_a():
            pass
        """})
    _, _, data = run_cache("--det-cache-no-follow")  # followed by default since step 1
    c = data["cache"]
    assert c["not_cached_ids"]["test_m.py::test_a"] == "subprocess"
    where = c["not_cached_where"]["test_m.py::test_a"]
    assert where.startswith("python") and "pkg/spawner.py:4" in where and where.endswith("(import of pkg/spawner.py)")
    assert c["not_cached_detail"] == {f"subprocess: {where}": 1}
