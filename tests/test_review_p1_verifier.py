"""Review P1 (rows F-01, F-02, F-03, F-18; audit G-0180, G-0041 and their family). Every test here FAILS on
release-1 @ 71f8081: they are findings, not fixes.

Run: python -m pytest -q -p no:randomly tests/test_review_p1_verifier.py

Shape of the verifier tests: run the same small project twice under ``pytest --det`` with identical inputs; every test
prints the value it observed. When a value differs between the two runs, ``fenvix verify`` must not report that test
identical (F-03: "never say same when the runs differ").
"""

from __future__ import annotations

import json
import os
import re
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


def _values(out: str) -> dict:
    return dict(m.groups() for m in re.finditer(r"^\.?VAL (\S+) (.*)$", out, re.M))


def _verify(root: Path, traces: list) -> dict:
    r = _fenvix(root, "verify", "--json", *map(str, traces))
    return json.loads(r.stdout)


LEAKS = {
    "tests/test_leaks.py": """
        import os, tempfile, hashlib, _thread, threading, concurrent.futures as cf

        def val(name, v):
            print(f"VAL {name} {v}")

        def test_pid():
            val("pid", os.getpid())

        def test_tempfile_name():
            val("tempfile_name", os.path.basename(tempfile.mkdtemp()))

        def test_dev_urandom():
            with open("/dev/urandom", "rb") as f:
                val("dev_urandom", f.read(8).hex())

        def test_proc_uptime():
            val("proc_uptime", open("/proc/uptime").read().split()[0])

        def test_outside_file():
            val("outside_file", open(os.environ["P1_OUTSIDE"]).read().strip())

        def _work(tag, out):
            for _ in range(150):
                hashlib.sha256(b"x" * 200000).digest()  # releases the GIL
                out.append(tag)

        def test_raw_thread_race():
            out, done = [], []
            def w(t):
                _work(t, out); done.append(1)
            _thread.start_new_thread(w, ("a",)); _thread.start_new_thread(w, ("b",))
            while len(done) < 2:
                pass
            val("raw_thread_race", hashlib.md5("".join(out).encode()).hexdigest())

        _B = threading.Barrier(5)
        POOL = cf.ThreadPoolExecutor(4)
        for _ in range(4):
            POOL.submit(_B.wait)
        _B.wait()

        def test_prestarted_pool_race():
            out = []
            for f in [POOL.submit(_work, t, out) for t in "abcd"]:
                f.result()
            val("prestarted_pool_race", hashlib.md5("".join(out).encode()).hexdigest())
    """,
}


def test_f03_no_test_whose_value_differs_is_reported_identical(tmp_path):
    """G-0180 (threads started with ``_thread`` or before the test), and sources the fixes did not reach: the PID,
    tempfile names, /dev/urandom read as a file, /proc/uptime, a file outside the project."""
    _write(tmp_path, LEAKS)
    outside = tmp_path / "outside.txt"
    vals, traces = [], []
    for i, content in enumerate(("A", "B")):
        outside.write_text(content)
        t = tmp_path / f"t{i}.jsonl"
        r = _det_run(tmp_path, t, "tests", env=_env(P1_OUTSIDE=str(outside)))
        assert r.returncode == 0, r.stdout + r.stderr
        vals.append(_values(r.stdout))
        traces.append(t)
    rep = _verify(tmp_path, traces)
    wrong = []
    for t in rep["tests"]:
        name = t["nodeid"].split("::")[-1].removeprefix("test_")
        if name in vals[0] and vals[0][name] != vals[1].get(name) and t["status"] == "stable":
            wrong.append(f"{name}: {vals[0][name]} vs {vals[1].get(name)}")
    assert not wrong, "verify reported these tests identical although their values differed:\n" + "\n".join(wrong)


def test_f03_a_test_that_uses_threads_is_never_reported_identical(tmp_path):
    """The rule of python/detpy/uncontrolled.py (G-0180): a test that uses threads is never identical. Deterministic
    check: both tests use threads, whatever values they printed."""
    _write(tmp_path, LEAKS)
    (tmp_path / "outside.txt").write_text("A")
    traces = []
    for i in range(2):
        t = tmp_path / f"t{i}.jsonl"
        r = _det_run(tmp_path, t, "tests/test_leaks.py::test_raw_thread_race",
                     "tests/test_leaks.py::test_prestarted_pool_race", env=_env(P1_OUTSIDE=str(tmp_path / "outside.txt")))
        assert r.returncode == 0, r.stdout + r.stderr
        traces.append(t)
    rep = _verify(tmp_path, traces)
    stable = [t["nodeid"] for t in rep["tests"] if t["status"] == "stable"]
    assert stable == [], f"reported identical although they ran threads: {stable}"


def test_f01_det_result_does_not_depend_on_the_pid_or_os_entropy(tmp_path):
    """F-01: identical --det runs give different results (the PID and /dev/urandom are neither controlled nor
    observed). Eight runs of the same suite must have one outcome per test."""
    _write(tmp_path, {"tests/test_flip.py": """
        import os
        def test_pid_parity():
            assert os.getpid() % 2 == 0
        def test_dev_urandom():
            with open("/dev/urandom", "rb") as f:
                assert f.read(1)[0] < 128
    """})
    outcomes = set()
    for i in range(8):
        r = _det_run(tmp_path, tmp_path / f"t{i}.jsonl", "tests")
        outcomes.add(r.stdout.strip().splitlines()[-1].split(" in ")[0])
    assert len(outcomes) == 1, f"8 identical --det runs gave {sorted(outcomes)}"


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
