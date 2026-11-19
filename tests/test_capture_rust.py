"""Round 2 of rust-hotpaths: the cache's capture in Rust (``_core.CaptureCore``, ``crates/detpy-py/src/capture.rs``)
against the Python ``Capture`` it replaces (``tests/rust_hotpaths_ref/_ref_proofcache.py``, run with
``-p _capref`` and ``DETPY_CAPTURE_REF=1``).

Whole sessions over projects that exercise every kind of capture (import-time reads, module/session fixtures,
conftest hooks, a doctest, a non-Python file, env reads of one variable and of the whole environment, clock,
random, a followed subprocess, a name lookup, a /proc read, sqlite (schemas read through ATTACH, triggers, own
definitions, file: URIs), loopback sockets, spawns, listings, writes read by later tests, failures,
skips, xfails; then edits, a changed variable and a stale reuse): the store written by each session (byte for
byte, but for the run id and durations), the warm receipts, the outcomes and the cache summary (reasons, where)
must be identical between the two paths.
"""

from __future__ import annotations

import json
import os
import re
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

REF = Path(__file__).parent / "rust_hotpaths_ref"
sys.path.insert(0, str(Path(__file__).parent))
from test_rust_hotpaths import FILES  # noqa: E402

EXTRA = {
    "test_more.py": """
        import os
        import shutil
        import sqlite3
        import time
        from pathlib import Path

        HERE = Path(__file__).parent

        def test_sqlite_now(tmp_path):
            c = sqlite3.connect(":memory:")
            assert c.execute("select date('now')").fetchone()

        def test_sqlite_file():
            c = sqlite3.connect(str(HERE / "db.sqlite"))
            c.execute("create table if not exists t (x)")
            c.close()

        def test_scandir_and_walk():
            assert sorted(e.name for e in os.scandir(HERE / "pkg"))
            assert list(os.walk(HERE / "sub"))

        def test_os_open_and_modes():
            fd = os.open(HERE / "config.txt", os.O_RDONLY)
            os.close(fd)
            with open(HERE / "rw.txt", "a+") as fh:
                fh.write("x")
            with open(HERE / "new.txt", "x" if not (HERE / "new.txt").exists() else "w") as fh:
                fh.write("n")

        def test_renames(tmp_path):
            p = HERE / "ren_a.txt"
            p.write_text("a")
            os.replace(p, HERE / "ren_b.txt")
            shutil.copyfile(HERE / "ren_b.txt", HERE / "ren_c.txt")
            os.remove(HERE / "ren_c.txt")

        def test_env_contains():
            assert ("EQ_NOPE" in os.environ) is False
            assert os.environb.get(b"EQ_VAR", b"x")

        def test_relative_paths():
            os.chdir(HERE / "pkg")
            try:
                assert open("table.txt").read()
                assert os.listdir(".")
            finally:
                os.chdir(HERE)

        def test_proc_listing():
            assert os.listdir("/proc/self/fd")

        def test_reads_twice():
            assert (HERE / "data.txt").read_text() == (HERE / "data.txt").read_text()
            time.sleep(0)
        """,
    # the sqlite trace, the loopback checks and the spawn details (crates/detpy-py/src/sqlcap.rs, sockcap.rs)
    "test_sqlnet.py": """
        import os
        import socket
        import sqlite3
        import subprocess
        from pathlib import Path
        from urllib.parse import quote

        import pytest

        HERE = Path(__file__).parent


        def _make(name, *sql):
            c = sqlite3.connect(str(HERE / name))
            for s in sql:
                c.execute(s)
            c.commit()
            c.close()


        def test_sql_0_make_dbs():
            # schemas that read the clock (their statements are flagged here)
            _make("dflt.sqlite", "create table if not exists o (x, t default current_timestamp)")
            _make("trig.sqlite", "create table if not exists l (x, t)",
                  "create trigger if not exists tr after insert on l begin "
                  "update l set t = datetime('now') where rowid = new.rowid; end")
            _make("sp ace%.sqlite", "create table if not exists s (x, t default (date('now')))")
            _make("plain.sqlite", "create table if not exists p (x)")


        def test_sql_attach_default():
            c = sqlite3.connect(str(HERE / "plain.sqlite"))
            c.execute("select count(*) from p").fetchone()
            c.execute("attach database '%s' as o" % (HERE / "dflt.sqlite"))
            c.execute("insert into o.o (x) values (1)")  # the attached schema's default reads the clock
            c.rollback()
            c.close()


        def test_sql_trigger():
            c = sqlite3.connect(str(HERE / "trig.sqlite"))
            c.execute("insert into l (x) values (1)")
            c.rollback()
            c.close()


        def test_sql_plain():
            c = sqlite3.connect(database=str(HERE / "plain.sqlite"))
            c.execute("pragma user_version")
            c.execute("insert into p (x) values (1)")
            c.rollback()
            c.close()


        @pytest.fixture(scope="module")
        def memconn():
            c = sqlite3.connect(":memory:")
            c.execute("create temp table t (x, t default current_time)")
            yield c
            c.close()


        def test_sql_own_schema(memconn):
            memconn.execute("insert into t (x) values (1)")


        def test_sql_uri_escapes():
            c = sqlite3.connect("file:" + quote(str(HERE / "sp ace%.sqlite")) + "?mode=ro", uri=True)
            assert c.execute("select count(*) from s").fetchone()
            c.close()


        def test_sql_uri_memory_and_attach():
            c = sqlite3.connect("file:memdb1?mode=memory&cache=shared", uri=True)
            c.execute("create table m (x)")
            c.execute("insert into m values (1)")
            c.execute("ATTACH 'file://localhost%s?mode=ro' AS s" % quote(str(HERE / "sp ace%.sqlite")))
            c.execute("select count(*) from m")
            c.close()


        def test_sql_new_file(tmp_path):
            c = sqlite3.connect(str(tmp_path / "new.sqlite"))
            c.execute("create table n (x)")
            c.execute("attach database '%s' as a" % str(tmp_path / "other''s.sqlite").replace("'", "''"))
            c.execute("create table a.q (y)")
            c.execute("insert into n values (1)")
            c.commit()
            c.close()


        def test_socket_own_listener_and_pair():
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen()
            c = socket.socket()
            c.connect(("127.0.0.1", srv.getsockname()[1]))
            s, _ = srv.accept()
            c.sendmsg([b"x"])
            assert s.recv(1) == b"x"
            for x in (s, c, srv):
                x.close()


        def test_socket_not_listening():
            c = socket.socket()
            try:
                c.connect(("127.0.0.1", 9))
            except OSError:
                pass
            c.close()


        def test_spawn_list_str_shell():
            subprocess.run(["/bin/sh", "-c", "true"], check=True)
            subprocess.run("true", check=True)
            subprocess.run("exit 0", shell=True, check=True)


        def test_spawn_os_system_and_posix_spawn():
            assert os.system("true  ") == 0
            os.waitpid(os.posix_spawn("/bin/true", ["true"], dict(os.environ)), 0)
        """,
    "pkg/lazy.py": """
        import os
        VAL = os.environ.get("EQ_LAZY", "z")

        def compute():
            return [i * i for i in range(3)]
        """,
    "test_alias.py": """
        def test_alias_import():
            from pkg import alias  # a symlink to pkg/lazy.py (review R-015b G2: the link is an input too)
            assert alias.compute() == [0, 1, 4]
        """,
    "test_lazy.py": """
        def test_lazy_import():
            from pkg import lazy
            assert lazy.compute() == [0, 1, 4] and lazy.VAL
        """,
    "test_stale.py": """
        import os
        from pathlib import Path

        HERE = Path(__file__).parent

        def test_stale_reader():
            assert (HERE / "stale_in.txt").read_text()

        def test_stale_writer():
            # reruns when EQ_MODE changes (session 3) and then writes the input of the reused test_stale_reader
            if os.environ.get("EQ_MODE") == "b":
                (HERE / "stale_in.txt").write_text("b\\n")
        """,
    "stale_in.txt": "a\n",
}


