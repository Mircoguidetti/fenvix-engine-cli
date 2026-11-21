"""F-03 / F-01: the verifier tells the truth (audit G-0139, G-0180, G-0041, G-0054 and their family: G-0514,
G-0515, G-0519, G-1517, G-1538, G-2218).

For every source the engine controls or observes, two real ``pytest --det`` runs that differ ONLY in that source
are reported divergent by ``fenvix verify`` / ``detpy verify``, with that source named as the first divergent event;
two runs that differ in nothing are reported identical. A test that uses a source this release does not control
(threads, child processes, I/O readiness) is never reported identical.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = '''
import asyncio, os, random, socket, subprocess, threading, time

def test_plain():
    assert 1 + 1 == 2

def test_reads_flag():
    assert os.environ.get("TRUTH_FLAG", "a") in ("a", "b")

def test_random():
    random.random()

def test_clock():
    time.time()
'''

UNCONTROLLED = '''
import asyncio, socket, subprocess, sys, threading

def test_thread():
    c = [0]
    def bump():
        for _ in range(10000):
            c[0] += 1
    ts = [threading.Thread(target=bump) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]

def test_executor_race():
    async def main():
        loop = asyncio.get_running_loop()
        await asyncio.gather(loop.run_in_executor(None, sum, [1]), loop.run_in_executor(None, sum, [2]))
    asyncio.run(main())

def test_child():
    subprocess.run([sys.executable, "-c", "pass"], check=True)

def test_io():
    async def main():
        a, b = socket.socketpair()
        a.setblocking(False)
        loop = asyncio.get_running_loop()
        loop.call_soon(b.send, b"x")  # sent after the loop starts waiting for a: readiness wakes it up
        assert await loop.sock_recv(a, 1) == b"x"
        a.close(); b.close()
    asyncio.run(main())

def test_no_source():
    assert True
'''


@pytest.fixture
def project(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_t.py").write_text(TESTS)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    return tmp_path


def _env(**extra) -> dict:
    env = dict(os.environ)
    for k in ("PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID",
              "TRUTH_FLAG", "PYTEST_CURRENT_TEST"):
        env.pop(k, None)
    env.update(extra)
    return env


def run_det(proj: Path, name: str, *args, env=None) -> Path:
    trace = proj / f"{name}.jsonl"
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", "--det",
                        f"--det-trace={trace}", *args], cwd=proj, env=env or _env(), capture_output=True, text=True,
                       timeout=600)
    assert trace.exists(), p.stdout + p.stderr
    return trace


def verify(*traces, extra=()) -> tuple[int, dict, str]:
    p = subprocess.run([sys.executable, "-m", "detpy.fenvix", "verify", *map(str, traces), *extra],
                       capture_output=True, text=True, timeout=120)
    j = subprocess.run([sys.executable, "-m", "detpy.fenvix", "verify", "--json", *map(str, traces), *extra],
                       capture_output=True, text=True, timeout=120)
    return p.returncode, json.loads(j.stdout), p.stdout + p.stderr


def _reasons(report) -> set:
    return {t["divergence"]["reason"] for t in report["tests"] if t.get("divergence")}


def test_same_inputs_are_identical(project):
    a = run_det(project, "a")
    b = run_det(project, "b")
    rc, rep, text = verify(a, b)
    assert rc == 0, text
    assert rep["summary"]["inputs_recorded"] is True
    assert rep["summary"]["stable"] == rep["summary"]["tests"] == 4
    assert "verdict: IDENTICAL" in text and "run inputs: identical in every run" in text
    # the header carries the shared vocabulary's fields and every input (G-2218)
    hdr = json.loads(a.read_text().splitlines()[0])["meta"]
    assert hdr["runtime"] == "CPython" and hdr["runtime_version"]
    for k in ("runtime", "runner", "hashseed", "seed", "clock", "tz", "locale", "env", "network", "fs", "urandom",
              "bytecode", "order"):
        assert k in hdr["inputs"], k
    assert any(k.startswith("env:") for k in hdr["inputs"])


# (name, run-a args/env, run-b args/env, reason named first)
FAMILY = [
    ("clock", ([], {}), (["--det-epoch=2025-02-01T00:00:00+00:00"], {}), "time"),
    ("seed", (["--det-seed=1"], {}), (["--det-seed=2"], {}), "seed"),
    ("hashseed", (["--det-disable=hashseed"], {"PYTHONHASHSEED": "1"}),
     (["--det-disable=hashseed"], {"PYTHONHASHSEED": "2"}), "hashseed"),
    ("network", ([], {}), (["--det-allow-host=example.invalid"], {}), "net"),
    ("fs", ([], {}), (["--det-disable=fs"], {}), "fs"),
    ("tz-pinned", (["--det-tz=UTC"], {}), (["--det-tz=Asia/Tokyo"], {}), "tz"),
    ("tz-kept", (["--det-tz=keep"], {"TZ": "UTC"}), (["--det-tz=keep"], {"TZ": "Asia/Tokyo"}), "tz"),
    ("locale-pinned", (["--det-locale=C.UTF-8"], {}), (["--det-locale=C"], {}), "locale"),
    ("locale-kept", (["--det-locale=keep"], {"LC_ALL": "C.UTF-8"}), (["--det-locale=keep"], {"LC_ALL": "C"}),
     "locale"),
    ("urandom", ([], {}), (["--det-urandom"], {}), "entropy"),
]


@pytest.mark.parametrize("name,a,b,reason", FAMILY, ids=[f[0] for f in FAMILY])
def test_runs_differing_in_one_source_are_divergent_and_name_it(project, name, a, b, reason):
    ta = run_det(project, "a", *a[0], env=_env(**a[1]))
    tb = run_det(project, "b", *b[0], env=_env(**b[1]))
    rc, rep, text = verify(ta, tb)
    assert rc == 1, text
    s = rep["summary"]
    assert s["stable"] == 0, f"{name}: a test was reported identical although {name} differs\n{text}"
    first = rep["input_differences"][0]
    assert first["reason"] == reason, (name, rep["input_differences"])
    # every test names the source; the test that read the variable names its own read (event with its site)
    for t in rep["tests"]:
        d = t["divergence"]
        assert d["reason"] == reason, (name, t["nodeid"], d)
    assert "verdict: DIVERGENT" in text and "run inputs: DIFFER" in text


def test_order_differing_only_in_order_is_divergent(project):
    ids = ["tests/test_t.py::test_plain", "tests/test_t.py::test_reads_flag", "tests/test_t.py::test_random",
           "tests/test_t.py::test_clock"]
    (project / "o1.txt").write_text("\n".join(ids) + "\n")
    (project / "o2.txt").write_text("\n".join(reversed(ids)) + "\n")
    ta = run_det(project, "a", f"--det-order={project / 'o1.txt'}")
    tb = run_det(project, "b", f"--det-order={project / 'o2.txt'}")
    rc, rep, text = verify(ta, tb)
    assert rc == 1, text
    assert rep["input_differences"] == []
    assert _reasons(rep) == {"order"}, text
    assert "it ran after different tests" in text


def test_env_read_is_input_differs_naming_the_variable_and_the_site(project):
    """Design A (2026-11-20): two runs that differ only in a variable a test reads: that test is INPUT DIFFERS (exit 3),
    naming the variable and the read's site; the tests that did not read it are identical; nothing diverged."""
    ta = run_det(project, "a", env=_env(TRUTH_FLAG="a"))
    tb = run_det(project, "b", env=_env(TRUTH_FLAG="b"))
    rc, rep, text = verify(ta, tb)
    assert rc == 3, text
    by = {t["nodeid"].split("::")[1]: t for t in rep["tests"]}
    t = by["test_reads_flag"]
    assert t["status"] == "input-differs", t
    assert t["divergence"]["description"].startswith("input differs: TRUTH_FLAG (read at tests/test_t.py:"), t
    assert by["test_plain"]["status"] == "stable"
    s = rep["summary"]
    assert (s["diverged"], s["input_differs"], s["missing"]) == (0, 1, 0), s
    assert "verdict: INPUT DIFFERS: TRUTH_FLAG: 1 of 4 tests" in text, text
    # the read event says which variable, never its value
    events = [json.loads(line) for line in ta.read_text().splitlines()[1:]]
    reads = [e for rec in events for e in rec.get("events", []) if e.get("o") == "env.get"]
    assert reads and all(e["v"] in ("TRUTH_FLAG=set", "TRUTH_FLAG=<unset>") for e in reads), reads


