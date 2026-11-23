"""AC2 of the spec "Engine P0: no false green": the verifyExit rows of the shared fixture
node/test/fixtures/exit-cases.json against Python's verify_exit_code, so `detjs verify` (node/src/exit-status.js)
and `fenvix verify` share one rule."""
import json
from pathlib import Path

from detpy.fenvix import verify_exit_code

FIXTURE = Path(__file__).resolve().parent.parent / "node/test/fixtures/exit-cases.json"


def test_every_verify_exit_row_matches_python():
    rows = [r for r in json.loads(FIXTURE.read_text()) if r["fn"] == "verifyExit"]
    assert len(rows) >= 7
    for row in rows:
        assert verify_exit_code(row["input"]) == row["expected"], row
