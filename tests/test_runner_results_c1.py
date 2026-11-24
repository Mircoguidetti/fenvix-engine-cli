"""Spec C1 (idea 3, "is this red real?"), runner part: runner/fenvix-run turns the engine's outcomes file, receipts
and (Node parallel) trace header into the per-test results the App stores (POST /v1/runner/results), written as
<out>/results/chunk-<n>.json for the machine's poster.

Unit tests of the pure functions (the outcome table, receipts, chunk limits, failSeq, the re-run set and its
mapping, the NOT PROVEN and re-run hazard files of a parallel run), and wrapper runs with a stand-in detjs for the
file handling (old chunks removed, FENVIX_SEND_RESULTS=0, the re-run set and summary lists). The end-to-end runs
with the real runners are in tests/test_runner_results_c1_e2e.py.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "runner" / "fenvix-run"
K = "0123456789abcdef0123456789abcdef"
FP = "fedcba9876543210fedcba9876543210"


def _load():
    loader = importlib.machinery.SourceFileLoader("fenvix_run_c1", str(WRAPPER))
    spec = importlib.util.spec_from_loader("fenvix_run_c1", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


W = _load()


def row(**kw):
    r = {"nodeid": "t::a", "reused": True, "key": K, "run": "20261124T000000-1", "fingerprint": FP, "duration": 0.25,
         "config": "c" * 32, "runtime": "r" * 32}
    r.update(kw)
    return r


# ---------------------------------------------------------------------------------------------------- outcome table
@pytest.mark.parametrize("engine,sent", [
    ("passed", "passed"), ("xpassed", "passed"),
    ("failed", "failed"), ("error", "failed"), ("unknown", "failed"), ("passed+teardown-error", "failed"),
    ("failed+teardown-error", "failed"), ("interrupted", "failed"), ("something-new", "failed"),
    ("skipped", None), ("todo", None), ("xfailed", None),
])
def test_outcome_table(engine, sent):
    # protects: spec C1 2.2's table; fails_when: an unknown or teardown-error outcome is sent passed or dropped, or a
    # skipped/todo/xfailed test is sent; no_claim: values the App would reject (it gets only these two)
    assert W.sent_outcome(engine) == sent


def test_rows_in_order_with_failseq_durations_and_failure_records():
    # protects: 2.2 order (order, then outcomes not in it), 2.4 failure records, 2.5 failSeq, durationMs units
    # fails_when: failSeq skips or follows another order, pytest seconds are not converted, a missing record is not
    #   the bare {kind: real, phase: call}
    # no_claim: the App's own ordering of what it stores
    outcomes = {"a": "failed", "b": "passed", "c": "skipped", "d": "error", "e": "passed+teardown-error", "z": "failed"}
    exceptions = {"a": ["AssertionError", "call", "assert 1 == 2", "t.py:3"], "e": ["RuntimeError", "teardown", "x", ""]}
    tests, receipts, too_long = W.results_rows(["e", "a", "b", "c", "d"], outcomes, {"a": 0.0125, "b": 2}, exceptions, {},
                                               seconds=True)
    assert [t["testId"] for t in tests] == ["e", "a", "b", "d", "z"]
    by = {t["testId"]: t for t in tests}
    assert [by[n]["failSeq"] for n in ("e", "a", "d", "z")] == [0, 1, 2, 3]
    assert by["a"]["failure"] == {"kind": "real", "phase": "call", "exceptionType": "AssertionError",
                                  "message": "assert 1 == 2", "location": "t.py:3"}
    assert by["e"]["failure"] == {"kind": "real", "phase": "teardown", "exceptionType": "RuntimeError", "message": "x"}
    assert by["d"]["failure"] == {"kind": "real", "phase": "call"}
    assert by["a"]["durationMs"] == 12 and by["b"]["durationMs"] == 2000 and by["d"]["durationMs"] == 0
    assert "failSeq" not in by["b"] and "failure" not in by["b"]
    assert receipts == {} and too_long == []
    assert W.failed_in_order(tests) == ["e", "a", "d", "z"]
    # Node: durations are whole ms already
    t2, _, _ = W.results_rows(["n"], {"n": "passed"}, {"n": 7}, {}, {}, seconds=False)
    assert t2[0]["durationMs"] == 7


def test_reused_test_is_skipped_with_proof_with_its_receipt():
    # protects: 2.2 reuse row and 2.3 receipt fields (apply.ts matches the receipt by testId)
    # fails_when: durationMs is not the receipt's, the receipt lists code/modules/filesRead/envRead, or a row the
    #   App would reject (no fingerprint, no run, a key not 32 hex) makes a skipped_with_proof test
    # no_claim: the lists code/modules/filesRead/envRead (out of scope)
    rows = {"a": row(nodeid="a"), "b": row(nodeid="b", fingerprint=""), "c": row(nodeid="c", run=None),
            "d": row(nodeid="d", runtime=None), "e": row(nodeid="e", key="not-hex")}
    outcomes = {k: "passed" for k in "abcde"}
    tests, receipts, _ = W.results_rows(list("abcde"), outcomes, {k: 0.001 for k in "abcde"}, {}, rows, seconds=True)
    by = {t["testId"]: t for t in tests}
    assert by["a"] == {"testId": "a", "outcome": "skipped_with_proof", "durationMs": 250, "cacheKey": K}
    assert receipts["a"] == {"testId": "a", "cacheKey": K, "reusedEngineRunId": "20261124T000000-1", "fingerprint": FP,
                             "reusedDurationMs": 250, "config": {"digest": "c" * 32}, "runtime": {"digest": "r" * 32}}
    assert by["b"]["outcome"] == by["c"]["outcome"] == by["e"]["outcome"] == "passed"
    assert by["d"]["outcome"] == "skipped_with_proof" and "runtime" not in receipts["d"]
    assert set(receipts) == {"a", "d"}


def test_not_proven_and_hazard_rerun_overrides():
    # protects: 2.2 NOT PROVEN rows (cause <= 500) and the complete re-run's outcome replacing pass 1's
    # fails_when: an unaccounted id is sent with pass 1's outcome, or a hazard test that failed in the re-run is sent
    #   passed, or it is sent with pass 1's failure record / receipt
    # no_claim: which tests the engine re-ran (node/src/parallel-rerun.js)
    outcomes = {"h.test.js::x": "passed", "h.test.js::y": "passed", "k.test.js::z": "failed"}
    np = {"h.test.js::y": "c" * 600}
    final = {"h.test.js::x": "failed"}
    tests, receipts, _ = W.results_rows(list(outcomes), outcomes, {"h.test.js::x": 4}, {"k.test.js::z": ["E", "call", "m", ""]},
                                        {"h.test.js::x": row(nodeid="h.test.js::x")}, seconds=False, not_proven=np, final=final)
    by = {t["testId"]: t for t in tests}
    assert by["h.test.js::y"]["outcome"] == "not_proven" and len(by["h.test.js::y"]["notProvenCause"]) == 500
    assert by["h.test.js::x"] == {"testId": "h.test.js::x", "outcome": "failed", "durationMs": 4,
                                  "failure": {"kind": "real", "phase": "call"}, "failSeq": 0}
    assert receipts == {}
    assert by["k.test.js::z"]["failSeq"] == 1


def test_node_hazard_overrides_from_meta_and_final_trace(tmp_path):
    # protects: reading meta.hazard_rerun (incomplete: unaccounted ids with their file's cause; complete: the final
    #   trace's records of the hazard files, streamed)
    # fails_when: the cause is not the file's, or a record of another file is taken
    # no_claim: traces the engine did not write
    meta = {"hazard_rerun": {"files": ["h.test.js"], "complete": False, "unaccounted": ["h.test.js::y"],
                             "not_proven": [{"file": "h.test.js", "cause": "it ran 1 of its 2 test(s)"}]}}
    np, final = W.node_hazard_overrides(meta, tmp_path / "none.jsonl")
    assert final == {} and list(np) == ["h.test.js::y"] and "it ran 1 of its 2 test(s)" in np["h.test.js::y"]
    trace = tmp_path / "t.jsonl"
    trace.write_text("\n".join(json.dumps(x, separators=(",", ":")) for x in [  # compact, as the engine writes
        {"type": "header", "meta": {}},
        {"type": "test", "nodeid": "h.test.js::x", "outcome": "failed"},
        {"type": "test", "nodeid": "h.test.js::w", "outcome": "todo"},
        {"type": "test", "nodeid": "k.test.js::z", "outcome": "passed"},
    ]) + "\n")
    meta = {"hazard_rerun": {"files": ["h.test.js"], "complete": True, "unaccounted": [], "not_proven": []}}
    np, final = W.node_hazard_overrides(meta, trace)
    assert np == {} and final == {"h.test.js::x": "failed", "h.test.js::w": "skipped"}
    assert W.node_hazard_overrides({}, trace) == ({}, {})


def test_too_long_id_is_skipped_and_logged(capsys):
    # protects: 2.2 (a testId over 2,000 characters would reject the whole chunk at the App)
    # fails_when: it is sent, or dropped silently; no_claim: ids of exactly 2,000 characters are kept (checked here)
    long_id, edge = "x" * 2001, "y" * 2000
    tests, _, too_long = W.results_rows([long_id, edge], {long_id: "failed", edge: "failed"}, {}, {}, {}, seconds=True)
    assert [t["testId"] for t in tests] == [edge] and tests[0]["failSeq"] == 0
    assert too_long == [long_id]
    assert "2001 characters" in capsys.readouterr().out


@pytest.mark.parametrize("engine,exc,expected", [
    ("passed", None, {"ran": True, "outcome": "passed"}),
    ("failed", ["AssertionError", "call", "m", "f:1"], {"ran": True, "outcome": "failed", "failure": {
        "kind": "real", "phase": "call", "exceptionType": "AssertionError", "message": "m", "location": "f:1"}}),
    ("error", None, {"ran": True, "outcome": "failed", "failure": {"kind": "real", "phase": "call"}}),
    ("skipped", None, {"ran": True, "outcome": "not_proven"}),
    (None, None, {"ran": True, "outcome": "not_proven"}),
])
def test_rerun_alone_mapping(engine, exc, expected):
    # protects: 2.6 rerunAlone; fails_when: an unreadable re-run or a skipped one reads as passed or failed
    # no_claim: why the re-run did not run the test
    assert W.rerun_alone(engine, exc) == expected


# ---------------------------------------------------------------------------------------------------- chunks
def _tests(n, reused_every=0):
    tests, receipts = [], {}
    for i in range(n):
        tid = f"f.py::t{i}"
        if reused_every and i % reused_every == 0:
            tests.append({"testId": tid, "outcome": "skipped_with_proof", "durationMs": 1, "cacheKey": K})
            receipts[tid] = W.receipt_of(row(nodeid=tid), tid)
        else:
            tests.append({"testId": tid, "outcome": "passed", "durationMs": 1})
    return tests, receipts


def test_chunk_limits_tests_receipts_bytes_and_pairs():
    # protects: 2.1 limits (5,000 tests, 2,000 receipts, 4,000,000 bytes) and a reused test with its receipt
    # fails_when: any chunk breaks a limit, a receipt is apart from its test, or chunk 0 lacks chunks/engineRunId/seed
    # no_claim: the fewest possible chunks
    head = {"engineRunId": "r1", "seed": None}
    tests, receipts = _tests(12_001, reused_every=2)
    chunks = W.chunk_tests(tests, receipts, head)
    assert chunks[0]["chunks"] == len(chunks) and chunks[0]["engineRunId"] == "r1" and chunks[0]["seed"] is None
    assert [c["chunk"] for c in chunks] == list(range(len(chunks)))
    assert all("chunks" not in c and "engineRunId" not in c for c in chunks[1:])
    for c in chunks:
        assert len(c["tests"]) <= 5000 and len(c["receipts"]) <= 2000
        assert len(json.dumps(c, separators=(",", ":")).encode()) <= 4_000_000
        here = {t["testId"] for t in c["tests"] if t["outcome"] == "skipped_with_proof"}
        assert here == {r["testId"] for r in c["receipts"]}
    assert sum(len(c["tests"]) for c in chunks) == 12_001
    assert [t["testId"] for c in chunks for t in c["tests"]] == [t["testId"] for t in tests]
    # bytes: 1,999-character ids reach 4,000,000 bytes before 5,000 tests
    big = [{"testId": f"{i:06d}" + "z" * 1993, "outcome": "failed", "durationMs": 1,
            "failure": {"kind": "real", "phase": "call", "message": "m" * 4000}, "failSeq": i} for i in range(1200)]
    chunks = W.chunk_tests(big, {}, head)
    assert len(chunks) > 1
    assert all(len(json.dumps(c, separators=(",", ":")).encode()) <= 4_000_000 for c in chunks)
    # an empty run: one chunk 0 with no tests
    assert W.chunk_tests([], {}, head) == [{"chunk": 0, "chunks": 1, "engineRunId": "r1", "seed": None, "tests": [],
                                            "receipts": []}]


@pytest.mark.parametrize("run,seed,shuffle,expected", [
    ("r", 5, True, {"engineRunId": "r", "seed": 5}),
    ("r", 5, False, {"engineRunId": "r", "seed": None}),
    (None, 5, True, {"seed": 5}),
    ("r" * 101, 0, True, {"seed": 0}),
    ("r", 2 ** 60, True, {"engineRunId": "r", "seed": None}),
])
def test_results_head(run, seed, shuffle, expected):
    # protects: engineRunId (<= 100) and seed (null without shuffle, contract l.471; only exact integers)
    # fails_when: a value the App rejects (whole chunk lost) is sent; no_claim: a seed over 2^53 is not kept
    assert W.results_head(run, seed, shuffle) == expected


# ---------------------------------------------------------------------------------------------------- wrapper runs
STUB = r"""#!/usr/bin/env python3
# A stand-in detjs (tests/test_runner_results_c1.py): writes outcomes, trace and cache summary from $STUB_PLAN.
import json, os, sys
a = sys.argv[1:]
if a[:1] == ["--version"]:
    print("fenvix 0.0.0-stub"); sys.exit(0)
