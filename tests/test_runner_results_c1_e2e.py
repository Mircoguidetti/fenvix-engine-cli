"""Spec C1 criterion 1, end to end: a job through runner/fenvix-run with the real runners (vitest, jest, node:test and
pytest, serial and parallel; mocha serial, its reused case under --det-isolate) writes per-test result chunks with:
22 failed tests (one flaky: fails in the suite, passes alone; pytest: 21 call failures and 1 teardown error), 2
skipped and (pytest) 1 xfailed test absent, 1 test reused from the cache sent `skipped_with_proof` with its receipt
and the receipt's duration, failSeq 0-19 re-run alone and 20-21 not, and summary.json's failed/flaky lists equal to
the re-run results of that set.

Set FENVIX_C1_CHUNKS_OUT to a directory to keep the chunks of every case (fenvix-app's runner-results-c1 test parses
them with the App's own parser).

Needs what tests/test_runner_node.py needs (Node 22+, detjs with its native core, npm for the fixtures' packages)
and, for pytest, detpy installed in this interpreter with pytest-xdist.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_runner_node import FIXTURES, WRAPPER, _detjs

N_FAIL = 21  # plain failures; with the flaky victim: 22 failed tests

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def _node_files(runner: str) -> dict[str, str]:
    """reuse (1 passing test), a_flaky (pollute + victim), fails (21 failures + 2 skipped)."""
    esm = runner == "vitest"
    imp = {"vitest": "import { test } from 'vitest';\nimport assert from 'node:assert';\n",
           "jest": "const assert = require('node:assert');\n",
           "node-test": "const test = require('node:test');\nconst assert = require('node:assert');\n",
           "mocha": "const assert = require('node:assert');\nconst test = it;\n"}[runner]
    skip = {"vitest": "test.skip", "jest": "test.skip", "node-test": "test.skip", "mocha": "it.skip"}[runner]
    del esm
    fails = "".join(f"test('f{i:02d}', () => {{ assert.strictEqual({i}, -1); }});\n" for i in range(N_FAIL))
    return {
        "reuse.test.js": imp + "test('reused', () => { assert.ok(true); });\n",
        "a_flaky.test.js": imp + ("test('pollute', () => { globalThis.__c1 = 1; });\n"
                                  "test('victim', () => { assert.strictEqual(globalThis.__c1, undefined); });\n"),
        "fails.test.js": imp + fails + f"{skip}('s1', () => {{}});\n{skip}('s2', () => {{}});\n",
    }


PY_FILES = {
    "test_a_flaky.py": "STATE = []\n\ndef test_1_pollute():\n    STATE.append(1)\n\ndef test_2_victim():\n    assert STATE == []\n",
    "test_fails.py": (
        "import pytest\n\n"
        + "".join(f"def test_f{i:02d}():\n    assert {i} == -1\n\n" for i in range(N_FAIL - 1))
        + "@pytest.fixture\ndef broken():\n    yield\n    raise RuntimeError('teardown broke')\n\n"
        "def test_teardown(broken):\n    pass\n\n"
        "@pytest.mark.skip(reason='c1')\ndef test_s1():\n    pass\n\n"
        "@pytest.mark.skip(reason='c1')\ndef test_s2():\n    pass\n\n"
        "@pytest.mark.xfail(strict=True)\ndef test_xf():\n    assert 0\n"),
    "test_0_reuse.py": "def test_reused():\n    assert True\n",
    "pytest.ini": "[pytest]\n",
}


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """The Node fixtures' packages, installed once per runner (`npm ci` from their lockfiles)."""
    out = {}
    for runner in ("vitest", "jest", "node-test", "mocha"):
        d = tmp_path_factory.mktemp(f"c1-{runner}") / runner
        shutil.copytree(FIXTURES / runner, d)
        lock = json.loads((d / "package-lock.json").read_text())
        if len(lock.get("packages", {})) > 1:
            r = subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=d, capture_output=True, text=True, timeout=600)
            assert r.returncode == 0, f"npm ci in the {runner} fixture failed:\n{r.stdout}\n{r.stderr}"
        for p in d.glob("*.test.js"):
            p.unlink()
        out[runner] = d
    return out