def test_env_difference_no_test_read_is_identical_and_listed(project):
    ta = run_det(project, "a", env=_env(TRUTH_OTHER="1"))
    tb = run_det(project, "b", env=_env(TRUTH_OTHER="2"))
    rc, rep, text = verify(ta, tb)
    assert rc == 0, text
    assert rep["env_not_read"] == ["env:TRUTH_OTHER"]
    assert "not compared: environment variables that differ but no test read: TRUTH_OTHER" in text


@pytest.mark.parametrize("var", ["GITHUB_RUN_ID", "RUNNER_TEMP", "EXAM_OUT", "SUDO_USER", "HTTPS_PROXY"])
def test_ci_volatile_variables_are_pinned_or_never_inputs(project, var):
    """Design A: run and attempt ids, runner and host names are pinned under --det; temp and workspace paths keep
    their values but are never inputs; FENVIX_VOLATILE_ENV adds a project's own (here a per-run output path); a sudo
    wrapper's session variables are never inputs; while the network is closed the proxy variables are its part."""
    extra = {"FENVIX_VOLATILE_ENV": "EXAM_*"} if var == "EXAM_OUT" else {}
    ta = run_det(project, "a", env=_env(**{var: "/run/1", **extra}))
    tb = run_det(project, "b", env=_env(**{var: "/run/2", **extra}))
    rc, rep, text = verify(ta, tb)
    assert rc == 0, text
    hdr = json.loads(ta.read_text().splitlines()[0])["meta"]["inputs"]
    assert f"env:{var}" not in hdr, hdr