plan = json.load(open(os.environ["STUB_PLAN"]))
opt = {x.split("=", 1)[0]: x.split("=", 1)[1] for x in a if x.startswith("--det-") and "=" in x}
rerun = "--det-cache" not in opt
if rerun:
    name = [x for x in a if not x.startswith("-")][-1].strip("^$").replace("\\", "")
    nid = next(n for n in plan["outcomes"] if n.endswith("::" + name))
    o = plan["alone"].get(nid, "failed")
    json.dump({"order": [nid], "outcomes": {nid: o}, "exceptions": {nid: ["E", "call", "again", ""]} if o == "failed" else {}},
              open(opt["--det-outcomes"], "w"))
    with open(os.environ["STUB_LOG"], "a") as fh:
        fh.write(nid + "\n")
    sys.exit(0)
json.dump({"order": plan["order"], "outcomes": plan["outcomes"], "durations": plan.get("durations", {}),
           "exceptions": {}, "seed": 3, "shuffle": True}, open(opt["--det-outcomes"], "w"))
json.dump({"run": "20261124T000000-abc"}, open(opt["--det-cache-summary"], "w"))
st = {"failed": sum(o != "passed" for o in plan["outcomes"].values()), "not_proven": 0, "passed": 1, "skipped": 0}
with open(opt["--det-trace"], "w") as fh:
    meta = {"status": st, "epoch_ns": "1795392000000000000", **plan.get("meta", {})}
    fh.write(json.dumps({"type": "header", "meta": meta}) + "\n")
    for t in plan.get("trace_tests", []):  # the final (merged) trace's records, compact as the engine writes them
        fh.write(json.dumps({"type": "test", **t}, separators=(",", ":")) + "\n")
