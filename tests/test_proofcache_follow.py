"""Cache with proof, step 1: child processes are followed (their inputs become the test's inputs), a test's own
loopback server is not the network, and the virtual clock's epoch is a stable configuration input."""

import json
import os
import shutil
import subprocess
import sys

import pytest

from test_proofcache import ids, outside_server, project, run_cache  # noqa: F401 (fixtures)

pytestmark = [
    pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring"),
    pytest.mark.skipif(shutil.which("strace") is None, reason="following needs strace"),
]


def nc(data):
    return data["cache"].get("not_cached_ids", {})


def miss(data):
    return data["cache"].get("miss_ids", {})


# ---------------------------------------------------------------------------------------------------------------
# following child processes


def test_child_file_read_is_an_input(pytester, run_cache):
    project(pytester, **{"data.txt": "hello\n", "test_m.py": """
        import subprocess

        def test_cat():
            out = subprocess.run(["cat", "data.txt"], capture_output=True, text=True, check=True).stdout
            assert out == "hello\\n"

        def test_plain():
            pass
        """})
    run_cache()
    r, reused, data = run_cache()
    r.assert_outcomes(passed=2)
    assert reused == ids("test_cat", "test_plain")
    # the child read data.txt: changing it reruns the test (and here the fresh run fails)
    (pytester.path / "data.txt").write_text("changed\n")
    r, reused, data = run_cache()
    assert reused == ids("test_plain")
    assert miss(data)["test_m.py::test_cat"].startswith("data")
    r.assert_outcomes(passed=1, failed=1)
    # a failure is never reused, even with every input unchanged
    r, reused, data = run_cache()
    assert reused == ids("test_plain")
    r.assert_outcomes(passed=1, failed=1)


def test_child_python_module_is_an_input(pytester, run_cache):
    # a Python child imports a repository module: the module's file is an input of the test that started it
    project(pytester, **{"pkg/helper.py": "X = 1\n", "test_m.py": """
        import subprocess, sys

        def test_child():
            out = subprocess.run([sys.executable, "-c", "import pkg.helper as h; print(h.X)"],
                                 capture_output=True, text=True)
            assert out.stdout.strip() == "1", out.stderr
        """})
    run_cache()
    _, reused, _ = run_cache()
    assert reused == ids("test_child")
    (pytester.path / "pkg" / "helper.py").write_text("X = 2\n")
    r, reused, data = run_cache()
    assert reused == set()
    assert miss(data)["test_m.py::test_child"].startswith("data")
    r.assert_outcomes(failed=1)


def test_child_program_is_an_input(pytester, run_cache):
    # the executable itself (found on PATH) is an input; the PATH entries searched before it are inputs too
    tool = pytester.path / "bin" / "tool"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\necho one\n")
    tool.chmod(0o755)
    project(pytester, **{"test_m.py": f"""
        import os, subprocess

        def test_tool():
            env = dict(os.environ, PATH="{tool.parent}" + os.pathsep + os.environ["PATH"])
            assert subprocess.run(["tool"], env=env, capture_output=True, text=True).stdout == "one\\n"
        """})
    run_cache()
    _, reused, _ = run_cache()
    assert reused == ids("test_tool")
    tool.write_text("#!/bin/sh\necho two\n")
    r, reused, data = run_cache()
    assert reused == set()
    assert miss(data)["test_m.py::test_tool"].startswith("data")
    r.assert_outcomes(failed=1)


def test_child_inheriting_the_environment_depends_on_all_of_it(pytester, run_cache, monkeypatch):
    # a child's getenv is invisible: when it inherits the environment, every variable is an input; an explicit
    # env= built from recorded reads adds only those reads
    monkeypatch.setenv("DETPY_T_A", "1")
    project(pytester, **{"test_m.py": """
        import os, subprocess

        def test_inherits():
            assert subprocess.run(["sh", "-c", "exit 0"]).returncode == 0

        def test_explicit_env():
            assert subprocess.run(["sh", "-c", "exit 0"], env={"PATH": os.environ["PATH"]}).returncode == 0
        """})
    run_cache()
    _, reused, _ = run_cache()
    assert reused == ids("test_inherits", "test_explicit_env")
    monkeypatch.setenv("DETPY_T_A", "2")
    _, reused, data = run_cache()
    assert reused == ids("test_explicit_env")
    assert miss(data)["test_m.py::test_inherits"].startswith("env")


