"""P0 big trace: `fenvix verify` / `detpy verify` write the report as it is serialized (detpy._core.verify_write).

protects=the bytes `fenvix verify` prints (JSON and text) and its exit code are those of the previous path
(`verify_with`, whole strings), over every case of the golden corpus (crates/detpy-core/tests/golden/), and the
chunked writer never cuts a UTF-8 character; fails_when=streaming changes, drops or re-encodes any byte of the report,
or the exit code no longer follows the summary; no_claim=memory (measured on the agentic-qe pair, 1.34 GB vs 7.06 GB:
harness/p0_big_trace/REPORT.md).
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from detpy import _core
from detpy.fenvix import cmd_verify, verify_exit_code

GOLDEN = Path(__file__).resolve().parent.parent / "crates" / "detpy-core" / "tests" / "golden"
CASES = sorted(p.name[: -len(".report.json")] for p in GOLDEN.glob("*.report.json"))


def runs(case: str) -> list[str]:
    out, i = [], 0
    while (GOLDEN / f"{case}.run{i}.jsonl").exists():
        out.append(str(GOLDEN / f"{case}.run{i}.jsonl"))
        i += 1
    return out


@pytest.mark.parametrize("case", CASES)
def test_verify_write_writes_what_verify_with_returned(case):
    paths = runs(case)
    report_json, text = _core.verify_with(paths, [], True)
    for as_json, want in ((True, report_json + "\n"), (False, text.replace("detpy verify", "fenvix verify", 1))):
        buf = io.StringIO()
        summary = _core.verify_write(paths, [], True, as_json, buf, "fenvix verify")
        assert buf.getvalue() == want, case
        assert json.loads(summary) == json.loads(report_json)["summary"]


def test_cmd_verify_prints_the_same_bytes_and_exit_code(capsys):
    paths = runs("all_diverge")
    report_json, _ = _core.verify_with(paths, [], False)
    code = cmd_verify([*paths, "--json"])
    assert capsys.readouterr().out == report_json + "\n"
    assert code == verify_exit_code(json.loads(report_json)["summary"]) == 1


def test_chunks_never_cut_a_multibyte_character(tmp_path):
    # two runs whose test ids are long and non-ASCII: the report is several MiB, so chunk borders fall inside them
    head = {"type": "header", "format": "detpy-trace", "version": 1, "encoding": 2, "meta": {}, "order": []}
    lines = [json.dumps(head)]
    for i in range(3000):
        nodeid = f"t.py::{'€ü' * 400}{i}"
        lines.append(json.dumps({"type": "test", "nodeid": nodeid, "index": i, "outcome": "passed", "fingerprint": f"{i:032x}",
                                 "n_events": 0, "truncated": True, "counts": {}, "checkpoints": [], "events": []}))
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text("\n".join(lines) + "\n", encoding="utf-8")
    b.write_text("\n".join(lines[:1] + lines[1:][::-1]) + "\n", encoding="utf-8")
    report_json, _ = _core.verify_with([str(a), str(b)], [], False)
    assert len(report_json.encode()) > 3 << 20
    buf = io.StringIO()
    _core.verify_write([str(a), str(b)], [], False, True, buf, "fenvix verify")
    assert buf.getvalue() == report_json + "\n"


class _Chunks:
    """A file object that records the size of every write."""

    def __init__(self):
        self.sizes, self.parts = [], []

    def write(self, text):
        self.sizes.append(len(text.encode()))
        self.parts.append(text)


@pytest.mark.parametrize("as_json", [True, False])
def test_large_reports_reach_python_in_bounded_chunks(tmp_path, as_json):
    """protects=both output modes hand Python the report in pieces of about 1 MiB (the 1.2 GB agentic-qe report was
    held 4-5 times in text mode, review of 73c0ae5); fails_when=the text rendering (or the JSON) is written in one
    piece; no_claim=the peak memory of render_text itself (the rendered text is still built whole)."""
    head = {"type": "header", "format": "detpy-trace", "version": 1, "encoding": 2, "meta": {}, "order": []}
    lines = [json.dumps(head)]
    for i in range(3000):
        lines.append(json.dumps({"type": "test", "nodeid": f"t.py::{'x' * 800}{i}", "index": i, "outcome": "passed",
                                 "fingerprint": f"{i:032x}", "n_events": 0, "truncated": True, "counts": {},
                                 "checkpoints": [], "events": []}))
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text("\n".join(lines) + "\n")
    b.write_text("\n".join(lines[:1] + lines[1:][::-1]) + "\n")
    report_json, text = _core.verify_with([str(a), str(b)], [], False)
    want = report_json + "\n" if as_json else text.replace("detpy verify", "fenvix verify", 1)
    assert len(want.encode()) > 4 << 20
    out = _Chunks()
    _core.verify_write([str(a), str(b)], [], False, as_json, out, "fenvix verify")
    assert "".join(out.parts) == want
    assert max(out.sizes) <= (1 << 20) + (64 << 10), out.sizes[:5]
