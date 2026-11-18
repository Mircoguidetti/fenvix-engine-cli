"""Shared cache: the service (content-addressed, append-only, per organization, token auth) and the engine client
(``--det-cache=http://...``): a second machine reuses with proof what the first recorded, checks every candidate
like a local entry, never reuses across runtimes, keeps working on its local mirror when the service is down, and
never shows the token to the tests."""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request

import pytest

from detpy import cache_service as cs
from detpy import remote_cache as rc

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


@pytest.fixture
def service(tmp_path):
    svc = cs.Service(str(tmp_path / "svc"), port=0, quiet=True)
    svc.start_thread()
    tokens = {
        "a": cs.Tokens.add(os.path.join(svc.data, "tokens.json"), "org-a"),
        "a_ro": cs.Tokens.add(os.path.join(svc.data, "tokens.json"), "org-a", write=False),
        "b": cs.Tokens.add(os.path.join(svc.data, "tokens.json"), "org-b"),
    }
    yield svc, tokens
    svc.shutdown()


def call(svc, token, method, path, body=None):
    return rc.Http(svc.url, token, retries=0).call(method, path, body)


# ---------------------------------------------------------------------------------------------------------------------
def test_service_requires_a_known_token_and_keeps_organizations_apart(service):
    svc, t = service
    with pytest.raises(rc.ServiceError, match="401"):
        call(svc, None, "POST", "/v1/blobs/missing", {"ids": []})
    with pytest.raises(rc.ServiceError, match="401"):
        call(svc, "fxc_not-a-token", "POST", "/v1/blobs/missing", {"ids": []})
    doc = {"kind": "file", "v": 1, "path": "a.py"}
    i = cs.doc_id(doc)
    assert call(svc, t["a"], "POST", "/v1/blobs/put", {"docs": {i: doc}}) == {"stored": 1, "existing": 0}
    assert call(svc, t["a"], "POST", "/v1/blobs/get", {"ids": [i]})["docs"] == {i: doc}
    # org B cannot read org A's document, even knowing its address
    assert call(svc, t["b"], "POST", "/v1/blobs/get", {"ids": [i]}) == {"docs": {}, "missing": [i]}
    assert call(svc, t["b"], "POST", "/v1/blobs/missing", {"ids": [i]}) == {"missing": [i]}
    entry = {"kind": "entry", "v": 1, "nodeid": "t::x"}
    e = cs.doc_id(entry)
    call(svc, t["a"], "POST", "/v1/blobs/put", {"docs": {e: entry}})
    call(svc, t["a"], "POST", "/v1/ns/proj/keys", {"put": [{"key": "k1", "doc": e, "run": "r1"}]})
    assert call(svc, t["a"], "POST", "/v1/ns/proj/lookup", {"keys": ["k1"]})["found"] == {"k1": [e]}
    assert call(svc, t["b"], "POST", "/v1/ns/proj/lookup", {"keys": ["k1"]})["found"] == {}
    # org B cannot file a key to a document it does not have
    with pytest.raises(rc.ServiceError, match="400"):
        call(svc, t["b"], "POST", "/v1/ns/proj/keys", {"put": [{"key": "k1", "doc": e}]})


