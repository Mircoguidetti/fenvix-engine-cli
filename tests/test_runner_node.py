"""runner/fenvix-run node: a Node suite (vitest, jest, node:test, mocha) runs inside detjs with the machine's cache.

For each runner, the fixture of tests/fixtures/runner-node/<runner>/ is copied to a temporary directory, its
packages are installed with `npm ci`, and it is run through the wrapper as a job on a `runs-on: fenvix` machine would:

* cold job, then warm job: the warm job reuses tests with a receipt each; `fenvix-run verify` finds no wrong reuse;
* FENVIX_FIXTURE_FAIL=1: exit 1, the test named in `failed` (re-run alone: fails again, so not flaky);
* FENVIX_FIXTURE_ENTROPY=1: `fenvix-run verify` exits 1 and names the entropy test NOT PROVEN;
* a package.json naming no runner (or two): exit 2.

What it needs: Node 22 or newer and detjs, as `runner/bootstrap.sh install` leaves them on a machine: `detjs` from
$FENVIX_DETJS, else `detjs` on PATH, else $FENVIX_HOME/bin/detjs, else this checkout's node/bin/detjs.js with its
native core (node/detjs.linux-x64.node, target/release, or dist/detjs.linux-x64.node of the CI build job, passed as
DETJS_NATIVE); and npm with access to the registry for the fixtures' pinned packages. A missing prerequisite fails
the test (it is never skipped): a machine that cannot run it cannot run a Node customer either.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "runner" / "fenvix-run"
FIXTURES = ROOT / "tests" / "fixtures" / "runner-node"
RUNNERS = ("vitest", "jest", "node-test", "mocha")
TEST_RUNNER = {"vitest": "vitest", "jest": "jest", "node-test": "node:test", "mocha": "mocha"}
# the fixture's test ids as detjs names them (file::[describe::]test)
IDS = {
    "vitest": {"fail": "fail.test.js::fails on demand", "entropy": "entropy.test.js::reads OS entropy"},
    "jest": {"fail": "fail.test.js::fails on demand", "entropy": "entropy.test.js::reads OS entropy"},
    "node-test": {"fail": "fail.test.js::fails on demand", "entropy": "entropy.test.js::reads OS entropy"},
    "mocha": {"fail": "fail.test.js::fail::fails on demand", "entropy": "entropy.test.js::entropy::reads OS entropy"},
}
# what the tests measured (exit codes, verify statuses, divergences), written to $FENVIX_NODE_RESULTS when set
RESULTS: dict = {}


def _load_wrapper():
    loader = importlib.machinery.SourceFileLoader("fenvix_run", str(WRAPPER))
    spec = importlib.util.spec_from_loader("fenvix_run", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _detjs() -> tuple[str, dict]:
    """The detjs command and the extra environment it needs."""
    node = shutil.which("node")
    if not node:
        pytest.fail("node not on PATH: Node 22 or newer is needed (runner/bootstrap.sh install checks it)")
    v = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    m = re.match(r"v(\d+)", v)
    if not m or int(m.group(1)) < 22:
        pytest.fail(f"node {v} on PATH: Node 22 or newer is needed")
    if os.environ.get("FENVIX_DETJS"):
        return os.environ["FENVIX_DETJS"], {}
    if shutil.which("detjs"):
        return shutil.which("detjs"), {}
    home = os.environ.get("FENVIX_HOME")
    if home and os.access(os.path.join(home, "bin", "detjs"), os.X_OK):
        return os.path.join(home, "bin", "detjs"), {}
    cmd = f"{node} {ROOT / 'node' / 'bin' / 'detjs.js'}"
    for addon in (ROOT / "node" / "detjs.linux-x64.node", ROOT / "target" / "release" / "libdetpy_node.so"):
        if addon.is_file():
            return cmd, {}
    if (ROOT / "dist" / "detjs.linux-x64.node").is_file():
        return cmd, {"DETJS_NATIVE": str(ROOT / "dist" / "detjs.linux-x64.node")}
    pytest.fail("detjs not found: no $FENVIX_DETJS, no detjs on PATH or in $FENVIX_HOME/bin, and no native core in "
                "this checkout (node node/scripts/build.js, or runner/bootstrap.sh install)")


@pytest.fixture(scope="module")
def detjs():
    return _detjs()


@pytest.fixture(scope="module", params=RUNNERS)
def project(request, tmp_path_factory):
    """The runner's fixture, copied and installed (`npm ci` from its lockfile)."""
    runner = request.param
    d = tmp_path_factory.mktemp(f"proj-{runner}") / runner
    shutil.copytree(FIXTURES / runner, d)
    lock = json.loads((d / "package-lock.json").read_text())
    if len(lock.get("packages", {})) > 1:
        r = subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=d, capture_output=True, text=True,
                           timeout=600)
        assert r.returncode == 0, f"npm ci in the {runner} fixture failed:\n{r.stdout}\n{r.stderr}"
    return runner, d