def _job(tmp: Path, argv: list[str], name: str, cache_root: Path, extra_env: dict | None = None):
    out = tmp / name
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp), "GITHUB_STEP_SUMMARY": str(tmp / f"{name}.md"),
         "FENVIX_CACHE_ROOT": str(cache_root), "TMPDIR": str(tmp), **(extra_env or {})}
    head = argv[:1] if argv[:1] == ["node"] else []
    r = subprocess.run([sys.executable, str(WRAPPER), *head, "--out", str(out), *argv[len(head):]], env=e,
                       capture_output=True, text=True, timeout=1800)
    s = json.loads((out / "summary.json").read_text()) if (out / "summary.json").exists() else {}
    chunks = [json.loads(p.read_text()) for p in sorted((out / "results").glob("chunk-*.json"),
                                                         key=lambda p: int(p.stem.split("-")[1]))]
    return r, s, chunks, out


def _check(case: str, chunks: list[dict], s: dict, ids: dict, node: bool, log: str) -> None:
    """The criterion 1 profile of one case."""
    keep = os.environ.get("FENVIX_C1_CHUNKS_OUT")
    if keep:
        d = Path(keep) / case
        d.mkdir(parents=True, exist_ok=True)
        for c in chunks:
            (d / f"chunk-{c['chunk']}.json").write_text(json.dumps(c, indent=1))
    assert chunks and chunks[0]["chunks"] == len(chunks), log
    assert isinstance(chunks[0].get("engineRunId"), str) and chunks[0]["engineRunId"], chunks[0].get("engineRunId")
    tests = [t for c in chunks for t in c["tests"]]
    receipts = [r for c in chunks for r in c["receipts"]]
    by = {t["testId"]: t for t in tests}
    assert len(by) == len(tests), "a test sent twice"
    for gone in ids["absent"]:
        assert gone not in by, f"{gone} (skipped/xfailed) must not be sent"
    failed = sorted((t for t in tests if t["outcome"] == "failed"), key=lambda t: t["failSeq"])
    assert len(failed) == 22, ([t["testId"] for t in failed], log[-3000:])
    assert [t["failSeq"] for t in failed] == list(range(22))
    for t in failed:
        assert t["failure"]["kind"] == "real" and t["failure"]["phase"], t
        assert t["rerunAlone"]["ran"] is (t["failSeq"] < 20), t
    victim = by[ids["victim"]]
    assert victim["failSeq"] < 20 and victim["rerunAlone"] == {"ran": True, "outcome": "passed"}, victim
    for t in failed:
        if t["rerunAlone"]["ran"] and t["testId"] != ids["victim"]:
            assert t["rerunAlone"]["outcome"] == "failed", t
    if "teardown" in ids:
        td = by[ids["teardown"]]
        assert td["outcome"] == "failed" and td["failure"]["phase"] == "teardown", td
    reused = by[ids["reused"]]
    assert reused["outcome"] == "skipped_with_proof", (reused, s.get("not_reused_reasons"), log[-2000:])
    rc = [r for r in receipts if r["testId"] == ids["reused"]]
    assert len(rc) == 1 and rc[0]["cacheKey"] == reused["cacheKey"] and reused["durationMs"] == rc[0]["reusedDurationMs"]
    holder = [c for c in chunks if any(t["testId"] == ids["reused"] for t in c["tests"])]
    assert len(holder) == 1 and rc[0] in holder[0]["receipts"], "a reused test and its receipt share a chunk"
    assert by[ids["pollute"]]["outcome"] == "passed"
    if node:
        for t in tests:
            if t["outcome"] in ("passed", "failed"):
                assert t["durationMs"] >= 1, t
    # summary.json lists follow the re-run results of that set
    assert [f["nodeid"] for f in s["flaky"]] == [ids["victim"]], s["flaky"]
    first20 = [t["testId"] for t in failed[:20]]
    rest = [t["testId"] for t in failed[20:]]
    assert s["failed"] == [n for n in first20 if n != ids["victim"]] + rest, s["failed"]
    if node:
        assert [x["nodeid"] for x in s["reruns"]] == first20


NODE_CASES = [("vitest", "serial"), ("vitest", "parallel"), ("jest", "serial"), ("jest", "parallel"),
              ("node-test", "serial"), ("node-test", "parallel"), ("mocha", "serial")]


