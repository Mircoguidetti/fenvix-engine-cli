"""Cache audit after review R-013: checks that go with ``tests/test_review_r013.py``.

* the per-project bound of ``GET /v1/audit`` reflects a wrong skip found by a pull-request job (the review's
  defect 4 with enough checks for a bound below 1: with 3 checks or fewer every bound is 1.0);
* the second fresh run (a new process) runs under the same Level 0 controls (here the clock epoch);
* the test ids the recorded run produced are compared (NOTE 1: the comparison was vacuous);
* a shared-cache document whose ``proof_key`` is not the key of its content is never reused (NOTE 2);
* a shared-cache document whose ``report`` and ``outcome`` disagree is never reused (defect 3).
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


def plant(pytester, nid: str, **report) -> None:
    st = json.loads(store_path(pytester).read_text())
    st["tests"][nid]["report"].update(report)
    if "call" in report:
        st["tests"][nid]["outcome"] = report["call"]["outcome"]
    store_path(pytester).write_text(json.dumps(st))


@pytest.fixture
def service(tmp_path, monkeypatch):
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
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


def forge(svc, t, tmp_path, nid: str, change) -> None:
    """File on the service, under machine 1's lookup key, a newer copy of machine 1's entry changed by ``change``."""
    st = json.loads((tmp_path / "machine-1" / "mirror" / "proof-cache.json").read_text())
    e = st["tests"][nid]
    lk = rc.lookup_key(nid, e["config"], e["runtime"], e.get("epoch"))
    good = call(svc, t["a"], "POST", "/v1/ns/proj/lookup", {"keys": [lk]})["found"][lk][0]
    doc = json.loads(json.dumps(call(svc, t["a"], "POST", "/v1/blobs/get", {"ids": [good]})["docs"][good]))
    doc["entry"]["run"] = "forger"
    change(doc)
    fid = cs.doc_id(doc)
    call(svc, t["a"], "POST", "/v1/blobs/put", {"docs": {fid: doc}})
    call(svc, t["a"], "POST", "/v1/ns/proj/keys", {"put": [{"key": lk, "doc": fid, "run": "forger"}]})


SKIPPED = {"setup": {"outcome": "passed"}, "call": {"outcome": "skipped", "longrepr": ["test_m.py", 1, "Skipped: forged"]}}


def skipped(doc):
    doc["entry"]["outcome"] = "skipped"
    doc["entry"]["report"] = json.loads(json.dumps(SKIPPED))


# ---------------------------------------------------------------------------------------------------------------------
def test_service_bound_reflects_a_wrong_skip_found_by_a_pull_request_job(service, pytester, tmp_path):
    svc, t = service
    tests = "def test_planted():\n    assert 1 + 1 == 2\n\n" + "".join(
        f"def test_other_{i}():\n    assert True\n\n" for i in range(5))
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": tests})
    url, nid = f"{svc.url}/proj", "test_m.py::test_planted"
    machine_run(pytester, tmp_path, url, t["a"], "1", "--det-cache-audit=0")
    forge(svc, t, tmp_path, nid, skipped)
    _, o2, _ = machine_run(pytester, tmp_path, url, t["a_ro"], "2", "--det-cache-audit=1")
    assert (o2["cache"]["audit"]["checked"], o2["cache"]["audit"]["wrong"]) == (6, 1)
    _, o5, _ = machine_run(pytester, tmp_path, url, t["a"], "5", "--det-cache-audit=1")
    assert (o5["cache"]["audit"]["checked"], o5["cache"]["audit"]["wrong"]) == (5, 0)
    rep = call(svc, t["a"], "GET", "/v1/audit")
    p = rep["projects"]["proj"]
    # write-token summaries: 0 + 5 checks, all matched; the read-only job's wrong skip: from the untrusted log
    assert p["wrong"] == 1 and p["upper_bound_95"] == cs.upper_bound_95(6, 1) > cs.upper_bound_95(6, 0), p
    assert (p["checked"], p["matched"], p["wrong"], p["checked_without_summary"]) == (6, 5, 1, 1)
    assert rep["all"]["wrong"] == 1 and rep["all"]["upper_bound_95"] == p["upper_bound_95"]
    # the same wrong skip reported by a summary and by the log is counted once
    call(svc, t["a"], "POST", "/v1/ns/proj/runs", {"run": "r-w", "summary": {"audit": {
        "checked": 2, "matched": 1, "wrong": 1, "flaky_evidence": 0, "wrong_ids": ["test_m.py::test_x"]}}})
    call(svc, t["a_ro"], "POST", "/v1/ns/proj/untrusted",
         {"put": [{"proof_key": "k" * 32, "nodeid": "test_m.py::test_x", "run": "r-w", "reason": "test"}]})
    p = call(svc, t["a"], "GET", "/v1/audit")["projects"]["proj"]
    assert (p["checked"], p["matched"], p["wrong"], p["checked_without_summary"]) == (8, 6, 2, 1)


def test_second_fresh_run_runs_under_the_same_level0_controls(pytester, run_cache):
    """The test passes only under the controlled clock: a second run without it would fail and call the wrong skip
    flaky."""
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": """
        import datetime

        def test_epoch():
            assert datetime.datetime.now(datetime.timezone.utc).year == 2001
    """})
    nid = "test_m.py::test_epoch"
    epoch = "--det-epoch=2001-02-03T04:05:06"
    run_cache(epoch)[0].assert_outcomes(passed=1)
    plant(pytester, nid, call=SKIPPED["call"])
    r, d = run_cache(epoch, "--det-cache-audit=1")
    a = d["cache"]["audit"]
    assert (a["checked"], a["wrong"], a["flaky_evidence"]) == (1, 1, 0), a
    w = a["wrong_tests"][0]
    assert (w["fresh"]["outcome"], w["fresh2"]["outcome"], w["fresh2"]["process"]) == ("passed", "passed", "new")
    r.assert_outcomes(passed=1)


def test_audit_compares_the_test_ids_the_recorded_run_produced(pytester, run_cache):
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": "def test_a():\n    pass\n"})
    nid = "test_m.py::test_a"
    run_cache()
    st = json.loads(store_path(pytester).read_text())
    assert "ids" not in st["tests"][nid]["report"]  # one test, its own id: not stored
    plant(pytester, nid, ids=[nid, "test_m.py::test_gone"])
    r, d = run_cache("--det-cache-audit=1")
    a = d["cache"]["audit"]
    assert (a["checked"], a["wrong"]) == (1, 1), a
    w = a["wrong_tests"][0]
    assert w["cached"] == {"outcome": "passed", "ids": [nid, "test_m.py::test_gone"]}
    assert w["fresh"] == {"outcome": "passed", "ids": [nid]}


def test_shared_cache_document_with_a_proof_key_not_of_its_content_is_not_reused(service, pytester, tmp_path):
    """NOTE 2: the service matches marks on the document's own ``proof_key``; a document that leaves it out (or
    names another) would dodge every mark. The client recomputes the key and refuses the document."""
    svc, t = service
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": "def test_planted():\n    assert True\n"})
    url, nid = f"{svc.url}/proj", "test_m.py::test_planted"
    machine_run(pytester, tmp_path, url, t["a"], "1", "--det-cache-audit=0")

    def no_key(doc):
        skipped(doc)
        doc.pop("proof_key", None)

    forge(svc, t, tmp_path, nid, no_key)
    _, o, rep = machine_run(pytester, tmp_path, url, t["a"], "6", "--det-cache-audit=0")
    assert o["outcomes"][nid] == "passed" and nid in o["cache"]["reused_ids"]  # machine 1's entry, the next one
    assert rep["pull_rejected_proof_key"] == 1


def test_shared_cache_document_whose_report_and_outcome_disagree_is_not_reused(service, pytester, tmp_path):
    svc, t = service
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": "def test_planted():\n    assert True\n"})
    url, nid = f"{svc.url}/proj", "test_m.py::test_planted"
    machine_run(pytester, tmp_path, url, t["a"], "1", "--det-cache-audit=0")

    def report_only(doc):  # outcome still says passed
        doc["entry"]["report"] = json.loads(json.dumps(SKIPPED))

    forge(svc, t, tmp_path, nid, report_only)
    _, o, rep = machine_run(pytester, tmp_path, url, t["a"], "6", "--det-cache-audit=0")
    assert o["outcomes"][nid] == "passed" and nid in o["cache"]["reused_ids"]
    assert rep["pull_rejected_inconsistent"] == 1


def test_marks_are_followed_by_sequence_and_applied_once(service, pytester, tmp_path):
    """A machine applies a service mark to its mirror once: after its own fresh run records the key again, the
    next run reuses that entry (the mark does not come back), and the mark is never pushed back."""
    svc, t = service
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": "def test_planted():\n    assert True\n"})
    url, nid = f"{svc.url}/proj", "test_m.py::test_planted"
    machine_run(pytester, tmp_path, url, t["a"], "1", "--det-cache-audit=0")
    forge(svc, t, tmp_path, nid, skipped)
    _, o3, _ = machine_run(pytester, tmp_path, url, t["a"], "3", "--det-cache-audit=0")
    assert o3["outcomes"][nid] == "skipped"  # the wrong entry, now in machine 3's mirror
    machine_run(pytester, tmp_path, url, t["a_ro"], "2", "--det-cache-audit=1")
    _, o3, rep3 = machine_run(pytester, tmp_path, url, t["a"], "3", "--det-cache-audit=0")
    assert o3["outcomes"][nid] == "passed" and not o3["cache"]["reused_ids"] and rep3["pull_marks_applied"] == 1
    assert "push_untrusted" not in rep3  # the service's own mark is not sent back
    _, o3, rep3 = machine_run(pytester, tmp_path, url, t["a"], "3", "--det-cache-audit=0")
    assert rep3["pull_marks_applied"] == 0 and o3["cache"]["reused_ids"] == [nid] and o3["outcomes"][nid] == "passed"
    marks = call(svc, t["a"], "GET", "/v1/ns/proj/untrusted?after=0")["untrusted"]
    assert len(marks) == 1 and isinstance(marks[0]["seq"], int)
    assert call(svc, t["a"], "GET", f"/v1/ns/proj/untrusted?after={marks[0]['seq']}")["untrusted"] == []


def test_fenvix_run_audit_is_not_turned_off_by_the_project_addopts(tmp_path):
    """NOTE 5: the runner passes the share and a fresh seed explicitly; command-line options come after ``addopts``,
    so a repository (or a pull request) cannot turn the audit off or freeze its choice."""
    import subprocess

    wrapper = Path(__file__).resolve().parents[1] / "runner" / "fenvix-run"
    proj = tmp_path / "proj"
    write(proj, {"pytest.ini": "[pytest]\naddopts = --det-cache-audit=0 --det-cache-audit-seed=fixed\n",
                 "test_m.py": "def test_a():\n    pass\n"})
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "FENVIX_CACHE_ROOT": str(tmp_path / "machine-cache"),
           "TMPDIR": str(tmp_path), "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md")}
    out = tmp_path / "job"
    subprocess.run([sys.executable, str(wrapper), "--project", str(proj), "--python", sys.executable, "--out",
                    str(out), "--key", "demo/addopts"], env=env, capture_output=True, text=True, timeout=600)
    a = json.loads((out / "summary.json").read_text())["audit"]
    assert a["share"] == 0.05 and a["seed"] != "fixed"
