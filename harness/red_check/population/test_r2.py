"""C5.3 revision 2 tests (PREREG_R2.md). Run: python3 -m pytest -q harness/red_check/population/

Each test states its card: protects=<observable>; fails_when=<wrong result>; no_claim=<what green does not prove>.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import r2  # noqa: E402
import rules as R  # noqa: E402

FIX = HERE / "fixtures"


def fx(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- R2.4 runner rules v2

@pytest.mark.parametrize("name,runner", [("pytest-q.log", "pytest"), ("turbo-vitest.log", "vitest"),
                                         ("pnpm-r-jest.log", "jest"), ("yarn-foreach-node-test.log", "node-test")])
def test_new_shapes_missed_by_v1_found_by_v2(name, runner):
    """protects=the widened rules find pytest -q and workspace-prefixed summaries that rev 1 missed; fails_when=v2
    misses them, or v1 already found them (then the fixture proves nothing); no_claim=every workspace tool's prefix."""
    assert R.detect_runner(fx(name), version=1)[0] == R.NO_RUNNER
    assert R.detect_runner(fx(name), version=2)[0] == runner


@pytest.mark.parametrize("name", ["pytest-q-pass.log", "turbo-pass.log", "vitest-pass.log", "jest-pass.log",
                                  "node-test-pass.log", "pytest-pass.log"])
def test_v2_negatives(name):
    """protects=passing summaries (count 0, or no 'failed') stay no_runner under v2; fails_when=the looser pytest
    pattern or a prefix strip accepts a passing line; no_claim=none."""
    assert R.detect_runner(fx(name), version=2) == (R.NO_RUNNER, None)


@pytest.mark.parametrize("name,runner", [("vitest.log", "vitest"), ("jest.log", "jest"),
                                         ("node-test.log", "node-test"), ("pytest.log", "pytest")])
def test_v2_keeps_v1_detections(name, runner):
    """protects=v2 is a widening: every rev-1 fixture gives the same runner; fails_when=a v1 match is lost;
    no_claim=none."""
    assert R.detect_runner(fx(name), version=2)[0] == runner


def test_v2_pytest_pattern_edges():
    """protects=the pytest summary needs the 'N word' list and ' in <s>s'; fails_when=prose with 'failed' and a time
    matches, or the banner form is lost; no_claim=none."""
    p = R.RUNNERS_V2["pytest"]
    assert p.search("===== 2 failed, 1 passed in 3.21s (0:00:03) =====")
    assert p.search("1 failed in 0.05s")
    assert p.search("3 passed, 1 failed, 2 skipped in 1.00s")
    assert not p.search("Build failed in 3.2s")
    assert not p.search("deploy: 1 failed in 0.5s retrying")
    assert R.detect_runner("1 passed, 0 failed in 0.2s\n", version=2)[0] == R.NO_RUNNER


def test_jest_line_not_eaten_by_prefix_strip():
    """protects=jest's own 'Tests:' label is not taken for a workspace prefix; fails_when=the strip removes it and jest
    is missed; no_claim=none."""
    assert R.WORKSPACE_PREFIX.sub("", "Tests:       1 failed, 2 passed", count=1) == "Tests:       1 failed, 2 passed"
    assert R.detect_runner("Tests:       1 failed, 2 passed, 3 total\n", version=2)[0] == "jest"


# ---------------------------------------------------------------- R2.2 screening

WF_DIRECT = "on:\n  pull_request:\njobs:\n  t:\n    steps:\n      - run: npx vitest run\n"
WF_WRAPPER = "on: [push, pull_request]\njobs:\n  t:\n    steps:\n      - run: pnpm test\n"
WF_PUSH_ONLY = "on: push\njobs:\n  t:\n    steps:\n      - run: pytest -q\n"
WF_COMMENT = "on: pull_request\njobs:\n  t:\n    steps:\n      - run: echo hi  # pytest later\n"