sys.exit(1)
"""


def _job(tmp_path, plan, env=None, out_name="out", max_reruns=None):
    stub = tmp_path / "detjs-stub"
    stub.write_text(STUB)
    stub.chmod(0o755)
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "package.json").write_text(json.dumps({"devDependencies": {"vitest": "5.1.0"}}))
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    log = tmp_path / "reruns.log"
    log.unlink(missing_ok=True)
    out = tmp_path / out_name
    e = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path), "FENVIX_CACHE_ROOT": str(tmp_path / "c"),
         "FENVIX_DETJS": str(stub), "STUB_PLAN": str(tmp_path / "plan.json"), "STUB_LOG": str(log),
         "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md"), **(env or {})}
    argv = [sys.executable, str(WRAPPER), "node", "--project", str(proj), "--out", str(out), "--key", "k"]
    if max_reruns is not None:
        argv += ["--max-reruns", str(max_reruns)]
    r = subprocess.run(argv, env=e, capture_output=True, text=True, timeout=300)
    s = json.loads((out / "summary.json").read_text())
    reran = log.read_text().split() if log.exists() else []
    chunks = sorted((out / "results").glob("chunk-*.json")) if (out / "results").is_dir() else []
    return r, s, reran, [json.loads(p.read_text()) for p in chunks], out


def test_rerun_set_follows_failseq_and_summary_lists_follow_it(tmp_path):
    # protects: 2.6 (re-run set = sent failed set in failSeq order, first --max-reruns; summary failed/flaky/reruns
    #   built from it) and rerunAlone ran true/false
    # fails_when: an `unknown` or `+teardown-error` test is not re-run, the order is sorted() instead of failSeq, or
    #   a test past --max-reruns claims ran: true
    # no_claim: the exit code (unchanged: detjs's 1 here)
    ids = [f"t.test.js::c{i}" for i in range(5)]
    outcomes = {ids[0]: "passed", ids[1]: "unknown", ids[2]: "failed", ids[3]: "passed+teardown-error", ids[4]: "failed"}
    plan = {"order": [ids[0], ids[4], ids[3], ids[2], ids[1]], "outcomes": outcomes, "alone": {ids[3]: "passed"},
            "durations": {i: 3 for i in ids}}
    r, s, reran, chunks, _ = _job(tmp_path, plan, max_reruns=3)
    assert r.returncode == 1, r.stdout + r.stderr
    assert reran == [ids[4], ids[3], ids[2]]
    assert [x["nodeid"] for x in s["reruns"]] == reran
    assert [f["nodeid"] for f in s["flaky"]] == [ids[3]]
    assert s["failed"] == [ids[4], ids[2], ids[1]]
    tests = {t["testId"]: t for c in chunks for t in c["tests"]}
    assert [tests[i]["failSeq"] for i in (ids[4], ids[3], ids[2], ids[1])] == [0, 1, 2, 3]
    assert tests[ids[3]]["rerunAlone"] == {"ran": True, "outcome": "passed"}
    assert tests[ids[4]]["rerunAlone"]["outcome"] == "failed" and tests[ids[4]]["rerunAlone"]["failure"]["message"] == "again"
    assert tests[ids[1]]["rerunAlone"] == {"ran": False}
    assert "rerunAlone" not in tests[ids[0]] and tests[ids[0]]["durationMs"] == 3
    assert chunks[0]["engineRunId"] == "20261124T000000-abc" and chunks[0]["seed"] == 3


def test_old_chunks_removed_and_send_results_0_writes_none(tmp_path):
    # protects: 2.1 (old chunk-*.json removed before a run, always; FENVIX_SEND_RESULTS=0 writes none)
    # fails_when: a chunk of an earlier run survives into this run's spool, or sending off still writes chunks
    # no_claim: other files in <out>/results
    plan = {"order": ["a.test.js::x"], "outcomes": {"a.test.js::x": "passed"}, "alone": {}}
    stale = tmp_path / "out" / "results"
    stale.mkdir(parents=True)
    for n in range(3):
        (stale / f"chunk-{n}.json").write_text("{}")
    _, _, _, chunks, out = _job(tmp_path, plan)
    assert [c["chunk"] for c in chunks] == [0] and chunks[0]["tests"][0]["testId"] == "a.test.js::x"
    assert sorted(p.name for p in (out / "results").glob("chunk-*.json")) == ["chunk-0.json"]
    r, _, _, chunks, out = _job(tmp_path, plan, env={"FENVIX_SEND_RESULTS": "0"})
    assert chunks == [] and "FENVIX_SEND_RESULTS=0" in r.stdout


def test_parallel_incomplete_rerun_sends_unaccounted_tests_not_proven(tmp_path):
    # protects: criterion 2a (an incomplete one-lane re-run: each unaccounted id NOT PROVEN with its file's cause)
    # fails_when: an unaccounted test is sent with the first pass's outcome or without the cause
    # no_claim: how the engine decides a re-run is incomplete (node/src/parallel-rerun.js accountRerun)
    outcomes = {"h.test.js::a": "passed", "h.test.js::b": "failed", "k.test.js::c": "passed"}
    meta = {"hazard_rerun": {"files": ["h.test.js"], "complete": False, "unaccounted": ["h.test.js::a", "h.test.js::b"],
                             "not_proven": [{"file": "h.test.js", "cause": "its trace is missing"}]}}
    plan = {"order": list(outcomes), "outcomes": outcomes, "alone": {}, "meta": meta}
    _, s, reran, chunks, _ = _job(tmp_path, plan)
    tests = {t["testId"]: t for c in chunks for t in c["tests"]}
    for n in ("h.test.js::a", "h.test.js::b"):
        assert tests[n]["outcome"] == "not_proven" and "its trace is missing" in tests[n]["notProvenCause"], tests[n]
        assert "failSeq" not in tests[n]
    assert tests["k.test.js::c"]["outcome"] == "passed"
    assert reran == [] and s["failed"] == []


def test_parallel_complete_rerun_failure_is_sent_failed(tmp_path):
    # protects: criterion 2b (a hazard-file test that passed in pass 1 and failed in the complete re-run is failed)
    # fails_when: pass 1's `passed` (the outcomes file) is sent for it
    # no_claim: the re-run's failure message (pass 2 writes no outcomes file: {kind: real, phase: call} only)
    outcomes = {"h.test.js::a": "passed", "h.test.js::b": "passed", "k.test.js::c": "passed"}
    meta = {"hazard_rerun": {"files": ["h.test.js"], "complete": True, "unaccounted": [], "not_proven": []}}
    trace_tests = [{"nodeid": "h.test.js::a", "outcome": "failed"}, {"nodeid": "h.test.js::b", "outcome": "passed"},
                   {"nodeid": "k.test.js::c", "outcome": "passed"}]
    plan = {"order": list(outcomes), "outcomes": outcomes, "alone": {"h.test.js::a": "failed"}, "meta": meta,
            "trace_tests": trace_tests, "durations": {"h.test.js::a": 9}}
    _, s, reran, chunks, _ = _job(tmp_path, plan)
    tests = {t["testId"]: t for c in chunks for t in c["tests"]}
    assert tests["h.test.js::a"]["outcome"] == "failed" and tests["h.test.js::a"]["failSeq"] == 0
    assert tests["h.test.js::a"]["failure"] == {"kind": "real", "phase": "call"} and tests["h.test.js::a"]["durationMs"] == 9
    assert tests["h.test.js::b"]["outcome"] == "passed"
    assert reran == ["h.test.js::a"] and s["failed"] == ["h.test.js::a"]
