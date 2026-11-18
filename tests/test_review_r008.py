"""Review R-008 (shared cache): holes in the content-keyed runtime identity and in the cache service.

Every test here FAILS on claude/shared-cache @ da1afa9. Each one sets up two "machines" whose tests can behave
differently and asserts the property the identity / service claims ("different whenever behaviour can differ",
"a token never reaches another organization", ...). Where it matters, the test first proves that behaviour really
differs, so a failure is a real hole, not a cosmetic one.
"""
from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

from test_runtime_id import changed, identity, install, make_wheel, site_packages, venv  # noqa: F401

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux identity")


def run(py: str, code: str, env_extra: dict | None = None, cwd: Path | None = None) -> str:
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    env.update(env_extra or {})
    r = subprocess.run([py, "-c", code], env=env, capture_output=True, text=True, cwd=cwd, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout.strip()


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "project"
    r.mkdir()
    return r


# ---------------------------------------------------------------------------------------------------------------------
# 1. files under site-packages that no RECORD lists: imports from site dirs are never per-test inputs
#    (proofcache._ignored), so the identity is their only guard -- and it does not see them
def test_hole_unowned_package_directory_in_site_packages(tmp_path, root):
    """A package copied into site-packages without dist-info (vendored by a build step, `pip install --target`
    leftovers, a system image layer): `site_loose` keeps only *files directly* in the site directory."""
    py1, py2 = venv(tmp_path / "m1"), venv(tmp_path / "m2")
    for py, v in ((py1, 1), (py2, 2)):
        pkg = site_packages(py) / "vendored"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(f"VALUE = {v}\n")
    assert run(py1, "import vendored; print(vendored.VALUE)") != run(py2, "import vendored; print(vendored.VALUE)")
    a, b = identity(py1, root), identity(py2, root)
    assert a["digest"] != b["digest"], "same identity although `import vendored` gives different values"


def test_hole_file_inside_a_distribution_not_listed_in_its_record(tmp_path, root):
    """A module or data file added inside an installed package after installation (a plugin dropped in, a generated
    `_version.py`, a compiled extension built in place): the identity hashes only the files RECORD lists."""
    whl = make_wheel(tmp_path / "w", "fenvixdemo", "1.0",
                     {"fenvixdemo/__init__.py": "try:\n    from ._extra import VALUE\nexcept ImportError:\n    VALUE = 0\n"})
    py1, py2 = venv(tmp_path / "m1"), venv(tmp_path / "m2")
    install(py1, whl, "uv")
    install(py2, whl, "uv")
    (site_packages(py2) / "fenvixdemo" / "_extra.py").write_text("VALUE = 42\n")
    assert run(py1, "import fenvixdemo; print(fenvixdemo.VALUE)") == "0"
    assert run(py2, "import fenvixdemo; print(fenvixdemo.VALUE)") == "42"
    a, b = identity(py1, root), identity(py2, root)
    assert a["digest"] != b["digest"], "same identity although fenvixdemo.VALUE is 0 on one machine and 42 on the other"


def test_hole_legacy_egg_info_distribution_is_keyed_on_metadata_only(tmp_path, root):
    """No RECORD (egg-info installs: `setup.py install`, Debian/Ubuntu python3-* packages in dist-packages): the
    identity keeps name, version and PKG-INFO text, not the files (installed-files.txt is ignored)."""
    py1, py2 = venv(tmp_path / "m1"), venv(tmp_path / "m2")
    for py, v in ((py1, 1), (py2, 2)):
        sp = site_packages(py)
        (sp / "legacy").mkdir()
        (sp / "legacy" / "__init__.py").write_text(f"VALUE = {v}\n")
        info = sp / "legacy-1.0-py3.13.egg-info"
        info.mkdir()
        (info / "PKG-INFO").write_text("Metadata-Version: 1.1\nName: legacy\nVersion: 1.0\n")
        (info / "top_level.txt").write_text("legacy\n")
        (info / "installed-files.txt").write_text("../legacy/__init__.py\nPKG-INFO\ntop_level.txt\n")
    assert run(py1, "import legacy; print(legacy.VALUE)") != run(py2, "import legacy; print(legacy.VALUE)")
    a, b = identity(py1, root), identity(py2, root)
    assert a["digest"] != b["digest"], "same identity although the egg-info package's code differs"


def test_hole_module_on_an_import_path_outside_site_and_root(tmp_path, root):
    """PYTHONPATH (or a .pth line) naming a directory outside the project and the site directories, at the same
    absolute path on both machines: `sys_path` keeps the path, nothing keys the modules in it, and the import
    system's reads are never per-test inputs."""
    py = venv(tmp_path / "m")
    ext = tmp_path / "shared-libs"
    ext.mkdir()
    env = {"PYTHONPATH": f"{Path(__file__).resolve().parents[1] / 'python'}:{ext}"}
    (ext / "helper.py").write_text("VALUE = 1\n")
    a = identity(py, root, env)
    (ext / "helper.py").write_text("VALUE = 2\n")
    b = identity(py, root, env)
    assert a["digest"] != b["digest"], "same identity although `import helper` gives another value"


# ---------------------------------------------------------------------------------------------------------------------
# 2. process environment read by C, never through os.environ (so never a per-test env input)
def test_hole_ld_preload_changes_behaviour_not_identity(tmp_path, root):
    """LD_PRELOAD (and /etc/ld.so.preload) put a library in the process ahead of libc; the native closure is computed
    from DT_NEEDED only. Here the preloaded library changes what os.getuid() returns (tests that skip as root...)."""
    if not shutil.which("gcc"):
        pytest.skip("needs gcc")
    src = tmp_path / "shim.c"
    src.write_text("#include <unistd.h>\nuid_t getuid(void){return 4242;}\nuid_t geteuid(void){return 4242;}\n")
    so = tmp_path / "libshim.so"
    subprocess.run(["gcc", "-shared", "-fPIC", "-o", str(so), str(src)], check=True)
    py = venv(tmp_path / "m")
    assert run(py, "import os; print(os.getuid())") != "4242"
    assert run(py, "import os; print(os.getuid())", {"LD_PRELOAD": str(so)}) == "4242"
    a, b = identity(py, root), identity(py, root, {"LD_PRELOAD": str(so)})
    assert a["digest"] != b["digest"], "same identity although a preloaded library replaces getuid()"


def test_hole_locale_categories_other_than_ctype(tmp_path, root):
    """The identity keeps LC_CTYPE only. LC_NUMERIC / LC_TIME / LC_COLLATE (and LOCPATH, the locale data itself) are
    read by glibc when a test calls setlocale(LC_ALL, ""), never through os.environ."""
    if not shutil.which("localedef") or not Path("/usr/share/i18n/locales/de_DE").exists():
        pytest.skip("needs localedef and the de_DE locale source")
    loc = tmp_path / "locales"
    loc.mkdir()
    r = subprocess.run(["localedef", "-i", "de_DE", "-f", "UTF-8", str(loc / "de_DE.UTF-8")], capture_output=True)
    if not (loc / "de_DE.UTF-8").exists():
        pytest.skip(f"localedef failed: {r.stderr[-300:]!r}")
    py = venv(tmp_path / "m")
    code = "import locale; locale.setlocale(locale.LC_ALL, ''); print(locale.str(1.5))"
    de = {"LOCPATH": str(loc), "LC_NUMERIC": "de_DE.UTF-8"}
    assert run(py, code) == "1.5"
    assert run(py, code, de) == "1,5"
    a, b = identity(py, root), identity(py, root, de)
    assert a["digest"] != b["digest"], "same identity although locale.str(1.5) is '1.5' on one machine, '1,5' on the other"


def test_hole_cpu_count_visible_to_the_process(tmp_path, root):
    """os.process_cpu_count() / len(os.sched_getaffinity(0)) (pool sizes, chunking, xdist-style splitting in a
    test) differ between machines; nothing records them per test and the identity does not include them. The hosted
    rehearsal itself ran machine 1 and machine 2 on different CPUs (AMD EPYC vs Intel Xeon) with equal identities."""
    if not shutil.which("taskset") or (os.cpu_count() or 1) < 2:
        pytest.skip("needs taskset and 2+ CPUs")
    py = venv(tmp_path / "m")
    code = "import os; print(len(os.sched_getaffinity(0)))"
    assert run(py, code) != subprocess.run(["taskset", "-c", "0", py, "-c", code], capture_output=True,
                                           text=True).stdout.strip()
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "python"),
           "FENVIX_RUNTIME_MEMO": "off", "LANG": "C.UTF-8", "HOME": str(root)}
    get = "import sys; from detpy import runtime_id; print(runtime_id.describe(sys.argv[1])['digest'])"
    one = subprocess.run(["taskset", "-c", "0", py, "-c", get, str(root)], env=env, capture_output=True, text=True)
    allc = subprocess.run([py, "-c", get, str(root)], env=env, capture_output=True, text=True)
    assert one.returncode == 0 and allc.returncode == 0, one.stderr + allc.stderr
    assert one.stdout.strip() != allc.stdout.strip(), "same identity with 1 CPU and with all CPUs"