def test_service_is_content_addressed_and_append_only(service):
    svc, t = service
    doc = {"kind": "entry", "v": 1, "nodeid": "t::y", "entry": {"outcome": "passed"}}
    i = cs.doc_id(doc)
    forged = dict(doc, entry={"outcome": "failed"})
    with pytest.raises(rc.ServiceError, match="does not match its address"):
        call(svc, t["a"], "POST", "/v1/blobs/put", {"docs": {i: forged}})
    assert call(svc, t["a"], "POST", "/v1/blobs/put", {"docs": {i: doc}})["stored"] == 1
    assert call(svc, t["a"], "POST", "/v1/blobs/put", {"docs": {i: doc}}) == {"stored": 0, "existing": 1}
    for method in ("PUT", "DELETE"):
        req = urllib.request.Request(f"{svc.url}/v1/blobs/{i}", method=method,
                                     headers={"Authorization": f"Bearer {t['a']}"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req)
        assert ei.value.code == 405
    # the key log only grows; a lookup returns the newest documents first
    docs = [{"kind": "entry", "v": 1, "nodeid": "t::y", "n": n} for n in range(5)]
    ids = [cs.doc_id(d) for d in docs]
    call(svc, t["a"], "POST", "/v1/blobs/put", {"docs": dict(zip(ids, docs))})
    for d in ids:
        call(svc, t["a"], "POST", "/v1/ns/p/keys", {"put": [{"key": "k", "doc": d}]})
    assert call(svc, t["a"], "POST", "/v1/ns/p/lookup", {"keys": ["k"], "limit": 3})["found"]["k"] == ids[::-1][:3]
    call(svc, t["a"], "POST", "/v1/ns/p/runs", {"run": "r1", "receipts": None, "summary": {}})
    # and the database itself refuses updates and deletes
    db = sqlite3.connect(os.path.join(svc.data, "cache.sqlite3"))
    for sql in ("UPDATE blobs SET kind='x'", "DELETE FROM blobs", "UPDATE keys SET doc='x'", "DELETE FROM keys",
                "DELETE FROM runs"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute(sql)


def test_read_only_token_can_look_up_but_not_write(service):
    svc, t = service
    doc = {"kind": "file", "v": 1, "path": "b.py"}
    with pytest.raises(rc.ServiceError, match="403"):
        call(svc, t["a_ro"], "POST", "/v1/blobs/put", {"docs": {cs.doc_id(doc): doc}})
    assert call(svc, t["a_ro"], "POST", "/v1/ns/p/lookup", {"keys": ["k"]}) == {"found": {}}


def test_gzip_request_bodies_are_accepted(service):
    svc, t = service
    docs = {cs.doc_id(d): d for d in ({"kind": "file", "v": 1, "path": f"m{n}.py", "pad": "x" * 500}
                                      for n in range(50))}
    body = gzip.compress(json.dumps({"docs": docs}).encode())
    req = urllib.request.Request(f"{svc.url}/v1/blobs/put", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {t['a']}", "Content-Encoding": "gzip",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        assert json.loads(r.read())["stored"] == 50


# ---------------------------------------------------------------------------------------------------------------------
PROJECT = {
    "pkg/__init__.py": "",
    "pkg/a.py": "def double(x):\n    return 2 * x\n",
    "pkg/b.py": "def inc(x):\n    return x + 1\n",
    "test_a.py": "from pkg.a import double\n\ndef test_double():\n    assert double(2) == 4\n",
    "test_b.py": "from pkg.b import inc\n\ndef test_inc():\n    assert inc(1) == 2\n\n"
                 "def test_inc_data():\n    assert open('data.txt').read().strip() == '7'\n",
    "test_clock.py": "import time\n\ndef test_reads_clock():\n    assert time.time() > 0\n",
    "test_env.py": "import os\n\ndef test_token_is_hidden():\n"
                   "    assert os.environ.get('FENVIX_CACHE_TOKEN') is None\n"
                   "    assert os.environ.get('FENVIX_CACHE_LOCAL') is None\n",
    "data.txt": "7\n",
}


def write(root, files):
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def machine_run(pytester, tmp_path, url, token, machine, *extra, env=None):
    """One job on one machine: its own local mirror (an empty disk on a fresh machine)."""
    report = tmp_path / f"report-{machine}.json"
    outcomes = tmp_path / f"outcomes-{machine}.json"
    for p in (report, outcomes):
        if p.exists():
            p.unlink()
    os.environ["FENVIX_CACHE_LOCAL"] = str(tmp_path / f"machine-{machine}" / "mirror")
    os.environ["FENVIX_CACHE_REPORT"] = str(report)
    os.environ["FENVIX_RUNTIME_MEMO"] = str(tmp_path / f"machine-{machine}" / "runtime-memo.json")
    if token is None:
        os.environ.pop("FENVIX_CACHE_TOKEN", None)
    else:
        os.environ["FENVIX_CACHE_TOKEN"] = token
    for k, v in (env or {}).items():
        os.environ[k] = v
    # basetemp outside the project (pytester's default adds a new runpytest-N directory to the project root)
    r = pytester.runpytest_subprocess("--det", f"--det-cache={url}", f"--det-outcomes={outcomes}",
                                      f"--basetemp={tmp_path / f'basetemp-{machine}'}", "-p", "no:cacheprovider", *extra)
    out = json.loads(outcomes.read_text())
    rep = json.loads(report.read_text()) if report.exists() else {}
    return r, out, rep


@pytest.fixture
def project(pytester):
    write(pytester.path, PROJECT)
    return pytester.path


def test_second_machine_reuses_with_proof_what_the_first_recorded(service, pytester, project, tmp_path, monkeypatch):
    svc, t = service
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    url = f"{svc.url}/org-a/project"
    r1, o1, rep1 = machine_run(pytester, tmp_path, url, t["a"], "1")
    r1.assert_outcomes(passed=5)
    assert o1["cache"]["reused"] == 0
    assert rep1["push_entry_docs_new"] == 5 and rep1["error"] is None
    # machine 2: empty local mirror, same commit -> every result comes from the service, checked locally
    r2, o2, rep2 = machine_run(pytester, tmp_path, url, t["a"], "2")
    r2.assert_outcomes(passed=5)
    assert rep2["pull_proven"] == 5 and rep2["error"] is None
    assert o2["cache"]["reused"] == 5
    assert rep2["push_entry_docs_new"] == 0  # what it pulled has the same address: nothing goes back
    # machine 3: one source file and one data file changed -> only their tests run, the rest is reused
    (project / "pkg" / "b.py").write_text("def inc(x):\n    return x + 2\n")
    r3, o3, rep3 = machine_run(pytester, tmp_path, url, t["a"], "3")
    r3.assert_outcomes(passed=4, failed=1)
    assert o3["outcomes"]["test_b.py::test_inc"] == "failed"
    assert o3["cache"]["reused"] == 4  # test_inc_data does not call inc(): its code is unchanged
    (project / "data.txt").write_text("8\n")
    r4, o4, _ = machine_run(pytester, tmp_path, url, t["a"], "4")
    assert o4["outcomes"]["test_b.py::test_inc_data"] == "failed"
    # every reuse matches a fresh run without the cache (no wrong reuse)
    fresh = tmp_path / "fresh.json"
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_CACHE_TOKEN"):
        os.environ.pop(k, None)
    pytester.runpytest_subprocess("--det", f"--det-outcomes={fresh}", "-p", "no:cacheprovider")
    real = json.loads(fresh.read_text())["outcomes"]
    assert o4["outcomes"] == real


def test_another_runtime_never_reuses(service, pytester, project, tmp_path, monkeypatch):
    svc, t = service
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    url = f"{svc.url}/org-a/project"
    machine_run(pytester, tmp_path, url, t["a"], "1")
    # -O strips asserts: another runtime identity, so nothing recorded on machine 1 is a candidate
    monkeypatch.setenv("PYTHONOPTIMIZE", "1")
    r2, o2, rep2 = machine_run(pytester, tmp_path, url, t["a"], "2")
    assert o2["cache"]["reused"] == 0
    assert rep2["pull_candidates"] == 0


def test_other_organization_gets_nothing(service, pytester, project, tmp_path, monkeypatch):
    svc, t = service
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    url = f"{svc.url}/shared-name"
    machine_run(pytester, tmp_path, url, t["a"], "1")
    _, o2, rep2 = machine_run(pytester, tmp_path, url, t["b"], "2")
    assert o2["cache"]["reused"] == 0 and rep2["pull_candidates"] == 0


def test_service_down_falls_back_to_the_local_mirror(pytester, project, tmp_path, monkeypatch):
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # nothing listens there
    url = f"http://127.0.0.1:{port}/org-a/project"
    r1, o1, rep1 = machine_run(pytester, tmp_path, url, "fxc_x", "1")
    r1.assert_outcomes(passed=5)
    assert rep1["error"] and "pull" in rep1["error"]
    r2, o2, rep2 = machine_run(pytester, tmp_path, url, "fxc_x", "1")  # same machine: the mirror serves
    r2.assert_outcomes(passed=5)
    assert o2["cache"]["reused"] == 5
    assert "shared cache:" in r2.stdout.str() and "local mirror" in r2.stdout.str()


def test_entries_pushed_while_the_service_was_down_are_pushed_later(service, pytester, project, tmp_path,
                                                                     monkeypatch):
    svc, t = service
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    url = f"{svc.url}/org-a/project"
    # machine 1 records with a token the service refuses (as if it were unreachable): nothing reaches the service
    _, _, rep = machine_run(pytester, tmp_path, url, "fxc_wrong", "1")
    assert rep["error"]
    # next job on machine 1 with a valid token: all reused locally, and the backlog is pushed
    _, o, rep = machine_run(pytester, tmp_path, url, t["a"], "1")
    assert o["cache"]["reused"] == 5 and rep["push_entry_docs_new"] == 5
    _, o2, _ = machine_run(pytester, tmp_path, url, t["a"], "2")
    assert o2["cache"]["reused"] == 5


def test_token_is_not_visible_even_to_a_test_that_enumerates_the_environment(service, pytester, tmp_path,
                                                                             monkeypatch):
    svc, t = service
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    write(pytester.path, {"test_e.py": "import os\n\ndef test_e():\n"
                                       "    assert not any(v.startswith('fxc_') for v in os.environ.values())\n"
                                       "    assert not any(k.startswith('FENVIX_CACHE') for k in os.environ)\n"
                                       "    assert b'fxc_' not in open('/proc/self/environ', 'rb').read()\n"
                                       "    for fd in [int(f) for f in os.listdir('/proc/self/fd') if int(f) > 2]:\n"
                                       "        try:\n"
                                       "            if not os.readlink(f'/proc/self/fd/{fd}').startswith('pipe:'):\n"
                                       "                continue\n"
                                       "            os.set_blocking(fd, False)\n"
                                       "            data = os.read(fd, 4096)\n"
                                       "        except OSError:\n"
                                       "            continue\n"
                                       "        assert b'fxc_' not in data\n"})
    r, o, rep = machine_run(pytester, tmp_path, f"{svc.url}/org-a/e", t["a"], "1")
    r.assert_outcomes(passed=1)
    assert rep["error"] is None


def test_lookup_key_is_stable():
    assert rc.lookup_key("t::a", "c", "r", None) == rc.lookup_key("t::a", "c", "r", None)
    assert rc.lookup_key("t::a", "c", "r", None) != rc.lookup_key("t::a", "c", "r", 0)
    assert rc.lookup_key("t::a", "c", "r", None) != rc.lookup_key("t::a", "c", "r2", None)
    assert rc.split_url("https://cache.example:8443/acme/repo") == ("https://cache.example:8443", "acme/repo")


def test_fenvix_run_on_two_machines_sharing_the_service(service, tmp_path):
    """runner/fenvix-run --cache <service URL>: job 2 on another machine (empty disk) reuses with proof what job 1
    recorded, its summary says how many came from the service, and verify finds no wrong reuse."""
    import subprocess
    from pathlib import Path

    svc, t = service
    wrapper = Path(__file__).resolve().parents[1] / "runner" / "fenvix-run"
    proj = tmp_path / "proj"
    write(proj, {k: v for k, v in PROJECT.items()})

    def job(machine: str, *extra: str):
        out = tmp_path / f"job-{machine}"
        tokf = tmp_path / f"token-{machine}"
        tokf.write_text(t["a"])
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / f"home-{machine}"), "TMPDIR": str(tmp_path),
               "FENVIX_CACHE_ROOT": str(tmp_path / f"disk-{machine}"), "FENVIX_CACHE_TOKEN_FILE": str(tokf),
               "FENVIX_RUNTIME_MEMO": "off", "GITHUB_STEP_SUMMARY": str(tmp_path / f"summary-{machine}.md")}
        verify = extra[:1] == ("verify",)
        args = [sys.executable, str(wrapper), *extra, "--project", str(proj), "--python", sys.executable, "--out",
                str(out)]
        if not verify:
            args += ["--key", "acme/proj", "--cache", f"{svc.url}/org-a"]
        r = subprocess.run(args, env=env, capture_output=True, text=True, timeout=600)
        name = "verify.json" if verify else "summary.json"
        return r, json.loads((out / name).read_text())

    r1, s1 = job("1")
    assert r1.returncode == 0, r1.stdout[-2000:] + r1.stderr[-2000:]
    assert not (tmp_path / "token-1").exists()  # the hand-off file is consumed before pytest starts
    assert s1["reused_with_proof"] == 0 and s1["shared_cache"]["push_entry_docs_new"] == 5
    r2, s2 = job("2")
    assert r2.returncode == 0, r2.stdout[-2000:] + r2.stderr[-2000:]
    assert s2["cache_was_warm"] is False  # a fresh machine: nothing on its disk
    assert s2["reused_with_proof"] == 5 and s2["reused_from_shared_cache"] == 5
    assert "proven from entries recorded on other machines" in (tmp_path / "summary-2.md").read_text()
    rv, v = job("2", "verify", "--summary", str(tmp_path / "job-2" / "summary.json"))
    assert rv.returncode == 0 and v["checked"] == 5 and v["wrong"] == []


def _non_loopback_ip() -> str | None:
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))  # no packet is sent: picks the outgoing interface
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


