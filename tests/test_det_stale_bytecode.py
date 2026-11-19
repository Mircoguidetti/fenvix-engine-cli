"""Review R-019b N5 (engine), ported from ``harness/culprit/review_r019b/test_wrong_culprits_r2.py``
(``test_det_replay_runs_the_checked_out_source_not_stale_bytecode``) on ``claude/review-r019b``.

The product situation: a reused CI workspace, a plain ``git checkout`` (no fresh mtimes), two versions of a project
module with the same size and the same mtime second. Bytecode validated by ``(mtime seconds, size)`` then runs the
previous version, and the proof key (computed from the source) pairs the new source's digest with the old
outcome: a cached false pass. Under ``--det`` every imported project module must run the checked-out source."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

EPOCH = "2026-01-01T00:00:00"
_DROP = ("PYTHONHASHSEED", "DETPY_REEXEC", "PYTHONPATH", "PYTEST_ADDOPTS", "PYTHONDONTWRITEBYTECODE",
         "PYTHONPYCACHEPREFIX", "DETPY_PRECOMPILE_S", "PYTHONWARNINGS")


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def _commit(repo: Path, msg: str, files: dict) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _run_det(repo: Path, nodeid: str, args=(), cache: Path | None = None) -> tuple[str, str]:
    """One ``--det`` run (as the culprit harness's ``run_det``: an empty proof cache unless ``cache`` is given); the
    bytecode caches are the real ones, as in a reused workspace."""
    tmp = tempfile.mkdtemp(prefix="detrun-")
    out = os.path.join(tmp, "outcomes.json")
    env = {k: v for k, v in os.environ.items() if k not in _DROP}
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--det", f"--det-epoch={EPOCH}",
           f"--det-cache={cache or tmp + '/cache'}", f"--det-outcomes={out}", "--tb=short", *args]
    p = subprocess.run([*cmd, nodeid], cwd=repo, env=env, capture_output=True, text=True)
    try:
        with open(out) as fh:
            o = json.load(fh)["outcomes"].get(nodeid)
    except (OSError, ValueError, KeyError):
        o = None
    shutil.rmtree(tmp, ignore_errors=True)
    return {"passed": "pass", "failed": "fail"}.get(o, f"? exit {p.returncode}"), p.stdout[-1500:]


GREEN = "def f(x):\n    return x + 1 + 0 * 4\n"
BAD = "def f(x):\n    return x * 3 + 0 * 8\n"  # same size


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    g0 = _commit(repo, "green", {"pytest.ini": "[pytest]\n", "pkg/__init__.py": "", "pkg/m.py": GREEN,
                                 "test_m.py": "from pkg import m\n\ndef test_f():\n    assert m.f(1) == 2\n"})
    bad = _commit(repo, "same-size break", {"pkg/m.py": BAD})
    assert len(GREEN) == len(BAD)
    return repo, g0, bad


# The reviewer's case ran an engine whose --det always used timestamp pycs. On this engine, --det with its
# bytecode control reads only the precompile's checked-hash pycs; without the control (no re-exec, the control
# disabled, or a re-exec that is not possible) it used the project's own __pycache__ (timestamp pycs).
MODES = {"default": (), "no-reexec": ("--det-no-reexec",), "bytecode-disabled": ("--det-disable=bytecode",)}


@pytest.mark.parametrize("mode", list(MODES))
def test_det_runs_the_checked_out_source_not_stale_bytecode(tmp_path, mode):
    """The ported N5 case (5 rounds there, 3 here): a plain checkout of a same-size version in the same mtime
    second; the ``--det`` run must run the checked-out source."""
    repo, g0, bad = _repo(tmp_path)
    nid = "test_m.py::test_f"
    outs = []
    for _ in range(3):
        _git(repo, "checkout", "-q", g0)
        stamp = int(time.time())
        os.utime(repo / "pkg/m.py", (stamp, stamp))  # what a checkout in the same second as the next one leaves
        o_green = _run_det(repo, nid, MODES[mode])
        _git(repo, "checkout", "-q", bad)
        os.utime(repo / "pkg/m.py", (stamp, stamp))
        o_bad = _run_det(repo, nid, MODES[mode])
        outs.append((o_green[0], o_bad[0]))
        assert outs[-1] == ("pass", "fail"), f"--det ran the other version's bytecode: {outs}\n{o_bad[1]}"


@pytest.mark.parametrize("mode", list(MODES))
def test_det_cache_does_not_record_a_false_pass(tmp_path, mode):
    """With ``--det-cache``: the run at the bad version re-runs (its source digest changed) and must record its
    failure, not the green version's pass; a third run reuses that failure."""
    repo, g0, bad = _repo(tmp_path)
    cache = tmp_path / "proofs"
    stamp = int(time.time())
    _git(repo, "checkout", "-q", g0)
    os.utime(repo / "pkg/m.py", (stamp, stamp))
    assert _run_det(repo, "test_m.py::test_f", MODES[mode], cache)[0] == "pass"
    _git(repo, "checkout", "-q", bad)
    os.utime(repo / "pkg/m.py", (stamp, stamp))
    o, tail = _run_det(repo, "test_m.py::test_f", MODES[mode], cache)
    assert o == "fail", "recorded a false pass for the bad source:\n" + tail
    assert _run_det(repo, "test_m.py::test_f", MODES[mode], cache)[0] == "fail"


def test_pyc_written_without_bytecode_control_is_checked_hash(tmp_path):
    """Without the bytecode control, a project module's pyc is written as a checked-hash pyc (PEP 552 flags 3),
    which plain Python validates by hash too; a library's is left to the import system."""
    repo, g0, bad = _repo(tmp_path)
    _git(repo, "checkout", "-q", g0)
    assert _run_det(repo, "test_m.py::test_f", ("--det-no-reexec",))[0] == "pass"
    (pyc,) = (repo / "pkg" / "__pycache__").glob("m.*.pyc")
    assert int.from_bytes(pyc.read_bytes()[4:8], "little") == 3