def _write(root: Path, files: dict) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


@pytest.fixture
def ref_env(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(REF), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep))


def _run(pytester, mode: str, *args):
    # the mode goes through a file: the environment (an input of the tests that read all of it) stays identical
    flag = pytester.path.parent / f"{pytester.path.name}-capref"
    flag.write_text("1" if mode == "ref" else "0")
    os.environ["DETPY_CAPTURE_REF"] = "@" + str(flag)
    try:
        return pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider", "-p", "_capref", *args)
    finally:
        del os.environ["DETPY_CAPTURE_REF"]


_VOLATILE = re.compile(rb'"(run|duration)": ?("[^"]*"|[0-9.e-]+)')


# the terminal summary's volatile parts: timings, run ids, digests (config holds the outcomes path), thread ids
_TERM_VOLATILE = [(re.compile(r"\(check [0-9.]+s, record [0-9.]+s\)"), "(check Ts, record Ts)"),
                  (re.compile(r"run=\S+"), "run=R"), (re.compile(r"(config|runtime) [0-9a-f]+"), r"\1 D"),
                  (re.compile(r"/proc/self/task/\d+/"), "/proc/self/task/N/")]


def _terminal_section(text: str) -> str:
    """The "detpy cache with proof" section of a run's output, its volatile parts masked."""
    m = re.search(r"=+ detpy cache with proof =+\n(.*?receipts: [^\n]*)", text, re.S)
    out = m.group(1) if m else ""
    for rx, rep in _TERM_VOLATILE:
        out = rx.sub(rep, out)
    return out