def node(created="2020-01-01T00:00:00Z", wf=(), pkg=None, **flags):
    return {"createdAt": created, "isFork": flags.get("fork", False), "isArchived": flags.get("archived", False),
            "isPrivate": False, "wf": {"entries": [{"name": n, "object": {"text": t}} for n, t in wf]},
            "pkg": {"text": pkg} if pkg is not None else None}


def test_screen_rules():
    """protects=R2.2: older than 365 days, not fork/archived, a pull_request workflow running a supported runner
    directly or through npm/pnpm/yarn test with a matching package.json test script; comments and push-only
    workflows do not count; fails_when=any rule differs; no_claim=runners invoked by other scripts or subdirectories."""
    s = r2.screen_repo
    assert s("a/b", None)["verdict"] == "repo_unreadable"
    assert s("a/b", node(fork=True, wf=[("ci.yml", WF_DIRECT)]))["verdict"] == "fork"
    assert s("a/b", node(archived=True, wf=[("ci.yml", WF_DIRECT)]))["verdict"] == "archived"
    assert s("a/b", node(created="2025-12-01T00:00:00Z", wf=[("ci.yml", WF_DIRECT)]))["verdict"] == "repo_too_young_r2"
    assert s("a/b", node(created="2025-11-26T23:00:00Z", wf=[("ci.yml", WF_DIRECT)]))["verdict"] == "eligible"
    ok = s("a/b", node(wf=[("ci.yml", WF_DIRECT), ("README.md", WF_DIRECT)]))
    assert ok["verdict"] == "eligible" and ok["workflows"] == [{"file": "ci.yml", "rule": "direct"}]
    assert s("a/b", node(wf=[("ci.yaml", WF_WRAPPER)], pkg='{"scripts": {"test": "vitest run"}}'))["workflows"] == \
        [{"file": "ci.yaml", "rule": "wrapper"}]
    assert s("a/b", node(wf=[("ci.yml", WF_WRAPPER)], pkg='{"scripts": {"test": "mocha"}}'))["verdict"] == "no_test_ci"
    assert s("a/b", node(wf=[("ci.yml", WF_WRAPPER)], pkg="not json"))["verdict"] == "no_test_ci"
    assert s("a/b", node(wf=[("ci.yml", WF_PUSH_ONLY)]))["verdict"] == "no_test_ci"
    assert s("a/b", node(wf=[("ci.yml", WF_COMMENT)]))["verdict"] == "no_test_ci"
    assert r2.workflow_match("on: pull_request\nrun: node --experimental-strip-types --test src/\n", None) == "direct"


class FakeGQL:
    def __init__(self, nodes, remaining=1000):
        self.nodes, self.remaining, self.limit, self.n_requests, self.queries = nodes, remaining, 1000, 0, []

    def low(self):
        return self.remaining < 200

    def query(self, q):
        self.n_requests += 1
        self.queries.append(q)
        import re
        names = re.findall(r'repository\(owner: "([^"]+)", name: "([^"]+)"\)', q)
        return 200, {"data": {f"r{i}": self.nodes.get(f"{o}/{n}") for i, (o, n) in enumerate(names)}}


def test_screen_batches_resume_and_bad_names():
    """protects=screening walks the candidate order in batches of 20, resumes from screen_next, records a missing
    repository as repo_unreadable and never puts an unqueryable name into a query; fails_when=a repository is skipped
    or screened twice; no_claim=GitHub's GraphQL costs."""
    pool = [{"repo": f"o{i:02d}/r"} for i in range(45)] + [{"repo": 'bad"/x'}]
    nodes = {f"o{i:02d}/r": node(wf=[("ci.yml", WF_DIRECT)]) for i in range(45) if i != 7}
    g, rows, state = FakeGQL(nodes), [], {"screen_next": 0, "screen_done": False}

    def emit(r):
        rows.append(r)
    assert r2.screen(g, pool, state, emit, None) == "screening done"
    assert len(rows) == 46 and len({r["repo"] for r in rows}) == 46 and g.n_requests == 3
    assert [r["verdict"] for r in rows if r["repo"] in ("o07/r", 'bad"/x')] == ["repo_unreadable", "repo_unreadable"]
    assert all('bad"' not in q for q in g.queries)
    state2, rows2 = {"screen_next": 0, "screen_done": False}, []
    g2 = FakeGQL(nodes)
    orig = g2.query

    def q_then_low(q):
        out = orig(q)
        g2.remaining = 100
        return out
    g2.query = q_then_low
    assert r2.screen(g2, pool, state2, rows2.append, None).startswith("graphql rate limit low")
    assert state2["screen_next"] == 20 and len(rows2) == 20


