"""Review R-013, round 2: each test here fails on the fix commit (49f0bd5) and names one defect.

5. The second fresh run now runs the test alone in a new process. For a test whose result depends on what ran
   before it in the session (order-dependent: state left by an earlier test, a session fixture's state), that run
   disagrees with the first fresh run, so a cached result contradicted by BOTH fresh runs is classified "flaky with
   evidence": the key is not marked untrusted, nothing reaches the shared cache, and every machine whose mirror holds
   the wrong entry keeps reusing it. On 5c77597 (second run in the same process) the same case was caught as wrong.
"""
from __future__ import annotations

import sys

import pytest

from test_review_r013 import _clean, call, forge_skipped_entry, machine_run, service, write  # noqa: F401

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

ORDER_DEPENDENT = """
    import state

    def test_a_sets_up():
        state.READY.append(1)

    def test_b_uses_it():
        assert state.READY
"""


def test_r013_5_wrong_skip_of_an_order_dependent_test_is_marked_on_the_shared_cache(
        service, pytester, tmp_path, monkeypatch):
    """Why it matters: P-024 item 5 ("any wrong skip pages us and disables reuse for that key"). The cached result
    says skipped; the test passes in the session (first fresh run) and fails alone (second fresh run): neither
    fresh run reproduces the cached result, so reusing it is wrong on every machine. The audit calls it flaky, drops
    the entry on the auditing machine only, marks nothing, counts it as not wrong in the bound, and machine 3 (warm
    mirror) skips the test again."""
    svc, t = service
    _clean(monkeypatch)
    write(pytester.path, {"pytest.ini": "[pytest]\n", "state.py": "READY = []\n", "test_m.py": ORDER_DEPENDENT})
    url = f"{svc.url}/proj"
    nid = "test_m.py::test_b_uses_it"
    machine_run(pytester, tmp_path, url, t["a"], "1", "--det-cache-audit=0")
    forge_skipped_entry(svc, t, tmp_path, nid)
    _, o3, _ = machine_run(pytester, tmp_path, url, t["a"], "3", "--det-cache-audit=0")
    assert o3["outcomes"][nid] == "skipped" and nid in o3["cache"]["reused_ids"]
    # machine 2 audits every reusable result: both fresh runs contradict the cached "skipped"
    _, o2, rep2 = machine_run(pytester, tmp_path, url, t["a_ro"], "2", "--det-cache-audit=1")
    res = o2["cache"]["audit"]
    assert res["wrong"] == 1, f"cached skipped, fresh passed then failed alone: audit says {res}"
    assert [m["nodeid"] for m in call(svc, t["a"], "GET", "/v1/ns/proj/untrusted")["untrusted"]] == [nid]
    _, o3b, _ = machine_run(pytester, tmp_path, url, t["a"], "3", "--det-cache-audit=0")
    assert nid not in o3b["cache"]["reused_ids"], "machine 3 still reuses the wrong skipped result"
