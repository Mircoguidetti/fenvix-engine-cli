"""runner/fenvix-run node: a Node suite (vitest, jest, node:test, mocha) runs inside detjs with the machine's cache.

For each runner, the fixture of tests/fixtures/runner-node/<runner>/ is copied to a temporary directory, its
packages are installed with `npm ci`, and it is run through the wrapper as a job on a `runs-on: fenvix` machine would:

* cold job, then warm job: the warm job reuses tests with a receipt each; `fenvix-run verify` finds no wrong reuse;
* FENVIX_FIXTURE_FAIL=1: exit 1, the test named in `failed` (re-run alone: fails again, so not flaky);
* FENVIX_FIXTURE_ENTROPY=1: `fenvix-run verify` exits 1 and names the entropy test (NOT PROVEN, or DIVERGED with
  reason entropy: the verifier's verdict for real entropy);
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
    own, runner_args = (list(wrapper_args), []) if "--" not in wrapper_args else \
        (list(wrapper_args[:wrapper_args.index("--")]), list(wrapper_args[wrapper_args.index("--"):]))
    argv = [sys.executable, str(WRAPPER), *wrapper_args] if verify else \
        [sys.executable, str(WRAPPER), "node", *own, "--project", str(proj), "--out", str(out),
         "--key", f"fixture/{proj.name}", *runner_args]
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
    # the check is not vacuous: every reused test is a row of the verify report (same ids)
    assert v["reused_checked"] == v["reused"] == s2["reused_with_proof"], v
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
    # real OS entropy is `--det-urandom=off` since P1 D (by default detjs draws it from a per-test seeded stream)
    code1, s, md1, log1 = job(tmp_path, proj, "entropy", detjs, "--", "--det-urandom=off", env=env)
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


STUB = r"""#!/usr/bin/env python3
# A stand-in detjs for the wrapper's guard branches (tests/test_runner_node.py). Behaviour from $STUB_MODE.
import json, os, sys
a = sys.argv[1:]
if a[:1] == ["--version"]:
    print("fenvix 0.0.0-stub"); sys.exit(0)
mode = os.environ.get("STUB_MODE", "")
if a[:1] == ["verify"]:
    if mode == "verify-junk":
        print("not json"); sys.exit(1)
    rows = [{"nodeid": "a.test.js::t", "status": "diverged", "outcomes": ["passed", "failed"]}]
    print(json.dumps({"status": "diverged", "summary": {"tests": 1, "diverged": 1}, "tests": rows})); sys.exit(1)
opt = {x.split("=", 1)[0]: x.split("=", 1)[1] for x in a if x.startswith("--det-") and "=" in x}
outcome = "failed" if mode == "failed-exit-0" else "passed"
if mode == "zero-tests":
    json.dump({"order": [], "outcomes": {}}, open(opt["--det-outcomes"], "w"))
elif mode != "no-outcomes":
    json.dump({"order": ["a.test.js::t"], "outcomes": {"a.test.js::t": outcome}}, open(opt["--det-outcomes"], "w"))
st = {"failed": int(outcome == "failed"), "not_proven": 0, "passed": int(outcome == "passed"), "skipped": 0}
with open(opt["--det-trace"], "w") as fh:
    # a sensor, as every real header declares one (node/src/session.js provableField; fenvix-run engine_signals)
    fh.write(json.dumps({"type": "header", "meta": {"status": st, "epoch_ns": "1795392000000000000",
                                                    "provable": {"sensor": "node-surface/1"}}}) + "\n")