def test_service_on_a_non_loopback_address_is_reachable_under_the_closed_network(tmp_path, pytester, monkeypatch):
    """Level 0 refuses external hosts even between tests; the client's own requests must still reach the service,
    while the tests stay behind the closed network."""
    ip = _non_loopback_ip()
    if ip is None:
        pytest.skip("no non-loopback interface")
    try:
        svc = cs.Service(str(tmp_path / "svc"), host=ip, port=0, quiet=True)
    except OSError:
        pytest.skip(f"cannot listen on {ip}")
    svc.start_thread()
    try:
        tok = cs.Tokens.add(os.path.join(svc.data, "tokens.json"), "org-a")
        for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN",
                  "no_proxy", "NO_PROXY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("no_proxy", ip)
        monkeypatch.setenv("FENVIX_CACHE_ALLOW_HTTP", "1")  # plain http to a non-loopback host must be allowed explicitly
        write(pytester.path, {"test_n.py": f"import socket, pytest\n\ndef test_closed():\n"
                                           f"    with pytest.raises(OSError):\n"
                                           f"        socket.create_connection(('{ip}', {svc.httpd.server_address[1]}), 2)\n"})
        r, o, rep = machine_run(pytester, tmp_path, f"http://{ip}:{svc.httpd.server_address[1]}/org-a/n", tok, "1")
        r.assert_outcomes(passed=1)
        assert rep["error"] is None and rep["push_entry_docs_new"] == 1
    finally:
        svc.shutdown()


