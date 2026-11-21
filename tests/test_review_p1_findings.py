"""Reviewer p1-verifier findings #5, #8, #9 and #10 (F-02, F-03, F-18), copied unchanged from the review branch
(claude/review-p1-verifier, tests/test_review_p1_verifier.py). The review's other findings belong to other sessions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PY = sys.executable


def _write(root: Path, files: dict) -> None:
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))


def _env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DETPY_", "PYTEST_"))}
    env.update(extra)
    return env


def _det_run(root: Path, trace: Path, *args, env=None) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "-p", "no:randomly", "--det",
                           f"--det-trace={trace}", *args], cwd=root, capture_output=True, text=True,
                          env=env or _env(), timeout=600)


def _fenvix(root: Path, *args, timeout=900) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-m", "detpy.fenvix", *args], cwd=root, capture_output=True, text=True, env=_env(),
                          timeout=timeout)


def test_f02_repro_does_not_name_a_polluter_that_is_not_the_cause(tmp_path):
    """F-02: the failure comes from state outside the process (here a counter file: every other run of the test
    fails, deterministic; in the wild /dev/urandom, the PID, a service); no other test has any effect on it.
    `fenvix repro` must not declare 'test order: it fails when run after <another test>'. Measured by hand with a
    /dev/urandom test instead: 'cause: test order: it fails when run after tests/test_flaky_leak.py::test_tempname'."""
    counter = tmp_path / "counter.txt"
    _write(tmp_path, {
        "tests/test_a.py": "def test_noop():\n    pass\n",
        "tests/test_b.py": f"""
            def test_noise():
                p = {str(counter)!r}
                try:
                    n = int(open(p).read())
                except OSError:
                    n = 0
                open(p, "w").write(str(n + 1))
                assert n % 2 == 1
        """,
    })
    r = _fenvix(tmp_path, "repro", "tests/test_b.py::test_noise", "--seeds", "10", "--confirm", "4",
                "--out", str(tmp_path / "rep"))
    cause = next((line for line in r.stdout.splitlines() if line.strip().startswith("cause:")), "")
    assert "fails when run after" not in cause, r.stdout + r.stderr


def test_f18_explore_does_not_exit_0_when_the_suite_cannot_run(tmp_path):
    """F-18: a suite with a syntax error is reported as '0 flaky failing tests' with exit 0."""
    _write(tmp_path, {"tests/test_broken.py": "def test_ok(:\n    pass\n"})
    r = _fenvix(tmp_path, "explore", "--budget", "0.3", "--max-seeds", "2", "--out", str(tmp_path / "ex"))
    assert r.returncode != 0, f"exit 0 for a suite that cannot be collected:\n{r.stdout}{r.stderr}"


def test_f02_replay_outside_the_project_is_an_error_not_a_fix(tmp_path):
    """F-02: `fenvix replay BUNDLE` run from another directory collects nothing and reports 'NOT REPRODUCED ...
    fixed'. It must say the test was not found (exit 2), never suggest the defect is fixed."""
    proj = tmp_path / "proj"
    _write(proj, {
        "tests/__init__.py": "",
        "tests/state.py": "FLAG = {}\n",
        "tests/test_a.py": "from tests.state import FLAG\ndef test_polluter():\n    FLAG['x'] = 1\n",
        "tests/test_b.py": "from tests.state import FLAG\ndef test_victim():\n    assert 'x' not in FLAG\n",
    })
    r = _fenvix(proj, "repro", "tests/test_b.py::test_victim", "--seeds", "2", "--confirm", "2",
                "--out", str(tmp_path / "rep"))
    assert r.returncode == 0, r.stdout + r.stderr
    bundle = next((tmp_path / "rep").glob("test_victim-*"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    r = _fenvix(elsewhere, "replay", str(bundle), "--runs", "2")
    assert r.returncode == 2 and "fixed" not in r.stdout, f"exit {r.returncode}:\n{r.stdout}{r.stderr}"


def test_f03_traces_without_run_inputs_are_not_called_identical(tmp_path):
    """G-0041 / G-0054: fenvix-go and the JVM agent record no run inputs (meta.inputs). `fenvix verify` prints
    'run inputs: NOT RECORDED' and still 'verdict: IDENTICAL: all tests ran with the same inputs', exit 0. Measured
    with fenvix-go: TZ=Asia/Tokyo FOO=bar vs default gave '1970-01-01 09:00:00 +0900 JST bar' vs
    '1970-01-01 00:00:00 +0000 UTC'. The traces below have the header fenvix-go writes."""
    head = {"type": "header", "format": "detpy-trace", "version": 1, "encoding": 2,
            "meta": {"controls": ["time"], "runner": "go test", "runtime": "go", "seed": 0}, "order": []}
    rec = {"type": "test", "nodeid": "g1::TestTZ", "index": 0, "outcome": "passed",
           "fingerprint": "31af55e422bc4accd412eab03c7f8ad0", "n_events": 1, "truncated": False,
           "counts": {"outcome": 1}, "checkpoints": [],
           "events": [{"t": 0, "s": "outcome", "o": "outcome", "at": "<end>", "v": "passed"}]}
    traces = []
    for i in range(2):
        p = tmp_path / f"go{i}.jsonl"
        p.write_text(json.dumps(head) + "\n" + json.dumps(rec) + "\n")
        traces.append(p)
    r = _fenvix(tmp_path, "verify", *map(str, traces))
    if "ERROR" in r.stdout or r.returncode == 2:
        pytest.skip(f"trace format not accepted here: {r.stdout}{r.stderr}")
    assert r.returncode != 0 or "IDENTICAL: all" not in r.stdout, r.stdout
