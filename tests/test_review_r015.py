"""Review R-015 (claude/rust-hotpaths): failing tests for the findings in
sessions/2026-11-18-review-rust-hotpaths/REPORT.md.

F1, F2: a recorded result that the code it is keyed on did not produce (pre-existing on 24b6d15, not closed by #11).
F3: the same through #2 (installed libraries in a virtual environment now load from cached bytecode): passes on
24b6d15, fails on claude/rust-hotpaths.
F4: the report's numbers against the raw results committed before it.
The last test is extra coverage of record_session against the reference loop (passes).
"""

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

REPO = Path(__file__).resolve().parents[1]
OLD = 1767225600  # 2026-01-01T00:00:00Z: a source's mtime that is not the time it was written (restored, skewed)


def _project(root: Path, files: dict) -> None:
    (root / "pytest.ini").write_text("[pytest]\n")
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


def _pytest(cwd, *args, python=sys.executable, stdin=subprocess.DEVNULL, **kw):
    return subprocess.run([python, "-m", "pytest", "-p", "no:cacheprovider", *args], cwd=cwd, stdin=stdin,
                          capture_output=True, text=True, timeout=300, **kw)


def _reused(out: Path) -> set:
    return set(json.loads(out.read_text()).get("cache", {}).get("reused_ids", ()))


