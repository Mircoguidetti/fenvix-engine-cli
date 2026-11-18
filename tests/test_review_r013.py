"""Review R-013 (cache audit, P-025): each test here fails on the delivered commit and names one defect.

1. A key marked untrusted on the shared cache is still reused by every machine whose local mirror already holds the
   wrong entry (marks are pushed, never pulled): the mark does not reach "all machines".
2. The second "fresh" run that tells a wrong skip from a flaky test runs in the same process right after the first,
   so a test whose result is the same in every fresh run is called flaky and its wrong entry stays reusable.
3. The audit compares the entry's ``outcome`` field, but reuse replays the entry's ``report``: an entry whose report
   says skipped while its outcome says passed is reused as skipped and the audit calls it matched.
4. The service's per-project audit report (``GET /v1/audit``) leaves out every wrong skip found by a pull-request
   job (read-only token): a project with a wrong skip marked on that very service reports wrong = 0.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from detpy import cache_service as cs
from detpy import remote_cache as rc

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def write(root: Path, files: dict) -> None:
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))


@pytest.fixture
def run_cache(pytester):
    counter = {"n": 0}

    def run(*args):
        counter["n"] += 1
        out = pytester.path / f"out{counter['n']}.json"
        r = pytester.runpytest_subprocess("--det", f"--det-cache={pytester.path / '.cachedir'}",
                                          f"--det-outcomes={out}", "-p", "no:cacheprovider", *args)
        data = json.loads(out.read_text()) if out.exists() else {}
        return r, data

    return run


def store_path(pytester) -> Path:
    return pytester.path / ".cachedir" / "proof-cache.json"


PLANT = """
    def test_planted():
        assert 1 + 1 == 2

    def test_other():
        assert True