# ---------------------------------------------------------------- R2.3 agent PRs

def _pr(n, login, created, ref="feature", body=""):
    return {"html_url": f"https://github.com/o/r/pull/{n}", "number": n, "user": {"login": login},
            "head": {"ref": ref}, "body": body, "created_at": created}


class FakePulls:
    def __init__(self, pages, status=200):
        self.pages, self.status, self.n_requests, self.paths = pages, status, 0, []

    def get_json(self, path):
        self.n_requests += 1
        self.paths.append(path)
        if self.status != 200:
            return self.status, "boom"
        page = int(path.split("&page=")[1])
        return 200, self.pages[page - 1] if page <= len(self.pages) else []


def test_agent_prs_window_families_and_paging():
    """protects=R2.3: only PRs created in [D-60, D) by a family rule, newest first; listing stops after the page that
    reaches before the window; page-1 failure is reported; fails_when=a human PR, an out-of-window PR or an unmarked
    codex/ branch is kept; no_claim=GitHub's ordering."""
    page1 = [_pr(100 - i, "someone", "2026-11-26T00:00:00Z") for i in range(96)] + [
        _pr(4, "Copilot", "2026-11-20T00:00:00Z"),
        _pr(3, "devin-ai-integration[bot]", "2026-11-27T01:00:00Z"),
        _pr(2, "human", "2026-10-01T00:00:00Z", ref="codex/x", body="see chatgpt.com/codex/abc"),
        _pr(1, "human", "2026-10-01T00:00:00Z", ref="codex/y", body="no marker")]
    page2 = [_pr(0, "google-labs-jules[bot]", "2026-09-01T00:00:00Z")] + [
        _pr(-i, "x", "2026-09-01T00:00:00Z") for i in range(1, 100)]
    api = FakePulls([page1, page2, []])
    prs, pages = r2.agent_prs(api, "o/r")
    assert [(p["number"], p["family"]) for p in prs] == [(4, "copilot"), (2, "codex")]
    assert pages == 2
    assert r2.agent_prs(FakePulls([], status=404), "o/r") == (None, 1)
    cc = r2.families_of(_pr(9, "Copilot", "x", body="Generated with [Claude Code](https://claude.com)"))
    assert cc == ["copilot", "claude_code"]


def test_collect_r2_uses_v2_rules_and_caps(monkeypatch):
    """protects=R2.3 reading: eligible repositories in order, agent PRs from the listing, runner rules v2 (a pytest -q
    log qualifies), pulls_unreadable skips a repository, the 30-repository stop holds; fails_when=rev 1's rules are
    used or a repository is read past the stop; no_claim=the live API."""
    import test_population as T
    prs = {("a/x", 1): {"head": "h1", "created_at": "2026-11-10T00:00:00Z", "jobs": [T._job(7, name="test (3.12)")]}}
    api = T.FakeAPI({}, prs, {7: fx("pytest-q.log")}, {})
    api._cur = {"h1"}
    listing = {"a/x": ([{"url": "u1", "repo": "a/x", "number": 1, "family": "copilot", "families": ["copilot"],
                         "created_at": "2026-11-10T00:00:00Z"}], 1), "b/y": (None, 1)}
    monkeypatch.setattr(r2, "agent_prs", lambda src, name: listing[name])
    state = {"next": 0, "repos": {}, "repos_read": 0, "requests": 0, "stopped": None}
    rows = []
    why = r2.collect(api, state, [("b/y", 9), ("a/x", 3)], rows.append)
    assert why == "eligible repositories exhausted"
    assert state["repos"]["b/y"]["reason"] == "pulls_unreadable"
    assert [(r["verdict"], r.get("runner")) for r in rows] == [("qualifying", "pytest")]
    many = {f"r{i:02d}/x": ([{"url": f"u{i}-{k}", "repo": f"r{i:02d}/x", "number": k, "family": "devin",
                               "families": ["devin"], "created_at": "2026-11-10T00:00:00Z"} for k in (1, 2)], 1)
            for i in range(31)}
    monkeypatch.setattr(r2, "agent_prs", lambda src, name: many[name])
    monkeypatch.setattr(r2.C, "read_pr", lambda src, pr, store_log=None, version=1: {"url": pr["url"], "repo": pr["repo"],
                                                                                        "verdict": "no_candidate_job"})
    state2, rows2 = {"next": 0, "repos": {}, "repos_read": 0, "requests": 0, "stopped": None}, []
    assert r2.collect(api, state2, [(f"r{i:02d}/x", 2) for i in range(31)], rows2.append) == "30 repositories read"
    assert len(rows2) == 59 and state2["repos_read"] == 30