def _session(pytester, mode: str, cache: Path, tag: str, *extra) -> dict:
    o = pytester.path.parent / f"{pytester.path.name}-o-{mode}-{tag}.json"
    r = _run(pytester, mode, f"--det-cache={cache}", f"--det-outcomes={o}", *extra)
    assert "INTERNALERROR" not in r.stdout.str(), r.stdout.str()[-3000:]
    d = json.loads(o.read_text())
    cache_part = d.get("cache") or {}
    summary = {k: v for k, v in cache_part.items() if not k.endswith("seconds") and k != "receipts"}
    receipts = [_VOLATILE.sub(b"", x.encode()) for x in (cache / "receipts.jsonl").read_text().splitlines()]
    return {"store": _VOLATILE.sub(b"", (cache / "proof-cache.json").read_bytes()), "receipts": receipts,
            "outcomes": d.get("outcomes"), "summary": summary,
            # the order of the outcomes file's cache keys and of its phase timings (the values are timings)
            "keys": list(cache_part), "phases": list(cache_part.get("phase_seconds") or {}),
            "terminal": _terminal_section(r.stdout.str())}


def test_capture_reference_plugin_is_active(pytester, ref_env):
    pytester.makepyfile(test_x="import detpy.proofcache as pc\ndef test_x():\n    print('REF', getattr(pc, "
                                "'CAPTURE_REFERENCE', False), pc.Capture.__mro__[1].__name__)\n")
    assert "REF True object" in _run(pytester, "ref", "-s").stdout.str()
    assert "REF False CaptureCore" in _run(pytester, "new", "-s").stdout.str()


