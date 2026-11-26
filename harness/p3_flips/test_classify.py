#!/usr/bin/env python3
"""Unit tests for the P3 verdict rule (classify.py) and the per-run state rules (cases.py, ladder.py), on synthetic
rows. Run: python3 -m pytest -q harness/p3_flips/test_classify.py

Every test states its card: protects / fails_when / no_claim. Common no_claim for this file: synthetic rows stand in
for the evidence ladder.py records from real runs; green says nothing about whether those runs were done right.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classify  # noqa: E402  (first: pins.py puts parallel_measure/, which has its own classify.py, on sys.path)
import cases  # noqa: E402
import ladder  # noqa: E402

P3 = ["plain"] * 3


def row(**kw):
    r = {"repo": "r", "kind": "flip", "test_id": "t.ts::a", "results": ["passed", "passed", "failed", "failed"],
         "unstable": False, "det_failure": ["Error: Test timed out in 5000ms.", None],
         "alone": {"states": ["repro", "repro"]}, "control": {"states": P3}}
    r.update(kw)
    return r


def order_cond(states, applied_ok=True, failure="Error: Test timed out in 5000ms."):
    return {"kind": "order", "states": states, "runs": [{"failure": failure}]}


def test_outcome_read_per_id_not_exit_code():
    # protects: a case's state comes from its own id's outcome; fails_when: a run with exit 1 (another test failed)
    # is read as 'reproduces'; no_claim: none beyond protects
    run = {"exit": 1, "outcomes": {"t.ts::a": "passed", "t.ts::b": "failed"}, "valid": True}
    st, cleared = ladder.step_states({"id": "t.ts::a", "kind": "flip"}, [run, run])
    assert st == ["clear", "clear"] and cleared


def test_absent_id_is_invalid_run():
    # protects: an id missing from a run makes that run invalid for flip/mixed/reverse/skipped kinds; fails_when: a
    # missing id counts as 'cleared' or 'reproduces'; no_claim: none beyond protects
    for k in ("flip", "mixed", "reverse", "skipped-in-det"):
        assert ladder.state(k, None) == "invalid"
        assert ladder.plain_state(k if k != "skipped-in-det" else "flip", None) == "invalid"
    # absent and det-only: absence is the measured outcome
    assert ladder.state("absent", None) == "repro" and ladder.state("det-only", None) == "clear"


def test_theirs_env_order():
    # protects: control 3/3 plain + condition >= 1/3 --det outcome -> THEIRS-ENV (order, candidate bug); fails_when:
    # that evidence gives any other verdict; no_claim: none beyond protects
    v, why, flags = classify.verdict(row(condition=order_cond(["plain", "det", "plain"]), clears_at="L6",
                                         set={"name": "smallest"}))
    assert v == "THEIRS-ENV" and "candidate-real-bug (order)" in flags and "1/3" in why


def test_different_failure_flag():
    # protects: a THEIRS-ENV row whose plain failure line differs from the --det one is flagged; fails_when: no flag;
    # no_claim: none beyond protects
    v, _, flags = classify.verdict(row(condition=order_cond(["det", "det", "det"], failure="AssertionError: x")))
    assert v == "THEIRS-ENV" and "different-failure" in flags


def test_plain_flaky_control_undecided():
    # protects: a mixed control is UNDECIDED (plain flaky), never THEIRS-ENV; fails_when: THEIRS-ENV/ARTIFACT;
    # no_claim: none beyond protects
    v, why, _ = classify.verdict(row(control={"states": ["plain", "det", "plain"]}, clears_at="L1",
                                     condition=order_cond(["det"] * 3)))
    assert v == "UNDECIDED" and "plain flaky" in why


def test_control_all_det_goes_to_whole_suite_comparison():
    # protects: control 0/3 plain on the smallest set -> whole-suite order comparison decides THEIRS-ENV or
    # UNDECIDED, never dropped; fails_when: the case disappears or gets ARTIFACT; no_claim: none beyond protects
    ws_yes = {"default": {"states": P3}, "forced": {"states": ["plain", "det", "plain"]}}
    ws_no = {"default": {"states": ["plain", "det", "plain"]}, "forced": {"states": ["det"] * 3}}
    v1, _, _ = classify.verdict(row(control={"states": ["det"] * 3}, whole_suite_order=ws_yes, clears_at="L1"))
    v2, why2, _ = classify.verdict(row(control={"states": ["det"] * 3}, whole_suite_order=ws_no, clears_at="L1"))
    assert v1 == "THEIRS-ENV" and v2 == "UNDECIDED" and why2 == "plain subset-dependent"


def test_time_seeds_open_net_never_theirs_env():
    # protects: causes with no plain equivalent end ARTIFACT, never THEIRS-ENV, even with a 'condition' present;
    # fails_when: THEIRS-ENV; no_claim: none beyond protects
    for step in ("L4", "L5", "L2b", "L1", "L2a", "L3", "L7", "wrapper"):
        v, _, _ = classify.verdict(row(clears_at=step))
        assert v == "ARTIFACT"
    v, _, _ = classify.verdict(row(clears_at="L2b", net_trigger=False,
                                   condition={"kind": "network", "states": ["det"] * 3, "runs": []}))
    assert v == "ARTIFACT"


def test_network_condition_only_on_trigger():
    # protects: the network condition counts only with a NetworkBlockedError or meta block/replay; fails_when: it
    # counts without; no_claim: none beyond protects
    c = {"kind": "network", "states": ["det", "plain", "plain"], "runs": [{"failure": "NetworkBlockedError: x"}]}
    assert classify.verdict(row(condition=c, net_trigger=True, det_failure=["NetworkBlockedError: x"]))[0] == "THEIRS-ENV"
    assert classify.verdict(row(condition=c, net_trigger=False, clears_at="L2b"))[0] == "ARTIFACT"


def test_artifact_and_wrapper():
    # protects: a ladder clear or an L7 reproduction is ARTIFACT with the cause named; fails_when: other verdict or
    # wrong cause; no_claim: none beyond protects
    assert classify.verdict(row(clears_at="L1"))[1].startswith("cause timers progression")
    assert classify.verdict(row(clears_at="wrapper")) == ("ARTIFACT", "cause wrapper (wrapper)", [])


def test_mixed_outcome_needs_5_of_5():
    # protects: a mixed-outcome case clears a step only with 5/5 clears; 4/5 is not cleared; fails_when: 4/5 clears;
    # no_claim: the 5-run count itself is chosen in ladder.ladder, tested here through step_states only
    c = {"id": "t.ts::a", "kind": "mixed"}
    runs = [{"outcomes": {"t.ts::a": "passed"}}] * 4 + [{"outcomes": {"t.ts::a": "failed"}}]
    assert ladder.step_states(c, runs)[1] is False
    assert ladder.step_states(c, [{"outcomes": {"t.ts::a": "passed"}}] * 5)[1] is True
    assert ladder.mixed_outcome({"kind": "mixed", "results": ["passed", "passed", "failed", "passed"]})


def test_no_clear_is_undecided():
    # protects: a case that clears at no step and is not wrapper is UNDECIDED; fails_when: ARTIFACT; no_claim: none
    v, why, _ = classify.verdict(row())
    assert v == "UNDECIDED" and "only some runs" in why


def test_absent_passing_alone_is_not_a_verdict():
    # protects: an absent/skipped case that passes alone still needs predecessor/ladder evidence; fails_when: a
    # verdict other than UNDECIDED from 'passes alone' only; no_claim: none beyond protects
    r = row(kind="absent", results=["passed", "passed", None, "passed"], alone={"states": ["clear", "clear"]},
            control={"states": P3})
    assert classify.verdict(r)[0] == "UNDECIDED"


def test_det_only_and_reverse_kinds():
    # protects: det-only and reverse kinds are built from the four results and classified; fails_when: missed or
    # mis-kinded; no_claim: none beyond protects
    assert cases.kind_of(None, None, "passed", None) == "det-only"
    assert cases.kind_of("failed", "failed", "passed", "skipped") == "reverse"
    assert cases.kind_of("passed", "passed", "failed", "failed") == "flip"
    assert cases.kind_of("passed", "passed", "failed", "passed") == "mixed"
    assert cases.kind_of("passed", "passed", None, "failed") == "absent"
    assert cases.kind_of("passed", "passed", "skipped", "failed") == "skipped-in-det"
    assert cases.kind_of("failed", "passed", "failed", "failed") == "other"
    assert cases.kind_of("skipped", "skipped", "passed", "skipped") == "other"
    assert cases.kind_of("passed", "passed", "passed", "passed") is None
    r = row(kind="reverse", results=["failed", "failed", "passed", "passed"], control={"states": P3}, clears_at="L2a")
    assert classify.verdict(r)[0] == "ARTIFACT"


def test_other_and_unstable_undecided():
    # protects: kind other and unstable ids are UNDECIDED without a search; fails_when: any other verdict;
    # no_claim: none beyond protects
    assert classify.verdict(row(kind="other", clears_at="L1")) == ("UNDECIDED", "kind other", [])
    assert classify.verdict(row(unstable=True, pattern="x #"))[1].startswith("unstable id")


def test_full_predecessor_set_not_reproducing():
    # protects: a case the full predecessor set does not reproduce is UNDECIDED with that reason; fails_when: any
    # other verdict; no_claim: none beyond protects
    r = row(undecided="not reproduced outside the whole suite", clears_at="L1")
    assert classify.verdict(r) == ("UNDECIDED", "not reproduced outside the whole suite", [])


def test_invalid_ladder_run_never_clears():
    # protects: a run whose flag did not take effect (L1 without meta timers=real) is invalid, never a clear or a
    # 'did not clear'; fails_when: it is counted; no_claim: none beyond protects
    r = {"meta": {"timers": "virtual"}, "controls": ["order"], "outcomes": {"t.ts::a": "passed"}}
    ok, _ = ladder.valid_ladder_run("L1", set(), r)
    assert not ok
    st, cleared = ladder.step_states({"id": "t.ts::a", "kind": "flip"}, [dict(r, valid=ok)] * 2)
    assert st == ["invalid", "invalid"] and not cleared
    ok2, _ = ladder.valid_ladder_run("L2b", {"timers", "net"}, {"meta": {}, "controls": ["net", "order"]})
    assert not ok2


def test_order_not_forced_cannot_be_theirs():
    # protects: an order condition whose harness config failed the neutrality check, or was not forced, cannot make
    # THEIRS-ENV; fails_when: THEIRS-ENV; no_claim: none beyond protects
    assert classify.verdict(row(condition=order_cond(["det"] * 3)), neutral=False)[0] == "UNDECIDED"
    c = {"kind": "order", "not_forced": "single file"}
    assert classify.verdict(row(condition=c)) == ("UNDECIDED", "order not forced", [])


def test_gone_rule_per_kind():
    # protects: spec D1 per kind; fails_when: a case left as UNDECIDED is called gone (or the reverse); no_claim:
    # none beyond protects
    assert classify.gone("flip", "passed", "passed")
    assert not classify.gone("flip", "passed", "failed")
    assert not classify.gone("absent", "passed", None)
    assert classify.gone("det-only", None, None) and not classify.gone("det-only", None, "passed")
    assert classify.gone("reverse", "failed", "failed")
    assert not classify.gone("mixed", "passed", "passed", small_plain_5=4, was_mixed_outcome=True)
    assert classify.gone("mixed", "passed", "passed", small_plain_5=5, was_mixed_outcome=True)
    assert not classify.gone("other", "passed", "passed")


def test_plain_flaky_in_a_is_undecided():
    # protects: founder D3, an id whose two plain runs of A differ is UNDECIDED "plain flaky", whatever B found;
    # fails_when: any other verdict; no_claim: none beyond protects
    r = row(kind="other", results=["failed", "passed", "failed", "failed"], clears_at="L1")
    v, why, _ = classify.verdict(r)
    assert v == "UNDECIDED" and why.startswith("plain flaky (plain runs of A")


def test_pattern_matched_once_per_run_is_one_case():
    # protects: founder D2, a pattern naming exactly one id per run is one ordinary case (or none when the four agree);
    # any other count keeps its ids unstable; fails_when: a 2-per-run pattern is merged, or a 1-per-run one is not;
    # no_claim: the shape rule itself (digits, leading minus) beyond the two ids used here
    a = [{"t::x 1": "passed"}, {"t::x 2": "passed"}, {"t::x 3": "failed"}, {"t::x 4": "failed"}]
    sh = [{cases.shape(k): {k} for k in r} for r in a]
    mem = [{"id": k, "kind": "other", "unstable": True, "pattern": "t::x #", "results": None} for r in a for k in r]
    det = [({}, {}), ({}, {})]
    out, rep = cases.match_patterns(mem, a, sh, det)
    assert [c["kind"] for c in out] == ["flip"] and rep[0]["matches_per_run"] == [1, 1, 1, 1]
    # a sibling present by exact name in all four runs is left out of the count: still matched
    a3 = [dict(r, **{"t::x 99": "passed"}) for r in a]
    sh3 = [{cases.shape(k): set(r) for k in r} for r in a3]
    out3, rep3 = cases.match_patterns(mem, a3, sh3, det)
    assert [c["kind"] for c in out3] == ["flip"] and rep3[0]["matches_per_run"] == [1, 1, 1, 1]
    sh2 = [dict(s, **{"t::x #": s["t::x #"] | {"t::x 9"}}) for s in sh]
    out2, rep2 = cases.match_patterns(mem, a, sh2, det)
    assert len(out2) == 4 and all(c["unstable"] for c in out2) and rep2[0]["matched"] is False