def test_host_name_is_pinned(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_h.py").write_text(
        "import os, platform, socket\n"
        "def test_h():\n"
        "    print('HOST', socket.gethostname(), platform.node(), os.uname().nodename)\n")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "--det", "tests"],
                       cwd=tmp_path, env=_env(GITHUB_RUN_ID="12345"), capture_output=True, text=True, timeout=300)
    assert "HOST localhost localhost localhost" in p.stdout, p.stdout + p.stderr


def test_cpu_count_is_pinned_and_the_engine_keeps_the_real_one(tmp_path):
    """Design A, same class as the host name: CI runners differ in CPUs. Under --det every way a test reads the CPU
    count answers 2; the engine's own sizing (runtime identity, precompile workers) still sees the machine."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_c.py").write_text(
        "import multiprocessing, os\n"
        "from detpy import _machine, runtime_id\n"
        "def test_c():\n"
        "    aff = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else 2\n"
        "    pc = os.process_cpu_count() if hasattr(os, 'process_cpu_count') else 2\n"
        "    print('CPU', os.cpu_count(), pc, aff, multiprocessing.cpu_count())\n"
        "    print('ENGINE', _machine.cpu_count(), runtime_id._cpu_part()['cpu_count'])\n")
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider", "--det", "tests"],
                       cwd=tmp_path, env=_env(), capture_output=True, text=True, timeout=300)
    assert "CPU 2 2 2 2" in p.stdout, p.stdout + p.stderr
    real = os.cpu_count()
    assert f"ENGINE {real} {real}" in p.stdout, p.stdout + p.stderr


def test_n_auto_is_sized_on_the_real_machine_under_det(tmp_path):
    """The pinned CPU count is the tests' view; `-n auto` is the engine's planning and uses the machine."""
    pytest.importorskip("xdist")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_c.py").write_text("def test_c():\n    pass\n")
    env = _env()
    env.pop("PYTEST_XDIST_AUTO_NUM_WORKERS", None)
    plain = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-n", "auto", "tests"],
                           cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    det = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--det", "-n", "auto", "tests"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    workers = [re.search(r"created: (\d+)/\d+ workers", p.stdout) for p in (plain, det)]
    assert all(workers), plain.stdout + det.stdout + det.stderr
    assert workers[0].group(1) == workers[1].group(1), (plain.stdout, det.stdout)


def test_declared_irrelevant_env_is_listed_and_ignored(project):
    ta = run_det(project, "a", env=_env(TRUTH_OTHER="1"))
    tb = run_det(project, "b", env=_env(TRUTH_OTHER="2"))
    rc, rep, text = verify(ta, tb, extra=["--ignore-env", "TRUTH_*"])
    assert rc == 0, text
    assert rep["ignored_inputs"] == ["env:TRUTH_OTHER"]
    assert "ignored at your request (--ignore-env): env:TRUTH_OTHER" in text


def test_uncontrolled_sources_are_never_identical(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_u.py").write_text(UNCONTROLLED)
    a = run_det(tmp_path, "a")
    b = run_det(tmp_path, "b")
    rc, rep, text = verify(a, b)
    assert rc == 1, text
    by = {t["nodeid"].split("::")[1]: t for t in rep["tests"]}
    assert by["test_no_source"]["status"] == "stable"
    assert by["test_thread"]["divergence"]["reason"] == "thread", by["test_thread"]
    # G-0180: an asyncio executor race (threads under the loop)
    assert by["test_executor_race"]["divergence"]["reason"] == "thread", by["test_executor_race"]
    assert by["test_child"]["divergence"]["reason"] == "child", by["test_child"]
    assert by["test_io"]["divergence"]["reason"] == "io", by["test_io"]
    assert "not controlled by this release" in text


def test_detpy_verify_agrees_and_empty_runs_verify_nothing(tmp_path, project):
    a = run_det(project, "a")
    b = run_det(project, "b", env=_env(TRUTH_FLAG="b"))
    p = subprocess.run([sys.executable, "-m", "detpy", "verify", str(a), str(b)], capture_output=True, text=True)
    assert p.returncode == 3 and "[env]" in p.stdout and "INPUT DIFFERS" in p.stdout, p.stdout  # design A
    # G-1538: two runs where nothing was collected
    (tmp_path / "empty").mkdir()
    e1 = run_det(tmp_path / "empty", "e1")
    e2 = run_det(tmp_path / "empty", "e2")
    for cmd in (["detpy", "verify"], ["detpy.fenvix", "verify"]):
        p = subprocess.run([sys.executable, "-m", *cmd, str(e1), str(e2)], capture_output=True, text=True)
        assert p.returncode == 1 and "NOTHING VERIFIED" in p.stdout, p.stdout
    # G-2204: a missing trace is one line, no traceback
    p = subprocess.run([sys.executable, "-m", "detpy", "verify", str(a), str(tmp_path / "nope.jsonl")],
                       capture_output=True, text=True)
    assert p.returncode == 2 and "trace not found" in p.stderr and "Traceback" not in p.stderr


def test_parallel_trace_records_inputs(project):
    pytest.importorskip("xdist")
    a = run_det(project, "ser")
    b = run_det(project, "par", "-n", "2")
    hdr = json.loads(b.read_text().splitlines()[0])["meta"]
    assert hdr.get("inputs", {}).get("tz") == json.loads(a.read_text().splitlines()[0])["meta"]["inputs"]["tz"]
    _, rep, _ = verify(a, b)
    assert rep["input_differences"] == [], rep["input_differences"]
