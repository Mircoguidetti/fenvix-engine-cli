"""Spec C1 (idea 3, "is this red real?"), engine part for pytest: the --det-outcomes file names the engine run of
the cache session (``cache.run``), the id the receipts of that run carry as ``run``, so the runner can send it as the
job's ``engineRunId`` and a reused test's receipt can name the run that recorded it."""
import json
import re
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 12), reason="--det-cache needs sys.monitoring")


def _run(pytester, n, cache):
    out = pytester.path / f"o{n}.json"
    pytester.runpytest_subprocess("--det", f"--det-cache={cache}", f"--det-outcomes={out}", "-p", "no:cacheprovider")
    return json.loads(out.read_text())


def test_outcomes_file_names_the_cache_run_and_receipts_carry_it(pytester):
    # protects: engineRunId and the receipt's reusedEngineRunId of spec C1 (1.2, 2.1, 2.3)
    # fails_when: the outcomes file has no cache.run, or it is not the id the run's receipts carry
    # no_claim: the id's format beyond "<UTC time>-<pid>"; runs without --det-cache (no cache dict at all)
    pytester.makepyfile(test_a="def test_one():\n    assert 1\n\ndef test_two():\n    assert 2\n")
    cache = pytester.path / ".c"
    o1 = _run(pytester, 1, cache)
    run1 = o1["cache"]["run"]
    assert re.fullmatch(r"\d{8}T\d{6}-\d+", run1), run1
    for k in ("epoch_ns", "miss_reasons"):
        assert k in o1["cache"], sorted(o1["cache"])  # the existing keys stay
    o2 = _run(pytester, 2, cache)
    run2 = o2["cache"]["run"]
    assert re.fullmatch(r"\d{8}T\d{6}-\d+", run2) and run2 != run1, (run1, run2)
    assert sorted(o2["cache"]["reused_ids"]) == ["test_a.py::test_one", "test_a.py::test_two"]
    rows = [json.loads(line) for line in (cache / "receipts.jsonl").read_text().splitlines() if line.strip()]
    reused = [r for r in rows if r.get("reused")]
    assert sorted(r["nodeid"] for r in reused) == ["test_a.py::test_one", "test_a.py::test_two"], rows
    # the receipt of a reused test names the run that recorded the entry: run 1, by the id its outcomes file gave
    assert {r["run"] for r in reused} == {run1}, (run1, run2, reused)
