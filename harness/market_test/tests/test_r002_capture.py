"""R-002 reviewer tests for harness/market_test dependency capture. Each test asserts what the proof rule promises
("a unit reuses its last result only if nothing it read changed") and FAILS on commit 6be49f6.

    python3 -m pytest -q harness/market_test/tests/test_r002_capture.py   (copied from review R-002)
Needs: git, strace, uv (creates a throwaway venv with pytest under a temp dir).
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
import walk  # noqa: E402

MAKE_DB = ("import sqlite3,sys\ncon=sqlite3.connect(sys.argv[1]);con.execute('create table if not exists t(v)');"
           "con.execute('delete from t');con.execute('insert into t values (?)',(int(sys.argv[2]),));con.commit()\n")
TEST_DB = ("import sqlite3\nfrom pathlib import Path\n\ndef test_fixture_value():\n"
           "    con = sqlite3.connect(Path(__file__).parent / 'fixture.db')\n"
           "    assert con.execute('select v from t').fetchone()[0] == 1\n")
TEST_ENV = "import os\n\ndef test_flag():\n    assert os.environ.get('R002_FLAG', '0') == '0'\n"


def g(src, *a):
    return subprocess.run(["git", *a], cwd=src, check=True, capture_output=True, text=True).stdout.strip()


def make_walker(tmp):
    work = Path(tmp) / "work"
    src = work / "src"
    (src / "tests").mkdir(parents=True)
    g(src, "init", "-q", "-b", "main")
    g(src, "config", "user.email", "r@x"); g(src, "config", "user.name", "r")
    (src / "tests" / "make_db.py").write_text(MAKE_DB)
    subprocess.run([sys.executable, "tests/make_db.py", "tests/fixture.db", "1"], cwd=src, check=True)
    (src / "tests" / "test_db.py").write_text(TEST_DB)
    (src / "tests" / "test_env.py").write_text(TEST_ENV)
    g(src, "add", "-A"); g(src, "commit", "-qm", "c0")
    c0 = g(src, "rev-parse", "HEAD")
    subprocess.run([sys.executable, "tests/make_db.py", "tests/fixture.db", "2"], cwd=src, check=True)
    g(src, "commit", "-qam", "c1: fixture value changes")
    c1 = g(src, "rev-parse", "HEAD")
    spec = {"name": "r002", "lang": "pytest", "seq": {"kind": "list", "commits": [c0, c1]},
            "units": {"include": ["tests/test_*.py"]}, "workers": 1,
            "install": ["test -x {py} || uv venv -q --python 3.13 {venv}", "uv pip install -q --python {py} pytest"],
            "cmd": ["{py}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "s2_report", "{unit}"]}
    w = walk.Walker(spec, work, Path(tmp) / "out.json.gz", 0, 1, 30, "r002")
    w.push = False
    assert w.install()[0]
    return w, c0, c1


def test_sqlite_fixture_change_is_a_dependency(tmp_path):
    w, c0, c1 = make_walker(tmp_path)
    w.checkout(c0)
    rec = w.run_unit("tests/test_db.py"); rec["sha"] = c0
    assert rec["code"] == 0
    w.checkout(c1)
    fresh = w.run_unit("tests/test_db.py", traced_run=False)
    assert fresh["code"] != 0                                 # the outcome really changed
    decision, _ = w.decide("tests/test_db.py", rec, c1, [c0, c1])
    assert decision["closure"] is not None, "closure reuses a PASS although the fixture it read changed"


def test_environment_variable_is_a_dependency(tmp_path, monkeypatch):
    w, c0, c1 = make_walker(tmp_path)
    w.checkout(c0)
    monkeypatch.delenv("R002_FLAG", raising=False)
    rec = w.run_unit("tests/test_env.py"); rec["sha"] = c0
    assert rec["code"] == 0
    monkeypatch.setenv("R002_FLAG", "1")                     # e.g. a CI matrix / runner variable differs
    fresh = w.run_unit("tests/test_env.py", traced_run=False)
    assert fresh["code"] != 0
    decision, _ = w.decide("tests/test_env.py", rec, c0, [c0, c1])
    assert decision["closure"] is not None, "closure reuses a PASS although an environment variable it read changed"