# ---------------------------------------------------------------------------------------------------------------------
# 3. the service: an unauthenticated request makes the server read and decompress its body before the token check
def test_hole_service_decompresses_unauthenticated_bodies(tmp_path, monkeypatch):
    """Handler.do_POST calls _body() (read up to 512 MB, then gzip.decompress with no output bound) before _auth().
    Anyone who can reach the port can make the server inflate a gzip bomb: a few MB of zeros become GBs in memory."""
    from detpy import cache_service as cs

    seen = []
    real = cs.gzip.decompress
    monkeypatch.setattr(cs.gzip, "decompress", lambda b: seen.append(len(b)) or real(b))
    svc = cs.Service(str(tmp_path / "svc"), port=0, quiet=True)
    svc.start_thread()
    try:
        body = gzip.compress(b"0" * (8 * 1024 * 1024))  # 8 MB inflated from ~8 KB; scale freely
        req = urllib.request.Request(svc.url + "/v1/blobs/put", data=body, method="POST",
                                     headers={"Content-Encoding": "gzip", "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            assert e.code in (400, 401)
    finally:
        svc.shutdown()
    assert seen == [], "the server inflated an unauthenticated request body before checking the token"


# ---------------------------------------------------------------------------------------------------------------------
# 4. end to end through the shared cache service: machine 2 reuses a "passed" that a real run on machine 2 fails
import json  # noqa: E402

from test_shared_cache import machine_run, service, write  # noqa: E402,F401


def _two_machines(pytester, tmp_path, monkeypatch, token_url, files, env1, env2, before_2=None):
    """Job 1 on machine 1 (pushes), job 2 on machine 2 (empty mirror, pulls), then a real run on machine 2."""
    svc, token = token_url
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    write(pytester.path, files)
    url = f"{svc.url}/org-a/project"
    for k, v in env1.items():
        monkeypatch.setenv(k, v)
    r1, o1, rep1 = machine_run(pytester, tmp_path, url, token, "1")
    r1.assert_outcomes(passed=1)
    # machine 1 must really record and push: with nothing pushed, machine 2 has nothing to reuse and the test would
    # pass without checking anything (REPORT-3: pytest-benchmark's start-up Popen made every test uncacheable)
    assert rep1.get("push_entries", 0) > 0, f"machine 1 pushed nothing: {o1['cache'].get('not_cached_where')}"
    for k in env1:
        monkeypatch.delenv(k, raising=False)
    for k, v in env2.items():
        monkeypatch.setenv(k, v)
    if before_2:
        before_2()
    _, o2, rep2 = machine_run(pytester, tmp_path, url, token, "2")
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_CACHE_TOKEN"):
        os.environ.pop(k, None)
    fresh = tmp_path / "fresh.json"
    pytester.runpytest_subprocess("--det", f"--det-outcomes={fresh}", "-p", "no:cacheprovider",
                                  f"--basetemp={tmp_path / 'basetemp-fresh'}")
    return o2["outcomes"], json.loads(fresh.read_text())["outcomes"], rep2


@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
def test_e2e_wrong_reuse_module_outside_site_and_root(service, pytester, tmp_path, monkeypatch):
    """Machine 1 and machine 2 have a sibling library at the same path on PYTHONPATH, at different versions."""
    svc, t = service
    ext = tmp_path / "shared-libs"
    ext.mkdir()
    (ext / "helper.py").write_text("VALUE = 1\n")
    pp = os.pathsep.join(x for x in [str(ext), os.environ.get("PYTHONPATH", "")] if x)
    files = {"test_h.py": "import helper\n\ndef test_value():\n    assert helper.VALUE == 1\n"}
    reused, real, rep2 = _two_machines(pytester, tmp_path, monkeypatch, (svc, t["a"]), files, {"PYTHONPATH": pp},
                                       {"PYTHONPATH": pp},
                                       before_2=lambda: (ext / "helper.py").write_text("VALUE = 2\n"))
    assert real["test_h.py::test_value"] == "failed"
    assert reused["test_h.py::test_value"] == "failed", "machine 2 reused 'passed' from the service"


@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
def test_e2e_wrong_reuse_ld_preload(service, pytester, tmp_path, monkeypatch):
    """Machine 2 runs with LD_PRELOAD (a shim, a sanitizer runtime, libfaketime...)."""
    if not shutil.which("gcc"):
        pytest.skip("needs gcc")
    svc, t = service
    src = tmp_path / "shim.c"
    src.write_text("#include <unistd.h>\nuid_t getuid(void){return 4242;}\nuid_t geteuid(void){return 4242;}\n")
    so = tmp_path / "libshim.so"
    subprocess.run(["gcc", "-shared", "-fPIC", "-o", str(so), str(src)], check=True)
    files = {"test_u.py": "import os\n\ndef test_uid():\n    assert os.getuid() != 4242\n"}
    reused, real, _ = _two_machines(pytester, tmp_path, monkeypatch, (svc, t["a"]), files, {},
                                    {"LD_PRELOAD": str(so)})
    assert real["test_u.py::test_uid"] == "failed"
    assert reused["test_u.py::test_uid"] == "failed", "machine 2 reused 'passed' from the service"


# ---------------------------------------------------------------------------------------------------------------------
# 5. trust: what a write token can do, and how a test gets one
@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
def test_hole_token_file_is_readable_by_the_tests(service, pytester, tmp_path, monkeypatch):
    """`hide_token` removes FENVIX_CACHE_TOKEN_FILE from the environment but the file stays on disk at a predictable
    place (the workflow: $RUNNER_TEMP/cache-token). docs/SHARED-CACHE.md: "tests never see the token"."""
    svc, t = service
    tok = tmp_path / "cache-token"
    tok.write_text(t["a"])
    tok.chmod(0o600)
    leak = tmp_path / "leaked"
    files = {"test_leak.py": f"def test_reads_token():\n    open({str(leak)!r}, 'w').write(open({str(tok)!r}).read())\n"}
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    write(pytester.path, files)
    machine_run(pytester, tmp_path, f"{svc.url}/org-a/project", None, "1", env={"FENVIX_CACHE_TOKEN_FILE": str(tok)})
    assert not (leak.exists() and leak.read_text() == t["a"]), "a test read the service's write token"


@pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")
def test_hole_entry_with_no_recorded_inputs_is_reused(service, pytester, tmp_path, monkeypatch):
    """The docs say the recorded *outcome* is a claim and every candidate is checked against code and data. The
    recorded *inputs* are a claim too: an entry that lists no code, data or environment passes every check, so one
    write token makes any test 'pass' on every machine of the organization, at every future commit."""
    from detpy import remote_cache as rc

    svc, t = service
    files = {"pkg.py": "def f():\n    return 1\n", "test_f.py": "from pkg import f\n\ndef test_f():\n    assert f() == 1\n"}
    for k in ("FENVIX_CACHE_LOCAL", "FENVIX_CACHE_REPORT", "FENVIX_RUNTIME_MEMO", "FENVIX_CACHE_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    write(pytester.path, files)
    url = f"{svc.url}/org-a/project"
    machine_run(pytester, tmp_path, url, t["a"], "1")
    store = json.loads((tmp_path / "machine-1" / "mirror" / "proof-cache.json").read_text())
    nid = "test_f.py::test_f"
    e = store["tests"][nid]
    ds = rc._Docs(store)
    forged = ds.entry(nid, e)
    empty = ds.set_of([])
    forged.update(content=empty, skeleton=empty, hooks=empty, unit_files=empty, units=[])
    forged["entry"] = dict(forged["entry"], data=[], env=[])
    http = rc.Http(svc.url, t["a"], retries=0)
    http.call("POST", "/v1/blobs/put", {"docs": {empty: ds.docs[empty], rc.doc_id(forged): forged}})
    key = rc.lookup_key(nid, e["config"], e["runtime"], e.get("epoch"))
    http.call("POST", "/v1/ns/org-a/project/keys", {"put": [{"key": key, "doc": rc.doc_id(forged), "run": "x"}]})
    (pytester.path / "pkg.py").write_text("def f():\n    return 2\n")  # the test now fails for real
    _, o2, _ = machine_run(pytester, tmp_path, url, t["a"], "2")
    assert o2["outcomes"][nid] == "failed", "an entry that claims no inputs was reused: 'passed' for a failing test"
