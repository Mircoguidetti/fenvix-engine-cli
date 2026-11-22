"""Copied from claude/review-py-cache-r053 (review R-053). Review R-053, re-check of PR #5 (claude/py-cache @ 29ef940): wrong results the R-052 fix does not cover.

1. K1: the code prefix (62be968) digests the test files at or before a test, but not the conftest.py / __init__.py
   files pytest loads with them. A conftest.py added next to an earlier test (or an import-time write added to an
   existing one) starts writing state a later test reads; the later test, whose stored needs are [], is reused as
   passed. Plain pytest and pytest --det fail it.
2. P: trunk 9e3663a pins the CPU count and the host name under --det (design A), and ``process_identity`` (part of
   every key) now reads the pinned values. A test that reads the real value by another path (``posix``, ``_socket``)
   is reused on another machine shape; --det without the cache fails it. Correct on 33bb5ff (before the merge).
3. E: ``posix.urandom`` is neither controlled nor refused (also on 33bb5ff): a test whose outcome depends on it is
   reused with the first outcome while fresh --det runs vary.

All FAIL on 29ef940 (CPython 3.13.18 and 3.12.3, MEASURED). They pass once the cached run reports what plain
pytest / uncached --det reports. No conftest at the root and ``import helper``, as in R-052.
"""
import os
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the cache gates run on Linux")

VICTIM = "tests/b/test_b.py::test_victim"
INI = {"pytest.ini": "[pytest]\npythonpath = .\n"}


def _write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _pytest(root, *args, prefix=()):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    p = subprocess.run([*prefix, sys.executable, "-m", "pytest", "-q", "-rA", "-s", "-p", "no:cacheprovider",
                        "-p", "no:randomly", *args, "tests"], cwd=root, capture_output=True, text=True, env=env,
                       timeout=600)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ")):
            out[line.split()[1]] = line.split()[0].lower()
    return p, out


def _check(root, before, after, par=()):
    cache = f"--det-cache={root / '.c'}"
    _write(root, {**INI, **before})
    _pytest(root, "--det", cache, *par)
    _pytest(root, *par)
    _write(root, after)
    p, o = _pytest(root, "--det", cache, *par)
    plain, po = _pytest(root, *par)
    assert plain.returncode == 1 and po.get(VICTIM) == "failed", plain.stdout[-1500:]
    det, do = _pytest(root, "--det", *par)
    assert det.returncode == 1 and do.get(VICTIM) == "failed", det.stdout[-1500:]
    assert p.returncode == 1 and o.get(VICTIM) == "failed", (
        f"--det-cache reports {o} (exit {p.returncode}); plain pytest and --det fail {VICTIM}:\n{p.stdout[-2000:]}")


HELPER = {"helper.py": "STATE = {'mode': 'good'}\n", "tests/a/test_a.py": "def test_a():\n    pass\n"}
READS = "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n"


@pytest.mark.parametrize("par", [(), ("-n", "1")], ids=["serial", "n1"])
def test_k1_a_new_conftest_next_to_an_earlier_test_starts_writing_the_state(tmp_path, par):
    _check(tmp_path, {**HELPER, "tests/b/test_b.py": READS},
           {"tests/a/conftest.py": "import pytest, helper\n\n@pytest.fixture(autouse=True)\ndef pol():\n"
                                   "    helper.STATE['mode'] = 'bad'\n"}, par)


def test_k1d_a_new_conftest_writes_the_state_at_import(tmp_path):
    _check(tmp_path, {**HELPER, "tests/b/test_b.py": READS},
           {"tests/a/conftest.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"})


def test_k1g_an_existing_conftest_gains_an_import_time_write(tmp_path):
    _check(tmp_path, {**HELPER, "tests/a/conftest.py": "import helper\n", "tests/b/test_b.py": READS},
           {"tests/a/conftest.py": "import helper\nhelper.STATE['mode'] = 'bad'\n"})


def test_k1e_a_new_conftest_lowers_the_recursion_limit(tmp_path):
    _check(tmp_path, {**HELPER, "tests/b/test_b.py": "def r(n):\n    return 0 if n == 0 else r(n - 1)\n\n"
                                                     "def test_victim():\n    assert r(400) == 0\n"},
           {"tests/a/conftest.py": "import pytest, sys\n\n@pytest.fixture(autouse=True)\ndef pol():\n"
                                   "    sys.setrecursionlimit(120)\n"})


def _pinned(root, body, prefix):
    """Run 1 on this machine (recorded), run 2 under ``prefix`` (another machine shape): cache vs uncached --det."""
    _write(root, {**INI, "tests/test_p.py": body})
    cache = f"--det-cache={root / '.c'}"
    p1, o1 = _pytest(root, "--det", cache)
    assert p1.returncode == 0, p1.stdout[-1500:]
    det, do = _pytest(root, "--det", prefix=prefix)
    assert det.returncode == 1, det.stdout[-1500:]  # the other machine shape fails the test without the cache
    p, o = _pytest(root, "--det", cache, prefix=prefix)
    assert p.returncode == 1, f"--det-cache reports {o} (exit {p.returncode}); --det fails it:\n{p.stdout[-2000:]}"


@pytest.mark.skipif(not hasattr(os, "sched_getaffinity") or len(os.sched_getaffinity(0)) < 2 or not shutil.which(
    "taskset"), reason="needs 2+ CPUs and taskset")
def test_p1_the_real_cpu_count_read_through_posix_is_an_input(tmp_path):
    n = len(os.sched_getaffinity(0))
    _pinned(tmp_path, f"import posix\n\ndef test_c():\n    assert len(posix.sched_getaffinity(0)) == {n}\n",
            ("taskset", "-c", "0"))


@pytest.mark.skipif(os.geteuid() != 0 or not shutil.which("unshare"), reason="needs root and unshare")
@pytest.mark.parametrize("call", ["_socket.gethostname()", "posix.uname().nodename"])
def test_p2_the_real_host_name_read_through_a_c_module_is_an_input(tmp_path, call):
    mod = call.split(".", 1)[0]
    _pinned(tmp_path, f"import {mod}\n\ndef test_h():\n    assert {call} == {os.uname().nodename!r}\n",
            ("unshare", "--uts", "sh", "-c", 'hostname otherbox-r053; exec "$@"', "sh"))


def test_e1_entropy_read_through_posix_is_controlled_or_refused(tmp_path):
    """Reused only if the bytes a fresh --det run sees are the same every run (controlled)."""
    _write(tmp_path, {**INI, "tests/test_e.py": "import posix\n\ndef test_e():\n    print('VALUE', posix.urandom(8))\n"})
    cache = f"--det-cache={tmp_path / '.c'}"
    _pytest(tmp_path, "--det", cache)
    p, _ = _pytest(tmp_path, "--det", cache)
    reused = any(line.startswith("reused 1 ") for line in p.stdout.splitlines())
    vals = [next(line for line in _pytest(tmp_path, "--det")[0].stdout.splitlines() if line.startswith("VALUE"))
            for _ in range(2)]
    assert not (reused and vals[0] != vals[1]), f"reused while fresh --det runs read {vals}:\n{p.stdout[-1500:]}"
