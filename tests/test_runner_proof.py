"""runner/fenvix-run node: the summary's ``proof`` and the two engine signals (proof to the customer, B2).

Pure helpers of the wrapper (node_proof, read_footer, group_causes, cut_utf16, engine_signals) on synthetic trace
headers, and the whole wrapper on a stand-in detjs that writes a chosen trace header, footer, outcomes and receipts,
so the exit status and ``summary["exit"]`` are checked together. No Node, no npm: the real runs are in the report
(docs/REPORT-proof-to-customer.md in fenvix-app) and in tests/fixtures/runner-node/vitest-hazard.

Each test states protects= / fails_when= / no_claim=.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "runner" / "fenvix-run"


def _load():
    loader = importlib.machinery.SourceFileLoader("fenvix_run_proof", str(WRAPPER))
    spec = importlib.util.spec_from_loader("fenvix_run_proof", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


W = _load()

OUT4 = {"a.test.js::1": "passed", "a.test.js::2": "passed", "b.test.js::1": "passed", "b.test.js::2": "passed"}


SENSOR = {"sensor": "node-surface/1", "contract": 1, "runtime": "node22", "surface": "x"}
CONTROLS = ["fs", "isolation", "net", "order", "seeds", "time", "timers"]


def meta(**over) -> dict:
    """A parallel final trace header: 2 workers, 4 tests passed, no hazard."""
    m = {
        # every real header declares its sensor (node/src/session.js provableField); without it the run is NOT PROVEN.
        # As a real header writes it (contract, runtime, controls): C4 refuses a declaration the core's judge refuses
        "provable": dict(SENSOR),
        "controls": list(CONTROLS),
        "status": {"passed": 4, "failed": 0, "not_proven": 0, "skipped": 0},
        # every real parallel header carries the observed placement (node/src/parallel.js collect)
        "parallel": {"workers": 2, "hazards": [], "placement": {"deviations": []},
                     "timing": {"files": 2, "test_file_seconds": 1.5, "lanes_wall_seconds": 0.9}},
    }
    m.update(over)
    return m


def proof(m: dict | None = None, footer: dict | None = None, outcomes: dict | None = None, reused: dict | None = None):
    return W.node_proof(m if m is not None else meta(), footer, outcomes if outcomes is not None else OUT4, reused or {})


# ---------------------------------------------------------------- one test per row of the mapping


def test_row_workers():
    """protects=proof.workers is meta.parallel.workers; fails_when=another value or a default; no_claim=lane use."""
    m = meta()
    m["parallel"]["workers"] = 3
    assert proof(m)[0]["workers"] == 3


def test_row_not_proven():
    """protects=proof.not_proven is the final trace's status.not_proven; fails_when=it is recomputed or dropped;
    no_claim=which tests they are."""
    m = meta(status={"passed": 2, "failed": 0, "not_proven": 2, "skipped": 0})
    p, why = proof(m)
    assert why is None and p["not_proven"] == 2


def test_row_proven_is_the_engines_counts_minus_reused_not_skipped():
    """protects=proven = passed + failed - reused tests not skipped/todo (a null reused outcome counts as passed);
    fails_when=reused tests are counted as proven in lanes, or skipped reused ones are subtracted; no_claim=that the
    engine's status counts are right."""
    out = {**OUT4, "c.test.js::1": "skipped", "c.test.js::2": "passed", "c.test.js::3": "passed"}
    reused = {"c.test.js::1": "skipped", "c.test.js::2": "passed", "c.test.js::3": None}
    m = meta(status={"passed": 6, "failed": 0, "not_proven": 0, "skipped": 1})
    p, why = proof(m, outcomes=out, reused=reused)
    assert why is None
    assert p["proven"] == 6 - 2  # c.test.js::2 and ::3 (None = passed) are reused; c::1 is skipped
    assert W.ran_executed_of(out, reused) == 4
    assert p["proven"] + p["not_proven"] == W.ran_executed_of(out, reused)


def test_row_rerun_one_lane():
    """protects=rerun_one_lane is hazard_rerun.tests, 0 without a re-run; fails_when=the files are counted, or a
    missing re-run is not 0; no_claim=what the re-run found."""
    assert proof()[0]["rerun_one_lane"] == 0
    m = meta(hazard_rerun={"files": ["a.test.js", "b.test.js"], "tests": 4, "not_proven": [], "complete": True})
    assert proof(m)[0]["rerun_one_lane"] == 4


def test_row_parallel_seconds():
    """protects=parallel_seconds is timing.lanes_wall_seconds; fails_when=the file-time sum or the job wall time is
    used; no_claim=the re-run's own time (not included, docstring)."""
    assert proof()[0]["parallel_seconds"] == 0.9