sys.exit(0)
"""


@pytest.fixture
def stub(tmp_path):
    p = tmp_path / "detjs-stub"
    p.write_text(STUB)
    p.chmod(0o755)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"devDependencies": {"vitest": "5.1.0"}}))
    return (str(p), {}), proj


@pytest.mark.parametrize("mode", ["failed-exit-0", "no-outcomes", "zero-tests"])
def test_detjs_exit_0_without_proof_is_red(stub, tmp_path, mode):
    """Never green without proof: detjs returning 0 with a failed test, or without its outcomes, gives exit 1."""
    detjs, proj = stub
    code, s, md, log = job(tmp_path, proj, "j", detjs, "--no-rerun", env={"STUB_MODE": mode})
    assert code == 1, log
    assert s["exit"] == 1


def test_verify_counts_a_wrong_reuse_and_keeps_detjs_exit(stub, tmp_path):
    detjs, proj = stub
    out = tmp_path / "j"
    out.mkdir()
    (out / "trace.jsonl").write_text("{}\n")
    summary = {"language": "node", "test_runner": "vitest", "project": str(proj), "trace_file": str(out / "trace.jsonl"),
               "epoch_ns": 1795392000000000000, "runner_args": ["run", "--det-cache=/elsewhere"],
               "reused_outcomes": {"a.test.js::t": "passed"}}
    (out / "summary.json").write_text(json.dumps(summary))
    code, v, md, log = job(tmp_path, proj, "v", detjs, "verify", "--summary", str(out / "summary.json"))
    assert code == 1 and v["wrong_reuse"] == 1 and v["wrong"] == ["a.test.js::t"] and v["reused_checked"] == 1, log
    fresh = [x for x in log.splitlines() if "--det-trace=" in x and "trace-fresh" in x]
    assert fresh and "--det-cache=/elsewhere" not in fresh[0], log  # never passed to the fresh run
    code, v, md, log = job(tmp_path, proj, "v2", detjs, "verify", "--summary", str(out / "summary.json"),
                           env={"STUB_MODE": "verify-junk"})
    assert code == 1 and v["verify_status"] is None, log


def test_wrapper_owned_args_are_not_passed_to_detjs(stub, tmp_path):
    detjs, proj = stub
    code, s, md, log = job(tmp_path, proj, "j", detjs, "--", "--det-cache=/other", "--det-trace", "/x",
                           "--det-cache-verify", "--reporter=dot")
    assert code == 0, log
    assert s["runner_args"] == ["run", "--det-cache-verify", "--reporter=dot"], s["runner_args"]
    assert "ignored (the wrapper sets them): --det-cache=/other --det-trace /x" in log


def test_bad_detjs_command_is_exit_2(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"devDependencies": {"jest": "1"}}))
    code, s, md, log = job(tmp_path, proj, "j", ("/nonexistent/detjs", {}))
    assert code == 2 and "detjs not found: '/nonexistent/detjs'" in log, log
    (proj / "package.json").write_text("[]")
    code, s, md, log = job(tmp_path, proj, "j2", ("/nonexistent/detjs", {}))
    assert code == 2 and "is not a JSON object" in log, log


@pytest.mark.parametrize("extra,kept", [
    (["run", "a.js", "--config", "c.ts"], ["--config", "c.ts"]),
    (["--det-cache=/x", "-r", "m", "--det-trace=/t", "--det-outcomes=/o"], ["-r", "m"]),
    (["--det-cache", "/x", "--det-cache-verify", "--det-cache-max-age=1", "--det-trace", "/t"],
     ["--det-cache-verify", "--det-cache-max-age=1"]),
    (["--reporter=dot", "src/"], ["--reporter=dot"]),
])
def test_keep_runner_args(extra, kept):
    assert _load_wrapper()._keep_runner_args(extra) == kept


@pytest.fixture(scope="module")
def hazard_project(tmp_path_factory):
    """tests/fixtures/runner-node/vitest-hazard, copied and installed: two files writing one temp path."""
    d = tmp_path_factory.mktemp("proj-hazard") / "vitest-hazard"
    shutil.copytree(FIXTURES / "vitest-hazard", d)
    r = subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=d, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f"npm ci in the vitest-hazard fixture failed:\n{r.stdout}\n{r.stderr}"
    return d


def test_parallel_hazard_run_sends_a_proof_with_the_one_lane_rerun(hazard_project, detjs, tmp_path):
    """protects=a real detjs run in 2 lanes with a cross-lane hazard: the wrapper's summary carries `proof` from the
    engine's own header (the fields fenvix-run reads: meta.parallel.workers, timing, hazards, hazard_rerun.tests),
    every test proven after the one-lane re-run, exit 0; fails_when=the engine renames or drops a field the runner
    reads (the proof fails closed, exit 1), or the re-run is not reported; no_claim=a hazard the engine does not see."""
    code, s, md, log = job(tmp_path, hazard_project, "hz", detjs, "--no-rerun", "--", "--det-workers=2",
                           env={"DETJS_PLAN_STATE": str(tmp_path / "plan-state.json")})
    header = json.loads(Path(s["trace_file"]).read_text().splitlines()[0])["meta"]
    assert header["parallel"]["hazards"], f"the fixture raised no hazard:\n{log}"
    assert code == 0 and s["exit"] == 0, log
    p = s.get("proof")
    assert p is not None, log
    assert p["workers"] == 2 and p["not_proven"] == 0 and p["not_proven_causes"] == []
    assert p["rerun_one_lane"] == 4 and p["proven"] == 4, p
    assert s["provable_absent"] is None and s["not_proven_outside"] == 0
    record("vitest-hazard", "proof", p)


# -- spec parallel-proof-gaps: the three gaps through the wrapper (shared service, recursive dir op, skip dir) --------

_GAP_HEAD = "import { test, expect } from 'vitest'; import fs from 'node:fs'; import net from 'node:net'; import path from 'node:path';\n"


def _gap_project(hazard_project: Path, tmp: Path, name: str, a: str, b: str, files: dict | None = None,
                 config: str | None = None) -> Path:
    """The installed vitest-hazard fixture with its two test files replaced by `a` and `b` (plus `files`)."""
    d = tmp / name
    shutil.copytree(hazard_project, d, symlinks=True, ignore=shutil.ignore_patterns(".detjs", ".fenvix*"))
    for f in d.glob("*.test.js"):
        f.unlink()
    (d / "a.test.js").write_text(_GAP_HEAD + a + "\n")
    (d / "b.test.js").write_text(_GAP_HEAD + b + "\n")
    for rel, text in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    if config is not None:
        (d / "vitest.config.mjs").write_text(config)
    return d


def _gap_run(proj: Path, tmp: Path, detjs) -> tuple[int, dict, dict, str]:
    code, s, _md, log = job(tmp, proj, "run", detjs, "--no-rerun", "--", "--det-workers=2",
                            env={"DETJS_PLAN_STATE": str(tmp / "plan-state.json")})
    header = json.loads(Path(s["trace_file"]).read_text().splitlines()[0])["meta"] if s.get("trace_file") else {}
    return code, s, header, log


def _assert_gap_rerun(code, s, header, log, kind):
    kinds = [h["kind"] for h in header.get("parallel", {}).get("hazards", [])]
    assert kind in kinds, f"no {kind} hazard ({kinds}):\n{log}"
    assert code == 0 and s["exit"] == 0, log
    p = s.get("proof")
    assert p is not None, log
    # every test of the two files is proven by the one-lane re-run, not by the lanes
    assert p["workers"] == 2 and p["rerun_one_lane"] == p["proven"] == 2 and p["not_proven"] == 0, p


def test_gap_shared_service_reruns_the_files_in_one_lane(hazard_project, detjs, tmp_path):
    """protects=two lanes talking to one local TCP service (served outside the lanes) are proven only through the
    one-lane re-run; fails_when=release-1's engine records no hazard and the wrapper reports the lanes proven
    (rerun_one_lane 0); no_claim=a toy echo server stands in for a database."""
    import socket
    import threading
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            c.sendall(b"hi")
            c.close()
    threading.Thread(target=serve, daemon=True).start()
    client = ("test('talks', async () => { const got = await new Promise((res) => { const s = net.connect(%d, '127.0.0.1'); "
              "let b = ''; s.on('data', (d) => { b += d; }); s.on('end', () => res(b)); s.on('error', (e) => res(String(e.code))); }); "
              "expect(got).toBe('hi'); });") % port
    try:
        proj = _gap_project(hazard_project, tmp_path, "svc", client, client)
        _assert_gap_rerun(*_gap_run(proj, tmp_path, detjs), "shared-service")
    finally:
        srv.close()


def test_gap_recursive_rm_reruns_the_files_in_one_lane(hazard_project, detjs, tmp_path):
    """protects=rm -r of a directory in one lane and a read inside it in the other are proven only through the one-lane
    re-run; fails_when=no hazard (release-1 matched identical keys only), lanes reported proven; no_claim=the read is of
    a path absent at rm time (an existing one already gave an unlink key on release-1)."""
    proj = _gap_project(hazard_project, tmp_path, "rmr",
                        "test('rm', () => { fs.rmSync(path.join(process.cwd(), 'work'), { recursive: true, force: true }); expect(1).toBe(1); });",
                        "test('read', () => { expect(fs.existsSync(path.join(process.cwd(), 'work', 'out.json'))).toBe(false); });",
                        files={"work/.keep": ""})
    _assert_gap_rerun(*_gap_run(proj, tmp_path, detjs), "recursive-write")


def test_gap_project_cache_dir_does_not_hide_a_conflict(hazard_project, detjs, tmp_path):
    """protects=a Vite cacheDir inside the project does not hide a write-write conflict there: the files are proven
    only through the one-lane re-run, and the ignored dir is in the trace; fails_when=the conflict is invisible and the
    lanes are reported proven; no_claim=Vitest 5.1 nests its cache under <cacheDir>/vitest/<sha1(project name)>."""
    import hashlib
    sub = f".cache/vite/vitest/{hashlib.sha1(b'').hexdigest()}"
    body = "test('writes', () => { fs.writeFileSync(path.join(process.cwd(), %s), String(Math.random())); expect(1).toBe(1); });" \
        % json.dumps(f"{sub}/shared.json")
    proj = _gap_project(hazard_project, tmp_path, "cachedir", body, body, files={f"{sub}/.keep": ""},
                        config="export default { cacheDir: '.cache/vite', test: { include: ['*.test.js'] } };\n")
    code, s, header, log = _gap_run(proj, tmp_path, detjs)
    _assert_gap_rerun(code, s, header, log, "write-write")
    ignored = header["parallel"].get("skip_dirs_ignored") or []
    assert any(x["dir"].endswith(sub) and x["reason"] == "outside node_modules and tmpdir" for x in ignored), ignored


def test_gap_clean_two_lane_run_keeps_its_proof_without_rerun(hazard_project, detjs, tmp_path):
    """protects=the positive control through the wrapper: files with nothing shared are proven by the lanes, with no
    one-lane re-run; fails_when=the new hazard kinds fire on an isolated pair; no_claim=a two-file suite."""
    proj = _gap_project(hazard_project, tmp_path, "clean",
                        "test('a', () => { fs.writeFileSync(path.join(process.cwd(), 'a.out'), 'a'); fs.mkdirSync(path.join(process.cwd(), 'ad', 'x'), { recursive: true }); expect(1).toBe(1); });",
                        "test('b', () => { fs.writeFileSync(path.join(process.cwd(), 'b.out'), 'b'); fs.rmSync(path.join(process.cwd(), 'bd'), { recursive: true, force: true }); expect(1).toBe(1); });")
    code, s, header, log = _gap_run(proj, tmp_path, detjs)
    assert header["parallel"]["hazards"] == [], log
    assert code == 0 and s["exit"] == 0, log
    p = s.get("proof")
    assert p is not None and p["workers"] == 2 and p["proven"] == 2 and p["rerun_one_lane"] == 0 and p["not_proven"] == 0, p
