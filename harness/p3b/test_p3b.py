#!/usr/bin/env python3
"""Unit tests for P3b's own files (timeouts.py, causes.py, report.py) on synthetic rows.
Run: python3 -m pytest -q harness/p3b/test_p3b.py

Every test states its card: protects / fails_when / no_claim. Common no_claim for this file: synthetic rows and
timeouts.json records stand in for what classify.py rows and timeouts.py measure write from real runs; green says
nothing about whether those runs were done right, or about the walls themselves.
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classify  # noqa: E402  (first: parallel_measure/ has its own classify.py)
import causes  # noqa: E402
import report  # noqa: E402
import timeouts  # noqa: E402

TMO = "Error: Test timed out in 5000ms. [test @ x]"


def wrapper_row(tid="f.test.ts::a", key="abc.g0", line=TMO, **kw):
    r = {"repo": "r", "kind": "flip", "test_id": tid, "file": "f.test.ts",
         "results": ["passed", "passed", "failed", "failed"], "unstable": False, "det_failure": [line, line],
         "set": {"name": "alone", "files": ["f.test.ts"]}, "clears_at": "wrapper",
         "ladder": {"L7": {"states": ["repro", "repro"], "runs": [{"tag": f"{key}.L7.r1", "cmd": "node detjs L7"}]}},
         "control": {"states": ["plain"] * 3, "runs": [{"tag": f"{key}.control.r1", "cmd": "npx vitest"}]},
         "verdict": "ARTIFACT", "reason": "cause wrapper (wrapper)", "flags": []}
    r.update(kw)
    return r


def tw(plain_walls, l7_walls, cases):
    p = timeouts.summarize({"plain": [{"wall_s": w} for w in plain_walls], "l7": [{"wall_s": w} for w in l7_walls]})
    return {"r": {"pairs": {"abc.g0": p}, "cases": cases}}


def case(kind="Test", ms=5000, plain_ms=100.0):
    return {"pair": "abc.g0", "timeout_kind": kind, "timeout_ms": ms, "plain_ms": plain_ms, "plain_source": "x"}


def test_ratio_over_threshold_sets_engine_overhead_keeps_verdict():
    # protects: L7 median / plain median >= 1.5 -> overhead.engine_overhead true, verdict ARTIFACT and P3's reason
    # unchanged; fails_when: the flag is false, or the verdict/reason is rewritten; no_claim: none beyond protects
    r = timeouts.annotate_row(wrapper_row(), tw([10, 10, 10], [16, 16, 16], {"f.test.ts::a": case()}))
    assert r["overhead"]["ratio"] == 1.6 and r["overhead"]["engine_overhead"] is True
    assert r["verdict"] == "ARTIFACT" and r["reason"] == "cause wrapper (wrapper)"


def test_ratio_low_and_budget_ok_is_false():
    # protects: ratio 1.2 with plain duration + overhead under the timeout -> engine_overhead false; fails_when: true;
    # no_claim: none beyond protects
    r = timeouts.annotate_row(wrapper_row(), tw([10, 10, 10], [12, 12, 12], {"f.test.ts::a": case(plain_ms=100.0)}))
    assert r["overhead"] == {"ratio": 1.2, "over_budget": False, "engine_overhead": False}


def test_ratio_low_but_over_budget_is_true():
    # protects: ratio 1.2 but test duration (4000 ms) + overhead (2 s) > 5000 ms -> over_budget and engine_overhead
    # true; fails_when: either false; no_claim: none beyond protects
    r = timeouts.annotate_row(wrapper_row(), tw([10, 10, 10], [12, 12, 12], {"f.test.ts::a": case(plain_ms=4000.0)}))
    assert r["overhead"]["over_budget"] is True and r["overhead"]["engine_overhead"] is True


def test_hook_timeout_uses_file_time_and_hook_ms(tmp_path):
    # protects: a Hook timeout is compared with its file's endTime - startTime (median of the two plain runs) and the
    # hook's own ms from its line; a Test timeout with its own duration; fails_when: the hook uses a test duration or
    # 5000 ms; no_claim: the runner JSON is synthetic (shape of Vitest's json reporter)
    cwd = str(tmp_path)
    for i, (s, e, d) in enumerate([(0, 9000, 30), (0, 9400, 50)], 1):
        j = {"testResults": [{"name": os.path.join(cwd, "f.test.ts"), "startTime": s, "endTime": e,
                              "assertionResults": [{"ancestorTitles": [], "title": "a", "duration": d}]}]}
        (tmp_path / f"plain{i}.runner.json").write_text(json.dumps(j))
    tests, files = timeouts.plain_durations(cwd, cwd)
    hook = wrapper_row(line="Error: Hook timed out in 10000ms. [hook]")
    assert timeouts.case_plain(hook, tests, files)[0] == 9200
    assert timeouts.case_plain(wrapper_row(), tests, files)[0] == 40
    assert timeouts.timeout_of(hook["det_failure"][0]) == ("Hook", 10000)
    r = timeouts.annotate_row(hook, tw([10] * 3, [11] * 3, {"f.test.ts::a": case("Hook", 10000, 9200.0)}))
    assert r["overhead"]["over_budget"] is True  # 9200 + 1000 > 10000


def theirs_row(path, failure, states=("det", "plain", "plain")):
    runs = [{"failure": failure if s == "det" else None} for s in states]
    r = wrapper_row(verdict="THEIRS-ENV", flags=["candidate-real-bug (order)"])
    if path == "condition":
        r.update(reason="order: control 3/3 plain, condition 1/3 --det",
                 condition={"kind": "order", "states": list(states), "runs": runs})
    else:
        r.update(reason="order (whole suite): default 3/3 plain, forced 1/3 --det",
                 whole_suite_order={"forced": {"states": list(states), "runs": runs}})
    return r


def test_theirs_env_condition_different_line_undecided():
    # protects: a timeout THEIRS-ENV on the condition path whose failing run has another line -> UNDECIDED with the
    # spec's reason; flags keep different-failure, drop candidate-real-bug (order); fails_when: stays THEIRS-ENV or
    # flags wrong; no_claim: none beyond protects
    r = timeouts.annotate_row(theirs_row("condition", "AssertionError: x"), {})
    assert (r["verdict"], r["reason"]) == ("UNDECIDED", "timeout THEIRS-ENV with a different failure line")
    assert r["flags"] == ["different-failure"]


def test_theirs_env_whole_suite_different_ms_undecided():
    # protects: the whole-suite forced-order path is checked too, and a timeout of another ms is "different";
    # fails_when: stays THEIRS-ENV; no_claim: none beyond protects
    r = timeouts.annotate_row(theirs_row("ws", "Error: Test timed out in 10000ms."), {})
    assert r["verdict"] == "UNDECIDED" and "different-failure" in r["flags"]


def test_theirs_env_missing_line_fails_closed():
    # protects: a failing run without a recorded line is "different" (fail closed); fails_when: stays THEIRS-ENV;
    # no_claim: none beyond protects
    r = timeouts.annotate_row(theirs_row("condition", None), {})
    assert r["verdict"] == "UNDECIDED"


def test_theirs_env_same_timeout_line_kept():
    # protects: the same kind and ms on every failing run keeps THEIRS-ENV and its flags; fails_when: it is demoted;
    # no_claim: none beyond protects
    r = timeouts.annotate_row(theirs_row("condition", "Error: Test timed out in 5000ms. [other]"), {})
    assert r["verdict"] == "THEIRS-ENV" and r["flags"] == ["candidate-real-bug (order)"]


def test_non_timeout_rows_unchanged_byte_for_byte():
    # protects: rows whose first --det line is not a timeout are not touched, even THEIRS-ENV ones; fails_when: any
    # byte differs; no_claim: none beyond protects
    rows = [wrapper_row(line="AssertionError: x"), theirs_row("condition", "AssertionError: y")]
    rows[1]["det_failure"] = ["AssertionError: z", None]
    before = [json.dumps(r, sort_keys=True) for r in rows]
    after = [json.dumps(timeouts.annotate_row(copy.deepcopy(r), tw([1] * 3, [9] * 3, {})), sort_keys=True) for r in rows]
    assert before == after


def test_two_cases_share_one_pair_and_annotate_is_deterministic(tmp_path):
    # protects: two cases of one command pair get the same timeout_wall; annotate rewrites rows.jsonl byte-identical
    # when run twice on the same input; fails_when: walls differ between the two or output changes; no_claim: none
    # beyond protects
    t = tw([10] * 3, [20] * 3, {"f.test.ts::a": case(), "f.test.ts::b": case()})
    d = tmp_path / "data" / "r"
    d.mkdir(parents=True)
    (d / "timeouts.json").write_text(json.dumps(t["r"]))
    rp = tmp_path / "rows.jsonl"
    classify.write_rows([wrapper_row(), wrapper_row(tid="f.test.ts::b")], str(rp))
    raw = rp.read_text()
    timeouts.annotate_cmd(None, str(rp), str(tmp_path / "data"))
    once = rp.read_text()
    rows = classify.load_rows(str(rp))
    a, b = (dict(r["timeout_wall"]) for r in rows)
    assert {k: v for k, v in a.items() if k != "case"} == {k: v for k, v in b.items() if k != "case"}
    rp.write_text(raw)
    timeouts.annotate_cmd(None, str(rp), str(tmp_path / "data"))
    assert rp.read_text() == once


def test_causes_groups_by_p3_label_and_lists_p3_rows():
    # protects: causes.py groups ARTIFACT rows by P3's reason, and lists P3's same-label rows plus P3's timeout rows of
    # other causes; fails_when: a P3b case or a P3 comparable row is missing or misgrouped; no_claim: P3's rows are
    # synthetic here (the real ones are read with git show)
    rows = [wrapper_row(), wrapper_row(tid="f.test.ts::c", reason="cause timers progression (virtual) (L1)",
                                       clears_at="L1", ladder={"L1": {"runs": [{"cmd": "x --det --det-timers=real"}]}}),
            wrapper_row(tid="f.test.ts::u", verdict="UNDECIDED", reason="plain flaky")]
    p3 = [{"repo": "ic", "test_id": "p::1", "reason": "cause wrapper (wrapper)", "verdict": "ARTIFACT",
           "det_failure": ["spawn ENOENT"]},
          {"repo": "cm", "test_id": "p::2", "reason": "cause timers progression (virtual) (L1)", "verdict": "ARTIFACT",
           "det_failure": [TMO]}]
    g = causes.group(rows)
    assert sorted(g) == ["cause timers progression (virtual) (L1)", "cause wrapper (wrapper)"]
    same, tmo = causes.p3_comparable("cause wrapper (wrapper)", p3)
    assert [r["test_id"] for r in same] == ["p::1"] and [r["test_id"] for r in tmo] == ["p::2"]
    md = causes.render(rows, "sha", p3, None, {}, {"r": "c0ffee"})
    assert "f.test.ts::u" not in md and "not named yet" in md
    rep = causes.reproduction(rows[1], "c0ffee")
    assert rep["fails"] == "x --det" and rep["clears"] == "x --det --det-timers=real"


def test_neutral_differ_reconciliation_reports_neither():
    # protects: every differ id is excluded (a) plain flaky, excluded (b) pattern, or not excluded; an excluded id that
    # is neither (a) nor (b) is reported; fails_when: an id is dropped or put in the wrong bucket; no_claim: none
    # beyond protects
    p1 = {"f::flaky": "passed", "f::seed 11": "passed", "f::orphan": "passed", "f::stable": "passed"}
    p2 = {"f::flaky": "failed", "f::seed 22": "passed", "f::orphan": "failed", "f::stable": "passed"}
    differ = [["f::flaky", "passed", "failed"], ["f::seed 11", "passed", None], ["f::orphan", "passed", "failed"],
              ["f::stable", "passed", "failed"], ["f::seed 33", None, "passed"]]
    cj = {"patterns": [{"pattern": "f::seed #", "matched": True, "kind": None}]}
    rows = [{"test_id": "f::flaky", "verdict": "UNDECIDED", "reason": "plain flaky (plain runs of A: passed / failed)"},
            {"test_id": "f::orphan", "verdict": "ARTIFACT", "reason": "cause time (L4)"}]
    _, _, rec = report.reconcile(differ, p1, p2, cj, rows)
    assert [k for k, _ in rec["excluded_a"]] == ["f::flaky"]
    assert [k for k, _ in rec["excluded_b"]] == ["f::seed 11", "f::seed 33"]
    assert [k for k, _ in rec["excluded_neither"]] == ["f::orphan"]
    assert [k for k, _ in rec["not_excluded"]] == ["f::stable"]


def test_gone_per_kind_and_mixed_fails_closed():
    # protects: report.gone_rows applies classify.gone per kind on the head's two --det runs; a formerly
    # mixed-outcome case is gone only with 5/5 plain outcomes on its smallest set (no count -> not gone); fails_when:
    # a flip still failing counts as gone, or a mixed case without its 5 runs does; no_claim: none beyond protects
    rows = [{"test_id": "a", "kind": "flip"}, {"test_id": "b", "kind": "flip"},
            {"test_id": "c", "kind": "mixed", "mixed_outcome": True}, {"test_id": "d", "kind": "det-only"}]
    d1 = {"a": "passed", "b": "failed", "c": "passed"}
    d2 = {"a": "passed", "b": "passed", "c": "passed"}
    g = {x["test_id"]: x["gone"] for x in report.gone_rows(rows, d1, d2)}
    assert g == {"a": True, "b": False, "c": False, "d": True}
    assert report.gone_rows(rows[2:3], d1, d2, {"c": 5})[0]["gone"] is True
