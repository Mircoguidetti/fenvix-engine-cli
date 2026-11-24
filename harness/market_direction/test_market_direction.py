"""Unit tests for the market direction check. Each test's card:
protects=<the rule gives the specified value on a fixture>; fails_when=<a rule returns another window, level, value,
class, R or verdict>; no_claim=<that live API data is read correctly (AC6 hand checks cover that)>.
Run: python -m pytest harness/market_direction/test_market_direction.py -q
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import md_rules as M  # noqa: E402
import pairs as P  # noqa: E402
import web  # noqa: E402

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 4, 20, 12, 0, tzinfo=UTC)

WF = """
name: CI
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - run: npm run lint
  test:
    name: Test ${{ matrix.node }}
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: [18, 20]
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - name: Unit
        run: npm test
      - name: E2E
        run: npx jest e2e
"""
PKG = json.dumps({"scripts": {"test": "jest", "lint": "eslint ."}})


def reader(files):
    return lambda p: files.get(p)


def step(name, secs, concl="success", n=1):
    a = dt.datetime(2026, 1, 1, tzinfo=UTC)
    return {"name": name, "number": n, "conclusion": concl, "started_at": M.iso(a),
            "completed_at": M.iso(a + dt.timedelta(seconds=secs))}


def job(name, steps, secs=600, concl="success"):
    a = dt.datetime(2026, 1, 1, tzinfo=UTC)
    return {"name": name, "conclusion": concl, "steps": steps, "started_at": M.iso(a),
            "completed_at": M.iso(a + dt.timedelta(seconds=secs))}


# ------------------------------------------------------------------------------------------------ T0 and windows

def test_t0_is_oldest_committer_date_over_both_files():
    """protects=T0 = min committer date over AGENTS.md and CLAUDE.md commits; fails_when=author date or one file."""
    c = lambda d, a="2020-01-01T00:00:00Z": {"commit": {"committer": {"date": d}, "author": {"date": a}}}
    t0 = M.t0_of([[c("2026-05-01T00:00:00Z"), c("2026-04-10T08:00:00Z")], [c("2026-04-09T23:00:00Z")]])
    assert t0 == dt.datetime(2026, 4, 9, 23, tzinfo=UTC)
    assert M.t0_of([[], []]) is None
    assert M.t0_in_range(dt.datetime(2026, 5, 24, 23, tzinfo=UTC), dt.date(2026, 4, 1))
    assert not M.t0_in_range(dt.datetime(2026, 5, 25, 0, tzinfo=UTC), dt.date(2026, 4, 1))
    assert not M.t0_in_range(dt.datetime(2026, 3, 31, 23, tzinfo=UTC), dt.date(2026, 4, 1))


def _runs(dates):
    return [{"id": i, "created_at": M.iso(d), "event": "push", "head_sha": f"s{i}"} for i, d in enumerate(dates)]


def test_d0_takes_10_newest_before_t0_across_subranges_half_open():
    """protects=D0 = 10 newest valued runs in [T0-90d, T0), walked back over 7-day sub-ranges, T0 itself excluded;
    fails_when=another window or order."""
    dates = [T0] + [T0 - dt.timedelta(days=d, hours=1) for d in range(0, 30, 2)] + [T0 - dt.timedelta(days=91)]
    runs = _runs(dates)
    sr = M.d0_subranges(T0)
    assert sr[0] == (T0 - dt.timedelta(days=7), T0) and sr[-1][0] == T0 - dt.timedelta(days=90)
    got = M.select_window(sr, lambda s, e: runs, lambda r: 1.0, newest_first=True)
    ids = [r["id"] for r, _ in got]
    assert len(ids) == 10 and 0 not in ids            # created_at == T0 is outside [., T0)
    assert ids == list(range(1, 11))                   # newest first


def test_d1_takes_10_oldest_from_t0_plus_182():
    """protects=D1 = 10 oldest valued runs in [T0+182d, min(T0+272d, read)]; fails_when=runs before T0+182d count."""
    start = T0 + dt.timedelta(days=182)
    dates = [start - dt.timedelta(seconds=1)] + [start + dt.timedelta(days=d) for d in range(0, 40, 3)]
    runs = _runs(dates)
    sr = M.d1_subranges(T0, T0 + dt.timedelta(days=400))
    assert sr[0][0] == start and sr[-1][1] == T0 + dt.timedelta(days=272)
    got = M.select_window(sr, lambda s, e: runs, lambda r: 1.0, newest_first=False, closed_last=True)
    assert [r["id"] for r, _ in got] == list(range(1, 11))


def test_window_skips_runs_without_value_and_pull_request_events():
    """protects=a run without a value or with a pull_request* event is skipped; fails_when=it counts."""
    runs = _runs([T0 - dt.timedelta(hours=h) for h in range(1, 30)])
    runs[0]["event"] = "pull_request_target"
    got = M.select_window(M.d0_subranges(T0), lambda s, e: runs, lambda r: None if r["id"] % 2 else 5.0,
                          newest_first=True)
    assert [r["id"] for r, _ in got] == [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]


class FakeClient:
    def __init__(self, route):
        self.route, self.n_requests, self.paths = route, 0, []

    def get(self, path, kind="core"):
        self.n_requests += 1
        self.paths.append(path)
        st, data, hd = self.route(path)
        return st, data, hd


def test_subrange_over_1000_splits_into_days():
    """protects=a sub-range with total_count > 1,000 is split into days; fails_when=it is read to the cap only."""
    def route(path):
        q = path.split("created=")[1].split("&")[0]
        s, e = [M.ts(x) for x in q.split("..")]
        tc = 5000 if (e - s) > dt.timedelta(days=1) else 1
        return 200, {"total_count": tc, "workflow_runs": [] if tc > 1000 else
                     [{"id": hash(q) % 10 ** 6, "created_at": M.iso(s), "event": "push"}]}, {}
    src = P.Source(FakeClient(route), "o/r")
    lst = P.list_runs_fn(src, "ci.yml", "main", [])
    runs = lst(T0 - dt.timedelta(days=7), T0)
    assert len(runs) == 7
    assert sum("created=" in p for p in src.c.paths) == 8


# ------------------------------------------------------------------------------------------------ values and levels

def test_value_is_sum_of_all_test_steps_of_matched_job_max_over_legs():
    """protects=per leg the sum of every resolving test step; run value = max over legs; fails_when=one step or one
    leg or a non-matching job is used."""
    files = {"package.json": PKG}
    jobs = [job("Test 18", [step("Set up job", 5), step("Unit", 100, n=3), step("E2E", 50, n=4)]),
            job("Test 20", [step("Unit", 120, n=3), step("E2E", 70, n=4)]),
            job("lint", [step("Run npm run lint", 999)])]
    assert M.run_value(WF, "test", reader(files), jobs, "step") == 190.0
    jobs[1]["steps"][1]["conclusion"] = "failure"   # that leg has no value; the other leg remains
    assert M.run_value(WF, "test", reader(files), jobs, "step") == 150.0


def test_run_without_resolving_step_at_head_sha_has_no_value():
    """protects=note 10: no resolving §2.2 step at head_sha -> no value; missing key -> no value."""
    jobs = [job("Test 18", [step("Unit", 100, n=3), step("E2E", 50, n=4)])]
    wf = WF.replace("npm test", "npm run unit").replace("npx jest e2e", "echo hi")
    assert M.run_value(wf, "test", reader({"package.json": PKG}), jobs, "step") is None
    assert M.run_value(WF, "nokey", reader({"package.json": PKG}), jobs, "step") is None


def test_empty_steps_raise_job_level_and_job_level_uses_job_duration():
    """protects=a matched job with empty steps triggers job level; job level = max over legs of job duration."""
    jobs = [job("Test 18", [], secs=300), job("Test 20", [], secs=420)]
    with pytest.raises(M.JobLevel):
        M.run_value(WF, "test", reader({"package.json": PKG}), jobs, "step")
    assert M.run_value(WF, "test", reader({"package.json": PKG}), jobs, "job") == 420.0


def test_job_level_restart_reselects_both_windows_never_mixed():
    """protects=if any run examined has empty steps, both windows are re-selected at job level; fails_when=D0 keeps
    step values while D1 uses job values."""
    files = {"package.json": PKG}
    d0 = [T0 - dt.timedelta(days=1, minutes=m) for m in range(12)]
    d1 = [T0 + dt.timedelta(days=200, minutes=m) for m in range(12)]
    runs = [{"id": i, "created_at": M.iso(d), "event": "push", "head_sha": "h"} for i, d in enumerate(d0 + d1)]
    wf_b64 = base64.b64encode(WF.encode()).decode()
    pkg_b64 = base64.b64encode(PKG.encode()).decode()

    def route(path):
        if "/contents/" in path:
            if "package.json" in path:
                return 200, {"type": "file", "sha": "p", "encoding": "base64", "content": pkg_b64, "size": 10}, {}
            return 200, {"type": "file", "sha": "w", "encoding": "base64", "content": wf_b64, "size": 10}, {}
        if "/jobs" in path:
            rid = int(path.split("/runs/")[1].split("/")[0])
            steps = [] if rid == 20 else [step("Unit", 100, n=3), step("E2E", 50, n=4)]
            return 200, {"jobs": [job("Test 18", steps, secs=1000 + rid)]}, {}
        if "/runs?" in path:
            q = path.split("created=")[1].split("&")[0]
            return 200, {"total_count": len(runs), "workflow_runs": runs}, {}
        raise AssertionError(path)
    P.Source.blobs.clear()
    src = P.Source(FakeClient(route), "o/r")
    res = P.timing(src, "main", T0, {"WF": ".github/workflows/ci.yml", "key": "test"}, T0 + dt.timedelta(days=400))
    assert res["level"] == "job"
    assert all(v >= 1000 for _, _, v in res["D0_runs"] + res["D1_runs"])


def test_median_of_10_is_mean_of_5th_and_6th():
    """protects=§3.4 median; fails_when=median of 9 or another index."""
    assert M.median10([10, 1, 9, 2, 8, 3, 7, 4, 6, 5]) == 5.5
    assert M.median10([1] * 9) is None
    assert M.median([3, 1, 2]) == 2 and M.median([4, 1, 2, 3]) == 2.5


# ------------------------------------------------------------------------------------------------ job choice

def test_measured_job_skips_workflow_call_only_files_and_picks_first_resolving_job():
    """protects=note 7 and 1.2 step 3: files by path, jobs in file order, first job with a resolving step; a
    workflow_call-only file is skipped; fails_when=a later or callee job is picked."""
    callee = "on:\n  workflow_call:\njobs:\n  t:\n    runs-on: x\n    steps:\n      - run: pytest\n"
    files = [(".github/workflows/a.yml", callee), (".github/workflows/b.yml", WF)]
    mj = M.measured_job(files, reader({"package.json": PKG}))
    assert mj["WF"] == ".github/workflows/b.yml" and mj["key"] == "test"
    no_e2e = WF.replace("npx jest e2e", "echo done")
    no_runner = {"package.json": json.dumps({"scripts": {"test": "ava"}})}
    assert M.measured_job([(".github/workflows/b.yml", no_e2e)], reader(no_runner))["reason"] == "no_test_step"
    assert M.measured_job([(".github/workflows/b.yml", no_e2e)], reader({}))["reason"] == "unresolved"
    assert M.measured_job([(".github/workflows/c.yml", "on: push\njobs:\n  a:\n    steps:\n      - run: ls\n")],
                          reader({}))["reason"] == "no_test_step"


# ------------------------------------------------------------------------------------------------ control

def test_control_rejected_when_any_agent_path_appears_by_t0_plus_272():
    """protects=a control with any of the 9 agent paths in history up to T0+272d is not eligible, and the checks
    stop there (note 11); fails_when=it is accepted or a later check runs first."""
    def route(path):
        if "path=.cursor%2Frules" in path:
            assert "until=" + M.iso(T0 + dt.timedelta(days=272)) in path
            return 200, [{"sha": "abc"}], {}
        if "/commits?" in path:
            return 200, [], {}
        raise AssertionError(f"unexpected call {path}")
    c = FakeClient(route)
    rec = P.read_control(c, {"full_name": "x/y", "id": 1, "default_branch": "main"}, T0, T0, set())
    assert rec["outcome"] == "agent_file:.cursor/rules/"
    assert len(c.paths) == 9
    assert M.agent_file_hit(rec["paths"]) == [".cursor/rules/"]


def test_control_order_dedupes_drops_frame_sorts_by_id_and_shuffles_with_agent_id():
    """protects=1.3 order; fails_when=a frame repository is tested or the seed differs."""
    items = [{"full_name": f"o/r{i}", "id": i} for i in (5, 3, 9, 1, 3)] + [{"full_name": "o/agent", "id": 7}]
    got = M.control_order(items, {"o/r9"}, "o/agent", 42)
    exp = sorted([{"full_name": f"o/r{i}", "id": i} for i in (5, 3, 1)], key=lambda x: x["id"])
    random.Random(42).shuffle(exp)
    assert got == exp
    assert M.control_query("Go", 15, dt.date(2026, 11, 24)) == \
        'language:"Go" stars:7..23 pushed:>=2026-10-25 archived:false fork:false'


# ------------------------------------------------------------------------------------------------ statistic

def test_faster_rule_tie_is_not_faster():
    """protects=faster = median(g_agent) > median(g_control), strict; fails_when=a tie counts as faster."""
    assert not M.faster([1.0, 2.0, 3.0], [2.0, 2.0, 2.0])
    assert M.faster([1.0, 2.1, 3.0], [2.0, 2.0, 2.0])


def test_bootstrap_uses_seed_2_and_indexes_249_9749():
    """protects=interval = sorted differences at 249 and 9,749 with random.Random(2); fails_when=other seed/index."""
    pairs = [(1.0 + i / 10, 1.0 + (i % 3) / 10) for i in range(20)]
    rng = random.Random(2)
    diffs = []
    for _ in range(10000):
        s = [pairs[rng.randrange(20)] for _ in range(20)]
        diffs.append(M.median([a for a, _ in s]) - M.median([c for _, c in s]))
    diffs.sort()
    assert M.bootstrap(pairs) == (diffs[249], diffs[9749])


# ------------------------------------------------------------------------------------------------ eval setup

def test_eval_setup_dependency_equality_after_normalising():
    """protects=note 15 name equality with - and _ normalised; root or one level down; fails_when=substring match."""
    ok, why = M.eval_setup({"pyproject.toml": '[project]\ndependencies = ["Inspect_AI>=0.3", "ragasx"]\n',
                            "a/b/package.json": json.dumps({"dependencies": {"promptfoo": "1"}})})
    assert ok and why == ["pyproject.toml: inspect-ai"]
    assert not M.eval_setup({"requirements.txt": "ragas-extra==1\n"})[0]
    assert M.eval_setup({"web/promptfooconfig.yaml": ""})[0]
    assert M.eval_setup({"requirements-dev.txt": "git+https://github.com/openai/evals.git\n"})[0]


# ------------------------------------------------------------------------------------------------ Part 2

@pytest.mark.parametrize("text,exp", [
    ("maintain", "borderline"), ("fastest", "borderline"), ("remodel", "borderline"),
    ("AI-powered CI for faster tests", "T"), ("Evaluate your LLM apps", "E"),
    ("The fastest GitHub Actions runners", "T"), ("AI-powered end-to-end testing", "borderline")])
def test_classification_fixtures(text, exp):
    """protects=the 7 pre-registered §2.3 fixtures; fails_when=a regex or rule order changes."""
    assert web.classify(text) == exp


def test_classification_public_and_unverified():
    """protects=public -> not summed; status != 200 or empty text -> UNVERIFIED."""
    assert web.classify("Evaluate your LLM apps", 200, public=True) == "public"
    assert web.classify("Evaluate your LLM apps", 404) == "UNVERIFIED"
    assert web.classify("   ", 200) == "UNVERIFIED"
    assert web.class_text('<h1 class="a">Fast<b>CI</b>\n &amp; tests</h1>') == ("Fast CI & tests", "h1")
    assert web.class_text('<h1> </h1><meta name="description" content="Evals &amp; more">') == \
        ("Evals & more", "meta description")


def test_ratio_cases():
    """protects=R = F_E/F_T; F_T = 0 < F_E -> infinite; both 0 -> 0 (Interpretation (PREREG))."""
    assert M.ratio(10, 30) == 3
    assert M.ratio(0, 5) == float("inf")
    assert M.ratio(0, 0) == 0


def test_part2_failure_rule_at_25_percent():
    """protects=more than 25% of seed UNVERIFIED -> failure; exactly 25% is not; no source at all -> failure."""
    assert not M.part2_failed(40, 10, True)
    assert M.part2_failed(40, 11, True)
    assert M.part2_failed(39, 0, False)


@pytest.mark.parametrize("p1", ["yes", "no", "NO DECISION", "BLOCKED"])
@pytest.mark.parametrize("p2", ["R>=3", "R<3", "NO DECISION"])
def test_verdict_table_all_12_combinations(p1, p2):
    """protects=verdict table (note 12); fails_when=any of the 12 cells differs."""
    exp = {("no", "R>=3"): "REOPEN", ("BLOCKED", "NO DECISION"): "BLOCKED"}.get((p1, p2))
    if exp is None:
        exp = "STANDS" if (p1 == "yes" or p2 == "R<3") else "NO DECISION"
    assert M.verdict(p1, p2) == exp
    table = {("yes", "R>=3"): "STANDS", ("yes", "R<3"): "STANDS", ("yes", "NO DECISION"): "STANDS",
             ("no", "R>=3"): "REOPEN", ("no", "R<3"): "STANDS", ("no", "NO DECISION"): "NO DECISION",
             ("NO DECISION", "R>=3"): "NO DECISION", ("NO DECISION", "R<3"): "STANDS",
             ("NO DECISION", "NO DECISION"): "NO DECISION", ("BLOCKED", "R>=3"): "NO DECISION",
             ("BLOCKED", "R<3"): "STANDS", ("BLOCKED", "NO DECISION"): "BLOCKED"}
    assert M.verdict(p1, p2) == table[(p1, p2)]


def test_part1_state():
    """protects=fewer than 100 pairs -> NO DECISION; BLOCKED from §0.2."""
    assert M.part1_state(99, False, True) == "NO DECISION"
    assert M.part1_state(100, False, False) == "no"
    assert M.part1_state(0, True, None) == "BLOCKED"
