"""Cache audit (``--det-cache-audit``): a seeded share of the results that would be reused with proof runs fresh
and is compared with the cached result. A planted wrong reuse is caught at 100%; a wrong skip marks its proof key
untrusted, which stops reuse locally and through the shared cache until a fresh run records the key again; a
mismatch the second fresh run does not reproduce is flaky with evidence; the seed in the receipts reproduces the
choice; audited tests count as run, never as skipped."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from detpy import _core
from detpy import audit_report
from detpy import cache_service as cs
from detpy import remote_cache as rc

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")

WRAPPER = Path(__file__).resolve().parents[1] / "runner" / "fenvix-run"


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


def receipts(pytester) -> list[dict]:
    return [json.loads(x) for x in (pytester.path / ".cachedir" / "receipts.jsonl").read_text().splitlines()]


def plant_skip(pytester, nodeid: str) -> dict:
    """Plant a wrong reuse: the recorded result of ``nodeid`` says *skipped* while the test passes. The proof key
    does not cover the outcome, so every input still checks out and the entry would be reused as it is."""
    p = store_path(pytester)
    st = json.loads(p.read_text())
    e = st["tests"][nodeid]
    e["outcome"] = "skipped"
    e["report"] = {"setup": {"outcome": "passed"},
                   "call": {"outcome": "skipped", "longrepr": [nodeid.split("::")[0], 1, "Skipped: planted"]}}
    p.write_text(json.dumps(st))
    return e


PLANT = """
    def test_planted():
        assert 1 + 1 == 2

    def test_other():
        assert True
