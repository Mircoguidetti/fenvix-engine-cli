"""Round 2 of rust-hotpaths: the cache's capture in Rust (``_core.CaptureCore``, ``crates/detpy-py/src/capture.rs``)
against the Python ``Capture`` it replaces (``tests/rust_hotpaths_ref/_ref_proofcache.py``, run with
``-p _capref`` and ``DETPY_CAPTURE_REF=1``).

Whole sessions over projects that exercise every kind of capture (import-time reads, module/session fixtures,
conftest hooks, a doctest, a non-Python file, env reads of one variable and of the whole environment, clock,
random, a followed subprocess, a name lookup, a /proc read, sqlite, listings, writes read by later tests, failures,
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
    "pkg/lazy.py": """
        import os
        VAL = os.environ.get("EQ_LAZY", "z")

        def compute():
            return [i * i for i in range(3)]
        """,
    "test_lazy.py": """
        def test_lazy_import():
            from pkg import lazy
            assert lazy.compute() == [0, 1, 4] and lazy.VAL
        """,
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


def _session(pytester, mode: str, cache: Path, tag: str) -> dict:
    o = pytester.path.parent / f"{pytester.path.name}-o-{mode}-{tag}.json"
    r = _run(pytester, mode, f"--det-cache={cache}", f"--det-outcomes={o}")
    assert "INTERNALERROR" not in r.stdout.str(), r.stdout.str()[-3000:]
    d = json.loads(o.read_text())
    summary = {k: v for k, v in (d.get("cache") or {}).items() if not k.endswith("seconds") and k != "receipts"}
    receipts = [_VOLATILE.sub(b"", x.encode()) for x in (cache / "receipts.jsonl").read_text().splitlines()]
    return {"store": _VOLATILE.sub(b"", (cache / "proof-cache.json").read_bytes()), "receipts": receipts,
            "outcomes": d.get("outcomes"), "summary": summary}


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
        steps.append(out)
    ref, new = steps
    for i in range(4):
        assert ref[i]["store"] == new[i]["store"], f"session {i + 1}: stores differ"
        assert ref[i]["receipts"] == new[i]["receipts"], f"session {i + 1}: receipts differ"
        assert ref[i]["outcomes"] == new[i]["outcomes"], f"session {i + 1}"
        # the summary's details name /proc/self/task/<tid>: the thread id is the process's own
        cut = lambda s: re.sub(r"/proc/self/task/\d+/", "/proc/self/task/N/", json.dumps(  # noqa: E731
            {k: v for k, v in s.items() if k not in ("config", "runtime")}, sort_keys=True))
        assert cut(ref[i]["summary"]) == cut(new[i]["summary"]), f"session {i + 1}: summaries differ"
    s1 = new[0]["summary"]
    assert s1["recorded"] > 20 and new[1]["summary"]["reused"] > 20
    nc = s1["not_cached"]
    assert {"host name lookup", "reads /proc, /sys or /dev", "real clock read outside the virtual clock",
            "outcome", "reads a file another test or fixture wrote"} <= set(nc), nc
    assert new[2]["summary"]["reused"] and new[2]["summary"]["recorded"], new[2]["summary"]
