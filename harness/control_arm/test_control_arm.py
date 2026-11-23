"""Tests of the control arm's verdict rules (on recorded fixtures) and of the minimal-pair bisect (synthetic 8 files)."""
import copy
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import control_arm as CA  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "nestjs-pino-6.json")


def recorded():
    """the 9 recorded nestjs-pino runs (6 tests), in the form verdicts() takes"""
    j = json.load(open(FIX))["runs"]
    runs = []
    for rn, kind, _ in CA.run_names():
        d = j[rn]
        st = "timeout" if d["row"]["timed_out"] else "crash" if d["row"]["crashed"] else "ok"
        runs.append({"name": rn, "kind": kind, "status": st, "outcomes": dict(d["outcomes"]),
                     "valid": kind == "P" and st == "ok" and d["row"]["overlapping_file_pairs"] > 0})
    return runs


def by(runs, name):
    return next(r for r in runs if r["name"] == name)


T0 = "__tests__/assign.spec.ts::assign::ExpressAdapter::in request context"
T1 = "__tests__/assign.spec.ts::assign::ExpressAdapter::out of request context"


def test_recorded_all_identical():
    runs = recorded()
    assert all(r["valid"] for r in runs if r["kind"] == "P")
    v = CA.verdicts(runs, {})
    assert len(v) == 6 and {x["verdict"] for x in v.values()} == {"IDENTICAL"}


def test_diverges_parallel():
    runs = recorded()
    by(runs, "P3")["outcomes"][T0] = "failed"
    v = CA.verdicts(runs, {})
    assert v[T0]["verdict"] == "DIVERGES" and v[T0]["label"] == "parallel" and v[T0]["diverging_runs"] == ["P3"]
    assert v[T1]["verdict"] == "IDENTICAL"


def test_diverges_order():
    runs = recorded()
    by(runs, "P1")["outcomes"][T0] = "failed"
    by(runs, "SS2")["outcomes"][T0] = "failed"
    v = CA.verdicts(runs, {})
    assert (v[T0]["verdict"], v[T0]["label"]) == ("DIVERGES", "order")


def test_diverges_order_only():
    runs = recorded()
    by(runs, "SS1")["outcomes"][T0] = "failed"
    assert CA.verdicts(runs, {})[T0]["verdict"] == "DIVERGES-order-only"


def test_invalid_parallel_run_is_not_evidence():
    runs = recorded()
    by(runs, "P2")["valid"] = False
    by(runs, "P2")["outcomes"][T0] = "failed"  # a run that ran serially says nothing about parallelism
    v = CA.verdicts(runs, {})
    assert v[T0]["verdict"] == "IDENTICAL" and "P2" not in v[T0]["reason"]


def test_undecided_serial_disagreement():
    runs = recorded()
    by(runs, "S2")["outcomes"][T0] = "failed"
    by(runs, "P1")["outcomes"][T0] = "failed"
    v = CA.verdicts(runs, {})
    assert (v[T0]["verdict"], v[T0]["label"]) == ("UNDECIDED", "serial-disagree")


def test_undecided_timeout_names_the_run():
    runs = recorded()
    p = by(runs, "P4")
    p["status"], p["outcomes"] = "timeout", None
    v = CA.verdicts(runs, {})
    for x in v.values():  # every test affected, none IDENTICAL
        assert x["verdict"] == "UNDECIDED" and x["label"] == "run-failed-or-short" and "P4 timed out" in x["reason"]


def test_undecided_crash_of_shuffled_serial():
    runs = recorded()
    by(runs, "SS1")["status"] = "crash"
    v = CA.verdicts(runs, {})
    assert all(x["verdict"] == "UNDECIDED" and "SS1 crashed" in x["reason"] for x in v.values())


def test_undecided_short_run_only_affected_tests():
    runs = recorded()
    del by(runs, "P5")["outcomes"][T1]
    v = CA.verdicts(runs, {})
    assert v[T1]["verdict"] == "UNDECIDED" and "P5 missing the test" in v[T1]["reason"]
    assert v[T0]["verdict"] == "IDENTICAL"


def test_undecided_insufficient_parallel():
    runs = recorded()
    for n in ("P1", "P2", "P3"):
        by(runs, n)["valid"] = False
    v = CA.verdicts(runs, {})
    assert all((x["verdict"], x["label"]) == ("UNDECIDED", "insufficient-parallel") for x in v.values())


def test_exactly_three_valid_parallel_is_enough():
    runs = recorded()
    for n in ("P1", "P2"):
        by(runs, n)["valid"] = False
    assert {x["verdict"] for x in CA.verdicts(runs, {}).values()} == {"IDENTICAL"}


def test_env_checked_first():
    runs = recorded()
    by(runs, "P1")["outcomes"][T0] = "failed"
    msgs = {T0: "Error: connect ECONNREFUSED 127.0.0.1:5432", T1: "Error: connect ECONNREFUSED 10.0.0.7:5432"}
    by(runs, "P1")["outcomes"][T1] = "failed"
    v = CA.verdicts(runs, msgs)
    assert v[T0]["verdict"] == "ENV"
    assert v[T1]["verdict"] == "DIVERGES"  # a non-local address is not this container


