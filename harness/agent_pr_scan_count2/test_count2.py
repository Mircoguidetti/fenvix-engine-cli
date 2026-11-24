"""Count 2 tests. Run: python3 -m pytest -q harness/agent_pr_scan_count2/test_count2.py

Each test states its card: protects=<observable>; fails_when=<wrong result>; no_claim=<what green does not prove>.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pipeline  # noqa: E402
import rules as R  # noqa: E402

REPO = "o/r"
SHA = "h" * 40
CREATED = "2026-06-10T12:00:00Z"
S = "2026-06-10T12:05:00Z"  # head check started


class FixtureSource:
    """Answers pipeline requests by endpoint pattern from small fixture tables (independent of exact query text)."""

    def __init__(self, head_runs=(), statuses=(), head_wf=(), jobs=None, base_runs=(), commits=(), commit_checks=None,
                 errors=(), pr_commits=()):
        self.head_runs, self.statuses, self.head_wf = list(head_runs), list(statuses), list(head_wf)
        self.jobs, self.base_runs, self.commits = jobs or {}, list(base_runs), list(commits)
        self.commit_checks, self.errors, self.seen = commit_checks or {}, set(errors), []
        self.pr_commits = list(pr_commits)

    def has(self, path):
        return path in self.seen

    def get(self, path):
        self.seen.append(path)
        p, _, q = path.partition("?")
        qs = dict(urllib.parse.parse_qsl(q))
        for e in self.errors:
            if re.search(e, path):
                return 404, '{"message":"Not Found"}'
        if p.endswith("/pulls/1"):
            return 200, {"head_sha": SHA, "base_ref": "main", "created_at": CREATED, "merged_at": None,
                         "closed_at": "2026-06-11T00:00:00Z"}
        if p.endswith("/pulls/1/commits"):
            return 200, self.pr_commits
        m = re.search(r"/commits/(\w+)/check-runs$", p)
        if m:
            runs = self.head_runs if m.group(1) == SHA else self.commit_checks.get(m.group(1), {}).get("runs", [])
            return 200, {"total_count": len(runs), "check_runs": runs}
        m = re.search(r"/commits/(\w+)/status$", p)
        if m:
            st = self.statuses if m.group(1) == SHA else self.commit_checks.get(m.group(1), {}).get("statuses", [])
            return 200, {"state": "x", "statuses": st}
        if p.endswith("/actions/runs") and "head_sha" in qs:
            return 200, {"total_count": len(self.head_wf), "workflow_runs": self.head_wf}
        if p.endswith("/actions/runs"):
            return 200, {"total_count": len(self.base_runs), "workflow_runs": self.base_runs}
        m = re.search(r"/actions/runs/(\d+)/jobs$", p)
        if m:
            js = self.jobs.get(int(m.group(1)), [])
            return 200, {"total_count": len(js), "jobs": js}
        if p.endswith("/commits"):
            return 200, self.commits
        raise AssertionError(f"unexpected request {path}")


def crun(id_, name, concl, started=S, app="github-actions", suite=900):
    return {"id": id_, "name": name, "status": "completed", "conclusion": concl, "started_at": started,
            "completed_at": started, "app": app, "check_suite_id": suite, "head_sha": SHA}


def wf(id_, name, started, concl="failure", suite=None, repo=REPO):
    return {"id": id_, "name": name, "workflow_id": 1, "check_suite_id": suite, "event": "push", "head_sha": "b",
            "head_branch": "main", "head_repo": repo, "status": "completed", "conclusion": concl,
            "created_at": started, "run_started_at": started, "run_attempt": 1}


def job(id_, name, concl, started):
    return {"id": id_, "name": name, "run_id": 0, "status": "completed", "conclusion": concl, "started_at": started,
            "completed_at": started, "head_sha": "b"}


def actions_fixture(base):
    """Head: workflow CI, job 'test' failed at S. base: list of (run_id, started, job conclusion)."""
    jobs = {500: [job(77, "test", "failure", S)]}
    runs = []
    for rid, started, concl in base:
        runs.append(wf(rid, "CI", started, concl))
        jobs[rid] = [job(rid * 10, "test", concl, started)]
    return FixtureSource(head_runs=[crun(77, "test", "failure")], head_wf=[wf(500, "CI", S, suite=900)], jobs=jobs,
                         base_runs=runs)


def run(src):
    return pipeline.run_pr(src, {"repo": REPO, "number": 1})


def test_primary_most_recent_failed_is_already_red():
    """protects=PR verdict ALREADY_RED when the newest base run of the identity before S failed;
    fails_when=a failed base run just before the head check gives NEW_RED or NO_BASE_SIGNAL;
    no_claim=that GitHub returns base runs in this shape."""
    out = run(actions_fixture([(1, "2026-06-09T10:00:00Z", "success"), (2, "2026-06-10T09:00:00Z", "failure")]))
    assert out["verdict"] == R.ALREADY_RED
    assert out["failed_checks"][0]["base"]["run_id"] == 2


def test_primary_recent_success_beats_older_failure():
    """protects=NEW_RED when the newest base run before S succeeded although an older one failed;
    fails_when=any failed base run in the window makes the PR ALREADY_RED;
    no_claim=the secondary rule (tested separately)."""
    out = run(actions_fixture([(1, "2026-06-08T10:00:00Z", "failure"), (2, "2026-06-10T09:00:00Z", "success")]))
    assert out["verdict"] == R.NEW_RED
    assert out["failed_checks"][0]["base"]["run_id"] == 2


def test_primary_ignores_base_run_after_head_start():
    """protects=a base run started at or after S is never the chosen base run;
    fails_when=a later failed base run turns a NEW_RED PR into ALREADY_RED;
    no_claim=correct ordering when run_started_at is missing (falls back to created_at)."""
    out = run(actions_fixture([(1, "2026-06-10T09:00:00Z", "success"), (2, "2026-06-10T12:30:00Z", "failure")]))
    assert out["verdict"] == R.NEW_RED
    assert out["failed_checks"][0]["base"]["run_id"] == 1


def test_primary_no_base_run_of_identity_is_no_base_signal():
    """protects=NO_BASE_SIGNAL when no base run of the identity exists in the 7-day window (other workflow, too old);
    fails_when=a run of another workflow, or one older than 7 days, is used as the base;
    no_claim=that the workflow really never runs on the base branch."""
    src = actions_fixture([(1, "2026-06-01T10:00:00Z", "failure")])
    src.base_runs.append(wf(3, "Lint", "2026-06-10T10:00:00Z", "failure"))
    src.jobs[3] = [job(30, "test", "failure", "2026-06-10T10:00:00Z")]
    out = run(src)
    assert out["verdict"] == R.NO_BASE_SIGNAL


def test_primary_api_error_is_unreadable():
    """protects=UNREADABLE with its reason when a needed base request fails (404 / Actions disabled);
    fails_when=an API error is silently counted as NO_BASE_SIGNAL or NEW_RED;
    no_claim=which HTTP codes GitHub returns for disabled Actions."""
    src = actions_fixture([(1, "2026-06-10T09:00:00Z", "failure")])
    src.errors.add(r"actions/runs\?branch=")
    out = run(src)
    assert out["verdict"] == R.UNREADABLE
    assert "404" in out["failed_checks"][0]["reason"]


def test_identity_head_and_base_match():
    """protects=head and base identities are both '<workflow name> / <job name>' and match on the same fixture;
    fails_when=the head identity uses the check name alone or the base uses a different workflow's job;
    no_claim=that two workflows never share a name in a real repository."""
    out = run(actions_fixture([(2, "2026-06-10T09:00:00Z", "failure")]))
    f = out["failed_checks"][0]
    assert f["identity"] == "CI / test" == R.actions_identity("CI", "test")
    assert f["job_confirmed"] is True


@pytest.mark.parametrize("concl,failed", [("failure", True), ("timed_out", True), ("startup_failure", True),
                                          ("cancelled", False), ("skipped", False), ("neutral", False),
                                          ("stale", False), ("action_required", False), ("success", False)])
def test_failure_states_check_runs(concl, failed):
    """protects=which check-run conclusions put a PR in the failed-check denominator;
    fails_when=cancelled/skipped/neutral/stale/action_required count as failed or timed_out/startup_failure do not;
    no_claim=the conclusions GitHub actually emits."""
    src = FixtureSource(head_runs=[crun(1, "x", concl, app="ci-app")], commits=[])
    out = run(src)
    assert (out["verdict"] != R.NO_FAILED_CHECK) is failed


@pytest.mark.parametrize("state,failed", [("failure", True), ("error", True), ("success", False), ("pending", False)])
def test_failure_states_statuses(state, failed):
    """protects=legacy status states failure/error count as failed and success/pending do not, and a failed status
    is judged against the base commit's status of the same context;
    fails_when=error is ignored, pending counts, or the status context is not the identity;
    no_claim=status timestamps equal job start times."""
    base = {"c1": {"runs": [], "statuses": [{"context": "ci/x", "state": "failure",
                                             "created_at": "2026-06-10T08:00:00Z", "updated_at": None}]}}
    src = FixtureSource(statuses=[{"context": "ci/x", "state": state, "created_at": S, "updated_at": S}],
                        commits=[{"sha": "c1", "date": "2026-06-10T08:00:00Z"}], commit_checks=base)
    out = run(src)
    assert (out["verdict"] != R.NO_FAILED_CHECK) is failed
    if failed:
        assert out["verdict"] == R.ALREADY_RED and out["failed_checks"][0]["identity"] == "ci/x"


def test_pr_own_commits_are_not_base_evidence():
    """protects=when the PR's head commit is in the base branch listing (merged later with a merge commit or
    fast-forward), the PR's own earlier commits are skipped by the base commit walk and only real base commits judge
    the status (change after the pre-registration, found by the hand check);
    fails_when=a failed status on the PR's own earlier commit makes the PR ALREADY_RED, or pulls/{n}/commits is read
    although the head commit is not in the listing;
    no_claim=a PR with more than 100 commits is fully excluded (one page is read)."""
    fail = {"context": "ci/x", "state": "failure"}
    head = [dict(fail, created_at=S, updated_at=S)]
    checks = {"p1": {"runs": [], "statuses": [dict(fail, created_at="2026-06-10T11:00:00Z", updated_at=None)]},
              "c1": {"runs": [], "statuses": [{"context": "ci/x", "state": "success",
                                               "created_at": "2026-06-10T08:00:00Z", "updated_at": None}]}}
    listing = [{"sha": SHA, "date": S}, {"sha": "p1", "date": "2026-06-10T11:00:00Z"},
               {"sha": "c1", "date": "2026-06-10T08:00:00Z"}]
    src = FixtureSource(statuses=head, commits=listing, commit_checks=checks,
                        pr_commits=[{"sha": "p1", "date": None}, {"sha": SHA, "date": None}])
    out = run(src)
    assert out["verdict"] == R.NEW_RED and out["failed_checks"][0]["base"]["commit"] == "c1"
    assert out["base_commits_own_excluded"] == 2
    src = FixtureSource(statuses=head, commits=listing[1:], commit_checks=checks)
    out = run(src)
    assert out["verdict"] == R.ALREADY_RED and not any(x.endswith("/pulls/1/commits?per_page=100") for x in src.seen)


def test_secondary_rule_on_same_fixtures():
    """protects=secondary 'already red' = any failed base run of the identity in [created-7d, created), while the
    primary stays NEW_RED when the newest run succeeded;
    fails_when=secondary ignores older failures, or counts runs after the PR was opened;
    no_claim=the secondary's cost caps (at most 10 job reads) never hide a failure."""
    out = run(actions_fixture([(1, "2026-06-08T10:00:00Z", "failure"), (2, "2026-06-10T09:00:00Z", "success")]))
    assert out["verdict"] == R.NEW_RED and out["secondary_already_red"] is True
    out = run(actions_fixture([(2, "2026-06-10T09:00:00Z", "success"), (3, "2026-06-10T12:01:00Z", "failure")]))
    assert out["secondary_already_red"] is False