def test_row_serial_seconds_estimate():
    """protects=serial_seconds_estimate is timing.test_file_seconds, else null; fails_when=a missing one is 0 or
    fails the proof; no_claim=how good the estimate is."""
    assert proof()[0]["serial_seconds_estimate"] == 1.5
    m = meta()
    del m["parallel"]["timing"]["test_file_seconds"]
    p, why = proof(m)
    assert why is None and p["serial_seconds_estimate"] is None


def test_row_order_digest():
    """protects=order_digest is the footer's, else null; fails_when=a missing footer fails the proof or a non-string
    digest is passed on; no_claim=the digest's meaning."""
    assert proof(footer={"type": "footer", "n_tests": 4, "order_digest": "ab12"})[0]["order_digest"] == "ab12"
    assert proof(footer=None)[0]["order_digest"] is None
    assert proof(footer={"type": "footer", "order_digest": 5})[0]["order_digest"] is None


def test_row_not_proven_causes_grouped_and_sorted():
    """protects=causes grouped by cause with tests summed, sorted by tests descending then cause; fails_when=one
    entry per file of the same cause, or another order; no_claim=the cause wording (engine, B1)."""
    np_ = [{"file": "b", "cause": "y", "tests": 1}, {"file": "a", "cause": "x", "tests": 2},
           {"file": "c", "cause": "y", "tests": 1}, {"file": "d", "cause": "a", "tests": 2}]
    m = meta(status={"passed": 0, "failed": 0, "not_proven": 6, "skipped": 0},
             hazard_rerun={"files": [], "tests": 6, "not_proven": np_})
    out = {f"t{i}": "passed" for i in range(6)}
    assert proof(m, outcomes=out)[0]["not_proven_causes"] == [
        {"cause": "a", "tests": 2}, {"cause": "x", "tests": 2}, {"cause": "y", "tests": 2}]


def test_51_cause_groups_become_50_entries():
    """protects=at most 50 causes (the App refuses a proof with more); fails_when=51 entries, or the merged count is
    lost; no_claim=which causes are merged beyond the order rule."""
    entries = [{"cause": f"c{i:02d}", "tests": 100 - i} for i in range(51)]
    g = W.group_causes(entries)
    assert len(g) == 50
    assert g[-1] == {"cause": "other causes", "tests": (100 - 49) + (100 - 50)}
    assert sum(x["tests"] for x in g) == sum(e["tests"] for e in entries)


def test_a_600_unit_cause_is_cut_to_500():
    """protects=a cause fits the App's 500 UTF-16 code units; fails_when=601..600 units pass, or a surrogate pair is
    split; no_claim=the words kept."""
    assert len(W.cut_utf16("x" * 600).encode("utf-16-le")) // 2 == 500
    emoji = "\U0001F600" * 300  # 600 UTF-16 units
    cut = W.cut_utf16(emoji)
    assert len(cut.encode("utf-16-le")) // 2 == 500 and cut == "\U0001F600" * 250
    g = W.group_causes([{"cause": "z" * 600, "tests": 1}])
    assert len(g[0]["cause"]) == 500


# ---------------------------------------------------------------- when no proof is due


def test_serial_run_has_no_proof():
    """protects=a run in one lane gets no proof and no NOT PROVEN for it; fails_when=workers 1 or no meta.parallel
    gives a proof or an incomplete field; no_claim=the serial run's own correctness."""
    m = meta()
    m["parallel"]["workers"] = 1
    assert proof(m) == (None, None)
    assert proof({"status": meta()["status"]}) == (None, None)
    # a meta.parallel that is not an object now fails closed (review 2026-11-25): test_review_fail_closed_shapes


def test_nothing_ran_in_lanes_has_no_proof_and_is_not_not_proven():
    """protects=a warm run that reused everything (workers 2) gets no proof and is not NOT PROVEN for it;
    fails_when=a proof of 0 of 0, or a fail-closed field; no_claim=the reuse receipts."""
    reused = dict(OUT4)
    m = meta()
    del m["parallel"]["timing"]  # a run where no file ran has no timing
    assert proof(m, reused=reused) == (None, None)
    skipped_only = {"a.test.js::1": "skipped", "a.test.js::2": "todo"}
    assert proof(m, outcomes=skipped_only) == (None, None)


# ---------------------------------------------------------------- fail closed (pure)


