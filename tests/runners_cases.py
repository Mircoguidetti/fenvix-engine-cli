"""The adversarial wrong-reuse cases shared by every runner's tests (``test_runners_<runner>.py``).

Each case: a test that passes, recorded with ``--det-cache``; then ONE input changes (a file's content or metadata,
a listing, an existence, a module appearing, an environment variable, the time zone, ...); the second run must not
reuse the old result: the test re-runs and (``expect="failed"``) now fails. ``expect="rerun"``: the test is never
reused (a socket, a real clock read in C), whatever its outcome. The cases translate the reviews' holes to every
runner: R-009 (child processes, /dev/shm, TZ read by C, real clock outside the virtual clock, .git reads, sqlite
schema clock, O_EXCL creates, interpreter shutdown, file timestamps), R-017 (sqlite ``file:`` URIs, non-UTF-8
environment names), R-021 (stat metadata beyond kind, recursive listings, failed resolution of an optional module,
reads through infrastructure).

A runner's test module wraps ``body`` in its own kind of test (``wrap``) with ``prelude`` at module level.
"""

from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

PRELUDE = "import os, sys, time, pathlib, subprocess, socket, sqlite3\n"


def _write(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text)


def _symlink(root: Path, name: str, target: str) -> None:
    p = root / name
    if p.is_symlink() or p.exists():
        p.unlink()
    os.symlink(target, p)


def _sqlite(path: Path, v: int) -> None:
    c = sqlite3.connect(path)
    c.execute("create table if not exists t(v)")
    c.execute("delete from t")
    c.execute("insert into t values (?)", (v,))
    c.commit()
    c.close()


def _git_init(root: Path) -> None:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_AUTHOR_DATE="2026-01-01T00:00:00", GIT_COMMITTER_DATE="2026-01-01T00:00:00")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "c"], cwd=root, check=True, env=env)


class _Server:
    """A loopback TCP server accepting connections (the socket case)."""

    def __init__(self):
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(16)
        self.port = self.s.getsockname()[1]
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                c, _ = self.s.accept()
                c.sendall(b"hi")
                c.close()
            except OSError:
                return


def case(name, body, mutate, files=None, prelude="", env1=None, expect="failed", needs=None, setup=None,
         control=True, modules=None):
    """``control``: a test of the same module that the change does not touch is reused in the second run (the cache
    works; the case's test is not refused for an unrelated reason)."""
    return {"name": name, "body": body, "mutate": mutate, "files": files or {}, "prelude": prelude,
            "env1": env1 or {}, "expect": expect, "needs": needs, "setup": setup, "control": control,
            "modules": modules or {}}


