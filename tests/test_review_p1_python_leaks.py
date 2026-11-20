"""Review P1 findings 3 and 4 (rows F-01, F-03; audit G-0180), copied verbatim from
claude/review-p1-verifier:tests/test_review_p1_verifier.py (the tests of findings 3 and 4; the other four tests of
that file belong to findings 5, 8, 9 and 10, fixed on claude/verifier-cli). Every test here FAILS on
release-1 @ 71f8081. Finding 11's test is tests/test_verifier_truth.py::test_parallel_trace_records_inputs.

Run: python -m pytest -q -p no:randomly tests/test_review_p1_python_leaks.py

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
