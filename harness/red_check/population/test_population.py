"""C5.3 rule, collection and selection tests (offline). Run: python3 -m pytest -q harness/red_check/population/

Each test states its card: protects=<observable>; fails_when=<wrong result>; no_claim=<what green does not prove>.
"""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect as C  # noqa: E402
import pool as P  # noqa: E402
import rules as R  # noqa: E402
import select_repos as S  # noqa: E402

FIX = HERE / "fixtures"


def fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 2.5 runner detection (acceptance 8)

@pytest.mark.parametrize("name,runner", [("vitest.log", "vitest"), ("jest.log", "jest"),
                                         ("node-test.log", "node-test"), ("pytest.log", "pytest")])
def test_each_runner_fixture_gives_its_runner(name, runner):
    """protects=each runner's default failing summary is recognised in a real-shaped job log; fails_when=a pattern
    misses its runner's summary or another pattern also fires; no_claim=every version or reporter of the runner."""
    got, idx = R.detect_runner(fx(name))
    assert got == runner
    assert idx is not None and R.RUNNERS[runner].search(R.clean_lines(fx(name))[idx])


@pytest.mark.parametrize("name", ["vitest-pass.log", "jest-pass.log", "node-test-pass.log", "pytest-pass.log"])
def test_each_negative_fixture_gives_no_runner(name):
    """protects=a passing summary (count 0 or no 'failed') is not a failing runner; fails_when=a pattern accepts a
    zero count or a passed-only line; no_claim=that logs without a summary are rare."""
    assert R.detect_runner(fx(name)) == (R.NO_RUNNER, None)


def test_two_runners_give_ambiguous():
    """protects=a log matching two patterns is excluded as ambiguous_runner; fails_when=one runner is picked;
    no_claim=how often this happens."""
    assert R.detect_runner(fx("ambiguous.log"))[0] == R.AMBIGUOUS


def test_timestamps_bom_and_ansi_stripped_before_matching():
    """protects=the vitest fixture (BOM, timestamp prefix, ANSI colour codes) only matches after cleaning; fails_when=
    cleaning is skipped or incomplete; no_claim=every escape sequence a terminal can emit."""
    raw = fx("vitest.log")
    assert raw.startswith("\ufeff2026-") and "\x1b[" in raw
    assert not any(R.RUNNERS["vitest"].search(line) for line in raw.splitlines())
    lines = R.clean_lines(raw)
    assert lines[0] == "##[group]Run npx vitest run"
    assert any(line.startswith(" Test Files  1 failed") for line in lines)


def test_excerpt_keeps_summary_line_and_at_most_200_before():
    """protects=the committed excerpt ends at the summary line and holds at most 200 lines before it;
    fails_when=the window is off by one or cut after the line; no_claim=that 200 lines show the failure."""
    text = "\n".join(f"l{i}" for i in range(500)) + "\n"
    ex = R.excerpt(text, 300).splitlines()
    assert ex[0] == "l100" and ex[-1] == "l300" and len(ex) == 201
    assert R.excerpt(text, 5).splitlines()[0] == "l0"


# ---------------------------------------------------------------- 2.6 job matching (acceptance 9)

def wf(text: str) -> dict:
    return yaml.safe_load(text)


def test_expression_name_found_by_b():
    """protects=rule (b): a name with ${{ }} matches its rendered display name; fails_when=the expression is taken
    literally or not anchored; no_claim=every expression GitHub can render."""
    w = wf("jobs:\n  test:\n    name: test (${{ matrix.node }})\n    runs-on: ubuntu-latest\n  lint:\n    runs-on: x\n")
    assert R.match_job(w, "test (18.x)") == (R.FOUND, "test")
    assert R.match_job(w, "xtest (18.x)") == (R.ABSENT, None)