CASES = [
    case("file_content", 'assert open("data.txt").read() == "hello\\n"',
         lambda r, m: _write(r, "data.txt", "changed\n"), files={"data.txt": "hello\n"}),
    case("native_read_os_open", 'fd = os.open("data.txt", os.O_RDONLY)\nassert os.read(fd, 100) == b"hello\\n"\nos.close(fd)',
         lambda r, m: _write(r, "data.txt", "changed\n"), files={"data.txt": "hello\n"}),
    case("pathlib_read", 'assert pathlib.Path("data.txt").read_bytes() == b"hello\\n"',
         lambda r, m: _write(r, "data.txt", "changed\n"), files={"data.txt": "hello\n"}),
    case("metadata_size", 'assert os.path.getsize("data.txt") == 6',
         lambda r, m: _write(r, "data.txt", "hello!\n"), files={"data.txt": "hello\n"}),
    case("metadata_mtime", 'assert os.path.getmtime("data.txt") < 3000000000',
         lambda r, m: os.utime(r / "data.txt", (3100000000, 3100000000)), files={"data.txt": "hello\n"}),
    case("metadata_mode", 'assert not os.access("tool.sh", os.X_OK)',
         lambda r, m: os.chmod(r / "tool.sh", 0o755), files={"tool.sh": "#!/bin/sh\n"}),
    case("symlink_target", 'assert os.readlink("link") == "a.txt"',
         lambda r, m: _symlink(r, "link", "b.txt"), files={"a.txt": "a\n", "b.txt": "b\n"},
         setup=lambda r: _symlink(r, "link", "a.txt")),
    case("realpath", 'assert os.path.realpath("link").endswith("a.txt")',
         lambda r, m: _symlink(r, "link", "b.txt"), files={"a.txt": "a\n", "b.txt": "b\n"},
         setup=lambda r: _symlink(r, "link", "a.txt")),
    case("listing", 'assert sorted(os.listdir("d")) == ["x"]',
         lambda r, m: _write(r, "d/y", ""), files={"d/x": ""}),
    case("listing_recursive", 'assert sum(len(f) for _, _, f in os.walk("tree")) == 1',
         lambda r, m: _write(r, "tree/a/y", ""), files={"tree/a/x": ""}),
    case("glob_recursive", 'import glob\nassert len(glob.glob("tree/**/*.txt", recursive=True)) == 1',
         lambda r, m: _write(r, "tree/a/b.txt", ""), files={"tree/a.txt": "", "tree/a/keep": ""}),
    case("existence_probe", 'assert not os.path.exists("flag")',
         lambda r, m: _write(r, "flag", "")),
    case("existence_pathlib", 'assert not pathlib.Path("flag").exists()',
         lambda r, m: _write(r, "flag", "")),
    case("kind_isdir", 'assert not os.path.isdir("thing")',
         lambda r, m: ((r / "thing").unlink(), (r / "thing").mkdir()), files={"thing": ""}),
    case("optional_module_appears",
         'try:\n    import optmod_detpy\nexcept ImportError:\n    optmod_detpy = None\nassert optmod_detpy is None',
         lambda r, m: _write(m, "optmod_detpy.py", "X = 1\n")),
    case("mock_patch_target_removed",
         'from unittest import mock\nimport pkghelper_detpy\nwith mock.patch("pkghelper_detpy.fetch", return_value=1):\n'
         '    assert pkghelper_detpy.use() == 2',
         lambda r, m: _write(m, "pkghelper_detpy.py", "def fetch2():\n    return 0\n\ndef use():\n    return fetch2() + 1\n"),
         modules={"pkghelper_detpy.py": "def fetch():\n    return 0\n\ndef use():\n    return fetch() + 1\n"}),
    case("env_single", 'assert os.environ.get("DETPY_T_X") is None',
         lambda r, m: {"DETPY_T_X": "1"}),
    case("env_enumeration", 'assert not [k for k in os.environ if k.startswith("DETPY_T_")]',
         lambda r, m: {"DETPY_T_Y": "1"}),
    case("timezone_read_by_c", 'assert time.strftime("%H", time.localtime(0)) == "00"',
         lambda r, m: {"TZ": "Asia/Tokyo"}, env1={"TZ": "UTC"}, control=False),
    case("child_process_reads_file",
         'out = subprocess.run(["cat", "data.txt"], capture_output=True, text=True, check=True).stdout\n'
         'assert out == "hello\\n"',
         lambda r, m: _write(r, "data.txt", "changed\n"), files={"data.txt": "hello\n"}),
    case("child_reads_dev_shm",
         'out = subprocess.run(["cat", os.environ["DETPY_T_SHM"]], capture_output=True, text=True, check=True).stdout\n'
         'assert out == "hello\\n"',
         lambda r, m: Path(os.environ["DETPY_T_SHM"]).write_text("changed\n"), needs="shm"),
    case("socket_loopback",
         's = socket.create_connection(("127.0.0.1", int(os.environ["DETPY_T_PORT"])))\nassert s.recv(2) == b"hi"\n'
         's.close()',
         lambda r, m: None, expect="rerun", needs="server"),
    case("sqlite_real_clock",
         'now = sqlite3.connect(":memory:").execute("select strftime(\'%s\', \'now\')").fetchone()[0]\n'
         'assert int(now) > 0',
         lambda r, m: None, expect="rerun"),
    case("git_head_read", 'assert open(".git/HEAD").read() == "ref: refs/heads/main\\n"',
         lambda r, m: subprocess.run(["git", "checkout", "-q", "-b", "other"], cwd=r, check=True),
         setup=_git_init),
    case("exclusive_create",
         'try:\n    fd = os.open("app.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY)\nexcept FileExistsError:\n'
         '    fd = None\nassert fd is not None, "app.lock is held"\nos.close(fd)\nos.remove("app.lock")',
         lambda r, m: _write(r, "app.lock", "")),
    case("sqlite_file_uri",
         'c = sqlite3.connect("file:r17.db?mode=ro", uri=True)\nassert c.execute("select v from t").fetchone()[0] == 1',
         lambda r, m: _sqlite(r / "r17.db", 2), setup=lambda r: _sqlite(r / "r17.db", 1)),
    case("file_written_by_child_timestamp",
         'out = subprocess.run(["sh", "-c", "echo > stamp && stat -c %Y stamp"], capture_output=True, text=True,\n'
         '                     check=True).stdout\nassert int(out) > 0',
         lambda r, m: None, expect="rerun"),
]


def needs_ok(c, request_env: dict) -> str | None:
    """None when the case can run here, else why not."""
    import shutil

    if c["name"].startswith("child") or c["name"].startswith("file_written_by_child"):
        if shutil.which("strace") is None:
            return None  # without strace a test that starts a process is never cached: the assertions hold too
    if c["needs"] == "shm" and not os.path.isdir("/dev/shm"):
        return "no /dev/shm"
    return None


def run_case(c, runner_run, root: Path, write_project, moddir: Path | None = None) -> tuple:
    """Run a case: first run (records), mutate, second run. Returns (first, second). The test reads its data files
    relative to ``root`` (the working directory); ``moddir`` is the importable directory of the runner's layout (on
    ``sys.path``, apart from ``root`` whose listing the import system reads)."""
    moddir = moddir or root
    import uuid

    env = dict(c["env1"])
    server = None
    shm = None
    if c["needs"] == "server":
        server = _Server()
        env["DETPY_T_PORT"] = str(server.port)
    if c["needs"] == "shm":
        shm = Path(f"/dev/shm/detpy-runners-{uuid.uuid4().hex}")
        shm.write_text("hello\n")
        env["DETPY_T_SHM"] = str(shm)
        os.environ["DETPY_T_SHM"] = str(shm)
    try:
        for name, text in c["files"].items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        for name, text in c["modules"].items():
            p = moddir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        if c["setup"]:
            c["setup"](root)
        write_project(root, c)
        first = runner_run(root, env)
        extra = c["mutate"](root, moddir)
        env2 = dict(env)
        if isinstance(extra, dict):
            env2.update(extra)
        time.sleep(0.01)
        second = runner_run(root, env2)
        return first, second
    finally:
        if shm is not None:
            shm.unlink(missing_ok=True)
            os.environ.pop("DETPY_T_SHM", None)
        if server is not None:
            server.s.close()


def check_case(c, first, second, nid: str, control: str | None = None) -> None:
    assert first.outcomes.get(nid) == "passed", first
    assert nid not in first.reused, first
    assert nid not in second.reused, second
    if c["expect"] == "failed":
        assert second.outcomes.get(nid) in ("failed", "error"), second
    else:
        assert nid in second.outcomes, second
    if control is not None and c["control"]:
        assert control in second.reused, second