def test_candidates_are_checked_when_the_project_looks_as_the_tests_saw_it(service, pytester, tmp_path, monkeypatch):
    """A test that lists the project root saw detpy's .detpy/ directory there; on a fresh checkout it appears only
    when the session opens its trace, so candidates must be checked after that, as local entries are."""
    import shutil

    svc, t = service
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    proj = pytester.path / "proj"  # pytester adds a runpytest-N directory to its own directory at every run
    write(proj, {"test_ls.py": "import os\n\ndef test_ls():\n"
                               "    assert 'test_ls.py' in os.listdir(os.path.dirname(__file__))\n"})
    args = ("--rootdir", str(proj), str(proj))
    url = f"{svc.url}/org-a/ls"
    machine_run(pytester, tmp_path, url, t["a"], "1", *args)
    assert (proj / ".detpy").is_dir()
    shutil.rmtree(proj / ".detpy")  # machine 2 checks out a clean tree
    _, o2, rep2 = machine_run(pytester, tmp_path, url, t["a"], "2", *args)
    assert o2["cache"]["reused"] == 1 and rep2["pull_proven"] == 1


def test_service_refuses_a_gzip_bomb_from_a_known_token_while_inflating(service):
    svc, t = service
    body = gzip.compress(b"0" * (cs.MAX_BODY + 1024))  # inflates past the limit
    req = urllib.request.Request(f"{svc.url}/v1/blobs/put", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {t['a']}", "Content-Encoding": "gzip",
                                          "Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=60)
    assert ei.value.code == 400 and b"too large" in ei.value.read()


def test_plain_http_to_a_remote_host_is_refused(pytester, tmp_path, monkeypatch):
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN",
              "FENVIX_CACHE_ALLOW_HTTP"):
        monkeypatch.delenv(k, raising=False)
    write(pytester.path, {"test_x.py": "def test_x():\n    pass\n"})
    r, o, rep = machine_run(pytester, tmp_path, "http://cache.example.invalid/org/p", "fxc_secret", "1")
    r.assert_outcomes(passed=1)
    assert "refusing plain http://" in rep["error"] and rep["requests"] == 0


def test_documents_that_do_not_match_their_address_are_dropped(service):
    svc, t = service
    good = {"kind": "file", "v": 1, "path": "a.py", "content": "1"}
    i = cs.doc_id(good)
    call(svc, t["a"], "POST", "/v1/blobs/put", {"docs": {i: good}})
    import zlib

    db = sqlite3.connect(os.path.join(svc.data, "cache.sqlite3"))
    db.execute("DROP TRIGGER blobs_append_only_u")  # a compromised server
    db.execute("UPDATE blobs SET data=? WHERE id=?", (zlib.compress(cs.canonical(dict(good, content="2"))), i))
    db.commit()
    client = rc.RemoteCache(f"{svc.url}/org-a/p", t["a"], "/nonexistent")
    assert client._get([i]) == {} and client.stats["pull_bad_address"] == 1
