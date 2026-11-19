"""Review R-017b (last round) of claude/rust-hotpaths-2 (REPORT-R2b). Failing tests for the findings in
sessions/2026-11-19-review-rust-r2/REPORT-2.md."""
import json
import os
import subprocess
import sys

import pytest

needs_monitoring = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

# A plugin that changes the rewritten code by patching a *method* of AssertionRewriter. The class object and
# ``rewrite_asserts`` keep their identity, so ``_cache_rewritten_tests`` still reads and writes keyed pycs, and the
# key (pass hook, optimize, rewrite.py hash) does not see the plugin.
PLUGIN = '''
import ast, os
from _pytest.assertion.rewrite import AssertionRewriter

os.environ["R17B_PLUG"] = "1"
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


def test_f1_rewritten_pyc_ignores_plugin_that_patches_rewriter_method(pytester):
    """F1 (H1 fix incomplete). The same command on the same sources gives a different outcome depending on whether
    an earlier ``--det`` run without the plugin left a keyed pyc behind."""
    pytester.makepyfile(r17bplug=PLUGIN, test_m=TEST)
    fresh = _run(pytester, "--det", "-p", "r17bplug", DETPY_REWRITE_CACHE="0")
    assert fresh.returncode == 0, fresh.stdout  # no rewrite cache: the plugin's rewrite runs, the test passes
    first = _run(pytester, "--det", DETPY_REWRITE_CACHE="1")  # no plugin: writes the keyed pyc
    assert first.returncode == 0, first.stdout
    second = _run(pytester, "--det", "-p", "r17bplug", DETPY_REWRITE_CACHE="1")
    assert second.returncode == 0, ("--det with the plugin loaded the rewritten code an earlier run wrote without "
                                    "it:\n" + second.stdout[-1500:])


@needs_monitoring
def test_f1_cache_records_result_of_stale_rewrite(pytester):
    """F1 with ``--det-cache``: adding the plugin re-runs the test (new configuration digest), the re-run executes
    the stale rewritten code, and its result is recorded."""
    pytester.makepyfile(r17bplug=PLUGIN, test_m=TEST)
    cache = pytester.path.parent / f"{pytester.path.name}-cache"
    out = pytester.path.parent / f"{pytester.path.name}-o.json"
    _run(pytester, "--det", f"--det-cache={cache}")
    r = _run(pytester, "--det", f"--det-cache={cache}", f"--det-outcomes={out}", "-p", "r17bplug")
    assert json.loads(out.read_text())["outcomes"]["test_m.py::test_m"] == "passed", r.stdout[-1500:]


@needs_monitoring
@pytest.mark.parametrize("uri", ["file:r17b.db", "file:r17b.db?mode=ro", "file:%FF.db?mode=ro", "file:%FE.db"])
def test_f2_sqlite_uri_database_is_an_input(pytester, uri):
    """F2 (pre-existing, carried into Rust: ``capture.rs`` "sqlite3.connect" and the reference ``_ref_proofcache``
    skip every database name that starts with ``file:``). A test that opens its database through a URI is
    recorded without that input; after the database changes, the old result is reused. For ``%FF`` / ``%FE`` the
    decoded name would also be lossy (``sqlcap.rs::unquote``, ``errors="replace"``: both become U+FFFD)."""
    import sqlite3
    from urllib.parse import unquote_to_bytes

    name = unquote_to_bytes(uri[5:].split("?")[0])
    db = bytes(pytester.path) + b"/" + name
    pytester.makepyfile(test_s=f'import sqlite3\n\ndef test_s():\n    c = sqlite3.connect({uri!r}, uri=True)\n'
                                f'    assert c.execute("select v from t").fetchone()[0] == 1\n')
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