def test_capture_sessions_match_reference(pytester, ref_env, monkeypatch):
    import shutil

    root = pytester.path
    steps = []
    # each path runs the same four sessions on a fresh copy of the project, in the same directory (paths are part
    # of the store; the project's own writes are inputs), each with its own cache
    for mode in ("ref", "new"):
        for name in os.listdir(root):
            if not name.startswith(".cache-"):
                p = root / name
                shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
        _write(root, FILES)
        _write(root, EXTRA)
        os.symlink("lazy.py", root / "pkg" / "alias.py")
        # one cache path for both (followed children load the clock shim from it: a path and a digest of every
        # spawning test); the second path starts from an empty cache holding the first one's shim
        cache = root.parent / f"{root.name}-cache"
        if cache.exists():
            prev = root.parent / f"{root.name}-cache-{mode}-prev"
            cache.rename(prev)
            cache.mkdir()
            for p in prev.iterdir():
                if p.name.startswith("clockshim-"):
                    shutil.copy2(p, cache / p.name)
        out = []
        monkeypatch.setenv("EQ_MODE", "a")
        out.append(_session(pytester, mode, cache, "1"))           # everything new
        out.append(_session(pytester, mode, cache, "2"))           # unchanged: reused
        _write(root, {"pkg/mod.py": FILES["pkg/mod.py"].replace("x * 2", "2 * x"), "write_data.flag": "1\n"})
        monkeypatch.setenv("EQ_MODE", "b")
        out.append(_session(pytester, mode, cache, "3"))           # code + env change, stale reuse
        out.append(_session(pytester, mode, cache, "4"))           # after the writes
        out.append(_session(pytester, mode, cache, "5", "--det-cache-verify=1"))  # every reusable result re-run
        out.append(_session(pytester, mode, cache, "6", "-v"))     # verbose: one REUSED line per result
        steps.append(out)
    ref, new = steps
    for i in range(6):
        assert ref[i]["store"] == new[i]["store"], f"session {i + 1}: stores differ"
        assert ref[i]["receipts"] == new[i]["receipts"], f"session {i + 1}: receipts differ"
        assert ref[i]["outcomes"] == new[i]["outcomes"], f"session {i + 1}"
        # the summary's details name /proc/self/task/<tid>: the thread id is the process's own
        cut = lambda s: re.sub(r"/proc/self/task/\d+/", "/proc/self/task/N/", json.dumps(  # noqa: E731
            {k: v for k, v in s.items() if k not in ("config", "runtime")}, sort_keys=True))
        assert cut(ref[i]["summary"]) == cut(new[i]["summary"]), f"session {i + 1}: summaries differ"
        assert ref[i]["keys"] == new[i]["keys"] and ref[i]["phases"] == new[i]["phases"], f"session {i + 1}"
        assert ref[i]["terminal"] == new[i]["terminal"], f"session {i + 1}: terminal summaries differ"
    s1 = new[0]["summary"]
    # review R-020 prefix rule: a test after a refused one in the same process is refused too ("after an earlier
    # test or fixture of this process"), so fewer results are recorded than before the rule (20 here); and
    # test_missing_and_listing lists the project root, which every session's writes change: carried into the later
    # tests of test_m.py, it reruns them (10 reused here)
    assert s1["recorded"] >= 15 and new[1]["summary"]["reused"] >= 8
    nc = s1["not_cached"]
    # parallel-proof round 3: SQLite's 'now' is Level 0's virtual clock (detpy/sqlvirt.py), no longer a real clock read;
    # the real-clock refusal is tested with --det-disable=time (test_proofcache_follow.py, test_review_r009*.py)
    assert {"host name lookup", "reads /proc, /sys or /dev",
            "outcome", "reads a file another test or fixture wrote"} <= set(nc), nc
    assert "real clock read outside the virtual clock" not in nc, nc
    assert new[2]["summary"]["reused"] and new[2]["summary"]["recorded"], new[2]["summary"]
    # a reused result whose input a later test of the session wrote: test_m.py::test_reads_data (first in its file);
    # test_stale.py runs after tests refused in test_m.py, so under the prefix rule its reader is never cached
    stale = new[2]["summary"]["stale_reuses"]
    assert stale and set(stale) <= {"test_m.py::test_reads_data", "test_stale.py::test_stale_reader"}, new[2]["summary"]
    assert all(f"WARNING reused {n}" in new[2]["terminal"] for n in stale), new[2]["terminal"]
    assert new[4]["summary"]["verified"] >= 8 and not new[4]["summary"]["reused"], new[4]["summary"]
    assert "verified " in new[4]["terminal"] and new[5]["terminal"].count("REUSED ") >= 8, new[5]["terminal"]
    # the sqlite trace, the loopback checks and the spawn detail ran (same results on both paths, above)
    where, ids = s1["not_cached_where"], s1["not_cached_ids"]
    t = "test_sqlnet.py::test_"
    # parallel-proof round 3: schemas whose defaults and triggers read 'now' are evaluated on the virtual clock now,
    # so these tests are no longer refused (the schema scan for a real-clock connection: test_proofcache_follow.py)
    for name in ("sql_attach_default", "sql_trigger", "sql_own_schema", "sql_uri_escapes", "sql_uri_memory_and_attach"):
        assert "real clock" not in ids.get(t + name, ""), ids
    assert where[t + "socket_not_listening"].startswith("socket.connect 127.0.0.1:9 at test_sqlnet.py:"), where
    assert where[t + "spawn_os_system_and_posix_spawn"].startswith("true (os.system) at test_sqlnet.py:"), where
    for name in ("sql_plain", "sql_new_file", "socket_own_listener_and_pair", "spawn_list_str_shell"):
        own = ids.get(t + name, "")
        own = "" if own.startswith("after an earlier test or fixture of this process") else own  # carried, not its own
        assert "real clock" not in own and "network" not in own, ids


# ---------------------------------------------------------------------------
# decisions and receipts (ProofCache.check_all / reuse_info / write_receipts): the helpers against Python
def test_float_repr_and_json_strings_match_python():
    import math
    import random

    from detpy import _core

    rnd = random.Random(3)
    xs = [0.0, -0.0, 1.0, 0.1, 1e-4, 1e-5, 0.0001234, 123456789012345.6, 1e15, 1e16, 1.5e16, 2.5e-7, 5e-324,
          1.7976931348623157e308, 3.0, 100.0, 0.000889701999767567, float("inf"), float("-inf"), float("nan")]
    xs += [rnd.random() * 10 ** rnd.randint(-12, 20) for _ in range(5000)]
    xs += [struct_f for struct_f in (rnd.uniform(-1, 1) for _ in range(1000))]
    for x in xs:
        want = json.dumps(x)
        assert _core.py_repr_float(x) == want, (x, want)
        if not math.isinf(x) and not math.isnan(x):
            assert _core.py_repr_float(x) == repr(x)
    strs = ["", "a", 'q"b\\c', "tab\tnl\nret\r\x00\x01\x1f\x7f\x80", "é", "日本", "😀", "a b::c[1-2]", "\b\f"]
    strs += ["".join(chr(rnd.choice([rnd.randint(0, 0x7f), rnd.randint(0x80, 0xd7ff), rnd.randint(0xe000, 0x10ffff)]))
                     for _ in range(rnd.randint(0, 20))) for _ in range(3000)]
    for s in strs:
        assert _core.json_dumps_str(s) == json.dumps(s), repr(s)
