"""Review R-019b: the 63 step-4 rows carried over from round 1 into REPORT-2's headline were measured before the
stale-bytecode fix. ``stale-d.jsonl`` (from ``stale_d.py``, which reconstructs each row's commit probes from its
verdict sequence and diffs the probed commits) lists, per row, the consecutive probe pairs where a .py file
changes between the two probed commits with the same size and the first run took under 1 s (so the second
checkout can land in the same second: the condition for running stale bytecode). No engine is needed."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def test_carried_over_step4_rows_are_free_of_the_stale_bytecode_condition():
    rows = [json.loads(line) for line in open(HERE / "stale-d.jsonl")]
    assert len(rows) == 63 and all(r["reconstructed"] for r in rows)
    exposed = [r for r in rows if r["same_size_pairs_prev_under_1s"]]
    pairs = sum(r["same_size_pairs_prev_under_1s"] for r in rows)
    assert not exposed, (
        f"{len(exposed)} of 63 carried-over step-4 rows have {pairs} probe pairs that meet the stale-bytecode "
        f"condition (same-size .py change, previous run < 1 s); they count as MEASURED in REPORT-2's 500/533")
