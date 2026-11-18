"""Equivalence of the code paths moved to Rust (rust-hotpaths): the old Python path (kept verbatim in
``tests/rust_hotpaths_ref``) and the new Rust path give identical keys, entries, receipts and decisions on the same
inputs."""

import json
import os
import socket
import sys
import textwrap
from pathlib import Path

import pytest

REF = Path(__file__).parent / "rust_hotpaths_ref"
sys.path.insert(0, str(REF))
pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness" / "rust_hotpaths"))


# ---------------------------------------------------------------------------
# socket scan
@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="needs /proc")
def test_socket_scan_matches_reference():
    from _ref_record import ScanSocketsRef

    from detpy import _core

    ref, new = ScanSocketsRef(), _core.SocketScan()
    seq = []

    def step(what):
        a, b = ref.scan(), new.scan()
        seq.append((what, a, b))

    step("baseline")
    step("nothing new")
    held = []
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    held.append(srv)
    step("tcp listener")
    step("unchanged")
    a, b = socket.socketpair(socket.AF_UNIX)
    held += [a, b]
    step("unix pair")
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.bind(("127.0.0.1", 0))
    held.append(u)
    step("udp")
    c = socket.create_connection(srv.getsockname())
    s2, _ = srv.accept()
    held += [c, s2]
    step("tcp pair")
    for h in held:
        h.close()
    step("closed")
    if socket.has_ipv6:
        try:
            v6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            v6.bind(("::1", 0))
            v6.listen()
            step("tcp6")
            v6.close()
        except OSError:
            pass
    assert [x[1] for x in seq] == [x[2] for x in seq], seq
    assert dict((w, a) for w, a, _ in seq)["tcp listener"] is True
    assert dict((w, a) for w, a, _ in seq)["unix pair"] is False


# ---------------------------------------------------------------------------
# end-of-session recording
FILES = {
    "pytest.ini": "[pytest]\naddopts = --doctest-modules\n",
    "pkg/__init__.py": "",
    "pkg/mod.py": """
        import os
        HERE = os.path.dirname(__file__)
        with open(os.path.join(HERE, "table.txt")) as fh:  # import-time read
            TABLE = fh.read()

        def f(x):
            return x + 1

        def g(x):
            return x * 2

        def h(x):
            return [y for y in range(x)]
        """,
    "pkg/table.txt": "a b c\n",
    "pkg/doc.py": '''
        def twice(x):
            """
            >>> twice(2)
            4
            """
            return 2 * x
        ''',
    "pkg/tmpl.txt": "not python {{ x }}\n",
    "conftest.py": """
        import os
        import pytest

        def pytest_collection_modifyitems(items):
            pass

        @pytest.fixture(scope="module")
        def config_text():
            with open(os.path.join(os.path.dirname(__file__), "config.txt")) as fh:
                return fh.read() + os.environ.get("EQ_MODE", "-")
        """,
    "config.txt": "cfg\n",
    "data.txt": "data\n",
    "sub/__init__.py": "",
    "sub/conftest.py": """
        import pytest

        @pytest.fixture(scope="session")
        def sess():
            return 42
        """,
    "sub/test_sub.py": """
        import os
        from pkg import mod

        def test_sub_env(sess):
            assert os.environ.get("HOME") is not None and sess == 42

        def test_sub_mod():
            assert mod.h(3) == [0, 1, 2]
        """,
    "helpers_test.py": """
        def helper():
            return 7

        def test_helper_itself():
            assert helper() == 7
        """,
    "test_uses_helpers.py": """
        from helpers_test import helper

        def test_uses():
            assert helper() == 7
        """,
    "test_m.py": """
        import os
        import random
        import subprocess
        import time
        from pathlib import Path

        import pytest
        from pkg import mod

        HERE = Path(__file__).parent

        def test_f(config_text):
            assert mod.f(1) == 2 and config_text.startswith("cfg")

        def test_g():
            assert mod.g(2) == 4

        def test_table():
            assert mod.TABLE.startswith("a")

        def test_reads_data():
            assert (HERE / "data.txt").read_text().startswith("data")

        def test_missing_and_listing():
            assert not (HERE / "nope.txt").exists()
            try:
                open(HERE / "nope.txt")
            except FileNotFoundError:
                pass
            assert "test_m.py" in os.listdir(HERE)

        def test_env_one():
            assert os.environ.get("EQ_VAR", "x") in ("x", "y")

        def test_env_all():
            assert len(dict(os.environ)) > 0

        def test_clock():
            assert time.time() > 0

        def test_random():
            assert 0 <= random.random() < 1

        def test_writer():
            (HERE / "out.txt").write_text("w")
            if (HERE / "write_data.flag").exists():
                (HERE / "data.txt").write_text("data written\\n")

        def test_reader_of_written():
            p = HERE / "out.txt"
            assert not p.exists() or p.read_text() == "w"

        def test_spawn():
            subprocess.run(["true"], check=True)

        def test_fail():
            assert mod.f(0) == 2

        @pytest.mark.skip(reason="no")
        def test_skip():
            pass

        @pytest.mark.xfail(reason="known")
        def test_xfail():
            assert False

        def test_dns():
            import socket
            try:
                socket.getaddrinfo("localhost", 80)
            except Exception:
                pass

        def test_proc():
            assert open("/proc/self/stat").read()

        def test_template():
            assert (HERE / "pkg" / "tmpl.txt").read_text().startswith("not")
        """,
}


