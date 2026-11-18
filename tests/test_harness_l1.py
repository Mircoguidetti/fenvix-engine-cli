"""Harness of the l1-threads rounds (review R-007 FIX 2 and FIX 3)."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))


def test_a_run_that_fails_as_a_session_is_a_broken_run():
    import l1_threads as L

    timing = [
        {"mode": "det", "run": 0, "exit": 0, "session_failed": False},
        {"mode": "l1-s1", "run": 0, "exit": 1, "session_failed": True},  # --cov-fail-under, 0 failed tests
        {"mode": "l1-s2", "run": 0, "exit": 0, "session_failed": False},
    ]
    assert L.broken_runs(timing, "det", "l1-s1") == [0]
    assert L.broken_runs(timing, "det", "l1-s2") == []
    # the reference fails as a session too: not caused by the mode under test
    timing[0]["session_failed"] = True
    assert L.broken_runs(timing, "det", "l1-s1") == []


def _suite(name, det, l1, seeds):
    timing = [{"mode": "plain", "run": 0, "duration_s": det, "timed_out": False},
              {"mode": "det", "run": 0, "duration_s": det, "timed_out": False},
              {"mode": "l1", "run": 0, "duration_s": l1, "timed_out": False,
               "stats": {"managed": 2, "escapes": 0, "deadlocks": 0}}]
    for sd, v in seeds.items():
        timing.append({"mode": f"l1-s{sd}", "run": 0, "duration_s": v, "timed_out": False})
    r = {"name": name, "status": "ok", "kind": "suite", "suite_seeds": list(seeds), "timing": timing,
         "broken_by_det": {}, "broken_by_l1": {}}
    for sd in seeds:
        r[f"broken_by_l1_s{sd}"] = {}
    return r


def test_seed_slowdown_takes_one_value_per_suite(tmp_path):
    rd = tmp_path / "f9"
    rd.mkdir()
    # anyio with 3 seeds at +10% each and four suites at +100%: pooled, the median
    # was +10% (anyio counted 3 times); one value per suite gives +100%.
    suites = {"anyio": {1: 110, 2: 110, 3: 110}, "requests": {1: 110, 2: 110, 3: 110},
              "networkx": {1: 200}, "structlog": {1: 200}, "more-itertools": {1: 200}}
    for name, seeds in suites.items():
        (rd / f"{name}.suite.json").write_text(json.dumps(_suite(name, 100.0, 100.0, seeds)))
    out = subprocess.run([sys.executable, str(ROOT / "harness" / "l1_threads_final_table.py"), str(tmp_path), "f9",
                          str(tmp_path / "t.json")], capture_output=True, text=True, check=True).stdout
    line = next(x for x in out.splitlines() if x.startswith("heavy seeds"))
    assert "median 100.0" in line, line
