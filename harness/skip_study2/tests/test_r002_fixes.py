"""Tests for the R-002 fixes of the skip study 2 harness (one per fix; the reviewer's own two tests are in
test_r002_capture.py). Run:

    python3 -m pytest -q harness/skip_study2/tests/

Needs git, strace and uv; the Go test needs go; the docusaurus test needs a built docusaurus checkout
(DOCUSAURUS_SRC, default: the reviewer's) and Node 26 (NODE_BIN_DIR) and is skipped without them.
"""
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))
import aggregate  # noqa: E402
import strace_deps  # noqa: E402
import walk  # noqa: E402
from test_r002_capture import g, make_walker  # noqa: E402

SCRATCH = "/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad/review-R-002"


# -- fix 1: read-write opens ---------------------------------------------------------------------------------
def test_parse_rdwr_is_read_but_trunc_and_new_are_not(tmp_path):
    root = str(tmp_path)
    log = tmp_path / "st.log"
    log.write_text("\n".join([
        f'1 openat(AT_FDCWD</x>, "{root}/fixture.db", O_RDWR|O_CREAT|O_CLOEXEC, 0644) = 3<{root}/fixture.db>',
        f'1 openat(AT_FDCWD</x>, "{root}/log.txt", O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC, 0666) = 4<{root}/log.txt>',
        f'1 openat(AT_FDCWD</x>, "{root}/out.txt", O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC, 0666) = 5<{root}/out.txt>',
        f'1 newfstatat(AT_FDCWD</x>, "{root}/new.db", 0x7ffd, 0) = -1 ENOENT (No such file or directory)',
        f'1 openat(AT_FDCWD</x>, "{root}/new.db", O_RDWR|O_CREAT|O_CLOEXEC, 0644) = 6<{root}/new.db>',
        f'1 openat(AT_FDCWD</x>, "{root}/snap.txt", O_RDONLY|O_CLOEXEC) = 7<{root}/snap.txt>',
        f'1 openat(AT_FDCWD</x>, "{root}/snap.txt", O_WRONLY|O_TRUNC|O_CLOEXEC) = 7<{root}/snap.txt>',
        f'1 openat(AT_FDCWD</x>, "{root}/excl", O_RDWR|O_CREAT|O_EXCL, 0600) = 8<{root}/excl>',
    ]) + "\n")
    d = strace_deps.parse(log, root, [root])
    assert set(d["reads"]) == {f"{root}/fixture.db", f"{root}/log.txt", f"{root}/snap.txt"}
    assert set(d["rw"]) == {f"{root}/fixture.db", f"{root}/log.txt", f"{root}/snap.txt"}


def test_rdwr_dependency_is_the_committed_content(tmp_path):
    """The sqlite fixture's recorded hash is its committed content, also when the test rewrites the file."""
    w, c0, c1 = make_walker(tmp_path)
    w.checkout(c0)
    (w.src / "tests" / "test_db.py").write_text(
        "import sqlite3\nfrom pathlib import Path\n\ndef test_fixture_value():\n"
        "    con = sqlite3.connect(Path(__file__).parent / 'fixture.db')\n"
        "    assert con.execute('select v from t').fetchone()[0] == 1\n"
        "    con.execute('update t set v = 7'); con.commit()\n")
    rec = w.run_unit("tests/test_db.py")
    p = str(w.src / "tests" / "fixture.db")
    committed = __import__("hashlib").sha1(subprocess.run(["git", "show", f"{c0}:tests/fixture.db"], cwd=w.src,
                                                          capture_output=True).stdout).hexdigest()[:16]
    assert rec["code"] == 0 and rec["deps"]["reads"][p] == committed != w.hasher.file(p)


# -- fix 2: environment variables -------------------------------------------------------------------------
def test_unread_environment_variable_does_not_invalidate(tmp_path, monkeypatch):
    w, c0, c1 = make_walker(tmp_path)
    w.checkout(c0)
    monkeypatch.delenv("R002_FLAG", raising=False)
    rec = w.run_unit("tests/test_env.py"); rec["sha"] = c0
    assert "R002_FLAG" in rec["deps"]["env"]
    monkeypatch.setenv("R002_UNREAD", "1")
    decision, _ = w.decide("tests/test_env.py", rec, c0, [c0, c1])
    assert decision["closure"] is None
    monkeypatch.setenv("R002_FLAG", "1")
    decision, _ = w.decide("tests/test_env.py", rec, c0, [c0, c1])
    assert decision["closure"] == "env-var:R002_FLAG"


def test_whole_environment_enumeration_is_a_dependency(tmp_path, monkeypatch):
    w, c0, c1 = make_walker(tmp_path)
    w.checkout(c0)
    (w.src / "tests" / "test_env.py").write_text(
        "import os\n\ndef test_flag():\n    assert 'R002_ANY' not in dict(os.environ)\n")
    rec = w.run_unit("tests/test_env.py"); rec["sha"] = c0
    assert "*" in rec["deps"]["env"]
    monkeypatch.setenv("R002_SOMETHING_ELSE", "1")
    decision, _ = w.decide("tests/test_env.py", rec, c0, [c0, c1])
    assert decision["closure"] == "env-var:*"


