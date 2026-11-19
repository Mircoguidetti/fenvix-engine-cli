"""parallel-proof round 3: P4 (shared store, ``--det-cache-shared``) and item 4 (re-exec before the other plugins).

P4: two "machines" are two local cache directories over one shared directory. Every reused result is compared with a
fresh serial ``--det`` run (the truth). The adversarial cases (an entry from another runtime filed under this
runtime's key, a partial upload, a code change after the push, concurrent pushers) must never produce a wrong reuse.
The store's own rules (documents by address, torn key lines, log order instead of clocks) are tested in Rust
(``detpy_core::shared::tests``).
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

FILES = {
    "pytest.ini": "[pytest]\n",
    "pkg/__init__.py": "",
    "pkg/calc.py": "def double(x):\n    return x * 2\n\ndef triple(x):\n    return x * 3\n",
    "test_a.py": "from pkg.calc import double\n\ndef test_double():\n    assert double(2) == 4\n\n"
                 "def test_double_neg():\n    assert double(-1) == -2\n",
    "test_b.py": "from pkg.calc import triple\n\ndef test_triple():\n    assert triple(2) == 6\n\n"
                 "def test_data():\n    assert open('data.txt').read() == 'x'\n",
    "data.txt": "x",
}


def _write(root, files):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


@pytest.fixture
def env(pytester, monkeypatch):
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_ADDOPTS",
              "DETPY_CACHE_SHARED"):
        monkeypatch.delenv(k, raising=False)
    _write(pytester.path, FILES)
    n = {"i": 0}

    def run(*args, cache="job1"):
        n["i"] += 1
        out = pytester.path / f"o{n['i']}.json"
        r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / cache}", f"--det-outcomes={out}",
                                          "-p", "no:cacheprovider", *args)
        d = json.loads(out.read_text()) if out.exists() else {}
        return r, d.get("outcomes", {}), d.get("cache", {})

    def truth():
        n["i"] += 1
        out = pytester.path / f"o{n['i']}.json"
        pytester.runpytest_subprocess("--det", f"--det-outcomes={out}", "-p", "no:cacheprovider")
        return json.loads(out.read_text())["outcomes"]

    return run, truth


def _no_wrong(outcomes, cache, truth):
    reused = cache.get("reused_ids") or []
    return {n: (outcomes.get(n), truth.get(n)) for n in reused if outcomes.get(n) != truth.get(n)}


@pytest.mark.parametrize("mode", ["serial", "n2"])
def test_second_machine_reuses_what_the_first_pushed(pytester, env, mode):
    run, truth = env
    par = () if mode == "serial" else ("-n", "2", "-p", "xdist")
    shared = f"--det-cache-shared={pytester.path / 'shared'}"
    r1, o1, c1 = run(shared, *par, cache="job1")
    r1.assert_outcomes(passed=4)
    assert "shared store" in r1.stdout.str() and "pushed 4" in r1.stdout.str(), r1.stdout.str()
    # machine 2: an empty local cache, the same shared store
    r2, o2, c2 = run(shared, *par, cache="job2")
    assert sorted(c2["reused_ids"]) == sorted(o2), r2.stdout.str()
    assert _no_wrong(o2, c2, truth()) == {}
    receipts = [json.loads(x) for x in (pytester.path / "job2" / "receipts.jsonl").read_text().splitlines()]
    assert all(x.get("origin", "").startswith("shared:") for x in receipts if x.get("reused")), receipts


def test_a_change_after_the_push_is_checked_like_a_local_entry(pytester, env):
    run, truth = env
    shared = f"--det-cache-shared={pytester.path / 'shared'}"
    run(shared, cache="job1")
    (pytester.path / "data.txt").write_text("y")  # test_data now fails
    (pytester.path / "pkg" / "calc.py").write_text("def double(x):\n    return x + x + 1\n\ndef triple(x):\n"
                                                  "    return x * 3\n")
    r2, o2, c2 = run(shared, cache="job2")
    assert set(c2["reused_ids"]) == {"test_b.py::test_triple"}, r2.stdout.str()
    assert _no_wrong(o2, c2, truth()) == {}
    r2.assert_outcomes(passed=1, failed=3)


def test_an_entry_from_another_runtime_filed_under_this_key_is_never_reused(pytester, env):
    """A poisoned shared store: machine 1 pushes; then its entries are refiled under the reader's lookup keys while
    they name another runtime (what a buggy or hostile writer of another interpreter could do). Machine 2 must
    reject them (foreign) and run every test."""
    from detpy import _core  # noqa: F401  (the binding exists)

    run, truth = env
    shared = pytester.path / "shared"
    r1, _o1, _c1 = run(f"--det-cache-shared={shared}", "--det-disable=fs", cache="job1")  # another configuration
    keys = list((shared / "keys").rglob("*.log"))
    assert keys
    # machine 2's lookup keys for the same tests: its run tells them only through the files, so compute: a run with
    # the reader's configuration pushes to a scratch store, then the poisoned lines are appended there
    scratch = pytester.path / "scratch"
    run(f"--det-cache-shared={scratch}", cache="probe")
    for log in (scratch / "keys").rglob("*.log"):
        lines = log.read_text().splitlines()
        # replace each line's document with machine 1's document of the same test (another configuration)
        for line in lines:
            body = json.loads(line.split("\t")[0])
            doc = json.loads((scratch / "blobs" / body["doc"][:2] / body["doc"]).read_text())
            for other in keys:
                for l2 in other.read_text().splitlines():
                    b2 = json.loads(l2.split("\t")[0])
                    d2 = json.loads((shared / "blobs" / b2["doc"][:2] / b2["doc"]).read_bytes())
                    if d2["nodeid"] == doc["nodeid"]:
                        target = shared / "keys" / log.parent.name / log.name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with open(target, "a") as fh:
                            fh.write(l2 + "\n")
    r2, o2, c2 = run(f"--det-cache-shared={shared}", cache="job2")
    assert c2["reused_ids"] == [], r2.stdout.str()
    assert "foreign 4" in r2.stdout.str(), r2.stdout.str()
    assert _no_wrong(o2, c2, truth()) == {}


def test_a_partial_upload_is_rejected_and_the_tests_run(pytester, env):
    run, truth = env
    shared = pytester.path / "shared"
    run(f"--det-cache-shared={shared}", cache="job1")
    # the upload of every file document was lost (the writer died before them; the key lines exist)
    blobs = list((shared / "blobs").rglob("*"))
    removed = 0
    for b in blobs:
        if b.is_file() and b'"skeleton"' in b.read_bytes() and b'"nodeid"' not in b.read_bytes():
            b.unlink()
            removed += 1
    assert removed
    r2, o2, c2 = run(f"--det-cache-shared={shared}", cache="job2")
    assert c2["reused_ids"] == [], r2.stdout.str()
    assert "incomplete" in r2.stdout.str(), r2.stdout.str()
    r2.assert_outcomes(passed=4)


def test_concurrent_pushers_lose_nothing(pytester, env):
    run, truth = env
    shared = pytester.path / "shared"
    procs = [subprocess.Popen([sys.executable, "-m", "pytest", "--det", f"--det-cache={pytester.path / f'job{i}'}",
                               f"--det-cache-shared={shared}", "-p", "no:cacheprovider", "-q"],
                              cwd=pytester.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
             for i in range(4)]
    pushed = 0
    for p in procs:
        out = p.communicate(timeout=300)[0].decode()
        import re

        m = re.search(r"pushed (\d+) entr", out)
        assert m, out
        pushed += int(m.group(1))
    torn = 0
    lines = 0
    for log in (shared / "keys").rglob("*.log"):
        for line in log.read_text().splitlines():
            lines += 1
            if "\t" not in line:
                torn += 1
    # a job that started after another one pushed adopts those entries and does not push them back: every entry a
    # job pushed is in the log, no line is torn
    assert torn == 0 and lines == pushed and pushed >= 4, (torn, lines, pushed)
    # a fifth job, started the same way (the same sys.path: it is part of the runtime identity)
    out = pytester.path / "o-new.json"
    subprocess.run([sys.executable, "-m", "pytest", "--det", f"--det-cache={pytester.path / 'job-new'}",
                    f"--det-cache-shared={shared}", f"--det-outcomes={out}", "-p", "no:cacheprovider", "-q"],
                   cwd=pytester.path, capture_output=True, timeout=300)
    d = json.loads(out.read_text())
    o, c = d["outcomes"], d["cache"]
    assert len(c["reused_ids"]) == 4 and _no_wrong(o, c, truth()) == {}, c


# ---------------------------------------------------------------------------------------------------------------
# item 4: the re-exec happens before pytest imports the plugins that load after detpy


def test_a_plugin_loaded_after_detpy_is_imported_once(pytester, monkeypatch):
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS", "DETPY_REEXEC"):
        monkeypatch.delenv(k, raising=False)
    log = pytester.path / "imports.log"
    pytester.makepyfile(countplug=f"""
        import os
        with open({str(log)!r}, "a") as fh:
            fh.write(str(os.getpid()) + "\\n")
        """)
    pytester.makepyfile(test_x="def test_x():\n    assert True\n")
    monkeypatch.setenv("PYTEST_PLUGINS", "countplug")  # loaded by pytest after the entry points (detpy's included)
    monkeypatch.setenv("PYTHONPATH", str(pytester.path))
    r = pytester.runpytest_subprocess("--det", "-p", "no:cacheprovider")
    r.assert_outcomes(passed=1)
    assert "already re-executed" not in r.stdout.str()
    pids = log.read_text().split()
    assert len(pids) == 1, pids  # before: imported by the first process too, then again after the re-exec
    assert "PYTHONHASHSEED=0 (ok)" in r.stdout.str()