def _verify(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "verify_count2.py")], capture_output=True, text=True)


def _committed() -> bool:
    return (HERE / "REPORT.md").exists() and (HERE / "results" / "rows.jsonl").exists()


@pytest.mark.skipif(not _committed(), reason="no committed results yet")
def test_verify_passes_on_committed_rows():
    """protects=every number in REPORT.md, every verdict and the decision sentence re-derive from committed rows;
    fails_when=verify_count2.py exits non-zero on the committed results;
    no_claim=that the raw JSON itself is what GitHub returned (only that the report follows from it)."""
    r = _verify(HERE)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(not _committed(), reason="no committed results yet")
def test_verify_fails_on_altered_number_verdict_or_sentence(tmp_path):
    """protects=verify_count2.py detects one altered number, one altered verdict, one altered decision sentence;
    fails_when=any of the three alterations still exits 0;
    no_claim=detection of alterations made consistently in both raw JSON and rows."""
    import json
    keys = ["n_rateable", "already_red"]
    for kind in ("number", "verdict", "sentence"):
        root = tmp_path / kind
        shutil.copytree(HERE, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        shutil.copytree(HERE.parent / "agent_pr_scan", tmp_path / "agent_pr_scan", dirs_exist_ok=True)
        rep = root / "REPORT.md"
        txt = rep.read_text()
        if kind == "number":
            m = re.search(r"(\d+)<!--(" + "|".join(keys) + r")-->", txt)
            txt = txt[:m.start(1)] + str(int(m.group(1)) + 1) + txt[m.end(1):]
            rep.write_text(txt)
        elif kind == "sentence":
            for a, b in ((R.SENT_INVALID, R.SENT_PARKED), (R.SENT_PARKED, R.SENT_FORWARD),
                         (R.SENT_FORWARD, R.SENT_PARKED)):
                if a in txt:
                    rep.write_text(txt.replace(a, b))
                    break
        else:
            rows = [json.loads(x) for x in (root / "results" / "rows.jsonl").read_text().splitlines()]
            for r in rows:
                if r["verdict"] in R.RATEABLE:
                    r["verdict"] = R.NEW_RED if r["verdict"] == R.ALREADY_RED else R.ALREADY_RED
                    break
            (root / "results" / "rows.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                                                                 for r in rows))
        res = _verify(root)
        assert res.returncode == 1, f"{kind}: {res.stdout}{res.stderr}"