DOCU = Path(os.environ.get("DOCUSAURUS_SRC", f"{SCRATCH}/src/docusaurus"))
NODE = Path(os.environ.get("NODE_BIN_DIR", f"{SCRATCH}/node26dl/node-v26.13.1-linux-x64/bin"))
GLOB_TEST = "packages/docusaurus-glob/src/__tests__/globUtils.test.ts"


@pytest.mark.skipif(not (DOCU / GLOB_TEST).exists() or not (NODE / "node").exists(),
                    reason="needs a built docusaurus checkout and Node 26")
def test_docusaurus_home_case_reruns_when_home_changes(tmp_path, monkeypatch):
    """R-002 error 2, real repository: globUtils.test.ts renders HOME into a snapshot (os.homedir())."""
    spec = json.loads((HARNESS / "specs" / "docusaurus.json").read_text())
    w = walk.Walker(spec, tmp_path / "w", tmp_path / "out.json", 0, 1, 30, "r002")
    w.src = DOCU
    w.push = False
    monkeypatch.setenv("PATH", f"{NODE}:{os.environ['PATH']}")
    # a HOME other than /root, kept across runs (pnpm's own binary is cached under it: a fresh HOME downloads it, a
    # network access the network guard rightly refuses to skip)
    home_a, home_b = Path(os.environ.get("R002_HOME_A", f"{SCRATCH}/../nt/out/fakehome")).resolve(), Path("/root")
    home_a.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home_a))
    sha = g(DOCU, "rev-parse", "HEAD")
    w.cur_sha = sha
    rec = w.run_unit(GLOB_TEST); rec["sha"] = sha
    assert rec["code"] == 0
    assert "HOME" in rec["deps"]["env"]
    monkeypatch.setenv("R002_UNREAD", "1")
    assert w.decide(GLOB_TEST, rec, sha, [sha])[0]["closure"] is None  # unread variable: still skipped
    monkeypatch.setenv("HOME", str(home_b))
    fresh = w.run_unit(GLOB_TEST, traced_run=False)
    assert fresh["code"] != 0                                          # the outcome really depends on HOME
    assert w.decide(GLOB_TEST, rec, sha, [sha])[0]["closure"] == "env-var:HOME"


# -- fix 3: Go network guard ------------------------------------------------------------------------------
def test_local_address_classification():
    loc = strace_deps.is_local_address
    assert loc("127.0.0.1", 8080) and loc("::1", 80) and loc("::ffff:127.0.0.1", 80) and loc("0.0.0.0", 80)
    assert not loc("127.0.0.53", 53)          # name resolution: the answer comes from outside
    assert not loc("75.2.60.5", 443) and not loc("?", 0) and not loc("2001:db8::1", 443)


GO_NET_TEST = """package netpkg

import (
\t"net"
\t"testing"
\t"time"
)

// like terraform internal/cloud: the test talks to a service outside the machine (TEST-NET-1 address)
func TestExternal(t *testing.T) {
\tc, err := net.DialTimeout("tcp", "192.0.2.1:443", 300*time.Millisecond)
\tif err == nil {
\t\tc.Close()
\t}
}
"""
GO_LOOP_TEST = """package looppkg

import (
\t"net"
\t"testing"
)

func TestLoopback(t *testing.T) {
\tl, err := net.Listen("tcp", "127.0.0.1:0")
\tif err != nil {
\t\tt.Fatal(err)
\t}
\tdefer l.Close()
\tc, err := net.Dial("tcp", l.Addr().String())
\tif err != nil {
\t\tt.Fatal(err)
\t}
\tc.Close()
}
"""


@pytest.mark.skipif(shutil.which("go") is None, reason="needs go")
def test_go_package_with_external_connect_is_never_skipped(tmp_path):
    src = tmp_path / "w" / "src"
    for d, body in (("netpkg", GO_NET_TEST), ("looppkg", GO_LOOP_TEST)):
        (src / d).mkdir(parents=True)
        (src / d / f"{d}_test.go").write_text(body)
    (src / "go.mod").write_text("module example.com/r002\n\ngo 1.22\n")
    g(src, "init", "-q", "-b", "main"); g(src, "config", "user.email", "r@x"); g(src, "config", "user.name", "r")
    g(src, "add", "-A"); g(src, "commit", "-qm", "c0")
    c0 = g(src, "rev-parse", "HEAD")
    (src / "README").write_text("unrelated\n")
    g(src, "add", "-A"); g(src, "commit", "-qm", "c1")
    c1 = g(src, "rev-parse", "HEAD")
    spec = {"name": "r002-go", "lang": "go", "seq": {"kind": "list", "commits": [c0, c1]},
            "units": {"patterns": ["./..."]}, "install_files": ["go.mod"], "verify": 0.0}
    w = walk.Walker(spec, tmp_path / "w", tmp_path / "out.json", 0, 1, 30, "r002")
    w.push = False
    os.environ.setdefault("GOFLAGS", "-mod=mod")
    w.walk()
    t = w.result["transitions"][0]
    dec = {u: d for u, d in t["decisions"].items()}
    assert "example.com/r002/netpkg" in dec and dec["example.com/r002/netpkg"]["go-cache"] is None  # go cache: hit
    assert dec["example.com/r002/netpkg"]["closure"] == "network"                                  # proof: rerun
    assert "example.com/r002/looppkg" not in dec or dec["example.com/r002/looppkg"]["closure"] is None
    info = w.result["unit_info"]
    assert info["example.com/r002/netpkg"]["net_ext"] >= 1 and info["example.com/r002/looppkg"]["net_ext"] == 0