def test_child_network_is_never_cached(pytester, run_cache, outside_server):
    # a child that connects anywhere (a loopback service another process runs, here) is never cached
    project(pytester, **{"test_m.py": f"""
        import subprocess, sys

        CODE = "import socket; socket.create_connection(('127.0.0.1', {outside_server})).close()"

        def test_child_connects():
            subprocess.run([sys.executable, "-c", CODE], check=True)

        def test_plain():
            pass
        """})
    run_cache()
    _, reused, data = run_cache()
    assert reused == ids("test_plain")
    assert nc(data)["test_m.py::test_child_connects"] == "subprocess"
    assert "[network: connect AF_INET]" in data["cache"]["not_cached_where"]["test_m.py::test_child_connects"]


def _loopback_alias():
    """A host name other than localhost that /etc/hosts maps to a loopback address (127.0.1.1 on Debian)."""
    try:
        lines = open("/etc/hosts").read().splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 2 and parts[0].startswith("127."):
            for name in parts[1:]:
                if name not in ("localhost", "localhost.localdomain"):
                    return name
    return None


@pytest.mark.skipif(shutil.which("curl") is None, reason="needs curl")
def test_child_through_a_proxy_named_by_a_loopback_hostname_is_never_cached(pytester, run_cache, monkeypatch,
                                                                             outside_server):
    # review R-002c: HTTPS_PROXY=http://<a name that resolves to loopback>:<port>; the child (curl) reaches the
    # outside through it. Every connect of a child, loopback included, is network: the name does not matter.
    name = _loopback_alias() or "localhost"
    monkeypatch.setenv("http_proxy", f"http://{name}:{outside_server}")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    project(pytester, **{"test_m.py": """
        import subprocess

        def test_curl():
            out = subprocess.run(["curl", "-s", "http://service.example/"], capture_output=True, text=True)
            assert out.stdout == "ok"
        """})
    run_cache()
    r, reused, data = run_cache()
    r.assert_outcomes(passed=1)
    assert reused == set()
    assert nc(data)["test_m.py::test_curl"] == "subprocess"
    assert "[network:" in data["cache"]["not_cached_where"]["test_m.py::test_curl"]


def test_child_still_running_at_the_end_is_never_cached(pytester, run_cache):
    project(pytester, **{"test_m.py": """
        import subprocess

        KEEP = []

        def test_daemon():
            KEEP.append(subprocess.Popen(["sleep", "30"]))

        def test_plain():
            pass
        """})
    run_cache()
    _, reused, data = run_cache()
    assert reused == ids("test_plain")
    assert "still running" in data["cache"]["not_cached_where"]["test_m.py::test_daemon"]


def test_child_reading_proc_is_never_cached(pytester, run_cache):
    # /proc of other processes (ps, a pid file of a service) is the machine's state, not a file
    project(pytester, **{"test_m.py": """
        import subprocess

        def test_uptime():
            subprocess.run(["cat", "/proc/uptime"], capture_output=True, check=True)
        """})
    run_cache()
    _, reused, data = run_cache()
    assert reused == set()
    assert "[reads /proc/uptime]" in data["cache"]["not_cached_where"]["test_m.py::test_uptime"]


def test_file_a_child_wrote_is_not_an_input_of_another_test(pytester, run_cache):
    # a later test that reads what another test's child wrote is not cached (the writer is not credited to it)
    project(pytester, **{"test_m.py": """
        import subprocess

        def test_a_writer():
            subprocess.run(["sh", "-c", "echo x > shared.txt"], check=True)

        def test_b_reader():
            assert open("shared.txt").read() == "x\\n"
        """})
    run_cache()
    _, reused, data = run_cache()
    assert "test_m.py::test_b_reader" not in reused
    assert nc(data)["test_m.py::test_b_reader"].startswith("reads a file another test or fixture wrote")