def _write(root: Path, files: dict) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def test_record_session_matches_reference(pytester, monkeypatch):
    import canon

    _write(pytester.path, FILES)
    eq = pytester.path / "eq.jsonl"
    monkeypatch.setenv("DETPY_EQ_OUT", str(eq))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(REF), os.environ.get("PYTHONPATH", "")]))
    monkeypatch.setenv("EQ_MODE", "a")
    cache = pytester.path / ".cachedir"

    def run(*extra):
        r = pytester.runpytest_subprocess("--det", f"--det-cache={cache}", "-p", "no:cacheprovider", "-p",
                                          "_eqplugin", *extra)
        line = eq.read_text().splitlines()[-1]
        return r, json.loads(line)

    def check(d):
        assert d["ref"] == d["new"]
        a = canon.canon(os.path.join(d["ref_dir"], "proof-cache.json"))
        b = canon.canon(os.path.join(d["dir"], "proof-cache.json"))
        assert canon.diff(a, b) == []
        return a

    # 1: everything new
    r, d = run()
    st = check(d)
    nc = d["new"]["not_cached"]
    assert "test_m.py::test_spawn" in st["tests"] or nc["test_m.py::test_spawn"].startswith("subprocess")
    assert nc["test_m.py::test_fail"] == "outcome failed"
    assert nc["test_m.py::test_dns"] == "host name lookup" and "test_m.py::test_dns" in d["new"]["where"]
    assert nc["test_m.py::test_proc"] == "reads /proc, /sys or /dev"
    assert "test_m.py::test_reads_data" in st["tests"] and "test_m.py::test_clock" in st["tests"]
    assert st["tests"]["test_m.py::test_clock"]["epoch"] is not None
    assert any(n.startswith("pkg/doc.py::") for n in st["tests"])
    # 2: unchanged: reused (receipts), nothing recorded except failures and the not cacheable
    r, d = run()
    check(d)
    # 3: a function changes, an env var changes, a test now writes an input of a reused test (stale reuse)
    _write(pytester.path, {"pkg/mod.py": FILES["pkg/mod.py"].replace("x * 2", "2 * x"),
                           "write_data.flag": "1\n"})
    (pytester.path / "test_m.py").write_text(
        (pytester.path / "test_m.py").read_text().replace('(HERE / "out.txt").write_text("w")',
                                                         'out = HERE / "out.txt"; out.write_text("w")'))
    monkeypatch.setenv("EQ_MODE", "b")
    r, d = run()
    check(d)
    assert "test_m.py::test_reads_data" in d["new"]["stale"]
    # 4: after the writes
    r, d = run()
    check(d)
    assert any("another test or fixture wrote" in w for w in d["new"]["not_cached"].values())


def test_record_session_rust_unit_ranges_match_file_facts(tmp_path):
    """``unit_ranges`` (Rust) returns what the old path read from ``file_facts`` one file at a time."""
    from detpy import _core

    st = _core.ProofCache(str(tmp_path), str(tmp_path))
    a = st.add_file("a.py", "c1", "s1", "h1", [("f", 2, 4, "d1"), ("g", 6, 9, "d2")], [])
    b = st.add_file("b.txt", "c2", "c2", "h2", [], [])
    ixs = [a, None, b]
    want = [[] if ix is None else [(x, y) for _, x, y, _ in st.file_facts(ix)[4]] for ix in ixs]
    assert st.unit_ranges(ixs) == want == [[(2, 4), (6, 9)], [], []]



# ---------------------------------------------------------------------------
# followed children: a log whose tracer is gone is final
@pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="needs /proc")
def test_tracer_prefixes_lists_live_log_writers_only(tmp_path):
    import subprocess

    from detpy import _core

    logdir = str(tmp_path) + os.sep
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "-o", logdir + "s1-1", "x"])
    q = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "-o", "/elsewhere/s1-2"])
    try:
        for _ in range(200):
            got = _core.tracer_prefixes(logdir)
            if got:
                break
        assert got == [logdir + "s1-1"]
    finally:
        p.kill()
        q.kill()
        p.wait()
        q.wait()
    assert _core.tracer_prefixes(logdir) == []