@pytest.mark.parametrize("runner,mode", NODE_CASES)
def test_node_job_sends_per_test_results(installed, tmp_path, runner, mode):
    # protects: spec C1 criterion 1 for the Node runners (fenvix-run node + the engine's side records)
    # fails_when: any field of the profile in _check is missing or wrong
    # no_claim: the App's storage (fenvix-app tests); parallel hazard re-runs (criterion 2, unit + stub tests)
    detjs = _detjs()
    proj = tmp_path / "proj"
    shutil.copytree(installed[runner], proj, symlinks=True)
    files = _node_files(runner)
    for name, body in files.items():
        (proj / name).write_text(body)
    if runner == "mocha":
        (proj / ".mocharc.json").write_text(json.dumps({"spec": sorted(files)}))
    det = ["--det-workers=1"] if mode == "serial" else ["--det-workers=2"]
    if runner == "mocha":
        det = ["--det-isolate"]  # one process per file: a file is reused alone (mocha/cli.js)
    env = {"FENVIX_DETJS": detjs[0], **detjs[1]}
    argv = ["node", "--project", str(proj), "--key", f"c1/{runner}-{mode}", "--runner", runner, "--", *det]
    cache_root = tmp_path / "machine-cache"
    r1, s1, _, _ = _job(tmp_path, argv, "job1", cache_root, env)
    assert r1.returncode == 1, r1.stdout[-3000:] + r1.stderr[-3000:]
    r2, s2, chunks, _ = _job(tmp_path, argv, "job2", cache_root, env)
    assert r2.returncode == 1 and s2["exit"] == 1, r2.stdout[-3000:] + r2.stderr[-3000:]
    ids = {"victim": "a_flaky.test.js::victim", "pollute": "a_flaky.test.js::pollute", "reused": "reuse.test.js::reused",
           "absent": ["fails.test.js::s1", "fails.test.js::s2"]}
    _check(f"{runner}-{mode}", chunks, s2, ids, True, r2.stdout + r2.stderr)


@pytest.mark.parametrize("mode", ["serial", "parallel"])
def test_pytest_job_sends_per_test_results(tmp_path, mode):
    # protects: spec C1 criterion 1 for pytest (outcomes, teardown error, xfail absent, receipts, re-run files)
    # fails_when: any field of the profile in _check is missing or wrong, or the re-runs share one outcomes file
    # no_claim: pytest's own durations as real time of the test body only (they include setup and teardown)
    proj = tmp_path / "proj"
    proj.mkdir()
    for name, body in PY_FILES.items():
        (proj / name).write_text(body)
    extra = [] if mode == "serial" else ["--", "-n", "2", "--dist", "loadfile"]
    argv = ["--project", str(proj), "--python", sys.executable, "--key", f"c1/pytest-{mode}", *extra]
    cache_root = tmp_path / "machine-cache"
    r1, _, _, _ = _job(tmp_path, argv, "job1", cache_root)
    assert r1.returncode != 0, r1.stdout[-3000:] + r1.stderr[-3000:]
    r2, s2, chunks, out = _job(tmp_path, argv, "job2", cache_root)
    log = r2.stdout + r2.stderr
    assert r2.returncode != 0, log[-3000:]
    ids = {"victim": "test_a_flaky.py::test_2_victim", "pollute": "test_a_flaky.py::test_1_pollute",
           "reused": "test_0_reuse.py::test_reused", "teardown": "test_fails.py::test_teardown",
           "absent": ["test_fails.py::test_s1", "test_fails.py::test_s2", "test_fails.py::test_xf"]}
    _check(f"pytest-{mode}", chunks, s2, ids, False, log)
    # criterion 4: the re-runs follow failSeq, each with its own outcomes file
    failed = sorted((t for c in chunks for t in c["tests"] if t["outcome"] == "failed"), key=lambda t: t["failSeq"])
    for i, t in enumerate(failed[:20]):
        data = json.loads((out / f"outcomes-rerun-{i}.json").read_text())
        assert list(data["outcomes"]) == [t["testId"]], (i, t["testId"], data["outcomes"])
    assert not (out / "outcomes-rerun-20.json").exists() and not (out / "outcomes-rerun.json").exists()