def test_child_own_temporary_files_are_not_inputs(pytester, run_cache):
    # files the child's process tree itself wrote first (a compiler's temporary objects) are internal
    project(pytester, **{"test_m.py": """
        import subprocess

        def test_tmp():
            subprocess.run(["sh", "-c", "d=$(mktemp -d) && echo 1 > $d/f && cat $d/f && rm -r $d"], check=True,
                           capture_output=True)
        """})
    run_cache()
    _, reused, _ = run_cache()
    assert reused == ids("test_tmp")


@pytest.mark.skipif(shutil.which("gcc") is None, reason="needs gcc")
def test_find_library_compiler_fallback_at_import_time_is_followed(pytester, run_cache):
    # r5's cause on pylint (pyenchant) and home-assistant (turbojpeg): a library missing from the linker cache makes
    # ctypes.util.find_library run gcc and ld at import time; a spawn there used to refuse every test
    project(pytester, **{"pkg/lib.py": """
        import ctypes.util

        FOUND = ctypes.util.find_library("detpy_no_such_library_42")
        """, "test_m.py": """
        import pkg.lib

        def test_a():
            assert pkg.lib.FOUND is None
        """})
    _, _, data = run_cache()
    assert data["cache"]["children"] >= 1
    r, reused, data = run_cache()
    r.assert_outcomes(passed=1)
    assert reused == ids("test_a")


def test_no_follow_and_missing_strace_refuse_with_the_reason(pytester, run_cache, monkeypatch):
    project(pytester, **{"test_m.py": """
        import subprocess

        def test_spawn():
            subprocess.run(["true"], check=True)
        """})
    _, _, data = run_cache("--det-cache-no-follow")
    assert nc(data)["test_m.py::test_spawn"] == "subprocess"
    # strace not on PATH: the child runs normally, the test is not cached and the reason says why
    bindir = pytester.path / "onlytrue"
    bindir.mkdir()
    os.symlink(shutil.which("true"), bindir / "true")
    monkeypatch.setenv("PATH", str(bindir))
    r, _, data = run_cache()
    r.assert_outcomes(passed=1)
    assert nc(data)["test_m.py::test_spawn"] == "subprocess"
    assert "not followed: strace not found" in data["cache"]["not_cached_where"]["test_m.py::test_spawn"]


def test_spawn_through_multiprocessing_is_followed_or_refused(pytester, run_cache):
    # multiprocessing's spawn starter calls fork_exec without a subprocess audit event; its children are followed
    # (the resource tracker outlives the test, so the test is refused: never reused with an unrecorded input)
    project(pytester, **{"pkg/work.py": "def f(x):\n    return x + 1\n", "test_m.py": """
        import multiprocessing as mp
        from pkg.work import f

        def test_pool():
            with mp.get_context("spawn").Pool(1) as p:
                assert p.map(f, [1]) == [2]
        """})
    run_cache()
    r, reused, data = run_cache()
    r.assert_outcomes(passed=1)
    if reused:
        (pytester.path / "pkg" / "work.py").write_text("def f(x):\n    return x + 2\n")
        r, reused, data = run_cache()
        assert reused == set()
    else:
        assert "test_m.py::test_pool" in nc(data)


# ---------------------------------------------------------------------------------------------------------------
# a server this very process listens on


def test_own_loopback_server_is_not_the_network(pytester, run_cache):
    project(pytester, **{"test_m.py": """
        import socket

        def test_own_server():
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            c = socket.create_connection(srv.getsockname())
            s, _ = srv.accept()
            c.sendall(b"x")
            assert s.recv(1) == b"x"
            for x in (c, s, srv):
                x.close()

        def test_own_server_any_address():
            srv = socket.socket()
            srv.bind(("0.0.0.0", 0))
            srv.listen(1)
            c = socket.create_connection(("127.0.0.1", srv.getsockname()[1]))
            c.close()
            srv.close()
        """})
    run_cache()
    _, reused, _ = run_cache()
    assert reused == ids("test_own_server", "test_own_server_any_address")