# ---------------------------------------------------------------------------
# F1: a repository module edited while the session runs (after the test imported it) is recorded under its new
# content: the entry's code digests are taken at the end of the session, not when the code was loaded
def test_F1_source_edited_during_the_run_is_not_reused(pytester):
    root = pytester.path
    _project(root, {
        "pkg/__init__.py": "",
        "pkg/mod.py": "VALUE = 1\n",
        "test_m.py": """
            import os
            from pkg import mod

            def test_a():
                print("READY", flush=True)
                os.read(0, 1)  # wait for the edit (stdin: no audit event, not an input)
                assert mod.VALUE == 1
            """,
    })
    cache = root / ".cachedir"
    p = subprocess.Popen([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-s", "--det",
                          f"--det-cache={cache}", f"--det-outcomes={root / 'o1.json'}"], cwd=root,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        for line in p.stdout:
            if "READY" in line:
                # the developer saves a change (or switches branch) while the suite is still running
                (root / "pkg" / "mod.py").write_text("VALUE = 2\n")
                p.stdin.write("x")
                p.stdin.flush()
        assert p.wait(timeout=300) == 0  # this session ran the old code: passed
    finally:
        p.kill()
    # fresh run of the code now on disk: fails
    fresh = _pytest(root, "-s", "--det")
    assert "1 failed" in fresh.stdout
    # the cache must not hand back the result of code that is no longer there
    r = _pytest(root, "-s", "--det", f"--det-cache={cache}", f"--det-outcomes={root / 'o2.json'}")
    assert _reused(root / "o2.json") == set(), "result of the replaced code reused"
    assert "1 failed" in r.stdout


# ---------------------------------------------------------------------------
# F2: #11 drops the bytecode of sources whose mtime is within 2 s of the precompile by the local clock. A source
# whose mtime is not its write time (git-restore-mtime / commit times, files from a host or server with another
# clock, archives) and whose same-size new content keeps the mtime second still runs the stale .pyc
def test_F2_same_size_edit_with_a_restored_mtime_runs_the_new_code(pytester):
    root = pytester.path
    _project(root, {
        "pkg/__init__.py": "",
        "pkg/mod.py": "VALUE = 1\n",
        "test_m.py": "from pkg import mod\n\ndef test_a():\n    assert mod.VALUE == 1\n",
    })
    for f in ("pkg/__init__.py", "pkg/mod.py", "test_m.py"):
        os.utime(root / f, (OLD, OLD))
    cache = root / ".cachedir"
    assert "1 passed" in _pytest(root, "--det", f"--det-cache={cache}").stdout
    # next commit: same size, mtime restored to its commit time, which falls in the same second
    (root / "pkg" / "mod.py").write_text("VALUE = 2\n")
    os.utime(root / "pkg" / "mod.py", (OLD + 0.5, OLD + 0.5))
    r = _pytest(root, "--det", f"--det-cache={cache}")
    assert "1 failed" in r.stdout, "stale bytecode ran under the new content's digest:\n" + r.stdout[-800:]


# ---------------------------------------------------------------------------
# F3: #2 compiles installed libraries inside a virtual environment, which 24b6d15 always compiled from source.
# _drop_fresh_pycs covers the project only, so a same-size module of an upgraded distribution whose installer
# kept the mtime second (archive mtimes, hard-linked caches, two installs in one second) loads the old version's
# bytecode, while the runtime identity (RECORD digest) says new version: the old code's result is recorded under
# the new identity. Passes on 24b6d15 (library from source), fails on claude/rust-hotpaths.
def test_F3_venv_library_upgrade_runs_the_new_code(tmp_path, monkeypatch):
    import sysconfig

    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    py = str(venv / "bin" / "python")
    site = subprocess.run([py, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                          capture_output=True, text=True, check=True).stdout.strip()
    outer = sysconfig.get_paths()["purelib"]
    Path(site, "outer.pth").write_text(f"import site; site.addsitedir({outer!r})\n")
    lib = Path(site, "libmod.py")
    lib.write_text("VALUE = 1\n")
    os.utime(lib, (OLD, OLD))
    di = Path(site, "libmod-1.0.dist-info")
    di.mkdir()
    (di / "METADATA").write_text("Metadata-Version: 2.1\nName: libmod\nVersion: 1.0\n\n")
    (di / "RECORD").write_text("libmod.py,sha256=v1,10\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    _project(proj, {"test_m.py": "import libmod\n\ndef test_a():\n    assert libmod.VALUE == 1\n"})
    monkeypatch.setenv("DETPY_PYC_CACHE", str(tmp_path / "pyc"))
    cache = proj / ".cachedir"
    assert "1 passed" in _pytest(proj, "--det", f"--det-cache={cache}", python=py).stdout
    # upgrade: new RECORD (new runtime identity), same-size module, mtime in the same second
    lib.write_text("VALUE = 2\n")
    os.utime(lib, (OLD + 0.5, OLD + 0.5))
    (di / "RECORD").write_text("libmod.py,sha256=v2,10\n")
    r = _pytest(proj, "--det", f"--det-cache={cache}", python=py)
    assert "1 failed" in r.stdout, "the old version's bytecode ran under the new runtime identity:\n" + r.stdout[-800:]


# ---------------------------------------------------------------------------
# F4: the report's home-assistant cold/plain range leaves out p3 shard 5, committed before the report
def test_F4_report_cold_over_plain_range_covers_every_committed_profile_shard():
    import re
    import statistics

    report = (REPO / "sessions" / "2026-11-18-rust-hotpaths" / "REPORT.md").read_text()
    m = re.search(r"\*\*(\d\.\d\d)-(\d\.\d\d)x\*\* on\s+the\s+profiled\s+shards", report)
    assert m, "headline range not found"
    lo, hi = float(m.group(1)), float(m.group(2))
    ratios = {}
    for run in ("p2", "p3"):
        for f in sorted((REPO / "tracks" / "rust-hotpaths" / "results" / run).glob("home-assistant-*.json")):
            w = json.loads(f.read_text())["walls"]
            ratios[f"{run}/{f.stem}"] = round(statistics.median(w["C:new"]) / statistics.median(w["P0"]), 2)
    outside = {k: v for k, v in ratios.items() if not lo <= v <= hi}
    assert outside == {}, f"report says {lo}-{hi}x; raw results: {ratios}"


# ---------------------------------------------------------------------------
# extra coverage (passes): record_session against the reference loop with scopes the author's project lacks
SCOPES = {
    "conftest.py": """
        import os
        from pathlib import Path
        import pytest

        ROOT = Path(__file__).parent
        ENV_AT_IMPORT = os.environ.get("EQ_IMPORT", "i")

        @pytest.fixture(scope="session")
        def sess():
            (ROOT / "gen").mkdir(exist_ok=True)
            (ROOT / "gen" / "sess.txt").write_text("s" + os.environ.get("EQ_MODE", "a"))
            return ROOT / "gen" / "sess.txt"
        """,
    "sub/__init__.py": "",
    "sub/conftest.py": """
        from pathlib import Path
        import pytest

        @pytest.fixture(scope="module")
        def modfix():
            return (Path(__file__).parent / "data_a.txt").read_text()

        @pytest.fixture(scope="package")
        def pkgfix():
            return sorted(p.name for p in Path(__file__).parent.iterdir() if p.suffix == ".txt")

        @pytest.fixture(scope="class")
        def clsfix():
            return 3
        """,
    "sub/data_a.txt": "a\n",
    "sub/test_s.py": """
        import os
        from pathlib import Path

        DATA = (Path(__file__).parent / "data_a.txt").read_text()

        def test_mod(modfix):
            assert modfix == DATA

        def test_pkg(pkgfix):
            assert "data_a.txt" in pkgfix

        def test_sess(sess):
            assert sess.read_text().startswith("s")

        def test_env_enum():
            assert any(k.startswith("EQ_") for k in os.environ)

        class TestC:
            def test_c1(self, clsfix):
                assert clsfix == 3

            def test_c2(self, clsfix, modfix):
                assert clsfix + len(modfix) == 5
        """,
    "sub2/__init__.py": "",
    "sub2/test_t.py": """
        from pathlib import Path

        def test_reads_session_output_without_the_fixture():
            p = Path(__file__).parents[1] / "gen" / "sess.txt"
            assert not p.exists() or p.read_text().startswith("s")
        """,
    "test_shared.py": """
        def helper():
            return 7

        def test_shared():
            assert helper() == 7
        """,
    "test_user.py": """
        from test_shared import helper

        def test_user():
            assert helper() == 7
        """,
}


def test_record_session_matches_reference_with_wider_scopes(pytester, monkeypatch):
    sys.path.insert(0, str(REPO / "harness" / "rust_hotpaths"))
    import canon

    _project(pytester.path, SCOPES)
    eq = pytester.path / "eq.jsonl"
    monkeypatch.setenv("DETPY_EQ_OUT", str(eq))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(REPO / "tests" / "rust_hotpaths_ref"),
                                                      os.environ.get("PYTHONPATH", "")]))
    monkeypatch.setenv("EQ_MODE", "a")
    cache = pytester.path / ".cachedir"

    def run():
        r = pytester.runpytest_subprocess("--det", f"--det-cache={cache}", "-p", "no:cacheprovider", "-p",
                                          "_eqplugin")
        d = json.loads(eq.read_text().splitlines()[-1])
        assert d["ref"] == d["new"]
        a = canon.canon(os.path.join(d["ref_dir"], "proof-cache.json"))
        b = canon.canon(os.path.join(d["dir"], "proof-cache.json"))
        assert canon.diff(a, b) == []
        return r, d

    r, d = run()
    assert d["new"]["recorded"] >= 8
    run()
    (pytester.path / "sub" / "data_a.txt").write_text("b\n")
    monkeypatch.setenv("EQ_MODE", "b")
    monkeypatch.setenv("EQ_IMPORT", "j")
    time.sleep(0.01)
    run()
    run()