@pytest.mark.parametrize("field,edit", [
    ("workers", lambda m: m["parallel"].pop("workers")),
    ("workers", lambda m: m["parallel"].__setitem__("workers", "2")),
    ("status.not_proven", lambda m: m["status"].pop("not_proven")),
    ("status.passed", lambda m: m["status"].pop("passed")),
    ("status.failed", lambda m: m["status"].__setitem__("failed", 1.5)),
    ("timing.lanes_wall_seconds", lambda m: m["parallel"]["timing"].pop("lanes_wall_seconds")),
    ("timing.lanes_wall_seconds", lambda m: m["parallel"]["timing"].__setitem__("lanes_wall_seconds", "1")),
    ("hazard_rerun.tests", lambda m: m.__setitem__("hazard_rerun", {"files": [], "not_proven": []})),
    ("hazard_rerun.not_proven[].tests", lambda m: m.__setitem__("hazard_rerun", {"tests": 2, "not_proven": [{"cause": "c"}]})),
])
def test_each_fail_closed_field(field, edit):
    """protects=a parallel run with a missing or malformed field gets no proof and names the field; fails_when=a
    proof is written from a guess, or the wrong field is named; no_claim=the summary and exit (wrapper tests below)."""
    m = meta()
    edit(m)
    assert proof(m) == (None, field)


@pytest.mark.parametrize("field,edit", [
    # review 2026-11-25: hazards recorded but no one-lane re-run (DETJS_HAZARD_RERUN=1 already in the job environment
    # makes detjs skip it): the conflicts were never resolved, so nothing is proven
    ("hazard_rerun", lambda m: m["parallel"].__setitem__("hazards", [{"kind": "path", "a": "a.test.js", "b": "b.test.js"}])),
    ("parallel.hazards", lambda m: m["parallel"].__setitem__("hazards", "x")),
    ("parallel", lambda m: m.__setitem__("parallel", "x")),
    ("workers", lambda m: m["parallel"].__setitem__("workers", 0)),
    ("workers", lambda m: m["parallel"].__setitem__("workers", -2)),
    ("hazard_rerun.not_proven", lambda m: m.__setitem__("hazard_rerun", {"tests": 2, "not_proven": "x"})),
    ("hazard_rerun.not_proven", lambda m: m.__setitem__("hazard_rerun", {"tests": 2, "not_proven": 0})),
    ("hazard_rerun.not_proven[].cause", lambda m: m.__setitem__("hazard_rerun", {"tests": 2, "not_proven": [{"tests": 1}]})),
    ("hazard_rerun.not_proven[].cause", lambda m: m.__setitem__("hazard_rerun", {"tests": 2, "not_proven": [{"tests": 1, "cause": ""}]})),
])
def test_review_fail_closed_shapes(field, edit):
    """protects=hazards without a re-run, a non-object meta.parallel, workers below 1, a non-list not_proven and a
    missing or empty cause all fail closed and name the field; fails_when=any of them gives a proof or "no proof due"
    (a green check); no_claim=why the engine wrote that shape."""
    m = meta()
    edit(m)
    assert proof(m) == (None, field)


def test_hazards_with_a_rerun_of_zero_tests_fail_closed():
    """protects=hazards recorded but a re-run that accounted for 0 tests (a hazard file the engine could not match to
    any test) is not proven; fails_when=it gives a proof with rerun_one_lane 0 and a green check; no_claim=why the
    engine could not match the file (review 2026-11-25, pass 2)."""
    m = meta(hazard_rerun={"files": ["x|y.test.js"], "tests": 0, "not_proven": [], "complete": True})
    m["parallel"]["hazards"] = [{"kind": "path", "a": "x|y.test.js", "b": "b.test.js"}]
    assert proof(m) == (None, "hazard_rerun.tests")


@pytest.mark.parametrize("first", ['[1, 2]', '{"type": "header", "meta": null}', '{"type": "header", "meta": [1]}', '"x"'])
def test_a_malformed_trace_header_reads_as_no_header(tmp_path, first):
    """protects=a first trace line that is not an object, or whose meta is not one, reads as no header (the wrapper
    then fails closed: no status, exit 1) instead of crashing without a summary; fails_when=AttributeError or a
    non-dict meta; no_claim=the rest of the trace."""
    t = tmp_path / "t.jsonl"
    t.write_text(first + "\n")
    assert W.trace_header(t) == {}


def test_hazards_with_a_rerun_still_give_a_proof():
    """protects=the normal hazard path (hazards and a complete re-run) keeps its proof; fails_when=the new hazard
    check fails it closed too; no_claim=the re-run's correctness."""
    m = meta(hazard_rerun={"files": ["a.test.js", "b.test.js"], "tests": 4, "not_proven": [], "complete": True})
    m["parallel"]["hazards"] = [{"kind": "path", "a": "a.test.js", "b": "b.test.js"}]
    p, why = proof(m)
    assert why is None and p["rerun_one_lane"] == 4


def test_proven_below_zero_fails_closed():
    """protects=engine counts below the reused tests never give a negative proven; fails_when=a proof with proven
    < 0 is written; no_claim=why the counts disagree."""
    m = meta(status={"passed": 1, "failed": 0, "not_proven": 0, "skipped": 0})
    out = {**OUT4, "r::1": "passed", "r::2": "passed"}
    assert proof(m, outcomes=out, reused={"r::1": "passed", "r::2": "passed"}) == (None, "proven")