def test_loopback_port_of_another_process_is_the_network(pytester, run_cache, outside_server):
    # a proxy or a service on loopback that the test process did not start (review R-002b)
    project(pytester, **{"test_m.py": f"""
        import socket

        def test_other():
            socket.create_connection(("127.0.0.1", {outside_server})).close()
        """})
    run_cache()
    _, reused, data = run_cache()
    assert reused == set()
    assert nc(data)["test_m.py::test_other"] == "network connection"


# ---------------------------------------------------------------------------------------------------------------
# the virtual clock's epoch under --det-cache


def _git(path, *args, date=None):
    env = dict(os.environ)
    if date:
        env.update(GIT_COMMITTER_DATE=date, GIT_AUTHOR_DATE=date)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=path, env=env, check=True,
                   capture_output=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_cache_epoch_is_kept_across_commits_within_the_window(pytester, run_cache):
    # structlog in r5: a clock read at import time made every test depend on the epoch, and --det-epoch=auto (the
    # HEAD commit time) moved at every commit, so nothing was ever reused across commits
    project(pytester, **{"pkg/stamp.py": "import time\n\nSTAMP = time.time()\n", "test_m.py": """
        import json, time
        from pkg import stamp

        def test_reads_import_stamp():
            assert stamp.STAMP > 0

        def test_now_is_the_cache_epoch():
            epoch = json.load(open(".cachedir/epoch.json"))["epoch_ns"] / 1e9
            assert abs(time.time() - epoch) < 1
        """, "other.txt": "1\n"})
    p = pytester.path
    _git(p, "init", "-q")
    _git(p, "add", "-A")
    _git(p, "commit", "-qm", "c1", date="2026-01-01T00:00:00Z")
    r, _, _ = run_cache()
    r.assert_outcomes(passed=2)
    (p / "other.txt").write_text("2\n")
    _git(p, "commit", "-qam", "c2", date="2026-01-10T00:00:00Z")
    r, reused, data = run_cache()
    assert reused == ids("test_reads_import_stamp", "test_now_is_the_cache_epoch")
    # the epoch is a configuration input: past the window it moves to the HEAD commit time and the readers rerun
    (p / "other.txt").write_text("3\n")
    _git(p, "commit", "-qam", "c3", date="2026-03-01T00:00:00Z")
    r, reused, data = run_cache()
    r.assert_outcomes(passed=2)
    assert reused == set()
    assert miss(data)["test_m.py::test_reads_import_stamp"].startswith("clock")
    assert json.load(open(p / ".cachedir" / "epoch.json"))["epoch_ns"] == 1772323200 * 10**9
    # an explicit --det-epoch is used as given
    r, reused, data = run_cache("--det-epoch=2026-03-01T00:00:00")
    assert reused == ids("test_reads_import_stamp", "test_now_is_the_cache_epoch")


def test_write_on_a_connection_between_two_own_sockets_is_not_the_network(pytester, run_cache, outside_server):
    # aiohttp writes with sendmsg(buffers) on the connected socket: no new destination
    project(pytester, **{"test_m.py": f"""
        import socket

        def test_own():
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            c = socket.create_connection(srv.getsockname())
            s, _ = srv.accept()
            s.sendmsg([b"hi"])
            c.sendmsg([b"yo"])
            assert c.recv(2) == b"hi" and s.recv(2) == b"yo"
            for x in (c, s, srv):
                x.close()

        def test_unix_pair():
            a, b = socket.socketpair()
            a.sendmsg([b"x"])
            assert b.recv(1) == b"x"
        """})
    run_cache()
    _, reused, data = run_cache()
    assert reused == ids("test_own")
    # a socketpair's peer is not a TCP address: still refused (conservative)
    assert nc(data)["test_m.py::test_unix_pair"] == "network connection"


