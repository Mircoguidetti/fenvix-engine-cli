"""Review R-052, re-check of PR #5 (claude/py-cache @ 33bb5ff): a later test's needs are stale after a code change.

The carried-set rule stores, per test, the earlier tests it may consume in-process state from (``Entry::needs``,
or ``Store::loose_needs`` for a test with no entry, decision (b)). They are computed from the code as it was when the
test last ran. When the earlier test or the later test is edited so that they become connected (both now reach the
same module or the interpreter), the stored needs still say "no earlier test": the earlier test is reused (not run)
or runs while the later one is reused, and the later test's result is reported from a process the user's run never
has. Plain ``pytest`` (and ``pytest --det``) fail the later test; ``--det-cache`` reports it passed, exit 0.

All four FAIL on 33bb5ff (CPython 3.12.13, 3.13.18, 3.14.6) and on the trunk cec096c (3.13). They pass once the
cached run reports what plain pytest reports.

No conftest: a conftest that imports a library connects every test (the rule is then sound by over-carrying). The
modules are imported with ``import helper`` (``from helper import X`` is matched as a library: also over-carrying).
"""
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the cache gates run on Linux")


def _write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _pytest(root, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "DETPY_CACHE_IN_PROCESS")}
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "-p", "no:randomly",
                        *args, "tests"], cwd=root, capture_output=True, text=True, env=env, timeout=600)
    out = {}
    for line in p.stdout.splitlines():
        if line.startswith(("PASSED ", "FAILED ", "ERROR ")):
            out[line.split()[1]] = line.split()[0].lower()
    return p, out


VICTIM = "tests/test_b.py::test_victim"
INI = {"pytest.ini": "[pytest]\npythonpath = .\n"}


def _clean(root):
    (root / "flag.txt").unlink(missing_ok=True)


def _check(root, before, after):
    """Run 1 (cold cache) on ``before``; apply ``after``; run 2 cached must equal plain pytest."""
    cache = f"--det-cache={root / '.c'}"
    _write(root, {**INI, **before})
    _pytest(root, "--det", cache)
    _pytest(root)  # the user's plain run in between, as a developer runs it
    _write(root, after)
    _clean(root)  # as a fresh checkout: no file a test wrote in an earlier run
    p, o = _pytest(root, "--det", cache)
    _clean(root)
    plain, po = _pytest(root)
    assert plain.returncode == 1 and po.get(VICTIM) == "failed", plain.stdout[-1500:]  # the user's normal run
    _clean(root)
    det, do = _pytest(root, "--det")
    assert det.returncode == 1 and do.get(VICTIM) == "failed", det.stdout[-1500:]
    assert p.returncode == 1 and o.get(VICTIM) == "failed", (
        f"--det-cache reports {o} (exit {p.returncode}); plain pytest and --det fail {VICTIM}:\n{p.stdout[-2000:]}")


HELPER = {"helper.py": "STATE = {'mode': 'good'}\n"}
READS = "import helper\n\ndef test_victim():\n    assert helper.STATE['mode'] == 'good'\n"
POLLUTES = "import helper\n\ndef test_a():\n    helper.STATE['mode'] = 'bad'\n"
BENIGN = "def test_a():\n    pass\n"


def test_s1_only_the_earlier_test_changes_it_starts_writing_the_state_the_later_test_reads(tmp_path):
    """The prompt's attack: only the earlier test is edited. The victim passed (entry, needs []); the edited earlier
    test runs, the victim is reused as passed."""
    _check(tmp_path, {**HELPER, "tests/test_a.py": BENIGN, "tests/test_b.py": READS}, {"tests/test_a.py": POLLUTES})


def test_s3_a_failed_test_edited_to_read_the_state_is_not_given_its_old_loose_needs(tmp_path):
    """Decision (b): the victim failed for its own reason (no entry, ``loose_needs`` []); it is edited to read the
    state the earlier test writes. It runs with its old needs: the polluter is reused (not run), the victim passes."""
    _check(tmp_path, {**HELPER, "tests/test_a.py": POLLUTES, "tests/test_b.py": "def test_victim():\n    assert 0\n"},
           {"tests/test_b.py": READS})


def test_c3_interpreter_state_an_edited_earlier_test_starts_changing(tmp_path):
    """C state of the interpreter (the recursion limit), read by a victim that imports nothing."""
    _check(tmp_path, {"tests/test_a.py": BENIGN,
                      "tests/test_b.py": "def r(n):\n    return 0 if n == 0 else r(n - 1)\n\n"
                                         "def test_victim():\n    assert r(400) == 0\n"},
           {"tests/test_a.py": "import sys\n\ndef test_a():\n    sys.setrecursionlimit(120)\n"})


def test_c5_py08_a_file_an_edited_earlier_tests_child_process_writes(tmp_path):
    """PY-08: the earlier test is edited to start a process that writes a file the victim reads. The same write made
    in the test's own process is caught (the victim runs); made by its child process, the victim is reused as
    passed."""
    victim = ("def test_victim():\n    try:\n        with open('flag.txt') as f:\n            assert f.read() != 'bad'\n"
              "    except FileNotFoundError:\n        pass\n")
    _check(tmp_path, {"tests/test_a.py": BENIGN, "tests/test_b.py": victim},
           {"tests/test_a.py": "import subprocess, sys\n\ndef test_a():\n    subprocess.run([sys.executable, '-c', "
                               "\"open('flag.txt', 'w').write('bad')\"], check=True)\n"})