def test_key_without_name_found_by_d():
    """protects=rule (d): an unnamed job is found by its key minus the matrix suffix; fails_when=the suffix is not
    removed; no_claim=matrix suffix formats other than ' (<...>)'."""
    w = wf("jobs:\n  unit:\n    runs-on: x\n    strategy:\n      matrix:\n        node: [18.x, 20.x]\n  e2e:\n    runs-on: x\n")
    assert R.match_job(w, "unit (18.x)") == (R.FOUND, "unit")
    assert R.match_job(w, "unit") == (R.FOUND, "unit")


def test_name_without_expression_found_by_c_and_a():
    """protects=rules (a) and (c); fails_when=an exact or suffixed static name is missed; no_claim=none."""
    w = wf("jobs:\n  t:\n    name: Unit tests\n    runs-on: x\n")
    assert R.match_job(w, "Unit tests") == (R.FOUND, "t")
    assert R.match_job(w, "Unit tests (ubuntu, 20)") == (R.FOUND, "t")


def test_two_matching_jobs_not_found():
    """protects=an ambiguous match is not a match; fails_when=the first of two matching jobs is taken;
    no_claim=none."""
    w = wf("jobs:\n  a:\n    name: test (${{ matrix.x }})\n    runs-on: x\n  test:\n    runs-on: x\n")
    assert R.match_job(w, "test (1)") == (R.ABSENT, None)


def test_reusable_workflow_caller():
    """protects=a 'caller / inner' job whose caller has a job-level uses: is reusable_workflow_job; fails_when=it is
    matched as an ordinary job or missed; no_claim=nested reusable workflows."""
    w = wf("jobs:\n  build:\n    uses: ./.github/workflows/build.yml\n  test:\n    runs-on: x\n")
    assert R.match_job(w, "build / test") == (R.REUSABLE, "build")
    w2 = wf("jobs:\n  b:\n    name: build\n    uses: o/r/.github/workflows/x.yml@v1\n")
    assert R.match_job(w2, "build / unit (18)") == (R.REUSABLE, "b")


def test_features_recorded():
    """protects=the job features C2 and C5.4 need are recorded; fails_when=services, matrix, needs, uses or the
    secrets rule are wrong; no_claim=that features predict whether the job can run on our machines."""
    w = wf("""jobs:
  test:
    runs-on: ubuntu-latest
    needs: build
    container: node:20
    services:
      db: {image: postgres:16}
    strategy: {matrix: {node: [18, 20, 22], os: [ubuntu]}}
    steps:
      - uses: actions/checkout@v4
      - run: npm test
        env: {TOKEN: "${{ secrets.GITHUB_TOKEN }}"}
""")
    f = R.features(w["jobs"]["test"])
    assert f == {"runs_on": "ubuntu-latest", "services": {"db": "postgres:16"}, "matrix": {"node": 3, "os": 1},
                 "container": True, "needs": ["build"], "uses": ["actions/checkout@v4"], "uses_secrets": False}
    w["jobs"]["test"]["steps"][1]["env"]["X"] = "${{ secrets.NPM_TOKEN }}"
    assert R.features(w["jobs"]["test"])["uses_secrets"] is True
    assert R.uses_secrets({"env": {"A": "${{ vars.REGION }}"}}) is True


# ---------------------------------------------------------------- 2.2 / 2.3 / 2.4 rules