def job(tmp: Path, proj: Path, name: str, detjs: tuple[str, dict], *wrapper_args: str, env: dict | None = None,
        cache_root: Path | None = None) -> tuple[int, dict, str, str]:
    """One job through the wrapper: (exit, summary.json or verify.json, step summary, log)."""
    out = tmp / name
    md = tmp / f"{name}.md"
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp), "GITHUB_STEP_SUMMARY": str(md),
         "FENVIX_CACHE_ROOT": str(cache_root or (tmp / "machine-cache")), "TMPDIR": str(tmp),
         "FENVIX_DETJS": detjs[0], **detjs[1], **(env or {})}
    verify = wrapper_args[:1] == ("verify",)
    argv = [sys.executable, str(WRAPPER), *wrapper_args] if verify else \
        [sys.executable, str(WRAPPER), "node", *wrapper_args, "--project", str(proj), "--out", str(out),
         "--key", f"fixture/{proj.name}"]
    r = subprocess.run(argv, env=e, capture_output=True, text=True, timeout=900)
    target = (Path(wrapper_args[wrapper_args.index("--summary") + 1]).parent / "verify.json") if verify \
        else out / "summary.json"
    data = json.loads(target.read_text()) if target.exists() else {}
    return r.returncode, data, md.read_text() if md.exists() else "", r.stdout + r.stderr


def record(runner: str, key: str, value) -> None:
    RESULTS.setdefault(runner, {})[key] = value
    p = os.environ.get("FENVIX_NODE_RESULTS")
    if p:
        Path(p).write_text(json.dumps(RESULTS, indent=1, sort_keys=True))