def test_device_listing_is_an_input_and_device_content_is_refused(pytester, run_cache):
    # home-assistant's usb watcher walks /dev/bus/usb: a listing (or its absence) is an input like any directory;
    # reading a pseudo-file's content (process or kernel state) is never cached
    project(pytester, **{"test_m.py": """
        import os

        def test_list_dev():
            os.listdir("/dev")

        def test_missing_dev_dir():
            assert not os.path.exists("/dev/detpy-no-such-dir") or True
            try:
                os.listdir("/dev/detpy-no-such-dir")
            except FileNotFoundError:
                pass

        def test_read_proc_content():
            open("/proc/uptime").read()
        """})
    run_cache()
    _, reused, data = run_cache()
    assert "test_m.py::test_read_proc_content" not in reused
    assert nc(data)["test_m.py::test_read_proc_content"] == "reads /proc, /sys or /dev"
    assert reused >= ids("test_missing_dev_dir")
    # /dev's listing is reused only while it is the same (a device appearing reruns the test)
    assert "test_m.py::test_list_dev" in reused or miss(data)["test_m.py::test_list_dev"].startswith("data")


# ---------------------------------------------------------------------------------------------------------------
# cold-run cost: memoised distribution identity, facts computed in worker processes


def test_distribution_identity_memo_follows_every_change(tmp_path, monkeypatch):
    from detpy import proofcache

    site = tmp_path / "site"
    di = site / "fakedist-1.0.dist-info"
    di.mkdir(parents=True)
    (di / "METADATA").write_text("Metadata-Version: 2.1\nName: fakedist\nVersion: 1.0\n")
    (di / "RECORD").write_text("fakedist/__init__.py,sha256=aaa,1\n")
    monkeypatch.syspath_prepend(str(site))
    memo = str(tmp_path / "memo.json")

    def part():
        parts, _ = proofcache._dist_infos(str(tmp_path / "proj"), memo)
        return next(p for p in parts if p.startswith("fakedist=="))

    first = part()
    assert part() == first and os.path.exists(memo)  # second call served by the memo
    assert first in proofcache._dist_infos(str(tmp_path / "proj"))[0]  # the same as without a memo
    # a reinstall rewrites RECORD (same size here): the memo entry no longer matches and the digest changes
    (di / "RECORD").write_text("fakedist/__init__.py,sha256=bbb,1\n")
    assert part() != first
    (di / "METADATA").write_text("Metadata-Version: 2.1\nName: fakedist\nVersion: 2.0\n")
    assert part().startswith("fakedist==2.0:")


def test_facts_in_worker_processes_equal_facts_in_process(tmp_path):
    from detpy import _codefacts

    jobs = []
    for k in range(80):
        p = tmp_path / f"m{k}.py"
        p.write_text(f"import os\nfrom . import sib\n\nX = {k}\n\nclass C:\n    def f(self):\n        return {k}\n\n"
                     f"def g():\n    '''doc'''\n    return X\n")
        jobs.append((str(p), f"digest{k}", f"pkg.m{k}", False))
    jobs.append((str(tmp_path / "missing.py"), "d", None, False))
    (tmp_path / "bad.py").write_text("def (:\n")
    jobs.append((str(tmp_path / "bad.py"), "bad", None, False))
    serial = [_codefacts.read_facts(*j) for j in jobs]
    parallel = _codefacts.read_many(jobs, str(tmp_path / "w"), min_parallel=2)
    assert parallel == serial
    assert not [f for f in os.listdir(tmp_path / "w")]


@pytest.mark.skipif(not hasattr(os, "O_TMPFILE"), reason="needs O_TMPFILE")
def test_unnamed_temporary_file_is_not_a_write_of_its_directory(pytester, run_cache):
    # tempfile opens the temp directory itself with O_TMPFILE (pylint's tests, and ctypes.util.find_library's
    # compiler fallback): taken as a write of /tmp it refused every other test that read /tmp
    project(pytester, **{"test_m.py": """
        import os

        def test_a_unnamed_tmp():
            fd = os.open("scratch", os.O_TMPFILE | os.O_RDWR)
            os.write(fd, b"x")
            os.close(fd)

        def test_b_reads_tmp():
            os.listdir("scratch")
        """})
    (pytester.path / "scratch").mkdir()
    run_cache()
    _, reused, data = run_cache()
    assert "test_m.py::test_b_reads_tmp" not in nc(data)