# ---------------------------------------------------------------- the footer read


class Counting(io.RawIOBase):
    """A file object that counts the bytes it hands out."""

    def __init__(self, data: bytes):
        self.f = io.BytesIO(data)
        self.read_bytes = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, *a):
        return self.f.seek(*a)

    def tell(self):
        return self.f.tell()

    def read(self, n=-1):
        b = self.f.read(n)
        self.read_bytes += len(b)
        return b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_footer_read_touches_at_most_64_kib_of_a_2_mib_trace(monkeypatch, tmp_path):
    """protects=the footer is read from the end, at most 65,536 bytes; fails_when=the whole trace is read, or the
    footer is missed; no_claim=the digest's value."""
    line = json.dumps({"type": "test", "nodeid": "x", "pad": "p" * 200}).encode() + b"\n"
    body = b'{"type": "header"}\n' + line * ((2 * 1024 * 1024) // len(line) + 1)
    data = body + json.dumps({"type": "footer", "n_tests": 1, "order_digest": "d1"}).encode() + b"\n"
    assert len(data) > 2 * 1024 * 1024
    seen = []

    def fake_open(path, mode="r", *a, **k):
        assert mode == "rb"
        c = Counting(data)
        seen.append(c)
        return c

    monkeypatch.setattr(W, "open", fake_open, raising=False)
    foot = W.read_footer(tmp_path / "trace.jsonl")
    assert foot == {"type": "footer", "n_tests": 1, "order_digest": "d1"}
    assert seen and seen[0].read_bytes <= 65536


def test_footer_read_rejects_a_non_footer_last_line_and_a_too_long_footer(tmp_path):
    """protects=only a real footer gives the digest; fails_when=a test line, a broken line or a fragment of a footer
    longer than 64 KiB is taken as the footer; no_claim=trace validity."""
    t = tmp_path / "t.jsonl"
    t.write_text('{"type": "header"}\n{"type": "test", "order_digest": "x"}\n')
    assert W.read_footer(t) is None
    t.write_text('{"type": "header"}\n{"type": "footer", "order_digest": "ok"}\n\n\n')
    assert W.read_footer(t) == {"type": "footer", "order_digest": "ok"}
    t.write_text('{"type": "header"}\n{"type": "footer", "order_dig')
    assert W.read_footer(t) is None
    big = {"type": "footer", "order_digest": "big", "late": ["y" * 70000]}
    t.write_text('{"type": "header"}\n' + json.dumps(big) + "\n")
    assert W.read_footer(t) is None
    t.write_bytes(b'{"type": "header"}\n\xff\xfe\n')
    assert W.read_footer(t) is None


# ---------------------------------------------------------------- the whole wrapper on a stand-in detjs

STUB = r"""#!/usr/bin/env python3
# A stand-in detjs (tests/test_runner_proof.py): writes $STUB_META as the trace header's meta, $STUB_OUTCOMES as the
# outcomes, $STUB_RECEIPTS as receipt lines and $STUB_FOOTER as the trace's last line; exits $STUB_EXIT.
import json, os, sys
a = sys.argv[1:]
if a[:1] == ["--version"]:
    print("fenvix 0.0.0-stub"); sys.exit(0)
opt = {x.split("=", 1)[0]: x.split("=", 1)[1] for x in a if x.startswith("--det-") and "=" in x}
outcomes = json.loads(os.environ["STUB_OUTCOMES"])
json.dump({"order": sorted(outcomes), "outcomes": outcomes}, open(opt["--det-outcomes"], "w"))
if "--det-cache-receipts" in opt:
    with open(opt["--det-cache-receipts"], "w") as fh:
        for r in json.loads(os.environ.get("STUB_RECEIPTS", "[]")):
            fh.write(json.dumps(r) + "\n")
with open(opt["--det-trace"], "w") as fh:
    fh.write(json.dumps({"type": "header", "meta": json.loads(os.environ["STUB_META"])}) + "\n")
    for n, o in outcomes.items():
        fh.write(json.dumps({"type": "test", "nodeid": n, "outcome": o}) + "\n")
    if os.environ.get("STUB_FOOTER"):
        fh.write(os.environ["STUB_FOOTER"] + "\n")
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""


@pytest.fixture
def stubjob(tmp_path):
    p = tmp_path / "detjs-stub"
    p.write_text(STUB)
    p.chmod(0o755)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "package.json").write_text(json.dumps({"devDependencies": {"vitest": "5.1.0"}}))

    def run(m: dict, outcomes: dict | None = None, receipts: list | None = None, footer: dict | None = None,
            name: str = "j", job_env: dict | None = None, exit_code: int = 0) -> tuple[int, dict, str]:
        out = tmp_path / name
        env = {k: v for k, v in os.environ.items() if not k.startswith("DETJS_")}
        env.update({"FENVIX_CACHE_ROOT": str(tmp_path / "cache"), "STUB_META": json.dumps(m),
                    "STUB_OUTCOMES": json.dumps(outcomes if outcomes is not None else OUT4),
                    "STUB_RECEIPTS": json.dumps(receipts or []), "STUB_FOOTER": json.dumps(footer) if footer else "",
                    "STUB_EXIT": str(exit_code), **(job_env or {})})
        env.pop("GITHUB_STEP_SUMMARY", None)
        r = subprocess.run([sys.executable, str(WRAPPER), "node", "--project", str(proj), "--detjs", str(p),
                            "--out", str(out), "--no-rerun"], capture_output=True, text=True, env=env)
        s = json.loads((out / "summary.json").read_text())
        return r.returncode, s, r.stdout + r.stderr
    return run


def test_wrapper_writes_the_proof_and_both_signals_on_a_clean_parallel_run(stubjob):
    """protects=a clean parallel run: proof written, signals null/0, exit 0; fails_when=no proof, a signal fires on
    nothing, or summary exit differs; no_claim=the App's reading (App unit tests)."""
    code, s, log = stubjob(meta(), footer={"type": "footer", "n_tests": 4, "order_digest": "od"})
    assert code == 0 and s["exit"] == 0, log
    assert s["proof"] == {"workers": 2, "proven": 4, "not_proven": 0, "rerun_one_lane": 0, "parallel_seconds": 0.9,
                          "serial_seconds_estimate": 1.5, "order_digest": "od", "not_proven_causes": []}
    assert s["provable_absent"] is None and s["not_proven_outside"] == 0 and s["not_proven"] == 0


def test_wrapper_serial_run_writes_no_proof_but_the_signals(stubjob):
    """protects=a serial summary has no proof key and still carries both signals; fails_when=a proof appears or the
    signal fields are missing; no_claim=Python summaries (they send neither)."""
    m = meta()
    m["parallel"] = {"workers": 1}
    code, s, log = stubjob(m)
    assert code == 0 and "proof" not in s, log
    assert "provable_absent" in s and s["not_proven_outside"] == 0


@pytest.mark.parametrize("field,edit", [
    ("workers", lambda m: m["parallel"].pop("workers")),
    ("status.not_proven", lambda m: m["status"].pop("not_proven")),
    ("status.passed", lambda m: m["status"].pop("passed")),
    ("status.failed", lambda m: m["status"].pop("failed")),
    ("timing.lanes_wall_seconds", lambda m: m["parallel"]["timing"].pop("lanes_wall_seconds")),
    ("hazard_rerun.tests", lambda m: m.__setitem__("hazard_rerun", {"files": ["a.test.js"], "not_proven": []})),
    ("hazard_rerun.not_proven[].tests", lambda m: m.__setitem__("hazard_rerun", {"tests": 2, "not_proven": [{"cause": "c", "tests": None}]})),
    # review 2026-11-25: hazards recorded, the one-lane re-run skipped; a meta.parallel that is not an object
    ("hazard_rerun", lambda m: m["parallel"].__setitem__("hazards", [{"kind": "path", "a": "a.test.js", "b": "b.test.js"}])),
    ("parallel", lambda m: m.__setitem__("parallel", "x")),
])
def test_wrapper_fails_closed_on_each_missing_field(stubjob, field, edit):
    """protects=an incomplete proof is never green: no proof, not_proven >= 1, exit 1, summary exit 1, the field in
    the log; fails_when=exit 0, a proof, or not_proven 0; no_claim=which engine bug left the field out."""
    m = meta()
    edit(m)
    code, s, log = stubjob(m)
    assert code == 1 and s["exit"] == 1, log
    assert "proof" not in s and s["not_proven"] >= 1
    assert f"proof incomplete: {field}" in log


def test_wrapper_not_proven_none_with_an_incomplete_proof(stubjob):
    """protects=a header without status (not_proven None) and an incomplete proof gives not_proven 1, no exception;
    fails_when=a crash (TypeError on None) or not_proven None; no_claim=the status line."""
    m = meta()
    del m["status"]
    code, s, log = stubjob(m)
    assert code == 1 and s["exit"] == 1 and s["not_proven"] == 1, log
    assert "Traceback" not in log


def test_wrapper_proven_below_zero_fails_closed(stubjob):
    """protects=a negative proven (engine counts below the reused tests) is NOT PROVEN, exit 1; fails_when=a proof
    with proven < 0 or exit 0; no_claim=why."""
    out = {**OUT4, "r.test.js::1": "passed"}
    receipts = [{"nodeid": "r.test.js::1", "reused": True, "kind": "test", "outcome": "passed"},
                {"nodeid": "a.test.js::1", "reused": True, "kind": "test", "outcome": "passed"},
                {"nodeid": "a.test.js::2", "reused": True, "kind": "test", "outcome": "passed"}]
    m = meta(status={"passed": 2, "failed": 0, "not_proven": 0, "skipped": 0})
    code, s, log = stubjob(m, outcomes=out, receipts=receipts)
    assert code == 1 and s["exit"] == 1 and "proof" not in s and s["not_proven"] >= 1, log
    assert "proof incomplete: proven" in log


def test_wrapper_warm_run_proven_excludes_reused_tests(stubjob):
    """protects=on a warm run, proven counts only the tests that ran in lanes (proven + not_proven = ranExecuted);
    fails_when=reused tests are counted as proven; no_claim=the reuse receipts' validity."""
    out = {**OUT4, "c.test.js::1": "passed", "c.test.js::2": "skipped"}
    receipts = [{"nodeid": "c.test.js::1", "reused": True, "kind": "test", "outcome": "passed"},
                {"nodeid": "c.test.js::2", "reused": True, "kind": "test", "outcome": "skipped"}]
    m = meta(status={"passed": 5, "failed": 0, "not_proven": 0, "skipped": 1})
    code, s, log = stubjob(m, outcomes=out, receipts=receipts)
    assert code == 0, log
    assert s["reused_with_proof"] == 2 and s["proof"]["proven"] == 4
    assert s["proof"]["proven"] + s["proof"]["not_proven"] == W.ran_executed_of(s["outcomes"], s["reused_outcomes"])


def test_wrapper_header_without_a_sensor_is_not_proven(stubjob):
    """protects=a header that declares no sensor and gives no reason makes the job NOT PROVEN through the whole
    wrapper (exit 1, summary exit 1, provable_absent named); fails_when=it reads as watched and the job is green;
    no_claim=why the engine declared none."""
    m = meta()
    del m["provable"]
    code, s, log = stubjob(m)
    assert code == 1 and s["exit"] == 1 and s["not_proven"] == 1, log
    assert s["provable_absent"] == "the run declared no sensor" and "could not watch" in log


@pytest.mark.parametrize("extra,why", [
    ({"provable_absent": "no sensor declared"}, "could not watch"),
    ({"not_proven_outside_tests": ["env:HOME", "env:USER"]}, "2 uncontrolled read(s)"),
])
def test_wrapper_signal_fires_exit_1_and_summary_agrees(stubjob, extra, why):
    """protects=either engine signal makes not_proven >= 1 and exit 1, and summary["exit"] equals the return value;
    fails_when=exit 0, not_proven 0, or the summary says 0 while the job exits 1; no_claim=the App's reason."""
    code, s, log = stubjob(meta(**extra), footer={"type": "footer", "order_digest": "od"})
    assert code == 1 and s["exit"] == 1, log
    assert s["not_proven"] == 1
    assert why in log
    assert s["provable_absent"] == extra.get("provable_absent")
    assert s["not_proven_outside"] == len(extra.get("not_proven_outside_tests", []))
    assert s["proof"]["not_proven"] == 0  # the proof itself stays the engine's; the run is NOT PROVEN by the signal


def test_engine_signals_fire_without_a_declared_sensor():
    """protects=a header with neither `provable` nor `provable_absent` (node/src/session.js provableField returns {}
    when no process declared a sensor) and an empty provable_absent both fire; fails_when=either reads as "watched";
    no_claim=why the sensor was missing."""
    assert W.engine_signals({"status": {}})[0] == "the run declared no sensor"
    assert W.engine_signals({"provable": "x"})[0] == "the run declared no sensor"
    assert W.engine_signals({"provable_absent": ""})[0] == "the run gave no reason"
    assert W.engine_signals({"provable": dict(SENSOR), "controls": CONTROLS}) == (None, 0)


def test_engine_signals_shapes():
    """protects=the signal fields' shapes (string or null; a whole number); fails_when=a non-string provable_absent
    is dropped (would read as no signal); no_claim=the engine's wording."""
    assert W.engine_signals({"provable": dict(SENSOR), "controls": CONTROLS}) == (None, 0)
    assert W.engine_signals({"provable_absent": "x", "not_proven_outside_tests": ["env:A"]}) == ("x", 1)
    assert W.engine_signals({"provable_absent": True})[0] == "true"


# ---------------------------------------------------------------- review 2026-11-25, pass 3


@pytest.mark.parametrize("field,edit", [
    ("parallel.placement", lambda m: m["parallel"].pop("placement")),
    ("parallel.placement", lambda m: m["parallel"].__setitem__("placement", "x")),
    ("parallel.placement.deviations", lambda m: m["parallel"]["placement"].pop("deviations")),
    ("parallel.placement.deviations", lambda m: m["parallel"]["placement"].__setitem__("deviations", "x")),
    ("parallel.placement.deviations", lambda m: m["parallel"]["placement"].__setitem__(
        "deviations", [{"file": "b.test.js", "what": "no marker (the file did not run or its process died)"}])),
    ("parallel.carried", lambda m: m["parallel"].__setitem__("carried", "x")),
    ("parallel.carried", lambda m: m["parallel"].__setitem__("carried", [{"file": "b.test.js", "state": [{"key": "k"}]}])),
])
def test_placement_and_carried_state_fail_closed(field, edit):
    """protects=a file the engine could not place as planned (no marker: no footprint, so no hazard could involve it;
    another worker or predecessors than the plan's) or that ran with state an earlier file of its process changed is
    not reported proven; fails_when=a proof with every test proven; no_claim=how often runners deviate from the plan
    (a deviation makes the run NOT PROVEN, never a wrong green)."""
    m = meta()
    edit(m)
    assert proof(m) == (None, field)


def test_an_empty_carried_list_keeps_the_proof():
    """protects=carried [] (nothing carried) is not a failure; fails_when=it fails closed; no_claim=other fields."""
    m = meta()
    m["parallel"]["carried"] = []
    assert proof(m)[1] is None and proof(m)[0]["proven"] == 4


@pytest.mark.parametrize("name,value", [
    ("DETJS_FOOTPRINT_SKIP_DIRS", "/"),
    ("DETJS_CACHE_SKIP_DIRS", "/"),
    ("DETJS_HAZARD_RERUN", "1"),
    ("DETJS_HAZARD_PASS", "1"),
    ("DETJS_EPOCH_RUN", "1"),
    ("DETJS_ISOLATE_CHILD", "1"),
    ("DETJS_DIR", "/tmp/x"),
    ("DETJS_DISABLE", "clock"),
    ("DETJS_HAZARD_RECURSIVE", "0"),
    ("DETJS_HAZARD_SHARED_SERVICE", "0"),
])
def test_wrapper_job_env_that_steers_the_engine_fails_closed(stubjob, name, value):
    """protects=a job environment that hides paths from the footprint recorder, turns the engine into one of its own
    child passes or turns controls off gives no proof, not_proven >= 1 and exit 1; fails_when=a proof is written (the
    trace alone cannot show the variable); no_claim=the variables the engine reads for other purposes."""
    code, s, log = stubjob(meta(), job_env={name: value})
    assert code == 1 and s["exit"] == 1, log
    assert "proof" not in s and s["not_proven"] >= 1
    assert f"proof incomplete: environment {name}" in log


def test_wrapper_exit_2_writes_no_proof(stubjob):
    """protects=when the engine could not establish the run's outcome (exit 2) the summary has no proof; fails_when=a
    full proof object sits next to exit 2; no_claim=the counts the engine wrote."""
    code, s, log = stubjob(meta(), exit_code=2)
    assert code == 2 and s["exit"] == 2, log
    assert "proof" not in s


# ---------------------------------------------------------------- C4 (spec "false greens on release-1")


@pytest.mark.parametrize("edit,why", [
    (lambda m: m["controls"].remove("timers"), "control `timers` off"),
    (lambda m: m.__setitem__("controls", []), "control `time` off"),
    (lambda m: m.pop("controls"), "control `time` off"),
    (lambda m: m["provable"].__setitem__("sensor", "totally-made-up/9"), "not one the engine has a rule for"),
    (lambda m: m["provable"].__setitem__("sensor", "py"), "not one the engine has a rule for"),
    (lambda m: m["provable"].__setitem__("contract", 2), "contract 2"),
    (lambda m: m["provable"].pop("contract"), "contract None"),
    (lambda m: m["provable"].__setitem__("runtime", "node99"), "not audited against 'node99'"),
])
def test_engine_signals_refuse_what_the_core_judge_refuses(edit, why):
    """protects=a header whose sensor declaration the core's judge refuses (a required control off, an unknown sensor,
    another contract, an unaudited runtime) reads as not watched; fails_when=any object in meta.provable reads as
    watched (runner-proof 6809aa13: a required control switched off and the job green); no_claim=the accounting
    table's digest (checked by the verifier, not here)."""
    m = meta()
    edit(m)
    pa, _ = W.engine_signals(m)
    assert pa is not None and why in pa, pa


def test_wrapper_required_control_off_is_not_proven(stubjob):
    """protects=through the whole wrapper, a parallel run whose header declares node-surface/1 with `timers` off is
    NOT PROVEN (exit 1); fails_when=the declared sensor alone makes it green; no_claim=why the control was off."""
    m = meta()
    m["controls"].remove("timers")
    code, s, log = stubjob(m)
    assert code == 1 and s["exit"] == 1 and s["not_proven"] >= 1, log
    assert "timers" in (s["provable_absent"] or ""), s


def _judge_cases():
    """provable::judge's own sensor/controls cases (crates/detpy-core/src/provable.rs tests), for a Node header."""
    base = list(W._NODE_CONTROLS)
    cases = [("clean", {}, None)]
    for drop in W._NODE_CONTROLS:
        cases.append((f"drop-{drop}", {"controls": [c for c in base if c != drop]}, None))
    cases.append(("no-controls", {"controls": []}, None))
    for sensor in ["cache-reuse/2", "totally-made-up/9", "x", "py", "node", "deno-whatever/1", "cache-reuse/1"]:
        cases.append((f"sensor-{sensor}", {"sensor": sensor}, None))
    cases += [("contract-2", {"contract": 2}, None), ("runtime-99", {"runtime": "node99"}, None),
              ("runtime-none", {"runtime": None}, None)]
    return cases


@pytest.fixture(scope="module")
def real_record(tmp_path_factory):
    """One test record of a real `detjs node-test --det` run (its fingerprint matches its events), and node's path."""
    import shutil
    node = shutil.which("node")
    if not node or not (ROOT / "node" / "detjs.linux-x64.node").exists():
        pytest.skip("needs node and the napi addon (node/detjs.linux-x64.node)")
    d = tmp_path_factory.mktemp("judge-parity")
    (d / "package.json").write_text('{"name": "judge-parity", "private": true}')
    (d / "t.test.js").write_text("const test = require('node:test');\ntest('a', () => {});\n")
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS", "DETJS", "NODE_TEST_CONTEXT", "NODE_OPTIONS")}
    subprocess.run([node, str(ROOT / "node" / "bin" / "detjs.js"), "node-test", "--det", "--det-workers=1", "t.test.js"],
                   cwd=d, env=env, capture_output=True, text=True, timeout=300)
    lines = (d / ".detjs" / "trace.jsonl").read_text().splitlines()
    return node, json.loads(lines[0]), next(json.loads(ln) for ln in lines[1:] if json.loads(ln).get("type") == "test")


@pytest.mark.parametrize("name,edit,_", _judge_cases(), ids=[c[0] for c in _judge_cases()])
def test_sensor_refusal_parity_with_the_core_judge(tmp_path, real_record, name, edit, _):
    """protects=the runner's port of judge's clauses 1-3 (sensor_refusal) gives the core's verdict on each of judge's
    own sensor/controls cases: the core's verdict is read from `detjs verify` on two copies of one clean trace whose
    header carries the case; fails_when=the port drifts from the core (a sensor, contract, runtime or required control
    added or changed in provable.rs and not here); no_claim=judge's other clauses (unaccounted calls, marks)."""
    node, real_header, rec = real_record
    bin_ = ROOT / "node" / "bin" / "detjs.js"
    # the real header, with the run-level signals outside tests emptied (the runner of node:test reads some), so the
    # sensor clauses are the only ground for NOT PROVEN
    meta_ = json.loads(json.dumps(real_header["meta"]))
    for k in ("not_proven_outside_tests", "env_read_outside_tests", "files_read_outside_tests"):
        meta_[k] = []
    prov = meta_["provable"]
    meta_["controls"] = ["fs", "isolation", "net", "order", "seeds", "time", "timers"]
    for k, v in edit.items():
        if k == "controls":
            meta_["controls"] = list(v)
        else:
            prov[k] = v
    header = {**real_header, "meta": meta_}
    trace = tmp_path / "t.jsonl"
    trace.write_text(json.dumps(header) + "\n" + json.dumps(rec) + "\n")
    r = subprocess.run([node, str(bin_), "verify", str(trace), str(trace), "--json"], capture_output=True, text=True)
    rep = json.loads(r.stdout)
    core_watched = rep["summary"]["identical"] == 1
    runner_watched = W.sensor_refusal(meta_) is None
    assert runner_watched == core_watched, (name, W.sensor_refusal(meta_), rep["summary"], rep["tests"][0])


# ---------------------------------------------------------------- C5 (spec "false greens on release-1")


@pytest.mark.parametrize("status", [
    {"passed": 4, "failed": "x", "not_proven": 0, "skipped": 0},
    {"passed": 4, "failed": 0, "not_proven": "1", "skipped": 0},
    {"passed": 4, "failed": 1.5, "not_proven": 0, "skipped": 0},
], ids=["failed-x", "not_proven-str", "failed-float"])
def test_wrapper_non_numeric_status_writes_the_summary_and_exits_2(stubjob, status):
    """protects=a trace header whose status counts are not whole numbers gives a summary.json with a clear
    status_error and exit 2 (the run's outcome is unknown), never a traceback; fails_when=int() raises (no summary,
    a Python traceback) or the job reads green; no_claim=how the engine came to write such a header (it does not)."""
    code, s, log = stubjob(meta(status=status))
    assert code == 2 and s["exit"] == 2, log
    assert "Traceback" not in log, log
    assert s["status_error"] and "not whole numbers" in s["status_error"], s
    assert "proof" not in s
