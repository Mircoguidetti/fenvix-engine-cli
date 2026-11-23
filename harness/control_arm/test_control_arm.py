"""Tests of the control arm's verdict rules (on recorded fixtures) and of the minimal-pair bisect (synthetic 8 files)."""
import json
import os
import sys


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


def test_overlapping_files_for_concurrent_search():
    times = {"/v": [10, 20], "/a": [0, 5], "/b": [15, 30], "/c": [20, 25], "/d": [5, 12]}
    assert CA.overlapping(times, "/v") == ["/d", "/b"]
    assert CA.overlapping(times, "/x") is None


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

    def __init__(self, polluter="f6.test.ts", modes=("serial",), flaky_alone=False, needs=None, alone_seeds=None):
        self.polluter, self.modes, self.flaky_alone, self.needs = polluter, modes, flaky_alone, needs
        self.alone_seeds = alone_seeds  # with flaky_alone: the seeds under which the file alone reproduces (None: all)
        self.calls = []

    def __call__(self, mode, polluters, victim, seed=CA.DEFAULT):
        self.calls.append((mode, tuple(polluters)))
        if not polluters:
            if self.alone_seeds is not None:
                return self.flaky_alone and (seed in self.alone_seeds), {}
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
    # controls 2 + 1 runs, 3 bisect steps (8 -> 4 -> 2 -> 1), the confirm 3 + 3 runs
    assert res["runs_spent"] <= 3 + 3 * 4 + 6
    assert all(m == "serial" for m, _ in f.calls)


def test_controls_before_bisect():
    f = Fake(polluter="f1.test.ts")
    CA.PairSearch(f).search(FILES, VICTIM)
    # victim alone twice, then the full candidate set (triggers at once), then the first half in start order
    assert f.calls[:4] == [("serial", ()), ("serial", ()), ("serial", tuple(FILES)), ("serial", tuple(FILES[:4]))]


def test_falls_back_to_concurrent_search_on_overlapping_files():
    f = Fake(polluter="f3.test.ts", modes=("concurrent",))
    res = CA.PairSearch(f).search(FILES, VICTIM, conc_cands=FILES[1:4])
    assert res["result"] == "pair found" and res["search"] == "concurrent" and res["polluter"] == "f3.test.ts"
    assert res["attempts"][0]["stop"] == "not reproduced (full candidate set)"
    assert all(set(p) <= set(FILES[1:4]) for m, p in f.calls if m == "concurrent")


def test_not_reproduced_by_full_set():
    res = CA.PairSearch(Fake(modes=())).search(FILES, VICTIM)
    assert res["result"] == "no minimal pair (not reproduced)" and res["runs_spent"] == 2 + 2 + 2


def test_interaction_no_minimal_pair():
    f = Fake(needs=["f1.test.ts", "f8.test.ts"], modes=("serial", "concurrent"))  # full set triggers, no half does
    res = CA.PairSearch(f).search(FILES, VICTIM)
    assert res["result"] == "no minimal pair (interaction)" and res["polluter"] is None


def test_victim_file_alone_reproduces_with_controls():
    f = Fake(flaky_alone=True, alone_seeds=[CA.DEFAULT])  # only under the diverging run's seed
    res = CA.PairSearch(f).search(FILES, VICTIM, control_seeds=[4, 5])
    assert res["result"] == CA.R_ALONE
    a = res["alone"]
    assert (a["alone_hits"], a["unseeded"], [c["reproduced"] for c in a["control_seeds"]]) == (3, [False, False], [False, False])
    assert res["runs_spent"] == 1 + 2 + 2 + 2  # first hit, 2 more confirm runs, 2 unseeded, 2 control seeds


def test_alone_without_seed_too():
    res = CA.PairSearch(Fake(flaky_alone=True)).search(FILES, VICTIM, control_seeds=[4])
    assert res["result"] == CA.R_ALONE_UNSEEDED


def test_alone_under_control_seed_too():
    res = CA.PairSearch(Fake(flaky_alone=True, alone_seeds=[CA.DEFAULT, 4])).search(FILES, VICTIM, control_seeds=[4])
    assert res["result"] == CA.R_ALONE_CTL