# ---------------------------------------------------------------- review fixes (2026-11-27)

def test_graphql_error_body_does_not_advance_or_emit():
    """protects=a whole-query GraphQL failure (200 with data null) or a non-NOT_FOUND alias error stops the chunk
    with nothing emitted and screen_next unchanged, so the next chunk retries; fails_when=the batch is recorded as
    repo_unreadable and skipped for good; no_claim=every GitHub error shape."""
    pool = [{"repo": "a/b"}, {"repo": 'bad"/x'}]
    for body in ({"data": None, "errors": [{"message": "timeout"}]},
                 {"data": {"r0": None}, "errors": [{"type": "FORBIDDEN", "path": ["r0"]}]}):
        g = FakeGQL({})
        g.query = lambda q, b=body: (200, b)
        state, rows = {"screen_next": 0, "screen_done": False}, []
        assert r2.screen(g, pool, state, rows.append, None).startswith("graphql")
        assert state["screen_next"] == 0 and rows == []
    g = FakeGQL({})
    g.query = lambda q: (200, {"data": {"r0": None}, "errors": [{"type": "NOT_FOUND", "path": ["r0"]}]})
    state, rows = {"screen_next": 0, "screen_done": False}, []
    assert r2.screen(g, pool, state, rows.append, None) == "screening done"
    assert [(r["repo"], r["reason"]) for r in rows] == [('bad"/x', "name not queryable"), ("a/b", "NOT_FOUND")]


def test_age_cutoff_day_is_too_young():
    """protects=PREREG_R2 R2.2: 'created before 2025-11-27'; a repository created on 2025-11-27 is too young;
    fails_when=the cutoff day is eligible; no_claim=none."""
    assert r2.screen_repo("a/b", node(created="2025-11-27T00:00:01Z", wf=[("ci.yml", WF_DIRECT)]))["verdict"] == \
        "repo_too_young_r2"
    assert r2.screen_repo("a/b", node(created="2025-11-26T23:59:59Z", wf=[("ci.yml", WF_DIRECT)]))["verdict"] == "eligible"


def test_pull_listing_cut_short_is_recorded():
    """protects=a listing that stopped on a later-page error or on the 3-page cap says so; fails_when=a truncated
    listing looks complete; no_claim=none."""
    full = [_pr(1000 - i, "x", "2026-11-20T00:00:00Z") for i in range(100)]
    api = FakePulls([full, full, full])
    r2.agent_prs(api, "o/r")
    assert r2.agent_prs.last_note == "page_cap"

    class Fail2(FakePulls):
        def get_json(self, path):
            if path.endswith("&page=2"):
                self.n_requests += 1
                return 502, "bad gateway"
            return super().get_json(path)
    prs, pages = r2.agent_prs(Fail2([full]), "o/r")
    assert pages == 2 and prs == [] and r2.agent_prs.last_note == "page_error"
    r2.agent_prs(FakePulls([[_pr(1, "Copilot", "2026-11-20T00:00:00Z")]]), "o/r")
    assert r2.agent_prs.last_note is None
