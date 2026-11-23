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
