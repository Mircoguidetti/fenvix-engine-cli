"""Tests for the agent tools count rules and pipeline (acceptance criterion 2 of the spec).

Each test states protects= (the behaviour it protects), fails_when= (the change that makes it fail) and no_claim=
(what it does not show). Run: python3 -m pytest harness/agent_tools_count/test_agent_tools_count.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import job as J  # noqa: E402
import pipeline as P  # noqa: E402
import rules as R  # noqa: E402
from common import seeded_order  # noqa: E402

REPO, N = "o/r", 7


# ================================================================ a fake GitHub for count_a

class Fake:
    """Answers trimmed responses by path pattern; unknown paths are a test failure (like ReplaySource)."""

    def __init__(self, routes):
        self.routes = routes
        self.paths = []

    def has(self, path):
        return False

    def get(self, path):
        self.paths.append(path)
        for pat, fn in self.routes:
            m = re.fullmatch(pat, path)
            if m:
                return 200, fn(m)
        raise P.Missing(path)


def sha(i: int) -> str:
    return f"{i:040x}"


def build(commits, x_states, *, base="failure", family="copilot", files=None, ann=None, base_ann=None,
          output_text="", tree=("src/orders.test.ts", "src/app.ts", "tests/test_a.py"), n_commits_pr=None,
          head_ref="copilot/fix-1", wf_path=".github/workflows/ci.yml"):
    """commits: list of dicts {author, message, parents (int)}; x_states: per commit 'failure' / 'success' / None
    (no check run). The check run X is Actions job ``test`` of workflow ``CI``; its base run ends in ``base``."""
    files = files or {}
    cs = []
    for i, c in enumerate(commits, start=1):
        cs.append({"sha": sha(i), "author_login": c.get("author", "Copilot"), "message": c.get("message", "wip"),
                   "date": f"2026-06-01T{i:02d}:00:00Z", "parents": [sha(100 + j) for j in range(c.get("parents", 1))]})
    by_sha = {c["sha"]: (i, c) for i, c in enumerate(cs, start=1)}

    def check_runs(m):
        i, _ = by_sha[m.group(1)]
        st = x_states[i - 1]
        if st is None:
            return {"total_count": 0, "check_runs": []}
        return {"total_count": 1, "check_runs": [{
            "id": 1000 + i, "name": "test", "status": "completed", "conclusion": st,
            "started_at": f"2026-06-01T{i:02d}:05:00Z", "completed_at": f"2026-06-01T{i:02d}:10:00Z",
            "app": "github-actions", "check_suite_id": 500 + i, "head_sha": m.group(1)}]}

    def head_runs(m):
        i, _ = by_sha[m.group(1)]
        return {"total_count": 1, "workflow_runs": [{"id": 700 + i, "name": "CI", "path": wf_path,
                                                     "check_suite_id": 500 + i, "head_sha": m.group(1),
                                                     "head_repo": REPO, "event": "pull_request"}]}

    def jobs(m):
        rid = int(m.group(1))
        if rid == 900:
            return {"total_count": 1, "jobs": [{"id": 9000, "name": "test", "status": "completed",
                                                "conclusion": base, "started_at": "2026-05-31T12:00:00Z"}]}
        return {"total_count": 1, "jobs": [{"id": 1000 + rid - 700, "name": "test", "status": "completed"}]}

    def base_runs(m):
        return {"total_count": 1, "workflow_runs": [{"id": 900, "name": "CI", "path": wf_path,
                                                     "check_suite_id": 999, "head_sha": "b" * 40,
                                                     "head_repo": REPO, "event": "push",
                                                     "run_started_at": "2026-05-31T12:00:00Z",
                                                     "created_at": "2026-05-31T12:00:00Z"}]}

    def check_run(m):
        cid = int(m.group(1))
        return {"id": cid, "name": "test", "output": {"title": "", "summary": "",
                                                      "text": output_text if cid != 9000 else ""}}

    def annotations(m):
        cid = int(m.group(1))
        if cid == 9000:
            return base_ann or []
        return ann or []

    def commit(m):
        i, c = by_sha[m.group(1)]
        return {"sha": c["sha"], "parents": c["parents"],
                "files": [{"filename": f, "status": "modified", "patch": "@@ -1 +1 @@"} for f in files.get(i, [])]}

    pull = {"number": N, "user_login": "Copilot", "head_sha": cs[-1]["sha"], "head_ref": head_ref,
            "base_ref": "main", "created_at": "2026-06-01T00:30:00Z", "commits": n_commits_pr or len(cs),
            "merged_at": None, "closed_at": None, "title": "t", "body": "b"}
    routes = [
        (rf"repos/{REPO}/pulls/{N}", lambda m: pull),
        (rf"repos/{REPO}/pulls/{N}/commits\?per_page=100", lambda m: cs),
        (rf"repos/{REPO}/issues/{N}/timeline\?per_page=100&page=1", lambda m: [{"event": "head_ref_force_pushed"}]),
        (rf"repos/{REPO}/commits/([0-9a-f]{{40}})/check-runs\?per_page=100&page=1", check_runs),
        (rf"repos/{REPO}/commits/([0-9a-f]{{40}})/status", lambda m: {"state": "pending", "statuses": []}),
        (rf"repos/{REPO}/actions/runs\?head_sha=([0-9a-f]{{40}})&per_page=100", head_runs),
        (rf"repos/{REPO}/actions/runs/(\d+)/jobs\?per_page=100", jobs),
        (rf"repos/{REPO}/actions/runs\?branch=main&created=.*", base_runs),
        (rf"repos/{REPO}/check-runs/(\d+)", check_run),
        (rf"repos/{REPO}/check-runs/(\d+)/annotations\?per_page=100", annotations),
        (rf"repos/{REPO}/git/trees/([0-9a-f]{{40}})\?recursive=1", lambda m: {"truncated": False,
                                                                               "blobs": list(tree)}),
        (rf"repos/{REPO}/commits/([0-9a-f]{{40}})", commit),
    ]
    return Fake(routes), {"repo": REPO, "number": N, "family": family}


FAIL_ANN = [{"path": "src/orders.test.ts", "annotation_level": "failure", "message": "expected 1"}]


# ================================================================ already red at a commit (§1.3, §1.4)

def test_already_red_at_commit_two_of_four_then_green_is_rateable():
    """protects=k(X) is the first commit whose failed X is ALREADY_RED by Count 2's base rule, and a pull request
    whose X turns green later stays rateable; fails_when=only the last head commit is judged (Count 2's limit) or
    k is taken as the first commit with any check; no_claim=real GitHub responses have this shape (see the §0
    probe)."""
    src, pr = build([{}, {}, {"message": "Fix failing tests"}, {}], [None, "failure", "failure", "success"])
    out = P.count_a(src, pr)
    assert [x["k"] for x in out["xs"]] == [2]
    assert out["xs"][0]["end"] == 4
    assert out["result"] in R.RATEABLE_A
    assert out["result"] == R.WASTED
    assert out["xs"][0]["wasted_commits"] == [3, 4]  # 3 by rule (ii), 4 by rule (iv) (change 2: X passes there)
    assert out["force_pushes"] == 1


def test_new_red_on_base_is_not_rateable():
    """protects=a check that passed on the base is not an already-red X; fails_when=any failed check makes the
    pull request rateable; no_claim=the base window is complete."""
    src, pr = build([{}, {}], ["failure", "failure"], base="success")
    out = P.count_a(src, pr)
    assert out["xs"] == [] and out["result"] == R.NOT_RATEABLE


# ================================================================ evidence (§1.5)

def cands(text="", ann=None):
    return R.evidence_candidates(ann or [], {"title": "", "summary": "", "text": text})


def test_evidence_annotation_file():
    """protects=a failure annotation's path is a failure file candidate; fails_when=annotations are ignored;
    no_claim=annotations name the failing file in most repositories."""
    assert cands(ann=FAIL_ANN) == ["src/orders.test.ts"]


def test_evidence_github_annotation_not_a_file():
    """protects=the generic Actions annotation (path .github) is not a failure file; fails_when=the .github rule
    is dropped; no_claim=-."""
    assert cands(ann=[{"path": ".github", "annotation_level": "failure", "message": "Process completed with exit "
                                                                                  "code 1"}]) == []
    assert cands(ann=[{"path": ".github/workflows/ci.yml", "annotation_level": "failure"}]) == []


def test_evidence_runner_path_tsx_not_ts():
    """protects=the runner prefix is stripped and .tsx is not cut to .ts; fails_when=extension order or the
    lookahead changes; no_claim=container (/__w/) paths are captured (they are not)."""
    assert cands("    at render (/home/runner/work/r/r/src/App.tsx:42:7)") == ["src/App.tsx"]


def test_evidence_python_traceback():
    """protects=a quoted Python traceback path is captured; fails_when=the quote prefix is removed; no_claim=-."""
    assert cands('  File "/home/runner/work/r/r/tests/test_a.py", line 3, in test_x') == ["tests/test_a.py"]


def test_evidence_passed_line_excluded():
    """protects=paths on PASS/PASSED or check-mark lines are not failure files; fails_when=the PASS rule is
    dropped; no_claim=-."""
    assert cands("tests/test_b.py::test_x PASSED") == []
    assert cands("PASS src/a.test.ts") == []
    assert cands("\u2713 src/b.test.ts (3 tests)") == []


def test_evidence_package_json_not_js():
    """protects=package.json is not read as package.js; fails_when=the (?![\\w.]) lookahead is dropped;
    no_claim=-."""
    assert cands("see package.json for scripts") == []


def test_evidence_node_modules_excluded():
    """protects=dependency paths are excluded; fails_when=the excluded-dir rule is dropped; no_claim=-."""
    assert cands("at node_modules/x/y.js:1:1") == []


def test_evidence_backtick_path():
    """protects=a backtick-quoted path is captured (gate rev 4 note 6); fails_when=the backtick is removed from
    the prefix class; no_claim=-."""
    assert cands("Type error in `src/a.ts`") == ["src/a.ts"]


def test_evidence_path_not_in_tree_excluded():
    """protects=only paths that exist in the tree at k count; fails_when=the tree filter is skipped;
    no_claim=-."""
    assert R.failure_files(["src/a.ts", "src/gone.ts"], {"src/a.ts"}.__contains__) == ["src/a.ts"]


def test_evidence_pipeline_files_and_none():
    """protects=count_a stores files evidence for X from annotations filtered by the tree, and none when only the
    generic annotation exists; fails_when=evidence is read from the wrong check run; no_claim=-."""
    src, pr = build([{}, {}], ["failure", "failure"], ann=FAIL_ANN)
    out = P.count_a(src, pr)
    assert out["xs"][0]["evidence"]["files"] == ["src/orders.test.ts"] and out["files_evidence"]
    src, pr = build([{}, {}], ["failure", "failure"], ann=[{"path": ".github", "annotation_level": "failure"}])
    out = P.count_a(src, pr)
    assert out["xs"][0]["evidence"]["class"] == "none" and not out["files_evidence"]


# ================================================================ window and merges (§1.7)

def test_commit_after_x_passes_again_not_counted():
    """protects=the window ends at the first commit where X passes, and the agent commit at which X passes is
    rule (iv) (change 2); fails_when=later commits are judged, or (iv) is dropped; no_claim=-."""
    src, pr = build([{}, {}, {}, {"message": "fix failing tests"}],
                    ["failure", "failure", "success", "failure"], files={4: ["src/orders.test.ts"]}, ann=FAIL_ANN)
    out = P.count_a(src, pr)
    x = out["xs"][0]
    assert x["end"] == 3 and x["wasted_commits"] == [3] and out["result"] == R.WASTED
    assert [c["reasons"] for c in x["window"]] == [[], ["iv"]]


def test_merge_commit_touching_failure_file_not_wasted():
    """protects=a commit with 2 parents is never wasted; fails_when=the parents test is dropped; no_claim=-."""
    src, pr = build([{}, {"parents": 2, "message": "Merge branch main"}], ["failure", "failure"],
                    files={2: ["src/orders.test.ts"]}, ann=FAIL_ANN)
    out = P.count_a(src, pr)
    assert out["xs"][0]["wasted_commits"] == [] and out["result"] == R.NO_LATER


def test_window_ends_when_x_becomes_new_red():
    """protects=gate rev 4 note 4: x_window stops at a NEW_RED commit; fails_when=only passes end the window;
    no_claim=-."""
    assert R.x_window(2, {2: "already", 3: "already", 4: "new_red", 5: "already"}, 6) == 4
    assert R.x_window(2, {2: "already", 3: "fail_other"}, 5) == 5


# ================================================================ base evidence (§1.5)

def test_in_base_marks():
    """protects=in-base yes / no / base-unknown (gate rev 3 note 2); fails_when=a two-valued mark is used;
    no_claim=-."""
    assert R.in_base("src/a.ts", ["src/a.ts", "src/b.ts"]) == "yes"
    assert R.in_base("src/c.ts", ["src/a.ts"]) == "no"
    assert R.in_base("src/a.ts", []) == "base-unknown"


def test_in_base_through_pipeline():
    """protects=B(X)'s evidence is read from the base job (job id = check run id) and filtered with the base tree;
    fails_when=the base check run id is lost; no_claim=-."""
    src, pr = build([{}, {}], ["failure", "failure"], ann=FAIL_ANN, base_ann=FAIL_ANN)
    x = P.count_a(src, pr)["xs"][0]
    assert x["in_base"] == {"src/orders.test.ts": "yes"}
    src, pr = build([{}, {}], ["failure", "failure"], ann=FAIL_ANN,
                    base_ann=[{"path": "src/app.ts", "annotation_level": "failure"}])
    assert P.count_a(src, pr)["xs"][0]["in_base"] == {"src/orders.test.ts": "no"}


# ================================================================ agent commits (§1.6)

def test_agent_commits():
    """protects=the per-family agent commit rules; fails_when=a login or trailer rule changes; no_claim=the
    trailer is present on every Claude Code commit (an undercount, reported)."""
    assert R.is_agent_commit("copilot", {"author_login": "Copilot", "message": "x"}, "Copilot", "copilot/x")
    assert not R.is_agent_commit("copilot", {"author_login": "alice", "message": "x"}, "Copilot", "copilot/x")
    assert R.is_agent_commit("claude_code", {"author_login": "bob", "message": "x\n\nCo-authored-by: Claude "
                                                                               "<noreply@anthropic.com>"}, "bob", "b")
    assert R.is_agent_commit("claude_code", {"author_login": "bob", "message": "x\n\nCo-Authored-By: Claude"},
                             "bob", "b")
    assert not R.is_agent_commit("claude_code", {"author_login": "bob", "message": "x"}, "bob", "b")
    assert R.is_agent_commit("codex", {"author_login": "dev", "message": "x"}, "dev", "codex/fix-tests")
    assert not R.is_agent_commit("codex", {"author_login": "dev", "message": "x"}, "dev", "feature/x")
    assert R.is_agent_commit("codex", {"author_login": None, "message": "x"}, "dev", "codex/x")  # probe finding
    assert not R.is_agent_commit("codex", {"author_login": "other", "message": "x"}, "dev", "codex/x")
    assert R.is_agent_commit("devin", {"author_login": "devin-ai-integration[bot]"}, "x", "y")


def test_human_commit_on_copilot_pr_is_not_counted():
    """protects=human commits never count as wasted; fails_when=every commit after k is judged; no_claim=-."""
    src, pr = build([{}, {"author": "alice", "message": "fix failing tests"}], ["failure", "failure"])
    out = P.count_a(src, pr)
    assert out["result"] == R.NO_LATER and out["human_after"] == 1


# ================================================================ wasted (§1.7)

X = {"failure_files": ["src/orders.test.ts"], "workflow_paths": [".github/workflows/ci.yml"]}


def test_wasted_rules():
    """protects=rules (i), (ii), (iii), (iv) and the NEW_RED guard of (ii) (rule (ii) and (iv) as of change 2);
    fails_when=a rule or regex changes; no_claim=a matching commit is truly wasted (the hand read decides)."""
    assert R.wasted_reasons({"message": "wip", "files": ["src/orders.test.ts"]}, X, False) == ["i"]
    assert R.wasted_reasons({"message": "Fix failing tests", "files": []}, X, False) == ["ii"]
    assert R.wasted_reasons({"message": "Make the button blue and add unit tests", "files": ["src/b.ts"]}, X,
                            False) == []
    assert R.wasted_reasons({"message": "fix tests", "files": []}, X, True) == []
    assert R.wasted_reasons({"message": "ci tweak", "files": [".github/workflows/ci.yml"]}, X, False) == ["iii"]
    assert R.wasted_reasons({"message": "wip", "files": []}, X, False, True) == ["iv"]


def test_fix_message_change_2():
    """protects=change 2 of rule (ii): a fix verb and a CI term anywhere in the message, the sample misses it was
    fixed for; fails_when=the verb or term lists shrink or the 30-character gap comes back; no_claim=precision."""
    assert R.fix_message("Fixes `TS2322` compilation error during Docker build.")
    assert R.fix_message("Palette: Fix E2E port mismatch and improve Sidebar UX")
    assert R.fix_message("Hardening Determinism & Fixing Portal Build")
    assert R.fix_message("fix(proto): two rustdoc links\n\nCI runs -D rustdoc::broken_intra_doc_links")
    assert not R.fix_message("feat: add a fixture loader")
    assert not R.fix_message("Bump the build number")
    assert not R.FIX_MSG_RE_V1.search("Fixes `TS2322` compilation error during Docker build.")


def test_wasted_iii_through_pipeline():
    """protects=the workflow file that defines X comes from the head run's path; fails_when=the path is not
    kept in the trim; no_claim=composite actions are covered (they are not)."""
    src, pr = build([{}, {"message": "ci"}], ["failure", "failure"], files={2: [".github/workflows/ci.yml"]})
    out = P.count_a(src, pr)
    assert out["result"] == R.WASTED and out["xs"][0]["window"][0]["reasons"] == ["iii"]


def test_callee_paths():
    """protects=reusable workflows called from the caller file (this repository only); fails_when=the uses
    parser changes; no_claim=-."""
    txt = "jobs:\n  a:\n    uses: ./.github/workflows/test.yml\n  b:\n    uses: o/r/.github/workflows/x.yml@main\n" \
          "  c:\n    uses: other/r/.github/workflows/y.yml@v1\n    steps:\n      - uses: actions/checkout@v4\n"
    assert P.callee_paths(txt, "o/r") == [".github/workflows/test.yml", ".github/workflows/x.yml"]


# ================================================================ results (§1.8, §1.9)

def test_no_agent_commit_after_k():
    """protects=no-later-commit when no agent commit follows k; fails_when=it is merged with not-wasted;
    no_claim=-."""
    src, pr = build([{}, {}], [None, "failure"])
    assert P.count_a(src, pr)["result"] == R.NO_LATER


def test_more_than_250_commits_uncertain():
    """protects=more than 250 commits is uncertain (the commits endpoint stops at 250); fails_when=the cap is
    dropped; no_claim=-."""
    src, pr = build([{}], ["failure"], n_commits_pr=300)
    assert P.count_a(src, pr)["result"] == R.UNCERTAIN


def test_hand_read_r_only_becomes_not_wasted():
    """protects=a wasted pull request with only R-* codes is not-wasted; fails_when=hand codes are ignored;
    no_claim=-."""
    assert R.hand_result(R.WASTED, ["R-product"]) == R.NOT_WASTED
    assert R.hand_result(R.WASTED, ["R-product", "W-file"]) == R.WASTED
    assert R.hand_result(R.WASTED, ["R-sync", "R-own"]) == R.NOT_WASTED


# ================================================================ validity and decisions

def test_validity():
    """protects=low files evidence turns a sub-20% Rate A into NOT ENOUGH DATA; fails_when=the 40% rule changes;
    no_claim=-."""
    assert R.decide_a(15, 100, 0.30) == R.NED
    assert R.decide_a(25, 100, 0.30) == R.CONTINUE
    assert R.decide_a(15, 100, 0.60) == R.DROP


def test_decision_a_boundaries():
    """protects=the 20% line on the point estimate (19/95 = 20.0%); fails_when=float rounding or > instead of >=;
    no_claim=-."""
    assert R.decide_a(19, 95, 0.5) == R.CONTINUE
    assert R.decide_a(18, 95, 0.5) == R.DROP


def test_decision_a_miss_adjusted():
    """protects=gate rev 4 note 1: 1-3 sample misses that lift the adjusted rate to 20% give NOT ENOUGH DATA;
    fails_when=misses are ignored; no_claim=-."""
    assert R.decide_a(15, 100, 0.6, misses=3, sample_n=30, not_wasted=60) == R.NED  # 15 + 6 = 21%
    assert R.decide_a(15, 100, 0.6, misses=1, sample_n=30, not_wasted=60) == R.DROP  # 15 + 2 = 17%


def test_decision_b():
    """protects=the 5% line and the 200 agent-addressed minimum; fails_when=either changes; no_claim=-."""
    assert R.decide_b(50, 199) == R.NED
    assert R.decide_b(10, 200) == R.CONTINUE
    assert R.decide_b(9, 200) == R.DROP


# ================================================================ links (§2.2)

def test_links():
    """protects=one link test (closing keyword for this issue in this repository, or the issue number as a head
    ref token); fails_when=a mention without either links, or another repository's reference links;
    no_claim=GitHub records every link (only links it records are seen)."""
    assert not R.closes("see #12 for context", REPO, 12)
    assert not R.ref_names_issue("copilot/improve-docs", 12)
    assert R.ref_names_issue("copilot/fix-12", 12)
    assert not R.ref_names_issue("copilot/fix-123", 12)
    assert not R.closes("Fixes https://github.com/other/repo/issues/12", REPO, 12)
    assert R.closes("Fixes https://github.com/o/r/issues/12", REPO, 12)
    assert R.closes("Fixes #12", REPO, 12)
    assert R.closes("fixes: O/R#12", REPO, 12)
    assert not R.closes("fixes #123", REPO, 12)
    assert R.closes("Closes #3, fixes #12", REPO, 12)


def test_cross_reference_from_other_repo_ignored():
    """protects=only cross-references from this repository count; fails_when=the repository test is dropped;
    no_claim=-."""
    assert not R.same_repo_pr_xref({"is_pr": True, "repo": "other/r"}, REPO)
    assert R.same_repo_pr_xref({"is_pr": True, "repo": "O/r"}, REPO)
    assert not R.same_repo_pr_xref({"is_pr": False, "repo": REPO}, REPO)


def tl_fake(xrefs, pulls):
    routes = [
        (rf"repos/{REPO}/issues/12/timeline\?per_page=100&page=1", lambda m: xrefs),
        (rf"repos/{REPO}/pulls/(\d+)", lambda m: pulls[int(m.group(1))]),
        (rf"repos/{REPO}/pulls/(\d+)/files\?per_page=20", lambda m: [{"filename": "a.py"}]),
        (rf"repos/{REPO}/pulls/(\d+)/reviews\?per_page=100", lambda m: []),
        (rf"repos/{REPO}/commits/([0-9a-f]{{40}})/check-runs\?per_page=100&page=1",
         lambda m: {"check_runs": []}),
        (rf"repos/{REPO}/commits/([0-9a-f]{{40}})/status", lambda m: {"state": "pending", "statuses": []}),
    ]
    return Fake(routes)


def xref(m, login, body, created, closed=None, merged=None, repo=REPO):
    return {"event": "cross-referenced", "is_pr": True, "number": m, "repo": repo, "user_login": login,
            "title": f"pr {m}", "body": body, "created_at": created, "closed_at": closed, "merged_at": merged}


def pull(m, ref):
    return {"number": m, "head_ref": ref, "head_sha": sha(m), "user_login": "Copilot"}


def test_issue_linking_through_timeline():
    """protects=_issue links an agent pull request by head ref token and ignores mentions and other
    repositories; fails_when=the link rule differs between numerator and denominator; no_claim=-."""
    xs = [xref(20, "Copilot", "Working on it", "2026-09-01T00:00:00Z"),
          xref(21, "Copilot", "mentions #12", "2026-09-02T00:00:00Z"),
          xref(22, "Copilot", "Fixes #12", "2026-09-03T00:00:00Z", repo="other/r")]
    src = tl_fake(xs, {20: pull(20, "copilot/fix-12"), 21: pull(21, "copilot/fix-123")})
    out = P._issue(src, REPO, {"number": 12, "title": "t", "body": "b", "closed_at": "2026-09-05T00:00:00Z"})
    assert [p["number"] for p in out["agent_prs"]] == [20] and out["class"] == R.SINGLE


# ================================================================ race (§2.4)

def P_(n, created, merged=None, closed=None):
    return {"number": n, "created_at": created, "merged_at": merged, "closed_at": closed}


def test_race_classes():
    """protects=competing = overlapping open intervals (symmetric), sequential = no overlap; fails_when=the overlap
    test changes or is order-dependent; no_claim=overlap means the two agents raced on purpose (the hand read
    reports that)."""
    a = P_(1, "2026-09-01T00:00:00Z", closed="2026-09-05T00:00:00Z")
    b = P_(2, "2026-09-03T00:00:00Z")
    c = P_(3, "2026-09-06T00:00:00Z", merged="2026-09-07T00:00:00Z")
    assert R.issue_class([a, b]) == R.COMPETING
    assert R.issue_class([b, a]) == R.COMPETING
    assert R.overlap(a, b) == R.overlap(b, a)
    assert R.issue_class([a, c]) == R.SEQUENTIAL
    assert R.issue_class([a]) == R.SINGLE
    assert R.issue_class([]) is None


def test_competing_through_timeline_and_labels():
    """protects=two linked overlapping agent pull requests make the issue competing and get choice labels;
    fails_when=_issue drops the second link; no_claim=-."""
    xs = [xref(20, "Copilot", "Fixes #12", "2026-09-01T00:00:00Z", closed="2026-09-04T00:00:00Z",
               merged="2026-09-04T00:00:00Z"),
          xref(21, "devin-ai-integration[bot]", "fixes: o/r#12", "2026-09-02T00:00:00Z",
               closed="2026-09-05T00:00:00Z")]
    src = tl_fake(xs, {20: pull(20, "copilot/x"), 21: pull(21, "devin/x")})
    out = P._issue(src, REPO, {"number": 12, "title": "t", "body": "b", "closed_at": "2026-09-05T00:00:00Z"})
    assert out["class"] == R.COMPETING and "first-opened" in out["labels"]


def test_choice_labels():
    """protects=the descriptive labels (first-green accepts skipped/neutral, gate rev 3 note 8); fails_when=a
    label rule changes; no_claim=-."""
    assert R.green_time([{"status": "completed", "conclusion": "skipped", "completed_at": "2026-09-01T00:00:00Z"},
                         {"status": "completed", "conclusion": "success", "completed_at": "2026-09-01T01:00:00Z"}]) \
        == R.ts("2026-09-01T01:00:00Z")
    assert R.green_time([{"status": "completed", "conclusion": "cancelled", "completed_at": "x"}]) is None
    prs = [dict(P_(1, "2026-09-01T00:00:00Z", merged="2026-09-03T00:00:00Z"), green="2026-09-02T00:00:00Z",
                approved=True),
           dict(P_(2, "2026-09-02T00:00:00Z"), green=None, approved=False)]
    assert R.choice_labels(prs) == ["first-opened", "first-green", "only-green", "reviewed"]
    assert R.choice_labels([dict(P_(1, "2026-09-01T00:00:00Z"), green=None)]) == ["none-merged"]


def test_pr_family():
    """protects=Count 2's family markers on pull requests (Codex needs the codex/ head ref too); fails_when=a
    marker changes; no_claim=-."""
    f = R.body_flags
    assert R.pr_family("Copilot", "x", f("")) == "copilot"
    assert R.pr_family("dev", "codex/x", f("https://chatgpt.com/codex/tasks/1")) == "codex"
    assert R.pr_family("dev", "feat/x", f("https://chatgpt.com/codex/tasks/1")) is None
    assert R.pr_family("dev", None, f("Generated with [Claude Code](https://claude.com/claude-code)")) \
        == "claude_code"


# ================================================================ order (§2)

def test_seeded_order_seed_2():
    """protects=Count B's repository order is reproducible and has no repeats; fails_when=the seed, the pool shape
    or the sort changes; no_claim=-."""
    a, b = J.b_order(), J.b_order()
    assert a == b and len(a) == len(set(a)) == 1171
    assert seeded_order({"all": [{"url": "x"}, {"url": "y"}]}, seed=2) == \
        seeded_order({"all": [{"url": "y"}, {"url": "x"}]}, seed=2)


# ================================================================ trim keeps what replay needs

def test_trim_keeps_fields():
    """protects=gate rev 3 note 4: the trim keeps author login, head ref, body, commit parents and messages, run
    path and check-run output; fails_when=a needed field is dropped (verify.py could not replay); no_claim=-."""
    pull = P.trim("repos/o/r/pulls/7", {"number": 7, "user": {"login": "Copilot"}, "body": "b", "commits": 3,
                                        "head": {"sha": "s", "ref": "copilot/x"}, "base": {"ref": "main"}})
    assert (pull["user_login"], pull["head_ref"], pull["body"], pull["commits"]) == ("Copilot", "copilot/x", "b", 3)
    c = P.trim("repos/o/r/pulls/7/commits?per_page=100", [{"sha": "a", "author": {"login": "x"}, "parents": [
        {"sha": "p1"}, {"sha": "p2"}], "commit": {"message": "m", "committer": {"date": "d"}}}])
    assert c == [{"sha": "a", "author_login": "x", "author_name": None, "message": "m", "date": "d", "parents": ["p1", "p2"]}]
    r = P.trim("repos/o/r/actions/runs?head_sha=a&per_page=100", {"workflow_runs": [{"id": 1, "path": "p"}]})
    assert r["workflow_runs"][0]["path"] == "p"
    cr = P.trim("repos/o/r/check-runs/5", {"id": 5, "name": "n", "output": {"title": "t", "text": "x"}})
    assert cr["output"]["text"] == "x"
    st = P.trim("repos/o/r/contents/src/status?ref=a", {"type": "file", "path": "src/status"})
    assert st == {"type": "file", "path": "src/status"}


def test_live_source_is_get_only():
    """protects=acceptance criterion 5: the live source builds GET requests only and never calls a search
    endpoint; fails_when=a method or data argument is added; no_claim=-."""
    import inspect
    src = inspect.getsource(P)
    assert "method=" not in src and "data=" not in src
    assert "search/" not in src and "search/" not in inspect.getsource(J)


def test_reconstructed_chunk_line_checked_against_raw(tmp_path, monkeypatch):
    """protects=a chunk summary line written after a cancelled run (``reconstructed``) is re-derived from that
    chunk's raw file by verify.py (items, requests, first and last item); fails_when=check_chunks skips
    reconstructed lines or compares other fields; no_claim=the requests of a repository cancelled mid-read are
    known (they are not in the raw file)."""
    import gzip
    import json
    import verify as V
    (tmp_path / "results" / "raw").mkdir(parents=True)
    with gzip.open(tmp_path / "results" / "raw" / "b_4.jsonl.gz", "wt") as f:
        for item, n in (("o/a", 3), ("o/b", 4)):
            f.write(json.dumps({"item": item, "requests": n}) + "\n")
    line = {"chunk": "4", "part": "B", "first": "o/a", "last": "o/b", "items_done": 2, "requests": 7,
            "reconstructed": "test"}
    monkeypatch.setattr(V, "HERE", tmp_path)
    monkeypatch.setattr(V, "errors", [])
    (tmp_path / "results" / "chunks.jsonl").write_text(json.dumps(line) + "\n")
    V.check_chunks()
    assert V.errors == []
    (tmp_path / "results" / "chunks.jsonl").write_text(json.dumps(dict(line, requests=8)) + "\n")
    V.check_chunks()
    assert len(V.errors) == 1