"""


# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def service(tmp_path):
    svc = cs.Service(str(tmp_path / "svc"), port=0, quiet=True)
    svc.start_thread()
    tokens = {"a": cs.Tokens.add(os.path.join(svc.data, "tokens.json"), "org-a"),
              "a_ro": cs.Tokens.add(os.path.join(svc.data, "tokens.json"), "org-a", write=False)}
    yield svc, tokens
    svc.shutdown()


def call(svc, token, method, path, body=None):
    return rc.Http(svc.url, token, retries=0).call(method, path, body)


def machine_run(pytester, tmp_path, url, token, machine, *extra):
    report, outcomes = tmp_path / f"report-{machine}.json", tmp_path / f"outcomes-{machine}.json"
    os.environ["FENVIX_CACHE_LOCAL"] = str(tmp_path / f"machine-{machine}" / "mirror")
    os.environ["FENVIX_CACHE_REPORT"] = str(report)
    os.environ["FENVIX_RUNTIME_MEMO"] = str(tmp_path / f"machine-{machine}" / "runtime-memo.json")
    os.environ["FENVIX_CACHE_TOKEN"] = token
    r = pytester.runpytest_subprocess("--det", f"--det-cache={url}", f"--det-outcomes={outcomes}",
                                      f"--basetemp={tmp_path / f'basetemp-{machine}'}", "-p", "no:cacheprovider", *extra)
    return r, json.loads(outcomes.read_text()), json.loads(report.read_text())


def forge_skipped_entry(svc, t, tmp_path, nid: str) -> None:
    """File on the service, under the same key and proof key as machine 1's entry, a newer entry that says skipped
    (the test passes): a wrong result that every input check accepts."""
    st = json.loads((tmp_path / "machine-1" / "mirror" / "proof-cache.json").read_text())
    e = st["tests"][nid]
    lk = rc.lookup_key(nid, e["config"], e["runtime"], e.get("epoch"))
    good = call(svc, t["a"], "POST", "/v1/ns/proj/lookup", {"keys": [lk]})["found"][lk][0]
    doc = call(svc, t["a"], "POST", "/v1/blobs/get", {"ids": [good]})["docs"][good]
    forged = json.loads(json.dumps(doc))
    forged["entry"]["outcome"] = "skipped"
    forged["entry"]["report"] = {"setup": {"outcome": "passed"},
                                 "call": {"outcome": "skipped", "longrepr": ["test_m.py", 1, "Skipped: forged"]}}
    forged["entry"]["run"] = "forger"
    fid = cs.doc_id(forged)
    call(svc, t["a"], "POST", "/v1/blobs/put", {"docs": {fid: forged}})
    call(svc, t["a"], "POST", "/v1/ns/proj/keys", {"put": [{"key": lk, "doc": fid, "run": "forger"}]})


def _clean(monkeypatch):
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------------------------------------------------
def test_r013_1_untrusted_mark_reaches_machines_whose_mirror_already_holds_the_wrong_entry(
        service, pytester, tmp_path, monkeypatch):
    """Why it matters: P-024 item 5 and P-025 item 2 say a wrong skip disables reuse of that key everywhere. A
    runner with a warm mirror (the normal case: the mirror is the machine's cache directory) never asks the service
    about a test its local entry already proves, so it keeps skipping the test with the wrong result after another
    machine found and marked it."""
    svc, t = service
    _clean(monkeypatch)
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": PLANT})
    url = f"{svc.url}/proj"
    nid = "test_m.py::test_planted"
    machine_run(pytester, tmp_path, url, t["a"], "1", "--det-cache-audit=0")
    forge_skipped_entry(svc, t, tmp_path, nid)
    # machine 3 pulls the wrong entry into its mirror and reuses it (no audit chose it)
    _, o3, _ = machine_run(pytester, tmp_path, url, t["a"], "3", "--det-cache-audit=0")
    assert o3["outcomes"][nid] == "skipped" and nid in o3["cache"]["reused_ids"]
    # machine 2 audits it: wrong skip, key marked untrusted on the service
    _, o2, rep2 = machine_run(pytester, tmp_path, url, t["a_ro"], "2", "--det-cache-audit=1")
    assert o2["cache"]["audit"]["wrong"] == 1 and rep2["push_untrusted"] == 1
    assert call(svc, t["a"], "GET", "/v1/ns/proj/untrusted")["untrusted"]
    # machine 3 again: the key is untrusted on the service, so the wrong result must not be reused
    _, o3b, _ = machine_run(pytester, tmp_path, url, t["a"], "3", "--det-cache-audit=0")
    assert nid not in o3b["cache"]["reused_ids"], (
        "machine 3 reused a result whose proof key the shared cache marks untrusted: "
        f"miss reasons {o3b['cache'].get('miss_ids')}")
    assert o3b["outcomes"][nid] == "passed"


def test_r013_2_second_fresh_run_is_not_fresh_a_deterministic_test_is_called_flaky(pytester, run_cache):
    """Why it matters: the second run decides wrong vs flaky, but it runs in the same process right after the first,
    so whatever the first run left behind (module state, a cache, a file) changes it. Here the test passes in every
    fresh run (each pytest process), the cached result says skipped: a wrong skip. The audit calls it flaky with
    evidence, marks nothing, keeps the wrong entry, and the next run skips it again, while the bound counts it as a
    correct skip."""
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": """
        CALLS = []

        def test_once_per_process():
            CALLS.append(1)
            assert len(CALLS) == 1
    """})
    nid = "test_m.py::test_once_per_process"
    # the same result in every fresh run: deterministic
    for _ in range(3):
        r = pytester.runpytest_subprocess("-p", "no:cacheprovider")
        r.assert_outcomes(passed=1)
    run_cache()
    st = json.loads(store_path(pytester).read_text())
    st["tests"][nid]["outcome"] = "skipped"
    st["tests"][nid]["report"] = {"setup": {"outcome": "passed"},
                                  "call": {"outcome": "skipped", "longrepr": ["test_m.py", 1, "Skipped: planted"]}}
    store_path(pytester).write_text(json.dumps(st))
    r, d = run_cache("--det-cache-audit=1")
    a = d["cache"]["audit"]
    assert (a["checked"], a["wrong"], a["flaky_evidence"]) == (1, 1, 0), (
        f"a wrong skip of a deterministic test was classified {a['flaky_tests'] or a['wrong_tests']}")
    r, d = run_cache("--det-cache-audit=0")
    assert d["outcomes"][nid] == "passed" and nid not in d["cache"]["reused_ids"]


def test_r013_3_audit_compares_what_reuse_replays(pytester, run_cache):
    """Why it matters: reuse replays the entry's ``report`` phases; the audit compares the entry's ``outcome``
    field. An entry whose two fields disagree (corrupted, or forged by a job with a write token) is reused with a
    wrong result that the audit, even at 100%, calls matched: never caught, never marked."""
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": PLANT})
    nid = "test_m.py::test_planted"
    run_cache()
    st = json.loads(store_path(pytester).read_text())
    st["tests"][nid]["report"] = {"setup": {"outcome": "passed"},
                                  "call": {"outcome": "skipped", "longrepr": ["test_m.py", 1, "Skipped: planted"]}}
    store_path(pytester).write_text(json.dumps(st))  # outcome still says passed
    r, d = run_cache("--det-cache-audit=0")
    r.assert_outcomes(passed=1, skipped=1)  # the wrong result reuse shows
    assert d["outcomes"][nid] == "skipped" and nid in d["cache"]["reused_ids"]
    st["tests"][nid]["report"]["call"]["outcome"] = "skipped"
    store_path(pytester).write_text(json.dumps(st))
    r, d = run_cache("--det-cache-audit=1")
    a = d["cache"]["audit"]
    assert a["wrong"] == 1, f"cached result shown as skipped, fresh passed: audit says {a['matched']} matched, 0 wrong"


def test_r013_4_service_audit_report_counts_wrong_skips_found_by_pull_request_jobs(
        service, pytester, tmp_path, monkeypatch):
    """Why it matters: ``GET /v1/audit`` (and ``python -m detpy.audit_report --service``) is one of the two places
    the per-project bound is reported. It sums only runs filed with a write token, so a wrong skip found by a
    pull-request job (read-only token), although marked on the same service, is not in ``wrong``: the project
    reports 0 wrong and the rule-of-three bound, which is false."""
    svc, t = service
    _clean(monkeypatch)
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": PLANT})
    url = f"{svc.url}/proj"
    nid = "test_m.py::test_planted"
    machine_run(pytester, tmp_path, url, t["a"], "1", "--det-cache-audit=0")
    forge_skipped_entry(svc, t, tmp_path, nid)
    _, o2, _ = machine_run(pytester, tmp_path, url, t["a_ro"], "2", "--det-cache-audit=1")
    assert o2["cache"]["audit"]["wrong"] == 1
    assert [m["nodeid"] for m in call(svc, t["a"], "GET", "/v1/ns/proj/untrusted")["untrusted"]] == [nid]
    machine_run(pytester, tmp_path, url, t["a"], "5", "--det-cache-audit=1")
    rep = call(svc, t["a"], "GET", "/v1/audit")
    p = rep["projects"]["proj"]
    assert p["wrong"] >= 1 and rep["all"]["wrong"] >= 1, f"project report after a wrong skip was found and marked: {p}"
    assert p["upper_bound_95"] > cs.upper_bound_95(p["checked"], 0)