def test_windows_cover_60_days_in_9_windows():
    """protects=the window [D-60, D) is cut into 8 windows of 7 days and a last one of 4; fails_when=a day is missed,
    repeated, or D itself included; no_claim=none."""
    w = P.windows(dt.date(2026, 11, 26))
    days = [dt.date.fromisoformat(a) + dt.timedelta(days=i) for a, b in w
            for i in range((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days + 1)]
    assert len(w) == 9 and len(days) == 60 == len(set(days))
    assert days[0] == dt.date(2026, 9, 27) and days[-1] == dt.date(2026, 11, 25)


def test_pool_family_rules_and_dedupe():
    """protects=Count 2's family rules and URL de-duplication; fails_when=a codex PR without the marker stays, or a
    URL found twice gives two rows; no_claim=search completeness."""
    def it(url, body):
        return {"html_url": url, "repository_url": "https://api.github.com/repos/o/r", "number": 1, "body": body,
                "user": {"login": "u"}, "state": "open", "created_at": "2026-11-01T00:00:00Z", "pull_request": {}}
    rows = [P.slim(it("u1", "see chatgpt.com/codex/x"), "codex", "w"), P.slim(it("u2", "no marker"), "codex", "w"),
            P.slim(it("u1", "Generated with [Claude Code](x) chatgpt.com/codex"), "claude_code", "w"),
            P.slim(it("u3", ""), "copilot", "w")]
    pool = P.dedupe(rows)
    assert [(r["url"], r["family"], r["families"]) for r in pool] == [
        ("u1", "codex", ["codex", "claude_code"]), ("u3", "copilot", ["copilot"])]


def test_exclusions_and_order():
    """protects=owner exclusions need no request; metadata exclusions; the 30-day rule; the repository order with
    its tie-break; fails_when=any rule differs from PREREG 2.3-2.4; no_claim=none."""
    assert R.owner_excluded("Microsoft/vscode") and not R.owner_excluded("acme/microsoft")
    assert R.repo_exclusion(404, None) == "repo_unreadable"
    assert R.repo_exclusion(200, {"fork": True}) == "fork"
    assert R.repo_exclusion(200, {"archived": True}) == "archived"
    assert R.repo_exclusion(200, {"fork": False, "archived": False, "private": False}) is None
    assert R.too_young("2026-11-01T00:00:00Z", "2026-11-30T23:00:00Z")
    assert not R.too_young("2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")
    pool = [{"repo": r} for r in ["b/x", "a/y", "a/y", "B/X", "openai/z", "openai/z", "openai/z", "c/w"]]
    assert R.repo_order(pool) == [("a/y", 2), ("b/x", 2), ("c/w", 1)]
    assert R.candidate({"conclusion": "failure", "labels": ["ubuntu-latest"]})
    assert not R.candidate({"conclusion": "failure", "labels": ["windows-2022"]})
    assert not R.candidate({"conclusion": "failure", "labels": ["macos-14"]})
    assert R.candidate({"conclusion": "timed_out", "labels": []})
    assert not R.candidate({"conclusion": "cancelled", "labels": []})


# ---------------------------------------------------------------- read_pr / collect with a fake API

WF = "jobs:\n  test:\n    name: test (${{ matrix.node }})\n    runs-on: ubuntu-latest\n    steps:\n      - run: npm test\n"


class FakeAPI:
    """Answers the collection's requests from tables; counts requests like ghrest.Client."""

    def __init__(self, repos: dict, prs: dict, logs: dict, workflows: dict, remaining=5000):
        self.repos, self.prs, self.logs, self.workflows = repos, prs, logs, workflows
        self.n_requests, self.remaining, self.limit, self.reset = 0, remaining, 5000, 0
        self.paths: list[str] = []

    def low(self, frac=0.2):
        return self.remaining < frac * self.limit

    def get_json(self, path: str):
        self.n_requests += 1
        self.paths.append(path)
        parts = path.split("?")[0].split("/")
        repo = f"{parts[1]}/{parts[2]}"
        if len(parts) == 3:
            return (200, self.repos[repo]) if repo in self.repos else (404, "Not Found")
        kind = parts[3]
        if kind == "pulls":
            n = int(parts[4])
            p = self.prs[(repo, n)]
            return 200, {"head": {"sha": p["head"]}, "base": {"sha": "base" + p["head"], "ref": "main"},
                         "created_at": p["created_at"], "state": "open", "merged_at": None}
        if kind == "actions" and parts[4] == "runs" and len(parts) == 5:
            sha = path.split("head_sha=")[1].split("&")[0]
            p = next(p for p in self.prs.values() if p["head"] == sha)
            return 200, {"workflow_runs": [{"id": 10, "path": ".github/workflows/ci.yml", "conclusion": "failure",
                                            "name": "CI", "event": "pull_request"}] if p["jobs"] else []}
        if kind == "actions" and parts[4] == "runs":
            run = int(parts[5])
            jobs = next(p["jobs"] for p in self.prs.values() if p["jobs"] and run == 10 and p["head"] in self._cur)
            return 200, {"jobs": jobs}
        if kind == "compare":
            return 200, {"merge_base_commit": {"sha": "b0" + parts[4].split("...")[1]}}
        if kind == "contents":
            ref = path.split("ref=")[1]
            text = self.workflows.get(ref, WF)
            if text is None:
                return 404, "Not Found"
            return 200, {"content": base64.b64encode(text.encode()).decode(), "encoding": "base64"}
        raise AssertionError(path)

    _cur: set = set()

    def get_log(self, repo, job_id):
        self.n_requests += 2
        body = self.logs.get(job_id)
        if body is None:
            self.n_requests -= 1
            return {"api_status": 410, "blob_status": None, "body": None, "error": "gone"}
        return {"api_status": 302, "blob_status": 200, "body": body.encode(), "error": None}


def _job(i, name="test (18.x)", labels=("ubuntu-latest",), conclusion="failure"):
    return {"id": i, "name": name, "run_id": 10, "labels": list(labels), "conclusion": conclusion}


def test_read_pr_qualifies_and_records_features():
    """protects=2.4 steps 1-6 end to end on one PR: candidates filtered (windows job dropped), at most 3 logs, the
    lowest single-runner job qualifies, B0 from compare, the job found at B0, features recorded; fails_when=any
    step is skipped or a later job is chosen; no_claim=GitHub's real API shapes beyond the fields used."""
    api = FakeAPI({}, {("o/r", 1): {"head": "h1", "created_at": "2026-11-10T00:00:00Z",
                                    "jobs": [_job(5, labels=["windows-latest"]), _job(7), _job(6), _job(8), _job(9)]}},
                  {6: fx("vitest-pass.log"), 7: fx("jest.log"), 8: fx("pytest.log"), 9: fx("vitest.log")}, {})
    api._cur = {"h1"}
    kept = []
    row = C.read_pr(api, {"url": "u", "repo": "o/r", "number": 1, "family": "copilot", "families": ["copilot"],
                          "created_at": "2026-11-10T00:00:00Z"}, lambda *a: kept.append(a[0]))
    assert row["verdict"] == "qualifying"
    assert [c["id"] for c in row["candidates"]] == [6, 7, 8]
    assert [c["runner"] for c in row["candidates"]] == ["no_runner", "jest", "pytest"]
    assert (row["job_id"], row["runner"], row["B0"], row["job_key"]) == (7, "jest", "b0h1", "test")
    assert row["features"]["runs_on"] == "ubuntu-latest" and row["differs_at_head"] is False
    assert kept == [6, 7, 8]


def test_read_pr_job_absent_at_base_and_no_runner():
    """protects=a workflow missing at B0 gives job_absent_at_base, and logs without a single runner give
    no_single_runner; fails_when=either becomes qualifying; no_claim=none."""
    api = FakeAPI({}, {("o/r", 1): {"head": "h1", "created_at": "2026-11-10T00:00:00Z", "jobs": [_job(7)]},
                       ("o/r", 2): {"head": "h2", "created_at": "2026-11-10T00:00:00Z", "jobs": [_job(8)]}},
                  {7: fx("jest.log"), 8: fx("ambiguous.log")}, {"b0h1": None})
    api._cur = {"h1"}
    pr = {"url": "u", "repo": "o/r", "number": 1, "family": "codex", "created_at": "2026-11-10T00:00:00Z"}
    assert C.read_pr(api, pr)["verdict"] == "job_absent_at_base"
    api._cur = {"h2"}
    assert C.read_pr(api, {**pr, "number": 2})["verdict"] == "no_single_runner"


def _pool(repo, n, created="2026-11-10T00:00:00Z"):
    return [{"url": f"https://github.com/{repo}/pull/{i}", "repo": repo, "number": i, "family": "copilot",
             "families": ["copilot"], "created_at": created} for i in range(1, n + 1)]


def test_collect_order_lazy_metadata_caps_and_resume():
    """protects=repositories in 2.4's order, metadata read lazily and counted, a fork skipped, too-young PRs recorded
    without requests, at most 40 PRs per repository, the chunk stops on a low rate limit and resumes from the
    checkpoint without re-reading a PR; fails_when=any of these differs; no_claim=the live budget."""
    pool = _pool("big/one", 45) + _pool("fork/two", 50) + _pool("young/three", 2) + _pool("openai/x", 99)
    prs = {(p["repo"], p["number"]): {"head": f"{p['repo']}#{p['number']}", "created_at": p["created_at"], "jobs": []}
           for p in pool}
    repos = {"big/one": {"fork": False, "archived": False, "private": False, "created_at": "2020-01-01T00:00:00Z"},
             "fork/two": {"fork": True, "created_at": "2020-01-01T00:00:00Z"},
             "young/three": {"fork": False, "archived": False, "private": False, "created_at": "2026-11-01T00:00:00Z"}}
    api = FakeAPI(repos, prs, {}, {})
    state = C.new_state(pool)
    assert [r for r, _ in state["order"]] == ["fork/two", "big/one", "young/three"]
    rows = []
    calls = [0]

    def emit(r):
        rows.append(r)
        calls[0] += 1
        if calls[0] == 10:
            api.remaining = 100  # below 20%: the chunk stops before the next PR
    why = C.collect(api, state, pool, emit)
    assert why.startswith("rate limit low") and state["stopped"] is None and len(rows) == 10
    api.remaining = 5000
    why = C.collect(api, state, pool, rows.append)
    assert why == "repository order exhausted"
    read = [r for r in rows if r["verdict"] != "repo_too_young"]
    assert len(read) == 40 and len({r["url"] for r in read}) == 40 and {r["repo"] for r in read} == {"big/one"}
    assert [r["number"] for r in rows if r["verdict"] == "repo_too_young"] == [2, 1]
    assert state["repos"]["fork/two"] == {"name": "fork/two", "status": "excluded", "reason": "fork", "read": 0,
                                          "done_urls": []}
    assert state["repos_read"] == 1
    assert [p for p in api.paths if p.count("/") == 2] == ["repos/fork/two", "repos/big/one", "repos/young/three"]
    assert state["requests"] == api.n_requests == 3 + 40 * 2


def test_collect_request_cap_and_30_repositories(monkeypatch):
    """protects=the final stops of 2.4 (30 repositories read; 10,000 requests) are checked before each PR and stored
    as the stop reason; fails_when=reading goes on past either; no_claim=none."""
    pool = [p for i in range(35) for p in _pool(f"r{i:02d}/x", 1)]
    prs = {(p["repo"], p["number"]): {"head": p["repo"], "created_at": p["created_at"], "jobs": []} for p in pool}
    repos = {p["repo"]: {"fork": False, "archived": False, "private": False, "created_at": "2020-01-01T00:00:00Z"}
             for p in pool}
    api = FakeAPI(repos, prs, {}, {})
    state = C.new_state(pool)
    rows = []
    assert C.collect(api, state, pool, rows.append) == "30 repositories read"
    assert state["repos_read"] == 30 and len(rows) == 30
    monkeypatch.setattr(C, "MAX_REQUESTS", 9)
    state2 = C.new_state(pool)
    rows2 = []
    assert C.collect(FakeAPI(repos, prs, {}, {}), state2, pool, rows2.append) == "9 requests made"
    assert len(rows2) == 3 and state2["stopped"] == "9 requests made"


# ---------------------------------------------------------------- 2.7 selection (acceptance 10)

def _rows(repo, n, verdict="qualifying"):
    return [{"url": f"https://github.com/{repo}/pull/{i}", "repo": repo, "number": i, "verdict": verdict,
             "family": "copilot", "families": ["copilot"], "runner": "jest", "B0": f"b{i}", "head_sha": f"h{i}",
             "job_id": i, "job_name": "test", "workflow_path": ".github/workflows/ci.yml"} for i in range(1, n + 1)]


def test_selection_tie_break_threshold_and_sampling():
    """protects=top 6 by count among count >= 3, ties by full_name, at most 12 PRs drawn with Random(3) from the
    sorted URLs; fails_when=order, threshold or sample differ; no_claim=that the 6 are representative."""
    rows = (_rows("z/z", 20) + _rows("b/b", 5) + _rows("a/a", 5) + _rows("c/c", 3) + _rows("d/d", 4)
            + _rows("e/e", 7) + _rows("f/f", 3) + _rows("g/g", 2) + _rows("h/h", 9, "no_single_runner"))
    out = S.select(rows)
    assert [r["full_name"] for r in out["repositories"]] == ["z/z", "e/e", "a/a", "b/b", "d/d", "c/c"]
    assert out["n_eligible"] == 7 and out["reaches_6"] is True
    z = out["repositories"][0]
    want = __import__("random").Random(3).sample(sorted(f"https://github.com/z/z/pull/{i}" for i in range(1, 21)), 12)
    assert [p["url"] for p in z["prs"]] == want
    assert len(out["repositories"][1]["prs"]) == 7
    few = S.select(_rows("a/a", 3) + _rows("b/b", 2))
    assert few["n_selected"] == 1 and few["reaches_6"] is False


def test_select_script_is_byte_reproducible(tmp_path):
    """protects=acceptance 10: select_repos.py twice on the same committed rows gives byte-identical selected.json;
    fails_when=set or dict ordering leaks into the output; no_claim=none."""
    import gzip
    import shutil
    d = tmp_path / "pop"
    (d / "results").mkdir(parents=True)
    for f in ("select_repos.py", "collect.py", "rules.py", "ghrest.py"):
        shutil.copy(HERE / f, d / f)
    with gzip.open(d / "results" / "prs.jsonl.gz", "wt") as f:
        for r in _rows("z/z", 20) + _rows("e/e", 4) + _rows("a/a", 3):
            f.write(json.dumps(r) + "\n")
    outs = []
    for _ in range(2):
        subprocess.run([sys.executable, str(d / "select_repos.py")], check=True, capture_output=True)
        outs.append((d / "selected.json").read_bytes())
    assert outs[0] == outs[1] and json.loads(outs[0])["n_selected"] == 3


# ---------------------------------------------------------------- review fixes (2026-11-27)

def test_30_repository_stop_checked_before_each_pr():
    """protects=PREREG 2.4: once 30 repositories have been read, no further PR is read, even of the 30th repository;
    fails_when=the stop is checked only between repositories (the 30th is read to its 40th PR); no_claim=none."""
    pool = [p for i in range(30) for p in _pool(f"r{i:02d}/x", 3)]
    prs = {(p["repo"], p["number"]): {"head": f"{p['repo']}#{p['number']}", "created_at": p["created_at"], "jobs": []}
           for p in pool}
    repos = {p["repo"]: {"fork": False, "archived": False, "private": False, "created_at": "2020-01-01T00:00:00Z"}
             for p in pool}
    state, rows = C.new_state(pool), []
    assert C.collect(FakeAPI(repos, prs, {}, {}), state, pool, rows.append) == "30 repositories read"
    by_repo = collections.Counter(r["repo"] for r in rows)
    assert len(by_repo) == 30 and sorted(by_repo.values()) == [1] + [3] * 29


def test_resume_never_reads_a_recorded_url_again():
    """protects=a PR already in prs.jsonl.gz is not read again on resume (no duplicate rows, no double-counted
    requests); fails_when=the checkpoint alone decides; no_claim=none."""
    pool = _pool("a/x", 3)
    prs = {(p["repo"], p["number"]): {"head": f"h{p['number']}", "created_at": p["created_at"], "jobs": []} for p in pool}
    repos = {"a/x": {"fork": False, "archived": False, "private": False, "created_at": "2020-01-01T00:00:00Z"}}
    rows = []
    C.collect(FakeAPI(repos, prs, {}, {}), C.new_state(pool), pool, rows.append, seen={pool[2]["url"], pool[1]["url"]})
    assert [r["number"] for r in rows] == [1]


def test_selection_counts_unique_prs_not_rows():
    """protects=a duplicated qualifying row cannot push a repository over the threshold; fails_when=rows are counted;
    no_claim=none."""
    rows = _rows("a/a", 2)
    assert S.select(rows + rows)["n_selected"] == 0


def test_max_minutes_is_a_chunk_stop():
    """protects=the deadline stops the chunk without a final stop (the next chunk resumes); fails_when=it is stored
    as the final stop or ignored; no_claim=none."""
    pool = _pool("a/x", 2)
    repos = {"a/x": {"fork": False, "archived": False, "private": False, "created_at": "2020-01-01T00:00:00Z"}}
    state, rows = C.new_state(pool), []
    assert C.collect(FakeAPI(repos, {}, {}, {}), state, pool, rows.append, deadline=0.0) == "max_minutes"
    assert state["stopped"] is None and rows == []


def test_workflow_path_and_ref_are_url_quoted_and_unparseable_reason():
    """protects=a workflow path with a space or '#' is read as one path (not cut or refused), and an unparseable
    workflow says so; fails_when=the path is interpolated raw; no_claim=GitHub's handling of every character."""
    api = FakeAPI({}, {}, {}, {"b0h1": "not: [a mapping with jobs"})
    st, wf, reason = C._yaml(api, "o/r", ".github/workflows/my ci#1.yml", "b0h1")
    assert api.paths[-1] == "repos/o/r/contents/.github/workflows/my%20ci%231.yml?ref=b0h1"
    assert (st, wf, reason) == (200, None, "workflow_unparseable")


def test_oracle_newest_completed_run_of_the_same_path():
    """protects=2.8: the newest completed push run of the same workflow path (any @ref suffix ignored) and the job of
    the same display name; fails_when=an in-progress or other-path run is used, or a missing job counts; no_claim=none."""
    class O:
        n_requests = 0

        def get_json(self, path):
            if "/jobs" in path:
                rid = int(path.split("/runs/")[1].split("/")[0])
                return 200, {"jobs": [{"id": rid * 10, "name": "test (18.x)", "conclusion": "failure"}]}
            return 200, {"workflow_runs": [
                {"id": 1, "status": "completed", "path": ".github/workflows/ci.yml@refs/heads/main", "created_at": "2026-11-01"},
                {"id": 2, "status": "completed", "path": ".github/workflows/ci.yml", "created_at": "2026-11-02"},
                {"id": 3, "status": "in_progress", "path": ".github/workflows/ci.yml", "created_at": "2026-11-03"},
                {"id": 4, "status": "completed", "path": ".github/workflows/other.yml", "created_at": "2026-11-04"}]}
    pr = {"url": "u", "repo": "o/r", "B0": "b0", "workflow_path": ".github/workflows/ci.yml", "job_name": "test (18.x)"}
    out = C.oracle(O(), pr)
    assert (out["run_id"], out["job_id"], out["conclusion"], out["has_job"]) == (2, 20, "failure", True)
    assert C.oracle(O(), {**pr, "job_name": "lint"})["has_job"] is False