def test_cold_then_warm_reuses_with_receipts_and_verify_finds_no_wrong_reuse(project, detjs, tmp_path):
    """AC1: the runner is detected from package.json (no --runner), the warm job reuses with a receipt per reused
    test, and verify (a fresh run without the cache, compared trace to trace by detjs verify) finds no wrong reuse."""
    runner, proj = project
    code1, s1, md1, log1 = job(tmp_path, proj, "job1", detjs)
    assert code1 == 0, log1
    assert s1["language"] == "node" and s1["test_runner"] == TEST_RUNNER[runner], log1
    assert s1["cache_was_warm"] is False and s1["reused_with_proof"] == 0 and s1["tests"] >= 4, s1
    assert "cold" in md1

    code2, s2, md2, log2 = job(tmp_path, proj, "job2", detjs)
    assert code2 == 0, log2
    assert s2["cache_was_warm"] is True
    assert s2["reused_with_proof"] >= 1, (s2["not_reused_reasons"], s2["not_cached"], log2)
    receipts = [json.loads(x) for x in Path(s2["receipts"]).read_text().splitlines() if x.strip()]
    outcome_id = _load_wrapper().outcome_id
    receipted = {outcome_id(r["nodeid"], s2["outcomes"]) for r in receipts if r.get("reused")}
    assert set(s2["reused_outcomes"]) <= receipted and s2["reused_outcomes"], (s2["reused_outcomes"], receipted)
    for r in receipts:
        if r.get("reused"):
            assert r.get("key") and r.get("why", "").startswith("reused"), r
    assert s2["reused_with_proof"] + s2["ran"] == s2["tests"]
    assert f"Skipped with proof (result reused, receipt kept) | **{s2['reused_with_proof']}** |" in md2

    code3, v, md3, log3 = job(tmp_path, proj, "verify", detjs, "verify", "--summary",
                              str(tmp_path / "job2" / "summary.json"))
    record(runner, "cold_warm_verify", {
        "cold": {"exit": code1, "tests": s1["tests"], "reused": s1["reused_with_proof"]},
        "warm": {"exit": code2, "tests": s2["tests"], "reused": s2["reused_with_proof"],
                 "saved_s": s2["test_seconds_saved"], "outcome_counts": s2["outcome_counts"]},
        "verify": {"exit": code3, "status": v.get("verify_status"), "wrong_reuse": v.get("wrong_reuse"),
                   "identical": v.get("identical"), "diverged": v.get("diverged"),
                   "not_proven": v.get("not_proven"), "diverged_tests": v.get("diverged_tests")}})
    assert v.get("verify_status") is not None, log3
    assert v["wrong_reuse"] == 0 and v["wrong"] == [], (v, log3)
    assert code3 in (0, 1, 3), log3
    # the verify exit is detjs verify's: 0 only when its status is identical
    assert (code3 == 0) == (v["verify_status"] == "identical"), (code3, v)
    assert json.loads((tmp_path / "job2" / "summary.json").read_text())["verify_status"] == v["verify_status"]


def test_a_failing_test_gives_exit_1_and_is_named(project, detjs, tmp_path):
    """AC2: FENVIX_FIXTURE_FAIL=1 -> exit 1, the test in `failed`; the re-run alone (no cache) fails again, so it is
    not reported flaky, and the exit code is not lowered."""
    runner, proj = project
    code, s, md, log = job(tmp_path, proj, "fail", detjs, env={"FENVIX_FIXTURE_FAIL": "1"})
    record(runner, "fail", {"exit": code, "failed": s.get("failed"), "flaky": s.get("flaky"),
                            "reruns": s.get("reruns")})
    assert code == 1, log
    assert IDS[runner]["fail"] in s["failed"], (s["failed"], s["outcomes"])
    assert s["flaky"] == []
    assert [r["nodeid"] for r in s["reruns"]] == [IDS[runner]["fail"]] and s["reruns"][0]["outcome"] == "failed", \
        s["reruns"]


def test_neither_variable_gives_exit_0(project, detjs, tmp_path):
    """AC2: with neither variable the run is green: exit 0, nothing failed, nothing NOT PROVEN."""
    runner, proj = project
    code, s, md, log = job(tmp_path, proj, "plain", detjs)
    record(runner, "plain", {"exit": code, "status": s.get("status")})
    assert code == 0 and s["failed"] == [] and s["not_proven"] == 0, log


def test_entropy_is_named_by_verify(project, detjs, tmp_path):
    """AC2: FENVIX_FIXTURE_ENTROPY=1 -> `fenvix-run verify` exits 1 and names the entropy test. The verifier
    (crates/detpy-core/src/verify.rs) gives NOT PROVEN only when the runs' fingerprints agree; real OS entropy makes
    them differ, so it names the test DIVERGED with reason `entropy` (MEASURED for all four runners, REPORT.md).
    Either verdict names it; it is never identical. A single run names no NOT PROVEN test of its own
    (node/src/session.js:478): what the plain run prints and returns is recorded, not asserted."""
    runner, proj = project
    env = {"FENVIX_FIXTURE_ENTROPY": "1"}
    code1, s, md1, log1 = job(tmp_path, proj, "entropy", detjs, env=env)
    status_line = [x for x in log1.splitlines() if x.startswith("detjs: status:")]
    code2, v, md2, log2 = job(tmp_path, proj, "entropy-verify", detjs, "verify", "--summary",
                              str(tmp_path / "entropy" / "summary.json"), env=env)
    record(runner, "entropy", {"run_exit": code1, "run_status_line": status_line,
                               "run_outcome": s.get("outcomes", {}).get(IDS[runner]["entropy"]),
                               "verify_exit": code2, "verify_status": v.get("verify_status"),
                               "not_proven_tests": v.get("not_proven_tests"),
                               "diverged_tests": v.get("diverged_tests")})
    assert code2 == 1, log2
    eid = IDS[runner]["entropy"]
    named = set(v["not_proven_tests"]) | {d["nodeid"] for d in v["diverged_tests"] if d["reason"] == "entropy"}
    assert eid in named, (v, log2)
    assert v["verify_status"] in ("not_proven", "diverged"), v