def test_parallelism_check_marks_serial_run_invalid():
    rows = [{"kind": "S", "tests": 2, "timed_out": False, "crashed": False, "overlapping_file_pairs": 0, "_ids": {"a", "b"}},
            {"kind": "P", "tests": 2, "timed_out": False, "crashed": False, "overlapping_file_pairs": 0, "_ids": {"a", "b"}},
            {"kind": "P", "tests": 1, "timed_out": False, "crashed": False, "overlapping_file_pairs": 3, "_ids": {"a"}},
            {"kind": "P", "tests": 2, "timed_out": False, "crashed": False, "overlapping_file_pairs": 3, "_ids": {"a", "c"}}]
    CA.finish_rows(rows)
    assert rows[1]["valid"] == "INVALID" and "ran serially" in rows[1]["invalid_reason"]
    assert rows[2]["valid"] == "valid" and rows[2]["short"] and rows[2]["missing_vs_serial"] == 1
    # same count, a renamed id: not short (the renamed test is UNDECIDED in verdicts(), the run is not short)
    assert not rows[3]["short"] and rows[3]["missing_vs_serial"] == 1


def test_overlap_count():
    assert CA.overlapping_pairs({"a": [0, 10], "b": [10, 20], "c": [20, 30]}) == 0
    assert CA.overlapping_pairs({"a": [0, 10], "b": [5, 20], "c": [6, 7]}) == 3
    j = json.load(open(FIX))["runs"]
    assert CA.overlapping_pairs(j["S1"]["file_times"]) == 0


def test_candidates_start_before_victim_end():
    times = {"/v": [10, 20], "/a": [0, 5], "/b": [15, 30], "/c": [20, 25], "/d": [19, 40]}
    assert CA.candidates(times, "/v") == ["/a", "/b", "/d"]
    assert CA.candidates(times, "/x") is None


def test_flags_copied_from_repro():
    assert CA.run_flags("vitest", "P", 3) == ["--maxWorkers=4", "--fileParallelism", "--sequence.shuffle", "--sequence.seed=3"]
    assert CA.run_flags("vitest", "SS", 2) == ["--no-file-parallelism", "--sequence.shuffle", "--sequence.seed=2"]
    assert CA.run_flags("jest", "P", 5) == ["--maxWorkers=4", "--randomize", "--seed=5"]
    assert CA.run_flags("jest", "SS", 1) == ["--runInBand", "--randomize", "--seed=1"]
    assert "--cacheDirectory=/t/jest" in CA.report_flags("jest", "r.json", None, "/t")


# ---------------------------------------------------------------------------------------------------------------
# bisect, synthetic 8 files

FILES = [f"f{i}.test.ts" for i in range(1, 9)]
VICTIM = "victim.test.ts"


class Fake:
    """victim fails when `polluter` runs before it (serial) / beside it (concurrent), per `modes`."""

    def __init__(self, polluter="f6.test.ts", modes=("serial",), flaky_alone=False, needs=None):
        self.polluter, self.modes, self.flaky_alone, self.needs = polluter, modes, flaky_alone, needs
        self.calls = []

    def __call__(self, mode, polluters, victim):
        self.calls.append((mode, tuple(polluters)))
        if not polluters:
            return self.flaky_alone, {}
        if mode not in self.modes:
            return False, {}
        if self.needs:
            return all(n in polluters for n in self.needs), {}
        return self.polluter in polluters, {}


def test_bisect_finds_known_polluter_serial():
    f = Fake()
    res = CA.PairSearch(f).search(FILES, VICTIM)
    assert res["result"] == "pair found" and res["polluter"] == "f6.test.ts" and res["search"] == "serial"
    assert res["confirm"] == {"pair_fail": 3, "pair_runs": 3, "alone_fail": 0, "alone_runs": 3, "confirmed": True}
    # 3 bisect steps (8 -> 4 -> 2 -> 1); the confirm is 3 + 3 runs
    assert res["runs_spent"] <= 3 * 4 + 6
    assert all(m == "serial" for m, _ in f.calls)


def test_bisect_halves_keep_start_order():
    f = Fake(polluter="f1.test.ts")
    CA.PairSearch(f).search(FILES, VICTIM)
    assert f.calls[0] == ("serial", tuple(FILES[:4]))


def test_falls_back_to_concurrent_search():
    f = Fake(polluter="f3.test.ts", modes=("concurrent",))
    res = CA.PairSearch(f).search(FILES, VICTIM)
    assert res["result"] == "pair found" and res["search"] == "concurrent" and res["polluter"] == "f3.test.ts"
    assert res["attempts"][0]["stop"] == "no minimal pair (interaction)"


def test_interaction_no_minimal_pair():
    f = Fake(needs=["f1.test.ts", "f8.test.ts"], modes=("serial", "concurrent"))
    res = CA.PairSearch(f).search(FILES, VICTIM)
    assert res["result"] == "no minimal pair (interaction)" and res["polluter"] is None


def test_not_confirmed_when_victim_fails_alone():
    f = Fake(flaky_alone=True, modes=("serial", "concurrent"))
    res = CA.PairSearch(f).search(FILES, VICTIM)
    assert res["result"] == "no minimal pair (not confirmed)"
    assert res["attempts"][0]["confirm"]["alone_fail"] == 3


def test_budget():
    f = Fake(modes=("concurrent",))
    res = CA.PairSearch(f, budget_runs=8).search(FILES, VICTIM)
    assert res["result"] == "pair not found (budget)" and res["runs_spent"] <= 8