def test_alone_once_in_three_is_not_claimed():
    class Once(Fake):
        def __call__(self, mode, polluters, victim, seed=CA.DEFAULT):
            super().__call__(mode, polluters, victim, seed)
            return (not polluters and len(self.calls) == 1), {}
    res = CA.PairSearch(Once()).search(FILES, VICTIM)
    assert res["result"] == CA.R_ALONE_ONCE and res["alone"]["alone_hits"] == 1


def test_failed_control_trial_is_no_evidence():
    def t(mode, polluters, victim, seed=CA.DEFAULT):
        return (None if seed == 4 else (not polluters and seed is CA.DEFAULT)), {}
    assert CA.PairSearch(t).search(FILES, VICTIM, control_seeds=[4])["result"] == CA.R_TRIAL_FAILED


def test_control_seeds_distinct_and_not_the_diverging_seed():
    runs = recorded()
    by(runs, "P3")["outcomes"][T0] = "failed"
    by(runs, "P1")["outcomes"][T0] = "failed"  # P1 shares seed 1 with SS1: seed 1 is no control
    v = CA.verdicts(runs, {})[T0]
    assert CA.control_seeds_for(runs, T0, v) == [2, 4]


def test_realtrial_jest_cmd_replays_seed_only_when_given():
    class R:
        runner, spec = "jest", {"args": ["--config", "jest.cfg.js"]}
    t = CA.RealTrial(R(), "passed", "v.test.ts::x", 60, seed=3)
    cmd = t._cmd(["/a", "/v"], "r.json", None, "/t", None)
    assert "--seed=3" in cmd and "--randomize" in cmd and cmd[-2:] == ["/a", "/v"] and "jest.cfg.js" in cmd
    assert "--randomize" not in t._cmd(["/v"], "r.json", None, "/t", None, seed=None)


def test_not_confirmed():
    class Half(Fake):
        def __call__(self, mode, polluters, victim, seed=CA.DEFAULT):  # the pair triggers on its 1st and 3rd run only
            hit, rec = super().__call__(mode, polluters, victim, seed)
            if polluters == ["f6.test.ts"]:
                hit = sum(1 for _, p in self.calls if p == ("f6.test.ts",)) % 2 == 1  # bisect run 1; confirm 2,3,4
            return hit, rec
    res = CA.PairSearch(Half(modes=("serial",))).search(FILES, VICTIM)
    assert res["result"] == "no minimal pair (not confirmed)" and res["attempts"][0]["confirm"]["pair_fail"] == 1


def test_budget():
    f = Fake(modes=("concurrent",))
    res = CA.PairSearch(f, budget_runs=8).search(FILES, VICTIM)
    assert res["result"] == "pair not found (budget)" and res["runs_spent"] <= 8


def test_trial_without_victim_outcome_is_not_evidence():
    def broken(mode, polluters, victim, seed=CA.DEFAULT):
        return None, {"victim_outcome": None, "timed_out": True}
    res = CA.PairSearch(broken).search(FILES, VICTIM)
    assert res["result"] == "no minimal pair (trial failed)" and res["runs_spent"] == 1


def test_reproduced_in_trials_counts_triggering_trials():
    assert CA.PairSearch(Fake()).search(FILES, VICTIM)["reproduced_in_trials"] >= 3
    # interaction: only the full-set control reproduces; not reproduced at all: 0
    assert CA.PairSearch(Fake(needs=["f1.test.ts", "f8.test.ts"])).search(FILES, VICTIM)["reproduced_in_trials"] == 1
    assert CA.PairSearch(Fake(modes=())).search(FILES, VICTIM)["reproduced_in_trials"] == 0


def test_load_failures(tmp_path):
    raw = tmp_path / "r.json"
    raw.write_text(json.dumps({"testResults": [
        {"name": "/r/a.test.ts", "status": "failed", "assertionResults": [], "message": "\n Error: Could not locate the bindings file\n more"},
        {"name": "/r/b.test.ts", "status": "failed", "assertionResults": [{"title": "t", "status": "failed"}]},
        {"name": "/r/c.test.ts", "status": "passed", "assertionResults": []}]}))
    assert CA.load_failures(str(raw)) == {"/r/a.test.ts": "Error: Could not locate the bindings file"}
    assert CA.load_failures(str(tmp_path / "missing.json")) is None
