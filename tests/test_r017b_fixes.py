"""Review R-017b fixes beyond the reviewer's own cases (``tests/test_review_r017b.py``):

* F1: the rewritten-pyc key is re-checked at each read, so a *conftest* (loaded after the first reads) that patches
  ``AssertionRewriter`` gets its own pycs; the digest is stable across runs (the cache still hits).
* F2: a database attached with ``ATTACH`` is an input too (no audit event for it); ``%XX`` names decode
  bytes-exact (``_core.sqlite_file_of``)."""
import json
import os
import subprocess
import sys

import pytest

needs_monitoring = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

CONFTEST = '''
import ast, os
from _pytest.assertion.rewrite import AssertionRewriter

if os.environ.get("R17B_PLUG") == "1":
    _run = AssertionRewriter.run

    def run(self, mod):
        _run(self, mod)
        mod.body.append(ast.parse("MARK = 1").body[0])

    AssertionRewriter.run = run
'''
TEST = 'import os\n\ndef test_m():\n    assert ("MARK" in globals()) == (os.environ.get("R17B_PLUG") == "1")\n'


def _run(pytester, *args, **extra):
    env = dict(os.environ, PYTHONPATH=str(pytester.path), **extra)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=pytester.path, env=env, capture_output=True, text=True)


def _keyed_pycs(pytester):
    """The keyed rewritten pycs of ``test_m.py`` in ``--det``'s bytecode cache (``get_cache_dir``: the prefix plus
    the source's absolute directory)."""
    from pathlib import Path

    from detpy import reexec

    return sorted(p.name for p in Path(reexec.pyc_cache_dir("0") + str(pytester.path)).glob("test_m.*.det-*.pyc"))


def test_f1_conftest_patching_the_rewriter_gets_its_own_pycs(pytester):
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(test_m=TEST)
    for plug in ("0", "1", "0", "1"):
        r = _run(pytester, "--det", R17B_PLUG=plug)
        assert r.returncode == 0, f"R17B_PLUG={plug}: loaded the other rewrite's pyc\n" + r.stdout[-1500:]


def test_f1_digest_is_stable_across_runs(pytester):
    """The keyed pyc of an unpatched rewriter is written once and reused (one name over two runs)."""
    pytester.makepyfile(test_m="def test_m():\n    assert 1\n")
    for _ in range(2):
        assert _run(pytester, "--det").returncode == 0
    names = _keyed_pycs(pytester)
    assert len(names) == 1, names


@needs_monitoring
def test_f2_attached_database_is_an_input(pytester):
    import sqlite3

    db = pytester.path / "att.db"
    pytester.makepyfile(test_s='import sqlite3\n\ndef test_s():\n    c = sqlite3.connect(":memory:")\n'
                                '    c.execute("ATTACH \'att.db\' AS a")\n'
                                '    assert c.execute("select v from a.t").fetchone()[0] == 1\n')
    cache = pytester.path.parent / f"{pytester.path.name}-cache"
    out = pytester.path.parent / f"{pytester.path.name}-o.json"
    res = []
    for v in (1, 2):
        c = sqlite3.connect(db)
        c.execute("create table if not exists t(v)")
        c.execute("delete from t")
        c.execute("insert into t values (?)", (v,))
        c.commit()
        c.close()
        _run(pytester, "--det", f"--det-cache={cache}", f"--det-outcomes={out}")
        res.append(json.loads(out.read_text())["outcomes"]["test_s.py::test_s"])
    assert res == ["passed", "failed"], res


@pytest.mark.parametrize("uri, name", [("file:%FF.db", "\udcff.db"), ("file:%FE.db?mode=ro", "\udcfe.db"),
                                       ("file:%C3%A9.db", "é.db"), ("file:a%00b.db", "a"),
                                       ("file:%zz.db", "%zz.db"), ("file:x.db?mode=memory", None)])
def test_f2_uri_names_decode_bytes_exact(uri, name):
    from detpy import _core

    got = _core.sqlite_file_of(uri, True)
    assert got == (None if name is None else os.path.join(os.getcwd(), name))
