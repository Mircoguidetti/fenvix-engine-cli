"""Point 6: per-test fingerprints and cross-run verification."""

import json
import subprocess
import sys

STABLE = """
import os, random, time, datetime
def test_mixed(tmp_path):
    (tmp_path / "b").touch(); (tmp_path / "a").touch()
    assert os.listdir(tmp_path) == ["a", "b"]
    time.sleep(1)
    print(time.time(), random.random(), datetime.datetime.now())
def test_plain():
    assert 1 + 1 == 2
"""


def verify(*traces):
    out = subprocess.run([sys.executable, "-m", "detpy", "verify", "--json", *map(str, traces)],
                         capture_output=True, text=True)
    return out.returncode, json.loads(out.stdout)


def test_stable_suite_is_covered(pytester, run_det):
    pytester.makepyfile(test_s=STABLE)
    p1, p2 = pytester.path / "1.jsonl", pytester.path / "2.jsonl"
    run_det(trace=str(p1))
    run_det(trace=str(p2))
    code, rep = verify(p1, p2)
    assert code == 0
    assert rep["summary"]["stable"] == 2 and rep["summary"]["diverged"] == 0
    assert rep["summary"]["order_identical"]


def test_entropy_is_reported_with_exact_site(pytester, run_det):
    pytester.makepyfile(
        test_u="""
        import time, uuid
        def test_uuid():
            time.time()
            token = uuid.uuid4()
            return token
        """
    )
    p1, p2 = pytester.path / "1.jsonl", pytester.path / "2.jsonl"
    run_det(trace=str(p1))
    result, _ = run_det(f"--det-compare={p1}", trace=str(p2))
    result.stdout.fnmatch_lines([
        "*covered=0 not-covered=1*",
        "*NOT COVERED by Level 0: test_u.py::test_uuid [[]entropy[]]*",
        "*event #1: os.urandom @ test_u.py:4 returned different values*",
    ])
    code, rep = verify(p1, p2)
    assert code == 1
    d = rep["tests"][0]["divergence"]
    assert d["index"] == 1 and d["reason"] == "entropy"
    assert d["event_a"]["at"] == "test_u.py:4"


def test_urandom_control_makes_entropy_deterministic(pytester, run_det):
    pytester.makepyfile(test_u="import uuid\ndef test_uuid():\n    print('UUID', uuid.uuid4())\n")
    p1, p2 = pytester.path / "1.jsonl", pytester.path / "2.jsonl"
    run_det("--det-urandom", trace=str(p1))
    run_det("--det-urandom", trace=str(p2))
    code, rep = verify(p1, p2)
    assert code == 0


def test_control_flow_divergence(pytester, run_det):
    # The second run takes another branch: one extra clock read.
    pytester.makepyfile(
        test_b="""
        import os, time
        def test_branch():
            if os.path.exists("marker"):
                time.monotonic()
            open("marker", "w").close()
        """
    )
    p1, p2 = pytester.path / "1.jsonl", pytester.path / "2.jsonl"
    run_det(trace=str(p1))
    run_det(trace=str(p2))
    _, rep = verify(p1, p2)
    d = rep["tests"][0]["divergence"]
    assert d["reason"] == "time" and d["index"] == 0
    assert d["event_a"]["at"] == "<end>" and d["event_b"]["o"] == "time.monotonic"
    assert d["event_b"]["at"] == "test_b.py:4"


def test_outcome_only_divergence(pytester, run_det):
    # State the controls do not observe (file contents) flips the outcome.
    pytester.makepyfile(
        test_o="""
        import os
        def test_flip():
            n = int(open("count").read()) if os.path.exists("count") else 0
            open("count", "w").write(str(n + 1))
            assert n % 2 == 0
        """
    )
    p1, p2 = pytester.path / "1.jsonl", pytester.path / "2.jsonl"
    run_det(trace=str(p1))
    run_det(trace=str(p2))
    _, rep = verify(p1, p2)
    t = rep["tests"][0]
    assert not t["outcome_stable"] and t["outcomes"] == ["passed", "failed"]
    assert t["divergence"]["reason"] == "outcome-only"
    assert rep["summary"]["outcome_unstable"] == 1


def test_thread_interleaving_is_detected(pytester, run_det):
    pytester.makepyfile(
        test_t="""
        import sys, threading, time
        def test_threads():
            sys.setswitchinterval(1e-6)
            def work():
                for _ in range(3000):
                    time.monotonic()
            ts = [threading.Thread(target=work) for _ in range(3)]
            for t in ts: t.start()
            for t in ts: t.join()
        """
    )
    paths = [pytester.path / f"{i}.jsonl" for i in range(3)]
    for p in paths:
        run_det(trace=str(p))
    _, rep = verify(*paths)
    t = rep["tests"][0]
    assert t["distinct_fingerprints"] > 1
    assert t["divergence"]["reason"] in ("thread", "beyond-trace")


def test_divergence_beyond_stored_events(pytester, run_det):
    pytester.makepyfile(
        test_l="""
        import os, time
        def test_long():
            for _ in range(50):
                time.monotonic()
            os.urandom(4)
        """
    )
    p1, p2 = pytester.path / "1.jsonl", pytester.path / "2.jsonl"
    run_det("--det-max-events=5", trace=str(p1))
    run_det("--det-max-events=5", trace=str(p2))
    _, rep = verify(p1, p2)
    d = rep["tests"][0]["divergence"]
    assert d["reason"] == "beyond-trace" and d["index"] is None
    lo, hi = d["window"]
    assert lo <= 50 < hi


def test_trace_structure(pytester, run_det):
    pytester.makepyfile(test_s=STABLE)
    _, (header, tests, footer) = run_det()
    assert header["format"] == "detpy-trace" and header["version"] == 1
    assert header["meta"]["hashseed"] == "0"
    assert footer["n_tests"] == 2
    rec = tests["test_s.py::test_mixed"]
    assert rec["outcome"] == "passed" and len(rec["fingerprint"]) == 32
    assert rec["counts"]["time"] >= 3 and rec["counts"]["fs"] == 1 and rec["counts"]["random"] >= 2
    assert rec["events"][-1] == {"t": 0, "s": "outcome", "o": "outcome", "at": "", "v": "passed"}


def test_outcomes_file_without_det(pytester):
    pytester.makepyfile(
        test_x="""
        import pytest
        def test_ok(): pass
        def test_bad(): assert 0
        @pytest.mark.xfail
        def test_xf(): assert 0
        @pytest.fixture
        def broken(): raise RuntimeError
        def test_err(broken): pass
        @pytest.mark.skip
        def test_skip(): pass
        """
    )
    out = pytester.path / "outcomes.json"
    pytester.runpytest_subprocess(f"--det-outcomes={out}")
    data = json.loads(out.read_text())
    assert data["outcomes"] == {
        "test_x.py::test_ok": "passed",
        "test_x.py::test_bad": "failed",
        "test_x.py::test_xf": "xfailed",
        "test_x.py::test_err": "error",
        "test_x.py::test_skip": "skipped",
    }
    assert data["exitstatus"] == 1