# -- fix 5: runtime identity ---------------------------------------------------------------------------------
@pytest.mark.skipif(not Path("/usr/bin/python3.12").exists(), reason="needs a second Python")
def test_interpreter_change_invalidates(tmp_path):
    w, c0, c1 = make_walker(tmp_path)
    w.checkout(c0)
    rec = w.run_unit("tests/test_env.py"); rec["sha"] = c0
    assert w.decide("tests/test_env.py", rec, c0, [c0, c1])[0]["closure"] is None
    shutil.rmtree(w.venv)
    subprocess.run(["uv", "venv", "-q", "--python", "/usr/bin/python3.12", str(w.venv)], check=True)
    w.spec["install"] = ["uv pip install -q --python {py} pytest"]
    assert w.install()[0]
    assert w.decide("tests/test_env.py", rec, c0, [c0, c1])[0]["closure"].startswith("runtime:")
    assert rec["deps"]["runtime"]["python"] != w.runtime()["python"]
    assert rec["deps"]["runtime"]["stdlib"] != w.runtime()["stdlib"]


def test_runtime_identity_covers_node_binary_and_tzdata(tmp_path):
    a = walk.runtime_identity("vitest", {"PATH": os.environ["PATH"]})
    assert {"node", "tzdata", "syslibs"} <= set(a)
    if (NODE / "node").exists():
        b = walk.runtime_identity("vitest", {"PATH": f"{NODE}:{os.environ['PATH']}"})
        assert a["node"] != b["node"] and a["tzdata"] == b["tzdata"]


# -- fix 8: a cached failure is never reused ---------------------------------------------------------------
def test_cached_failure_is_never_reused(tmp_path, monkeypatch):
    w, c0, c1 = make_walker(tmp_path)
    w.checkout(c0)
    monkeypatch.setenv("R002_FLAG", "1")
    rec = w.run_unit("tests/test_env.py"); rec["sha"] = c0
    assert rec["code"] == 1
    assert w.decide("tests/test_env.py", rec, c0, [c0, c1])[0]["closure"] == "cached-failure"


# -- fix 6: extra skips of the other rules are compared ----------------------------------------------------
def test_extra_skips_of_func_rules_are_verified(tmp_path):
    src = tmp_path / "w" / "src"
    (src / "tests").mkdir(parents=True)
    (src / "pkg.py").write_text("def used():\n    return 1\n\n\ndef unused():\n    return 2\n")
    (src / "tests" / "test_pkg.py").write_text("import pkg\n\ndef test_used():\n    assert pkg.used() == 1\n")
    g(src, "init", "-q", "-b", "main"); g(src, "config", "user.email", "r@x"); g(src, "config", "user.name", "r")
    g(src, "add", "-A"); g(src, "commit", "-qm", "c0")
    c0 = g(src, "rev-parse", "HEAD")
    (src / "pkg.py").write_text("def used():\n    return 1\n\n\ndef unused():\n    return 3\n")
    g(src, "commit", "-qam", "c1")
    c1 = g(src, "rev-parse", "HEAD")
    spec = {"name": "r002-x", "lang": "pytest", "seq": {"kind": "list", "commits": [c0, c1]},
            "units": {"include": ["tests/test_*.py"]}, "workers": 1, "verify": 0.0, "plain_baseline": False,
            "install": ["test -x {py} || uv venv -q --python 3.13 {venv}", "uv pip install -q --python {py} pytest"],
            "cmd": ["{py}", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "s2_report", "{unit}"],
            "env": {"PYTHONPATH": "{src}"}}
    w = walk.Walker(spec, tmp_path / "w", tmp_path / "out.json", 0, 1, 30, "r002")
    w.push = False
    w.walk()
    t = w.result["transitions"][0]
    assert t["decisions"]["tests/test_pkg.py"]["closure"].startswith("py-source")
    assert t["decisions"]["tests/test_pkg.py"]["func+guard"] is None
    assert [(x["unit"], x["same"], "func+guard" in x["rules"]) for x in t["xverify"]] == [
        ("tests/test_pkg.py", True, True)]


# -- fix 7: re-check verdicts are an allow-list ------------------------------------------------------------
def test_recheck_verdicts_allow_list():
    ok = aggregate.recheck_says_flaky
    assert ok("flaky (plain runs disagree)")
    assert ok("flaky (same intermittent teardown error at both commits): the cached failure ...")
    assert ok("capture-induced flaky failure: the cached failure was recorded under strace ...")
    assert ok("not-reproducible")
    assert not ok("missed dependency")
    assert not ok("code-change")
    assert not ok("incomplete")
    assert not ok("")