"""


# ---------------------------------------------------------------------------------------------------------------------
def test_planted_wrong_reuse_is_caught_at_full_share(pytester, run_cache):
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": PLANT})
    r, d = run_cache()
    r.assert_outcomes(passed=2)
    plant_skip(pytester, "test_m.py::test_planted")
    # without the audit the planted entry is reused: the wrong skip is invisible
    r, d = run_cache("--det-cache-audit=0")
    r.assert_outcomes(passed=1, skipped=1)
    assert set(d["cache"]["reused_ids"]) == {"test_m.py::test_planted", "test_m.py::test_other"}
    key = d["cache"]["reused_ids"] and json.loads(store_path(pytester).read_text())["tests"]["test_m.py::test_planted"]["key"]
    # at 100% every reusable result runs fresh: the planted one is a wrong skip (two fresh runs say passed)
    r, d = run_cache("--det-cache-audit=100%")
    r.assert_outcomes(passed=2)
    a = d["cache"]["audit"]
    assert (a["share"], a["candidates"], a["checked"], a["matched"], a["wrong"], a["flaky_evidence"]) == (1.0, 2, 2, 1, 1, 0)
    w = a["wrong_tests"][0]
    assert w["nodeid"] == "test_m.py::test_planted" and w["key"] == key and w["verdict"] == "wrong"
    assert (w["cached"]["outcome"], w["fresh"]["outcome"], w["fresh2"]["outcome"]) == ("skipped", "passed", "passed")
    assert w["fresh"]["ids"] == ["test_m.py::test_planted"]
    assert d["cache"]["reused_ids"] == []  # audited tests ran: none of them counts as skipped
    assert a["upper_bound_95"] > 0.5  # 1 wrong of 2
    r.stdout.fnmatch_lines(["*cache audit (share 100.0%*2 reusable result(s) run fresh, 1 matched, 1 wrong*",
                            "*WRONG SKIP test_m.py::test_planted: cached skipped, fresh passed and passed; key * marked untrusted*"])
    st = json.loads(store_path(pytester).read_text())
    assert key in st["untrusted"] and st["untrusted"][key]["nodeid"] == "test_m.py::test_planted"
    assert "test_m.py::test_planted" not in st["tests"]  # the wrong entry is dropped, the fresh run not recorded
    # receipts: the seed and the choice first, then the reuse decision of every audited test with its verdict
    rows = receipts(pytester)
    assert rows[0]["kind"] == "audit" and rows[0]["share"] == 1.0 and rows[0]["seed"] == a["seed"]
    assert rows[0]["chosen"] == ["test_m.py::test_other", "test_m.py::test_planted"]
    row = next(x for x in rows if x["nodeid"] == "test_m.py::test_planted")
    assert row["audited"] and not row["reused"] and row["key"] == key and row["audit"]["verdict"] == "wrong"


def test_untrusted_key_stops_reuse_until_a_fresh_run_records_it_again(pytester, run_cache):
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": PLANT})
    run_cache()
    planted = plant_skip(pytester, "test_m.py::test_planted")
    run_cache("--det-cache-audit=1")  # wrong skip: key untrusted
    # the same wrong entry comes back (a copy from another machine, a restored cache): never reused
    st = json.loads(store_path(pytester).read_text())
    st["tests"]["test_m.py::test_planted"] = planted
    store_path(pytester).write_text(json.dumps(st))
    r, d = run_cache("--det-cache-audit=0")
    r.assert_outcomes(passed=2)
    assert d["cache"]["reused_ids"] == ["test_m.py::test_other"]
    assert d["cache"]["miss_ids"]["test_m.py::test_planted"].startswith("untrusted: a cache audit found this result wrong")
    # that run was fresh and recorded the same key again: the mark is gone, the (true) result is reused
    st = json.loads(store_path(pytester).read_text())
    assert st.get("untrusted", {}) == {} and st["tests"]["test_m.py::test_planted"]["key"] == planted["key"]
    r, d = run_cache("--det-cache-audit=0")
    r.assert_outcomes(passed=2)
    assert set(d["cache"]["reused_ids"]) == {"test_m.py::test_planted", "test_m.py::test_other"}


def test_mismatch_the_second_fresh_run_does_not_reproduce_is_flaky_with_evidence(pytester, run_cache):
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": """
        RUNS = []

        def test_alternates():
            RUNS.append(1)
            assert len(RUNS) % 2 == 1
    """})
    run_cache()
    planted = plant_skip(pytester, "test_m.py::test_alternates")
    r, d = run_cache("--det-cache-audit=1")
    a = d["cache"]["audit"]
    assert (a["checked"], a["wrong"], a["flaky_evidence"]) == (1, 0, 1)
    f = a["flaky_tests"][0]
    assert (f["cached"]["outcome"], f["fresh"]["outcome"], f["fresh2"]["outcome"]) == ("skipped", "passed", "failed")
    st = json.loads(store_path(pytester).read_text())
    assert st.get("untrusted", {}) == {}  # not shown wrong: no key marked
    assert st["tests"]["test_m.py::test_alternates"]["key"] == planted["key"]
    r.assert_outcomes(passed=1)  # the run reports the first fresh run; the second is evidence only


def test_seed_in_the_receipts_reproduces_the_choice(pytester, run_cache):
    write(pytester.path, {"pytest.ini": "[pytest]\n",
                          "test_m.py": "".join(f"def test_{i}():\n    pass\n\n" for i in range(24))})
    run_cache()
    ids = [f"test_m.py::test_{i}" for i in range(24)]
    expected = sorted(n for n in ids if _core.audit_chosen("fixed-seed", n, 0.5))
    assert 0 < len(expected) < 24
    r, d = run_cache("--det-cache-audit=0.5", "--det-cache-audit-seed=fixed-seed")
    head = receipts(pytester)[0]
    assert head["seed"] == "fixed-seed" and head["chosen"] == expected and head["candidates"] == 24
    assert sorted(d["cache"]["reused_ids"]) == sorted(set(ids) - set(expected))
    assert d["cache"]["audit"]["checked"] == len(expected) and d["cache"]["audit"]["wrong"] == 0
    r, d = run_cache("--det-cache-audit=0.5", "--det-cache-audit-seed=fixed-seed")
    assert receipts(pytester)[0]["chosen"] == expected
    # without a seed every run draws a new one, written in the receipts
    run_cache("--det-cache-audit=0.5")
    s1 = receipts(pytester)[0]
    run_cache("--det-cache-audit=0.5")
    s2 = receipts(pytester)[0]
    assert s1["seed"] != s2["seed"]
    for s in (s1, s2):
        assert s["chosen"] == sorted(n for n in ids if _core.audit_chosen(s["seed"], n, 0.5))


def test_default_share_is_five_percent(pytester, run_cache, monkeypatch):
    monkeypatch.delenv("FENVIX_AUDIT_SHARE", raising=False)
    write(pytester.path, {"pytest.ini": "[pytest]\n",
                          "test_m.py": "".join(f"def test_{i}():\n    pass\n\n" for i in range(200))})
    run_cache()
    r, d = run_cache()
    a = d["cache"]["audit"]
    seed = receipts(pytester)[0]["seed"]
    expected = [f"test_m.py::test_{i}" for i in range(200) if _core.audit_chosen(seed, f"test_m.py::test_{i}", 0.05)]
    assert a["share"] == 0.05 and a["candidates"] == 200 and a["checked"] == len(expected) and a["wrong"] == 0
    assert len(d["cache"]["reused_ids"]) == 200 - len(expected)


def test_share_option_values(pytester, run_cache):
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": PLANT})
    r, _ = run_cache("--det-cache-audit=150%")
    r.stderr.fnmatch_lines(["*--det-cache-audit*not between 0 and 1*"])
    r, _ = run_cache("--det-cache-audit=lots")
    r.stderr.fnmatch_lines(["*--det-cache-audit: not a share*"])


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


def test_untrusted_key_stops_reuse_through_the_shared_cache(service, pytester, tmp_path, monkeypatch):
    svc, t = service
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    write(pytester.path, {"pytest.ini": "[pytest]\n", "test_m.py": PLANT})
    url = f"{svc.url}/proj"
    nid = "test_m.py::test_planted"
    _, o1, rep1 = machine_run(pytester, tmp_path, url, t["a"], "1", "--det-cache-audit=0")
    assert rep1["push_entry_docs_new"] == 2
    # a forged entry on the service: the same inputs (same proof key), outcome skipped
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
    # machine 2 (pull-request job: read-only token) audits everything: the forged entry is a wrong skip, and the
    # mark reaches the service although the token cannot write entries
    r2, o2, rep2 = machine_run(pytester, tmp_path, url, t["a_ro"], "2", "--det-cache-audit=1")
    a = o2["cache"]["audit"]
    assert a["wrong"] == 1 and a["wrong_tests"][0]["nodeid"] == nid and a["wrong_tests"][0]["cached"]["outcome"] == "skipped"
    assert rep2["push_untrusted"] == 1 and "untrusted" not in (rep2["error"] or "")
    marks = call(svc, t["a"], "GET", "/v1/ns/proj/untrusted")["untrusted"]
    assert [m["proof_key"] for m in marks] == [e["key"]] and marks[0]["nodeid"] == nid
    # machine 3, empty mirror, no audit: every entry filed under the key before the mark is out of the lookup
    r3, o3, rep3 = machine_run(pytester, tmp_path, url, t["a"], "3", "--det-cache-audit=0")
    assert o3["cache"]["reused_ids"] == ["test_m.py::test_other"]
    assert o3["outcomes"][nid] == "passed" and rep3["pull_proven"] == 1
    # machine 3 ran it fresh and recorded the key again: machine 4 reuses that new entry
    r4, o4, rep4 = machine_run(pytester, tmp_path, url, t["a"], "4", "--det-cache-audit=0")
    assert sorted(o4["cache"]["reused_ids"]) == ["test_m.py::test_other", nid] and rep4["pull_proven"] == 2
    assert o4["outcomes"][nid] == "passed"
    # the service sums the audits of the runs filed with a write token (a read-only token cannot file a run, so a
    # pull-request job cannot inflate the counts) per project and over all projects
    machine_run(pytester, tmp_path, url, t["a"], "5", "--det-cache-audit=1")
    rep = call(svc, t["a"], "GET", "/v1/audit")
    assert rep["projects"]["proj"] == {"runs": 4, "checked": 2, "matched": 2, "wrong": 0, "flaky_evidence": 0,
                                       "upper_bound_95": 1.0}
    assert rep["all"]["checked"] == 2 and rep["all"]["upper_bound_95"] == cs.upper_bound_95(2, 0)


def test_client_drops_candidates_with_a_locally_untrusted_key_even_when_the_service_has_no_mark(tmp_path):
    """Defence in depth: a service that never got the mark (offline when it was pushed, an older service) still
    cannot hand the wrong entry back."""
    from detpy.remote_cache import RemoteCache

    class Store:
        def untrusted(self):
            return {"K": ("t::a", "r", "why")}

        def check(self, nid):
            return False, "new: no recorded result"

    class PC:
        store, config_digest, runtime_digest, epoch, root = Store(), "c", "r", 0, str(tmp_path)

    rcache = RemoteCache("http://127.0.0.1:9/ns", None, str(tmp_path / "m"))
    rcache.pc = PC()
    doc = {"kind": "entry", "nodeid": "t::a", "proof_key": "K", "entry": {"data": [["t", "f:x"]]}}
    did = cs.doc_id(doc)
    rcache.http.call = lambda m, p, b=None: ({"found": {k: [did] for k in b["keys"]}} if p.endswith("lookup")
                                             else {"docs": {did: doc} if did in b["ids"] else {}})
    rcache._refresh_facts = lambda: None

    class Item:
        nodeid = "t::a"

    rcache.pull([Item()])
    assert rcache.stats["pull_rejected_untrusted"] >= 1 and rcache.stats["pull_injected"] == 0


# ---------------------------------------------------------------------------------------------------------------------
def test_fenvix_run_counts_audited_tests_as_run_and_reports_the_audit(tmp_path):
    proj = tmp_path / "proj"
    write(proj, {"pytest.ini": "[pytest]\n", "test_m.py": PLANT})

    def job(name, *extra):
        out = tmp_path / name
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GITHUB_STEP_SUMMARY": str(tmp_path / f"{name}.md"),
               "FENVIX_CACHE_ROOT": str(tmp_path / "machine-cache"), "TMPDIR": str(tmp_path)}
        r = subprocess.run([sys.executable, str(WRAPPER), "--project", str(proj), "--python", sys.executable,
                            "--out", str(out), "--key", "demo/audit", *extra], env=env, capture_output=True,
                           text=True, timeout=600)
        return r, json.loads((out / "summary.json").read_text()), (tmp_path / f"{name}.md").read_text()

    r, s1, _ = job("job1", "--audit", "0")
    assert s1["audit"]["checked"] == 0 and s1["reused_with_proof"] == 0
    cache = Path(s1["cache_dir"])
    st = json.loads((cache / "proof-cache.json").read_text())
    st["tests"]["test_m.py::test_planted"]["outcome"] = "skipped"
    st["tests"]["test_m.py::test_planted"]["report"] = {
        "setup": {"outcome": "passed"}, "call": {"outcome": "skipped", "longrepr": ["test_m.py", 1, "Skipped: p"]}}
    (cache / "proof-cache.json").write_text(json.dumps(st))
    r, s2, md = job("job2", "--audit", "100%")
    a = s2["audit"]
    assert {k: a[k] for k in ("checked", "matched", "wrong", "flaky_evidence")} == \
        {"checked": 2, "matched": 1, "wrong": 1, "flaky_evidence": 0}
    assert a["wrong_tests"] == [{"nodeid": "test_m.py::test_planted", "key": st["tests"]["test_m.py::test_planted"]["key"],
                                 "cached": "skipped", "fresh": "passed", "fresh2": "passed"}]
    # audited tests ran: the dashboard and the billing never see them as skipped
    assert s2["reused_with_proof"] == 0 and s2["ran"] == 2 and s2["tests"] == 2 and s2["test_seconds_saved"] == 0
    assert s2["project_key"].startswith("demo_audit")
    assert "[fenvix] ERROR wrong skip: test_m.py::test_planted" in r.stdout
    assert "Skips audited (run fresh anyway, compared) | 2: 1 matched, **1 wrong**" in md
    assert "### Wrong skips found by the audit" in md
    # per project and over all projects
    other = dict(s2, project_key="other/project", audit=dict(a, checked=300, matched=300, wrong=0, wrong_tests=[]))
    (tmp_path / "other.json").write_text(json.dumps(other))
    rep = audit_report.aggregate([(audit_report.project_of(s, "x"), audit_report.audit_of(s)) for s in (s1, s2, other)])
    assert rep["projects"]["other/project"]["upper_bound_95"] == pytest.approx(0.01)  # rule of three
    p = rep["projects"][s2["project_key"]]
    assert (p["runs"], p["checked"], p["wrong"]) == (2, 2, 1) and p["wrong_tests"] == ["test_m.py::test_planted"]
    assert (rep["all"]["checked"], rep["all"]["wrong"]) == (302, 1)
    assert rep["all"]["upper_bound_95"] == pytest.approx(_core.audit_upper_bound(302, 1))
    out = subprocess.run([sys.executable, "-m", "detpy.audit_report", str(tmp_path / "job2" / "summary.json"),
                          str(tmp_path / "other.json")], capture_output=True, text=True)
    assert "ALL PROJECTS" in out.stdout and "other/project" in out.stdout


def test_bounds_agree_between_the_core_and_the_service():
    for n, k in [(0, 0), (1, 0), (3, 0), (300, 0), (2, 1), (100, 1), (1000, 5), (50, 7), (10, 10)]:
        assert cs.upper_bound_95(n, k) == pytest.approx(_core.audit_upper_bound(n, k), abs=1e-9), (n, k)


def test_the_javascript_reference_chooses_like_the_core():
    """detjs (Node) chooses the same tests as the Rust core for the same seed: one audit rule in every shell."""
    import shutil

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    cases = [(f"seed-{i % 7}", f"tests/test_{i % 13}.py::test_{i}[é{i}]", (0.05, 0.3, 0.5, 1.0, 0.0)[i % 5])
             for i in range(3000)]
    ref = Path(__file__).resolve().parents[1] / "docs" / "audit" / "chosen.mjs"
    out = subprocess.run([node, str(ref), "--check"], input=json.dumps(cases), capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [_core.audit_chosen(s, t, x) for s, t, x in cases]