def test_no_runner_in_package_json_gives_exit_2(detjs, tmp_path):
    """AC2: no runner found -> exit 2, the message names what was found."""
    proj = tmp_path / "none"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "x", "scripts": {"test": "echo no tests"}}))
    code, s, md, log = job(tmp_path, proj, "none", detjs)
    record("no-runner", "exit", code)
    assert code == 2 and "no test runner found" in log and not s, log


def test_two_runners_in_package_json_give_exit_2(detjs, tmp_path):
    proj = tmp_path / "two"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"name": "x", "devDependencies": {"vitest": "5.1.0", "jest": "30.5.2"}}))
    code, s, md, log = job(tmp_path, proj, "two", detjs)
    assert code == 2 and "more than one test runner found" in log and "vitest, jest" in log, log


@pytest.mark.parametrize("pkg,expected", [
    ({"devDependencies": {"vitest": "1"}}, "vitest"),
    ({"devDependencies": {"jest": "1"}}, "jest"),
    ({"devDependencies": {"mocha": "1"}}, "mocha"),
    ({"scripts": {"test": "node --test"}}, "node-test"),
    ({"scripts": {"test": "node --experimental-strip-types --test src/"}}, "node-test"),
    ({"scripts": {"test": "tsc && node --test-reporter=spec --test"}}, "node-test"),
    ({"scripts": {"test": "echo node is great -- test"}}, None),
    ({"dependencies": {"jest": "1"}}, None),
    ({}, None),
])
def test_detect_node_runner(tmp_path, pkg, expected):
    w = _load_wrapper()
    (tmp_path / "package.json").write_text(json.dumps(pkg))
    assert w.detect_node_runner(tmp_path)[0] == expected


@pytest.mark.parametrize("runner,nodeid,expected", [
    ("vitest", "a.test.js::adds", ["run", "a.test.js", "-t", "^adds$"]),
    ("jest", "a.test.js::outer::x (1+1)", ["a.test.js", "-t", r"^outer x \(1\+1\)$"]),
    ("node-test", "a.test.js::outer::inner", ["--test-name-pattern", "^inner$", "a.test.js"]),
    ("mocha", "a.test.js::outer::adds", ["a.test.js", "--grep", "^outer adds$"]),
    ("vitest", "a.test.js@@web::adds", ["run", "a.test.js", "-t", "^adds$"]),
])
def test_single_test_command(runner, nodeid, expected):
    assert _load_wrapper().single_test_args(runner, nodeid) == expected



@pytest.mark.parametrize("text,key", [
    ("new", "new"),
    ("outcome failed", "outcome-failed"),
    ("os entropy (not controlled; use --det-urandom)", "os-entropy"),
    ("reads a clock Level 0 does not virtualize", "reads-a-clock-level-0-does-not"),
    ("x" * 50, "x" * 40),
])
def test_reason_keys_fit_the_app(text, key):
    """not_cached / not_reused_reasons keys: short tags the App accepts (github-app/src/results/summary.ts counts():
    ``^[A-Za-z0-9_.:-]{1,40}$``); the detjs text is kept in reason_texts."""
    w = _load_wrapper()
    assert w.reason_key(text) == key
    texts: dict = {}
    counts = w.reason_counts({text: 2}, texts)
    assert counts == {key: 2} and texts == {key: text}
    assert re.fullmatch(r"[A-Za-z0-9_.:-]{1,40}", key)
