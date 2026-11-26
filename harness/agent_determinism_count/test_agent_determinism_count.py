"""AC2 fixtures of the agent-determinism count. Each test states protects= ; fails_when= ; no_claim= .

Run: python3 -m pytest -q harness/agent_determinism_count/test_agent_determinism_count.py
No network: GitHub answers come from ``Fake`` (raw API JSON, trimmed by pipeline.trim through LiveSource).
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import sys
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discover  # noqa: E402
import ghapi  # noqa: E402
import handread  # noqa: E402
import pipeline as P  # noqa: E402
import report  # noqa: E402
import rules as R  # noqa: E402
import texts as T  # noqa: E402
import verify  # noqa: E402

RUNS_Q = urllib.parse.urlencode({"created": ">=2026-01-01", "per_page": 100})
CI_PY = """name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - name: Tests
        run: uv run pytest -q
"""
REQ = "langchain-openai==0.2\n"


def vcr_yaml(host: str = "api.openai.com") -> str:
    return ("interactions:\n- request:\n    method: POST\n    uri: https://" + host + "/v1/chat/completions\n"
            "  response:\n    status: {code: 200}\nversion: 1\n")


def har_json(host: str) -> str:
    return json.dumps({"log": {"entries": [{"request": {"url": f"https://{host}/v1/messages"}, "response": {}}]}})


class Fake:
    """A fake GitHub for one repository: raw API JSON per GET path (missing path -> 404)."""

    def __init__(self, files: dict, repo: str = "acme/agent", truncated: bool = False, meta: dict | None = None,
                 listing: dict | None = None):
        self.repo, self.raw, self.calls = repo, {}, []
        self.raw[f"repos/{repo}"] = {"full_name": repo, "fork": False, "archived": False,
                                     "pushed_at": "2026-06-01T00:00:00Z", "default_branch": "main",
                                     "owner": {"login": repo.split("/")[0]}, "html_url": f"https://github.com/{repo}",
                                     **(meta or {})}
        tree = []
        for p, t in files.items():
            sha = hashlib.sha1((p + t).encode()).hexdigest()
            tree.append({"path": p, "type": "blob", "sha": sha, "size": len(t)})
            self.raw[f"repos/{repo}/git/blobs/{sha}"] = {"content": base64.b64encode(t.encode()).decode(),
                                                         "encoding": "base64", "size": len(t)}
        self.raw[f"repos/{repo}/git/trees/main?recursive=1"] = {"truncated": truncated, "tree": tree}
        for path, entries in (listing or {}).items():
            key = f"repos/{repo}/contents?ref=main" if path == "" else f"repos/{repo}/contents/{path}?ref=main"
            self.raw[key] = [{"name": e.split("/")[-1], "path": e, "type": "dir" if e.endswith("/") else "file",
                              "sha": hashlib.sha1((e + files.get(e, "")).encode()).hexdigest(), "size": 1}
                             for e in entries]

    def sha(self, path: str, files: dict) -> str:
        return hashlib.sha1((path + files[path]).encode()).hexdigest()

    def runs(self, wf: str, runs: list[dict], total: int | None = None):
        self.raw[f"repos/{self.repo}/actions/workflows/{wf}/runs?{RUNS_Q}"] = {
            "total_count": len(runs) if total is None else total,
            "workflow_runs": [{"id": r["id"], "created_at": "2026-03-01T00:00:00Z", "conclusion": r.get("conclusion",
                               "success"), "status": "completed", "html_url": f"https://x/runs/{r['id']}"} for r in runs]}
        for r in runs:
            self.raw[f"repos/{self.repo}/actions/runs/{r['id']}/jobs?per_page=100&page=1"] = {
                "total_count": len(r["jobs"]), "jobs": r["jobs"]}

    def commit_date(self, path: str, date: str):
        self.raw[f"repos/{self.repo}/commits?" + urllib.parse.urlencode({"path": path, "sha": "main",
                                                                          "per_page": 1})] = [
            {"sha": "abc", "commit": {"committer": {"date": date}}, "html_url": "https://x/commit/abc"}]

    def get(self, path, search=None):
        self.calls.append(path)
        if path in self.raw:
            return 200, json.loads(json.dumps(self.raw[path])), {}
        return 404, {"message": "Not Found"}, {}


def ok_run(rid=1, step_conclusion="success", job="test", step="Tests"):
    return {"id": rid, "jobs": [{"id": rid * 10, "name": job, "status": "completed", "conclusion": "success",
                                 "steps": [{"name": "Set up job", "number": 1, "conclusion": "success"},
                                           {"name": step, "number": 4, "conclusion": step_conclusion}]}]}


def run(fake: Fake, opts=None, cap=R.REQUEST_CAP):
    src = P.LiveSource(fake, cap=cap)
    row = P.run_candidate(src, {"idx": 0, "repo": fake.repo, "html_url": f"https://github.com/{fake.repo}",
                                "stratum": "S1"}, opts or {})
    return row, src


def member_fake(extra: dict | None = None, dates: dict | None = None) -> Fake:
    files = {"requirements.txt": REQ, ".github/workflows/ci.yml": CI_PY, **(extra or {})}
    f = Fake(files)
    f.runs("ci.yml", [ok_run()])
    for p, d in (dates or {}).items():
        f.commit_date(p, d)
    return f


# ====================================================================================== manifests

def test_requirements_dev_prefix_library():
    """protects=Definitions agent library list (langchain-* prefix) and requirements*.txt manifests;
    fails_when=langchain-openai==0.2 in requirements-dev.txt is not found as a dev/test library;
    no_claim=that every requirements syntax (hashes, markers) parses."""
    deps = R.parse_manifest("requirements-dev.txt", "langchain-openai==0.2\n")
    assert R.libraries_of("requirements-dev.txt", deps) == [("langchain-openai", R.DEV)]


def test_pep503_normalisation():
    """protects=PEP 503 name normalisation; fails_when=LangChain_Core is not matched as langchain-core;
    no_claim=normalisation of npm names (they are matched lower-case only)."""
    deps = R.parse_manifest("requirements.txt", "LangChain_Core>=0.3\n")
    assert R.libraries_of("requirements.txt", deps) == [("langchain-core", R.RUNTIME)]


def test_package_json_ai_dev_and_ai_sdk():
    """protects=npm exact key `ai` and the @ai-sdk/* scope, devDependencies as dev/test;
    fails_when="ai": "^4.0" in devDependencies or "@ai-sdk/openai" is not a library;
    no_claim=workspaces or nested package.json resolution."""
    pj = json.dumps({"devDependencies": {"ai": "^4.0"}, "dependencies": {"@ai-sdk/openai": "^1"}})
    libs = R.libraries_of("package.json", R.parse_manifest("package.json", pj))
    assert sorted(libs) == [("@ai-sdk/openai", R.RUNTIME), ("ai", R.DEV)]


def test_aim_and_pydantic_are_not_libraries():
    """protects=exact matching of `ai` and of the Python list; fails_when="aim" or pydantic alone counts;
    no_claim=nothing about pydantic-ai (it is listed)."""
    assert R.libraries_of("package.json", R.parse_manifest("package.json", json.dumps({"dependencies":
                                                                                         {"aim": "1.0"}}))) == []
    assert R.libraries_of("requirements.txt", R.parse_manifest("requirements.txt", "pydantic==2\n")) == []
    assert R.libraries_of("requirements.txt", R.parse_manifest("requirements.txt", "pydantic-ai\n")) == \
        [("pydantic-ai", R.RUNTIME)]


def test_poetry_test_group():
    """protects=Poetry dependency groups; fails_when=[tool.poetry.group.test.dependencies] crewai is missed;
    no_claim=Poetry extras semantics beyond optional=true."""
    t = '[tool.poetry]\nname="x"\n[tool.poetry.group.test.dependencies]\ncrewai = "^0.80"\n'
    assert R.libraries_of("pyproject.toml", R.parse_manifest("pyproject.toml", t)) == [("crewai", R.DEV)]


def test_broken_pyproject_is_uncertain():
    """protects=§2.2 manifest-error -> uncertain, never no-agent-lib; fails_when=a pyproject.toml that does not parse
    and no other library gives non-member; no_claim=which TOML errors exist."""
    f = Fake({"pyproject.toml": "[project\nname = 1", ".github/workflows/ci.yml": CI_PY})
    row, _ = run(f)
    assert row["cls"] == "uncertain" and "manifest-error" in row["why"]


def test_node_modules_manifest_skipped():
    """protects=skip list for vendored manifests; fails_when=a package.json under node_modules/ yields a library;
    no_claim=other vendoring layouts."""
    assert R.manifest_kind("node_modules/ai/package.json") is None
    f = Fake({"node_modules/x/package.json": json.dumps({"dependencies": {"ai": "1"}})})
    row, _ = run(f)
    assert row["cls"] == "non-member" and row["stage"] == "no-agent-lib"


def test_truncated_tree_without_library_is_uncertain():
    """protects=§2.1 truncated tree -> uncertain when nothing is found in what was fetched; fails_when=a truncated
    tree gives no-agent-lib; no_claim=that deeper manifests are read."""
    f = Fake({"README.md": "x", "src/requirements.txt": "flask\n"}, truncated=True,
             listing={"": ["README.md", "src/"], "src": ["src/requirements.txt"], ".github/workflows": []})
    row, _ = run(f)
    assert row["cls"] == "uncertain" and "tree-truncated" in row["why"]


def test_setup_py_non_literal_is_manifest_error():
    """protects=setup.py read by regex on literals only; fails_when=install_requires=REQS is read as no dependency;
    no_claim=setup.py executed (it never is)."""
    with pytest.raises(R.ManifestError):
        R.parse_manifest("setup.py", "from setuptools import setup\nsetup(install_requires=REQS)\n")
    assert R.libraries_of("setup.py", R.parse_manifest(
        "setup.py", "setup(install_requires=['dspy-ai>=2', \"requests\"], extras_require={'x': ['agno']})")) == \
        [("dspy-ai", R.RUNTIME), ("agno", R.OPTIONAL)]


def test_request_cap_in_membership_is_uncertain():
    """protects=§2.4 300-request cap; fails_when=reaching the cap during membership gives member or non-member;
    no_claim=the cap value is right for every repository (median/p90/max are printed after chunk 1)."""
    f = member_fake()
    row, src = run(f, cap=3)
    assert row["cls"] == "uncertain" and row["stage"] == "request-cap" and src.core == 3


# ====================================================================================== CI tests

def _step(cmd):
    return {"run": cmd}


def test_test_step_commands():
    """protects=§2.3 test-step detection with prefix stripping, the RUNNER_RE additions and script resolution;
    fails_when=uv run pytest, bun test, npm run test:unit -> vitest or python -m unittest is not a test step;
    no_claim=every task runner (just, task, rake...) is resolved."""
    pkg = json.dumps({"scripts": {"test:unit": "vitest run", "ci": "npm run test:unit"}})
    read = {"package.json": pkg}.get
    assert R.is_test_step(_step("uv run pytest -q"), "", read)
    assert R.is_test_step(_step("bun test"), "", read)
    assert R.is_test_step(_step("npm run test:unit"), "", read)
    assert R.is_test_step(_step("npm run ci"), "", read)  # resolved through two scripts to vitest
    assert R.is_test_step(_step("python -m unittest discover"), "", read)
    assert R.is_runner_command("python -m unittest") and R.is_runner_command("unittest")


def test_pip_install_pytest_is_not_test_step():
    """protects=install filter; fails_when=pip install pytest counts as a test step; no_claim=install commands of
    every package manager."""
    assert not R.is_test_step(_step("pip install pytest"), "", lambda p: None)


def test_test_reporter_action_is_not_test_step():
    """protects=uses: rule (test but not report/summary/publish/coverage); fails_when=dorny/test-reporter counts;
    no_claim=that every test action name contains 'test'."""
    assert not R.is_test_step({"uses": "dorny/test-reporter@v1"}, "", lambda p: None)
    assert R.is_test_step({"uses": "pavelzw/pytest-action@v2"}, "", lambda p: None)


def test_skipped_test_step_is_no_evidence():
    """protects=§2.3 'test step not skipped'; fails_when=a run whose test step was skipped makes ci-tests yes;
    no_claim=steps renamed between the YAML and the run."""
    f = Fake({"requirements.txt": REQ, ".github/workflows/ci.yml": CI_PY})
    f.runs("ci.yml", [ok_run(step_conclusion="skipped")])
    row, _ = run(f)
    assert row["cls"] == "non-member" and row["stage"] == "no-ci-tests"
    f2 = member_fake()
    row2, _ = run(f2)
    assert row2["cls"] == "member" and row2["ci"]["ci"] == "yes"


def test_twenty_runs_without_job_and_more_is_uncertain():
    """protects=§2.3 20-run inspection cap -> uncertain; fails_when=20 runs without the job while more exist give
    no-ci-tests; no_claim=that older runs would show the job."""
    f = Fake({"requirements.txt": REQ, ".github/workflows/ci.yml": CI_PY})
    f.runs("ci.yml", [ok_run(i, job="lint") for i in range(1, 21)], total=35)
    row, _ = run(f)
    assert row["cls"] == "uncertain" and "uncertain-more-runs" in row["why"]
    assert row["ci"]["workflows"][0]["inspected"] == 20


def test_workflow_call_without_caller_is_uncertain():
    """protects=§2.3 workflow_call through the caller; fails_when=a reusable test workflow without a caller gives
    no-ci-tests; no_claim=remote reusable workflows."""
    wf = CI_PY.replace("on: [push, pull_request]", "on: workflow_call")
    f = Fake({"requirements.txt": REQ, ".github/workflows/reuse.yml": wf})
    row, _ = run(f)
    assert row["cls"] == "uncertain"


# ====================================================================================== recordings

def test_vcr_cassette_2025_yes_and_2023_not():
    """protects=§3.1 recording rule with the HISTORY_START date; fails_when=a 2025 VCR cassette with an OpenAI uri is
    not yes, or the same file dated 2023 is yes; no_claim=that the recording is used by a test run in CI."""
    p = "tests/cassettes/test_chat.yaml"
    row, _ = run(member_fake({p: vcr_yaml()}, {p: "2025-04-01T00:00:00Z"}))
    assert row["recordings"]["yes"]["path"] == p
    row2, _ = run(member_fake({p: vcr_yaml()}, {p: "2023-04-01T00:00:00Z"}))
    assert "yes" not in row2["recordings"] and row2["recordings"]["hits_before_history"]


def test_github_only_cassette_not_yes():
    """protects=§Hosts list; fails_when=a cassette recording only api.github.com counts; no_claim=hosts not listed."""
    p = "tests/cassettes/gh.yaml"
    row, _ = run(member_fake({p: vcr_yaml("api.github.com")}, {p: "2025-04-01T00:00:00Z"}))
    assert "yes" not in row["recordings"]


def test_har_in_recordings_anthropic_yes():
    """protects=__recordings__ segment and HAR files; fails_when=a HAR with api.anthropic.com under __recordings__ is
    not yes; no_claim=Polly's other persisters."""
    p = "src/__recordings__/chat_123/recording.har"
    row, _ = run(member_fake({p: har_json("api.anthropic.com")}, {p: "2025-09-01T00:00:00Z"}))
    assert row["recordings"]["yes"]["hosts"] == ["api.anthropic.com"]


def test_vcr_shape_outside_test_paths_not_checked():
    """protects=shape rule limited to test paths; fails_when=a VCR-shaped JSON under src/ is fetched or counted;
    no_claim=recordings kept outside test paths do not exist."""
    p = "src/data/sample.json"
    assert R.recording_file(p) is None
    assert R.recording_file("tests/data/sample.json") == "shape"
    f = member_fake({p: json.dumps({"interactions": [{"request": {"uri": "https://api.openai.com/v1"}}]})},
                    {p: "2025-01-01T00:00:00Z"})
    row, _ = run(f)
    assert row["recordings"]["fetched"] == 0 and "yes" not in row["recordings"]


def test_201_cassettes_capped_unknown():
    """protects=§3.1 200-file cap -> recording-capped -> pain at most unknown; fails_when=201 host-free cassettes give
    pain no; no_claim=that file 201 holds a recording."""
    extra = {f"tests/cassettes/c{i:03d}.yaml": vcr_yaml("api.github.com") for i in range(201)}
    row, _ = run(member_fake(extra))
    assert row["recordings"]["capped"] and row["recordings"]["fetched"] == 200
    assert "recording-capped" in row["pain_flags"]
    pain = R.member_pain(None, row["pain_flags"], [], {})
    assert pain["pain"] == "unknown"


def test_first_hit_old_second_new_is_yes():
    """protects=§3.1 'a hit dated earlier -> continue with the next file'; fails_when=an old first hit stops the
    search; no_claim=ordering beyond sorted paths."""
    a, b = "tests/cassettes/a.yaml", "tests/cassettes/b.yaml"
    row, _ = run(member_fake({a: vcr_yaml(), b: vcr_yaml()}, {a: "2023-01-01T00:00:00Z", b: "2025-01-01T00:00:00Z"}))
    assert row["recordings"]["yes"]["path"] == b


def test_mp3_under_recordings_not_fetched():
    """protects=text extensions only; fails_when=an .mp3 under recordings/ is fetched; no_claim=binary recordings."""
    assert R.recording_file("tests/recordings/a.mp3") is None
    row, _ = run(member_fake({"tests/recordings/a.mp3": "ID3..."}))
    assert row["recordings"]["files"] == 0


def test_recording_package_in_manifest_yes():
    """protects=§0.2d model-answer recording packages counted only with a manifest dated after HISTORY_START;
    fails_when=a declared recording package is ignored or counted with an old manifest; no_claim=which packages
    qualify (the probe decides)."""
    f = member_fake({"requirements.txt": REQ + "evalcraft==1\n"}, {"requirements.txt": "2025-02-01T00:00:00Z"})
    row, _ = run(f, {"recording_packages": ["evalcraft"]})
    assert row["recordings"]["yes"]["rule"] == "package"
    f2 = member_fake({"requirements.txt": REQ + "evalcraft==1\n"}, {"requirements.txt": "2023-02-01T00:00:00Z"})
    row2, _ = run(f2, {"recording_packages": ["evalcraft"]})
    assert "yes" not in row2["recordings"]


# ====================================================================================== texts

def test_text_candidates_regexes():
    """protects=PAIN_RE and MODEL_RE (both required); fails_when=the two pain texts are not candidates or the db text
    is; no_claim=that a candidate is pain (hand reads decide)."""
    assert R.is_text_candidate("flaky test: LLM returns different JSON each run")
    assert not R.is_text_candidate("fix flaky db test")
    assert R.is_text_candidate("skip openai tests in CI, too expensive")
    assert R.is_text_candidate("we mock the LLM in unit tests")


def test_reader_rule_text_holds_mock_clauses():
    """protects=§4 item 1b given verbatim to the second reader, with the mock interpretation; fails_when=the prompt
    lacks the clauses that reject 'we mock the LLM in unit tests' and confirm 'replaced the live OpenAI test with a
    mock, it kept giving different answers'; no_claim=how a reader labels a text (human judgement)."""
    clause = "a test calling a live model was replaced by a mock because of varying output or cost"
    for name in ("second_read_prompt.md", "PREREG.md"):
        t = " ".join((HERE / name).read_text().split())
        assert clause in t
        assert "mocking a model in unit tests from the start is ordinary practice and is not pain" in t


def test_labels_propagate_rejected_confirmed():
    """protects=§4.3 pain from labels; fails_when=a rejected mock text gives yes, or a text both readers confirm does
    not; no_claim=the labels themselves."""
    mock = {"url": "u1", "created_at": "2025-01-01"}
    live = {"url": "u2", "created_at": "2025-02-01"}
    reads = {"u1": {"first": {"label": "rejected"}}}
    assert R.member_pain(None, [], [mock], reads)["pain"] == "no"
    reads["u2"] = {"first": {"label": "confirmed", "quote": "q", "reason": "varying-output"},
                   "second": {"label": "confirmed"}}
    p = R.member_pain(None, [], [mock, live], reads)
    assert p["pain"] == "yes" and p["evidence"]["url"] == "u2"


def test_disagreement_is_unclear_unknown():
    """protects=both readers required; fails_when=a first confirmed with a second rejected gives yes or no;
    no_claim=reader quality."""
    reads = {"u": {"first": {"label": "confirmed", "quote": "q"}, "second": {"label": "rejected"}}}
    assert R.final_label("confirmed", "rejected") == "unclear"
    assert R.member_pain(None, [], [{"url": "u"}], reads)["pain"] == "unknown"
    assert R.final_label("confirmed", None) == "pending"


def _search_rec(total: int, items=None):
    return {"queries": [{"q": "x", "kind": "issues", "status": 200, "total_count": total, "read": 0,
                         "incomplete": False, "capped": total > 100}], "hits": items or []}


def test_text_capped_is_unknown():
    """protects=§3.2 first 100 results; fails_when=a repository search with total_count 140 allows pain no;
    no_claim=that the unread 40 hold pain."""
    flags = T.search_flags(_search_rec(140))
    assert flags == ["text-capped"]
    assert R.member_pain(None, flags, [], {})["pain"] == "unknown"


def test_issue_matching_only_in_comment_becomes_candidate():
    """protects=§3.2 comment fetch; fails_when=an issue whose model term appears only in a comment stays filtered;
    no_claim=comments beyond the first page of 100."""
    hit = {"kind": "issue", "url": "https://github.com/acme/agent/issues/7", "repo": "acme/agent", "number": 7,
           "title": "Flaky test",
           "body": "test_chat fails sometimes", "created_at": "2025-05-01T00:00:00Z", "query": "q"}
    texts = T.member_texts("acme/agent", [], {"queries": [], "hits": [hit]})
    assert T.candidates_of(texts, {})[0] == []
    assert [t["url"] for t in T.comment_targets(texts, {})] == [hit["url"]]
    f = Fake({})
    f.raw["repos/acme/agent/issues/7/comments?per_page=100"] = [
        {"created_at": "2025-05-02T00:00:00Z", "body": "the LLM answer varies between runs"}]
    cr = T.comments_pass(P.LiveSource(f), "acme/agent", texts)
    cands, _ = T.candidates_of(texts, T.comment_map(cr))
    assert [t["url"] for t in cands] == [hit["url"]]


def test_repo_queries_at_most_five_operators():
    """protects=GitHub's limit of 5 boolean operators; fails_when=any §3.2 query (or S2 cost query) has more than 5
    parsed operators; no_claim=GitHub's parser matches this count."""
    qs = R.repo_text_queries("a/b", "issues") + R.repo_text_queries("a/b", "commits") + \
        [d["q"] for d in R.discovery_queries() if d["family"] == "issues"]
    assert len(R.repo_text_queries("a/b", "issues")) == 6 and max(R.operator_count(q) for q in qs) <= 5
    assert R.operator_count('repo:a/b (flaky OR "x OR y" OR z)') == 2


def test_45_candidates_none_confirmed_in_40_unknown():
    """protects=TEXT_CAP; fails_when=a member with 45 candidates and 40 rejected reads gives pain no;
    no_claim=that the 5 unread are pain."""
    cands = [{"url": f"u{i}"} for i in range(45)]
    reads = {f"u{i}": {"first": {"label": "rejected"}} for i in range(40)}
    p = R.member_pain(None, [], cands, reads)
    assert p["pain"] == "unknown" and "text-cap" in p["why"]
    assert handread.member_queue(cands, reads) == []


def test_read_stops_at_first_double_confirmed():
    """protects=§4.1 reading order and stop; fails_when=texts after the first doubly confirmed one are queued, or a
    confirmed first read without its second read lets reading continue; no_claim=the order of equal dates."""
    cands = [{"url": f"u{i}"} for i in range(5)]
    reads = {"u0": {"first": {"label": "rejected"}},
             "u1": {"first": {"label": "confirmed", "quote": "q"}}}
    assert handread.member_queue(cands, reads) == []  # waits for the second read of u1
    reads["u1"]["second"] = {"label": "confirmed"}
    assert handread.member_queue(cands, reads) == []
    reads["u1"]["second"] = {"label": "rejected"}
    assert [t["url"] for t in handread.member_queue(cands, reads)] == ["u2", "u3", "u4"]
    t = R.text_order([{"url": "a", "created_at": "2025-01-01", "discovery": False},
                      {"url": "b", "created_at": "2024-01-01", "discovery": True},
                      {"url": "c", "created_at": "2026-01-01", "discovery": False}])
    assert [x["url"] for x in t] == ["b", "c", "a"]


def test_every_s3_pm_query_has_test():
    """protects=§1.C query shapes; fails_when=an S3 query lacks the word test or holds OR; no_claim=GitHub commit
    search semantics."""
    s3 = [d["q"] for d in R.discovery_queries() if d["family"] == "commits"]
    assert len(s3) == 216 + 9 + 12
    assert all(R._has_test_word(q) or q.endswith((" llm", " openai", " agent")) for q in s3)
    assert all(" test" in q for q in s3[:216]) and not any(" OR " in q for q in s3)
    s2 = [d for d in R.discovery_queries() if d["family"] == "issues"]
    assert len(s2) == 229


# ====================================================================================== discovery

class SearchFake:
    """Code search answering total_count 25,000 for one query and 0 for the others, 100 items a page."""

    def __init__(self, hot: str):
        self.hot, self.n_search, self.paths = hot, {"code": 0, "issues": 0}, []
        self.n_429, self.limit, self.remaining, self.reset = 0, {}, {}, {}

    def get(self, path, search=None):
        self.paths.append(path)
        qd = urllib.parse.parse_qs(path.split("?", 1)[1])
        q, page = qd["q"][0], int(qd.get("page", ["1"])[0])
        if q.startswith(self.hot):
            items = [{"repository": {"full_name": f"o{page}x{i}/r"}, "path": "tests/cassettes/a.yaml",
                      "html_url": "u"} for i in range(100)]
            return 200, {"total_count": 25000, "incomplete_results": False, "items": items}, {}
        return 200, {"total_count": 0, "incomplete_results": False, "items": []}, {}


def test_capped_query(tmp_path, monkeypatch):
    """protects=QUERY_CAP: a query above 20,000 is not bisected, its first 1,000 results are read and the rest enters
    N_s; fails_when=the capped query is bisected or its 24,000 unread hits are not added to N_s;
    no_claim=best-match order is representative."""
    monkeypatch.setattr(discover, "RES", tmp_path)
    monkeypatch.setattr(discover, "DISC", tmp_path / "discovery")
    hot = "api.openai.com path:cassettes"
    pp = {d["key"]: {"family": "code", "stratum": "S1", "status": 200, "total_count": 25000 if d["key"] == hot else 0}
          for d in R.discovery_queries() if d["family"] == "code"}
    (tmp_path / "prepass_code.json").write_text(json.dumps(pp))
    (tmp_path / "prepass_text.json").write_text(json.dumps({}))
    (tmp_path / "launch.json").write_text(json.dumps({"launch": "2026-11-26", "at": "x"}))
    fake = SearchFake(hot)
    monkeypatch.setattr(discover, "_client", lambda route: fake)
    assert discover.run("code", "session", 60, None) == 0
    leaves = discover.read_leaves()
    hotleaf = [lf for lf in leaves if lf["query"] == hot]
    assert len(hotleaf) == 1 and hotleaf[0]["capped_query"] and hotleaf[0]["read"] == 1000
    hot_qs = [urllib.parse.parse_qs(p.split("?")[1])["q"][0] for p in fake.paths]
    hot_qs = [q for q in hot_qs if q.startswith(hot)]
    assert len(hot_qs) == 10 and all(q == f"{hot} size:0..400000" for q in hot_qs)  # never bisected
    st = {"code": json.loads((tmp_path / "discovery_state_code.json").read_text()), "text": {}}
    rows, orders, pool = discover.build(leaves, st, {k: v for k, v in pp.items()})
    assert pool["S1"]["missing"] == 24000 and pool["S1"]["N"] == 1000 + 24000
    assert pool["S1"]["capped_queries"] == [hot]


def test_date_ranges_replace_qualifier():
    """protects=§1 date bisection replaces the created:/committer-date: qualifier; fails_when=a second date qualifier
    is added; no_claim=GitHub's date parsing."""
    d = {"family": "issues", "q": f"{R.ISSUES_PREFIX} flaky llm test"}
    q = R.ranged_query(d, "2024-01-01", "2025-06-30")
    assert q.count("created:") == 1 and "created:2024-01-01..2025-06-30" in q
    c = {"family": "commits", "q": f"{R.COMMITS_PREFIX} flaky llm test"}
    assert R.ranged_query(c, "2024-01-01", "2024-01-01").count("committer-date:") == 1
    assert discover.split(d, "2024-01-01", "2024-01-03") == [["2024-01-01", "2024-01-02"], ["2024-01-03",
                                                                                            "2024-01-03"]]
    assert discover.split(d, "2024-01-01", "2024-01-01") is None


def test_s1_wins_over_s2():
    """protects=§1 strata: a repository belongs to the first stratum it appears in, and keeps every hit;
    fails_when=a repository found in S1 and S2 is put in S2 or loses its S2 hit; no_claim=nothing about S3 order."""
    leaves = [{"query": "issues q", "stratum": "S2", "a": "x", "b": "y", "items": [
        {"repo": "Acme/Agent", "url": "https://github.com/Acme/Agent/issues/1", "kind": "issue"}]},
        {"query": "code q", "stratum": "S1", "a": 0, "b": 1, "items": [
            {"repo": "acme/agent", "path": "tests/cassettes/a.yaml", "url": "u"}]}]
    rows, orders, _ = discover.build(leaves, {}, {})
    assert len(rows) == 1 and rows[0]["stratum"] == "S1" and len(rows[0]["hits"]) == 2
    assert orders["S1"] == [0] and orders["S2"] == []


def test_order_reproducible_no_repeats():
    """protects=§1 order (sort by html_url, Random(1).shuffle, phases); fails_when=two runs differ or a repository
    repeats; no_claim=randomness quality."""
    repos = [{"html_url": f"https://github.com/o/r{i}", "idx": i} for i in range(700)]
    a = [r["idx"] for r in R.stratum_order(repos)]
    b = [r["idx"] for r in R.stratum_order(list(reversed(repos)))]
    assert a == b and len(set(a)) == 700
    s = R.static_order(list(range(400)), list(range(1000, 1350)), list(range(2000, 2100)))
    assert len(s) == len(set(s)) == 850 and s[:300] == list(range(300)) and s[300:302] == [1000, 2000]
    nxt = R.plan_next({"S1": list(range(400)), "S2": [1000, 1001], "S3": [2000]}, set(range(290)), {"S1": 290})
    assert nxt == list(range(290, 300))
    nxt = R.plan_next({"S1": list(range(400)), "S2": [1000, 1001], "S3": [2000]}, set(range(300)), {"S1": 300})
    assert nxt == [1000, 2000, 1001]


# ====================================================================================== decision

def test_wilson_values():
    """protects=§5 Wilson upper bound; fails_when=q=0, r=300 is not about 0.01264 or U x 1,000 not about 12.6;
    no_claim=the bound's coverage under dependence."""
    u = R.wilson_upper(0, 300)
    assert abs(u - 0.01264) < 1e-5 and abs(u * 1000 - 12.6) < 0.05
    b = R.stratum_bound(0, 300, 1000, False, True, False)
    assert b["how"] == "wilson" and abs(b["B"] - 12.64) < 0.01


def test_full_stratum_uses_count_truncated_undefined():
    """protects=§5 B_s cases; fails_when=a fully read untruncated stratum does not use A_s, or a truncated stratum
    has a bound before 300 reads; no_claim=nothing about incomplete leaves beyond undefined."""
    assert R.stratum_bound(4, 120, 130, True, False, False)["B"] == 4.0
    assert R.stratum_bound(4, 120, 130, True, True, False)["B"] is None
    assert R.stratum_bound(4, 299, 5000, False, True, False)["B"] is None
    assert R.stratum_bound(4, 300, 5000, False, True, True)["B"] is None


def test_decision_branches():
    """protects=§5 decision lines as the founder's "lettura A" (2026-11-26 19:01Z; coordinator 19:04Z) sets them:
    CONTINUE at 50, no DROP before the stop, at the stop NOT ENOUGH DATA unless the summed Wilson 95% upper bound over
    the candidate pool is below 50 (then DROP), NO DECISION only when reading never started; fails_when=a DROP comes
    before the stop, the budget end still gives DROP (memo line), or the projection uses N_s instead of candidates;
    no_claim=the threshold is right (memo, ASSUMED)."""
    big = {"S1": {"yes": 0, "A": 0, "read": 12, "candidates": 12, "all_read": True},
           "S2": {"yes": 8, "A": 9, "read": 825, "candidates": 113511, "all_read": False},
           "S3": {"yes": 1, "A": 1, "read": 75, "candidates": 50005, "all_read": False}}
    small = {"S1": {"yes": 0, "A": 0, "read": 12, "candidates": 12, "all_read": True},
             "S2": {"yes": 2, "A": 2, "read": 4000, "candidates": 9000, "all_read": False},
             "S3": {"yes": 0, "A": 0, "read": 3000, "candidates": 4000, "all_read": False}}
    base = {"yes": 9, "handcheck_ok": True, "strata": big, "read_started": True}
    # CONTINUE at 50, before or at the stop
    assert R.decide({**base, "yes": 50, "state": {}})["kind"] == "CONTINUE"
    assert R.decide({**base, "yes": 50, "state": {"hard_stop": True}})["kind"] == "CONTINUE"
    # no DROP before the stop, however low the upper bound; the withdrawn 24 h budget end changes nothing
    assert R.decide({**base, "strata": small, "state": {}})["kind"] == "IN PROGRESS"
    assert R.decide({**base, "state": {"budget_end": True}})["kind"] == "IN PROGRESS"
    # at the stop: NOT ENOUGH DATA with read count, rate and projection; DROP only when the upper bound is below 50
    d = R.decide({**base, "state": {"hard_stop": True}})
    assert d["kind"] == "NOT ENOUGH DATA" and d["first"] == "DONE"
    p = d["projection"]
    assert p["read"] == 912 and p["upper"] >= 50 and p["lower"] <= p["point"] <= p["upper"]
    assert "912 read" in d["line"] and "upper" in d["line"]
    d = R.decide({**base, "yes": 2, "strata": small, "state": {"hard_stop": True}})
    assert d["kind"] == "DROP" and d["projection"]["upper"] < 50
    # a fully read stratum projects its own count
    assert R.project({"S1": {"yes": 3, "A": 4, "read": 12, "candidates": 12, "all_read": True}})["upper"] == 4
    # NO DECISION only when reading never started
    d = R.decide({**base, "read_started": False, "state": {"prepass_stop": True}})
    assert d["kind"] == "NO DECISION" and d["first"] == "NOT DONE"
    d = R.decide({**base, "read_started": False, "state": {"hard_stop": True}})
    assert d["kind"] == "NO DECISION"
    assert R.decide({**base, "state": {"blocked": True}})["first"] == "BLOCKED"
    assert R.decide({**base, "yes": 50, "handcheck_ok": False, "state": {}})["kind"] == "IN PROGRESS"
    assert R.decide({**base, "handcheck_ok": False, "state": {"hard_stop": True}})["kind"] == "IN PROGRESS"


def test_excluded_not_read_and_owner_list():
    """protects=§1 exclusions; fails_when=an excluded candidate (library owner, fork, stale) is counted as read;
    no_claim=the list holds every library repository."""
    row, _ = run(Fake({"requirements.txt": REQ}, repo="langchain-ai/langgraph"))
    assert row["cls"] == "excluded" and row["excluded"] == ["library-owner"]
    row, _ = run(Fake({"requirements.txt": REQ}, meta={"pushed_at": "2025-12-31T00:00:00Z"}))
    assert row["cls"] == "excluded" and "stale" in row["excluded"]
    assert P.excluded({"full_name": "google/adk-java", "pushed_at": "2026-02-01"}, "google/adk-java")
    assert not P.excluded({"full_name": "Netflix/other", "pushed_at": "2026-02-01"}, "Netflix/other")


# ====================================================================================== report / verify / rules 9

def _write_results(tmp: Path):
    """Two strata of rows from fakes: a recording member, a member with a confirmed text, an uncertain, an excluded."""
    res = tmp / "results"
    (res / "raw").mkdir(parents=True)
    p = "tests/cassettes/a.yaml"
    fakes = [member_fake({p: vcr_yaml()}, {p: "2025-01-01T00:00:00Z"}),
             member_fake(), Fake({"pyproject.toml": "[x", ".github/workflows/ci.yml": CI_PY}),
             Fake({"requirements.txt": REQ}, meta={"fork": True})]
    names = ["a/rec", "b/text", "c/unc", "d/fork"]
    cands = []
    for i, (f, nm) in enumerate(zip(fakes, names)):
        f.raw = {k.replace(f.repo, nm): (dict(v, full_name=nm) if k == f"repos/{f.repo}" else v)
                 for k, v in f.raw.items()}
        f.repo = nm
        stratum = "S1" if i in (0, 2) else "S2"
        hits = [] if stratum == "S1" else [{"stratum": "S2", "query": "q", "kind": "issue",
                                            "url": f"https://github.com/{nm}/issues/1", "number": 1,
                                            "title": "flaky LLM test", "body": "openai answers vary",
                                            "created_at": "2025-03-01T00:00:00Z"}]
        cand = {"idx": i, "repo": nm, "html_url": f"https://github.com/{nm}", "stratum": stratum, "hits": hits}
        cands.append(cand)
        src = P.LiveSource(f)
        row = P.run_candidate(src, cand, {})
        row.update(chunk=1, requests=src.core, read_at="2026-12-01T00:00:00+00:00")
        with open(res / "rows.jsonl", "a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        with gzip.open(res / "raw" / "1.jsonl.gz", "at") as fh:
            fh.write(json.dumps({"idx": i, "repo": nm, "opts": {}, "responses": src.responses}) + "\n")
    with gzip.open(res / "candidates.jsonl.gz", "wt") as fh:
        for c in cands:
            fh.write(json.dumps(c) + "\n")
    (res / "orders.json").write_text(json.dumps({"S1": [0, 2], "S2": [1, 3], "S3": []}))
    (res / "pool.json").write_text(json.dumps({s: {"candidates": n, "N": n, "missing": 0, "truncated_leaves": 0,
                                                   "incomplete_leaves": 0, "capped_queries": [], "unfinished": []}
                                               for s, n in (("S1", 2), ("S2", 2), ("S3", 0))}))
    srec = {"repo": "b/text", "query_repo": "b/text", "chunk": 1, "route": "session", "at": "t1",
            "queries": [{"q": "x", "kind": "issues", "status": 200, "total_count": 0, "read": 0, "incomplete": False,
                         "capped": False}], "hits": []}
    (res / "texts_search.jsonl").write_text(json.dumps(srec) + "\n")
    url = "https://github.com/b/text/issues/1"
    (res / "reads.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"url": url, "reader": "first", "label": "confirmed", "reason": "varying-output", "quote": "openai answers vary",
         "chunk": 1, "at": "2026-12-01T01:00:00+00:00"},
        {"url": url, "reader": "second", "label": "confirmed", "chunk": 1, "at": "2026-12-01T02:00:00+00:00"}]) + "\n")
    return res


def test_report_counts_and_verify_roundtrip(tmp_path):
    """protects=AC3 (report numbers recomputed, rows replayed from raw) and §5 A_s counting uncertain and pain yes;
    fails_when=a row differs from its replay, a number differs from the recount, or A_s skips uncertain;
    no_claim=the committed run's numbers (checked by verify.py on the real rows)."""
    res = _write_results(tmp_path)
    d = report.load(res)
    x = report.compute(d)
    assert x["strata"]["S1"]["A"] == 2 and x["strata"]["S1"]["read"] == 2  # recording yes + uncertain
    assert x["strata"]["S2"]["read"] == 1 and x["strata"]["S2"]["excluded"] == 1  # the fork is not read
    assert [m["pain"]["pain"] for m in x["members"]] == ["yes", "yes"]
    text, _ = report.render(d)
    (tmp_path / "REPORT.md").write_text(text)
    assert verify.main(["--res", str(res), "--report", str(tmp_path / "REPORT.md")]) == 0
    (tmp_path / "REPORT.md").write_text(text.replace("pain yes 2<!--yes-->", "pain yes 3<!--yes-->"))
    assert verify.main(["--res", str(res), "--report", str(tmp_path / "REPORT.md")]) == 1


def test_unknown_counts_in_A(tmp_path):
    """protects=§5 A_s includes pain unknown; fails_when=a member whose texts were never searched counts as no;
    no_claim=nothing about the reason mix."""
    res = _write_results(tmp_path)
    (res / "texts_search.jsonl").unlink()
    (res / "reads.jsonl").unlink()
    x = report.compute(report.load(res))
    m = [m for m in x["members"] if m["row"]["repo"] == "b/text"][0]
    assert m["pain"]["pain"] == "unknown" and "texts-missing" in m["pain"]["why"]
    assert x["strata"]["S2"]["A"] == 1


def test_no_search_before_budget_free(tmp_path, monkeypatch):
    """protects=rule 9 / AC1 and the coordinator's split budget (D1 = A): no search before the message, code search
    and session-token search refused until freed; fails_when=a search reaches the transport outside the freed
    scopes; no_claim=nothing about REST."""
    monkeypatch.setattr(ghapi, "BUDGET_FREE", tmp_path / "missing.json")
    c = ghapi.Client(token="x")
    monkeypatch.setattr(c, "_once", lambda path: pytest.fail("transport reached"))
    for path, kind in (("search/code?q=a", "code"), ("search/issues?q=a", "issues"), ("search/commits?q=a", "issues")):
        with pytest.raises(ghapi.SearchRefused):
            c.get(path, search=kind)
    bf = tmp_path / "bf.json"
    bf.write_text(json.dumps({"scopes": ["text-workflow"]}))
    monkeypatch.setattr(ghapi, "BUDGET_FREE", bf)
    with pytest.raises(ghapi.SearchRefused):
        c.get("search/code?q=a", search="code")
    g = ghapi.Client(use_gh=True)
    monkeypatch.setattr(g, "_once", lambda path: pytest.fail("transport reached"))
    with pytest.raises(ghapi.SearchRefused):
        g.get("search/issues?q=a", search="issues")
    monkeypatch.setattr(c, "_once", lambda path: (200, {}, {"total_count": 0, "items": []}))
    monkeypatch.setattr(c, "_wait", lambda search: None)
    assert c.get("search/commits?q=a", search="issues")[0] == 200


def test_probe_decide_text_only_and_commits_gate():
    """protects=partial probes (D1 = A): workflow-only issues/commits probes give the workflow text route and no
    BLOCKED while code search is pending; a failing commits probe holds S3 back; fails_when=decide blocks or keeps
    S3; no_claim=GitHub answers."""
    import probe
    W = [{"id": "c-issues", "status": 200, "total_count": 3}, {"id": "c-commits", "status": 422}]
    d = probe.decide([], W, [])
    assert not d["blocked"] and d["code_pending"] and d["issues_route"] == "workflow"
    assert d["commits_route"] is None
    assert not any(q["family"] == "commits" for q in discover.family_queries("text", d))


def test_get_only_and_retry_seconds(monkeypatch, tmp_path):
    """protects=AC5 (GET only; 429 waits parsed from the message as f2e649b, ms winning over Retry-After);
    fails_when=a request uses another method or the ms wait is misread; no_claim=GitHub's message format is stable."""
    assert abs(ghapi.retry_seconds("try again in 581.6ms", {"retry-after": "60"}) - 2.5816) < 1e-6
    assert ghapi.retry_seconds("try again in 7.9s", {}) == pytest.approx(9.9)
    assert ghapi.retry_seconds("", {"retry-after": "30"}) == 30
    import inspect
    src = inspect.getsource(ghapi)
    assert 'method="GET"' in src and '"-X", "GET"' in src and "POST" not in src
    for mod in (P, T, discover, report):
        assert "method=" not in inspect.getsource(mod).replace('method="GET"', "")


def test_prereg_appendix_matches_rules():
    """protects=PREREG lists every query and regex verbatim (AC1, rule 3); fails_when=rules.py changes a query or
    regex without PREREG.md's appendix being regenerated; no_claim=that the change was listed in CHANGES.md."""
    import prereg_appendix
    assert (HERE / "PREREG.md").read_text().endswith(prereg_appendix.appendix())


def test_workflow_trigger_and_owned_files():
    """protects=§0.3 trigger (push to this branch, request paths only) and the commit-back scope; fails_when=the
    workflow runs on another branch or event, or its commit step adds files the work session writes (reads, searches,
    discovery state); no_claim=GitHub's runner behaviour."""
    import yaml
    wf = (HERE.parent.parent / ".github/workflows/agent-determinism-count.yml").read_text()
    assert "commit_results.sh" in wf
    script = (HERE / "commit_results.sh").read_text()
    d = yaml.safe_load(wf)
    on = d[True]
    assert list(on) == ["push"] and on["push"]["branches"] == ["claude/agent-determinism-count"]
    assert on["push"]["paths"] == ["harness/agent_determinism_count/requests/**"]
    own = [ln for ln in script.splitlines() if ln.strip().startswith('own="')][0]
    for session_file in ("reads.jsonl", "texts_search.jsonl ", "discovery_state_code", "leaves_code", "prepass_code",
                         "search_budget_free", "handcheck", "probe_session", "probe_decisions", "candidates.jsonl.gz"):
        assert session_file not in own
    # the build moved to the workflow (2026-11-26, CHANGES.md item 9): it commits pool, orders and the candidates index
    assert all(f in own for f in ("pool.json", "orders.json", "candidates_index.json"))
    # the S1 code workflow: its own requests, group and markers; it never commits the text family's or session files
    wfc = yaml.safe_load((HERE.parent.parent / ".github/workflows/agent-determinism-count-code.yml").read_text())
    assert wfc[True]["push"]["paths"] == ["harness/agent_determinism_count/requests_code/**"]
    assert wfc["concurrency"]["group"] != d["concurrency"]["group"]
    assert wfc["env"]["ADC_FAMILY"] == "code" and wfc["env"]["ADC_DONE"] == "requests_done_code"
    own_code = [ln for ln in script.splitlines() if ln.strip().startswith('own_code="')][0]
    for f in ("_text", "requests_done ", "reads.jsonl", "search_budget_free", "candidates", "leaves_"):
        assert f not in own_code + " "
    assert "--ignore-removal" in script


# ====================================================================================== review fixes (/review cycle 1)

def test_undated_recording_hit_is_unknown():
    """protects=rules that could hide pain go to unknown (a host hit whose last commit cannot be dated);
    fails_when=an undated cassette hit leaves pain no; no_claim=why GitHub returns no commit."""
    p = "tests/cassettes/a.yaml"
    f = member_fake({p: vcr_yaml()})
    f.raw["repos/acme/agent/commits?" + urllib.parse.urlencode({"path": p, "sha": "main", "per_page": 1})] = []
    row, _ = run(f)
    assert "recording-undated" in row["pain_flags"]
    assert R.member_pain(None, row["pain_flags"], [], {})["pain"] == "unknown"


def test_oversize_recording_unread_is_unknown(monkeypatch):
    """protects=blob size cap without hiding pain; fails_when=a recording too large to fetch is fetched or leaves
    pain no; no_claim=the cap value."""
    monkeypatch.setattr(R, "RECORDING_MAX", 10)
    row, _ = run(member_fake({"tests/cassettes/big.yaml": vcr_yaml()}))
    assert row["recordings"]["fetched"] == 0 and "recording-unread" in row["pain_flags"]


def test_step_unmatched_is_uncertain():
    """protects=§2.3: a concluded job whose test step is not found among the API steps -> uncertain;
    fails_when=a renamed step makes the repository a non-member; no_claim=step renames are rare."""
    f = Fake({"requirements.txt": REQ, ".github/workflows/ci.yml": CI_PY})
    f.runs("ci.yml", [ok_run(step="Renamed")])
    row, _ = run(f)
    assert row["cls"] == "uncertain" and "uncertain-step-unmatched" in row["why"]


def test_pain_stage_cap_and_api_error_unknown():
    """protects=§2.4 in the pain read: cap or API error -> pain unknown; fails_when=either flag is dropped;
    no_claim=nothing about which file would have hit."""
    extra = {f"tests/cassettes/c{i}.yaml": vcr_yaml("api.github.com") for i in range(5)}
    f = member_fake(extra)
    _, src = run(member_fake())
    row, _ = run(f, cap=src.core + 2)
    assert row["cls"] == "member" and "request-cap" in row["pain_flags"]
    f2 = member_fake(extra)
    sha = f2.sha("tests/cassettes/c0.yaml", {"tests/cassettes/c0.yaml": vcr_yaml("api.github.com")})
    del f2.raw[f"repos/acme/agent/git/blobs/{sha}"]
    f2.raw = dict(f2.raw)
    row2, _ = run(f2)
    assert "api-error" in row2["pain_flags"]
    assert R.member_pain(None, row2["pain_flags"], [], {})["pain"] == "unknown"


def test_unexpected_manifest_shape_is_manifest_error():
    """protects=replayable rows: a manifest with an unexpected shape is a manifest-error, not a crash;
    fails_when=optional-dependencies as a list raises; no_claim=every malformed shape."""
    with pytest.raises(R.ManifestError):
        R.parse_manifest("pyproject.toml", '[project]\noptional-dependencies = ["x"]\n')
    row, _ = run(Fake({"pyproject.toml": '[project]\noptional-dependencies = ["x"]\n'}))
    assert row["cls"] == "uncertain"


def test_unexpected_exception_row_replays():
    """protects=AC3 replay of error rows; fails_when=an unexpected response shape crashes the chunk or the replay
    differs; no_claim=which shapes GitHub sends."""
    f = member_fake()
    f.raw["repos/acme/agent"]["default_branch"] = None
    src = P.LiveSource(f)
    row = P.run_candidate(src, {"idx": 0, "repo": "acme/agent", "stratum": "S1"}, {})
    assert row["cls"] == "uncertain" and row["stage"] == "error"
    again = P.run_candidate(P.ReplaySource(src.responses), {"idx": 0, "repo": "acme/agent", "stratum": "S1"}, {})
    assert again == row


def test_nested_workflow_call_and_truncated_no_ci_uncertain():
    """protects=§2.3 conservative paths; fails_when=a callee called only by another reusable workflow, or a
    truncated tree without CI evidence, gives no-ci-tests; no_claim=multi-level resolution."""
    callee = CI_PY.replace("on: [push, pull_request]", "on: workflow_call")
    mid = "on: workflow_call\njobs:\n  call:\n    uses: ./.github/workflows/callee.yml\n"
    f = Fake({"requirements.txt": REQ, ".github/workflows/callee.yml": callee, ".github/workflows/mid.yml": mid})
    row, _ = run(f)
    assert row["cls"] == "uncertain"
    f2 = Fake({"requirements.txt": REQ}, truncated=True,
              listing={"": ["requirements.txt"], ".github/workflows": []})
    row2, _ = run(f2)
    assert row2["cls"] == "uncertain" and "tree-truncated" in row2["why"]


def test_on_unparsed_flag_without_test_word():
    """protects=PREREG §2.3: an on: that is not a string/list/mapping -> uncertain unconditionally;
    fails_when=it is dropped when the file lacks 'test'; no_claim=YAML errors without 'test' (still ignored)."""
    wf = "on: 5\njobs:\n  ci:\n    runs-on: x\n    steps:\n      - run: make check\n"
    row, _ = run(Fake({"requirements.txt": REQ, ".github/workflows/ci.yml": wf}))
    assert row["cls"] == "uncertain"


def test_empty_stratum_counts_and_shape_dropped(tmp_path):
    """protects=§5 B_s for an empty stratum (count 0, so the statistical DROP can fire) and the §0.2b dropped
    §3.2 shape -> unknown; fails_when=S3 is undefined with no candidates, or a dropped shape allows pain no;
    no_claim=nothing about non-empty strata."""
    res = _write_results(tmp_path)
    x = report.compute(report.load(res))
    assert x["strata"]["S3"]["how"] == "count" and x["strata"]["S3"]["B"] == 0.0
    (res / "probe_decisions.json").write_text(json.dumps({"repo_text_shapes_ok": False}))
    (res / "reads.jsonl").unlink()
    x = report.compute(report.load(res))
    m = [m for m in x["members"] if m["row"]["repo"] == "b/text"][0]
    assert "text-shape-dropped" in m["pain"]["why"] and m["pain"]["pain"] == "unknown"


def test_probe_or_check_requires_answers():
    """protects=§0.2b never recorded as 0: an errored OR probe splits the queries; fails_when=missing OR probes
    give or_ok True or a 0-hit repository shape counts as fine; no_claim=GitHub's semantics."""
    import probe
    S = [{"id": i, "status": 200, "total_count": 5} for i in ("a1", "c-issues", "c-commits", "b-code-cassette",
                                                              "b-code-recordings", "b-code-vcr")]
    S += [{"id": "b-r-issues-pain", "status": 200, "total_count": 0}]
    d = probe.decide(S, [], [])
    assert d["issues_or_ok"] is False and d["commits_or_ok"] is False and d["repo_text_shapes_ok"] is False


def test_readers_tolerate_truncated_files_and_verify_last_raw(tmp_path):
    """protects=a job killed mid-write: a partial last line is dropped, a raw record without a row is ignored and
    the last raw record per candidate is replayed; fails_when=readers raise or verify reports a mismatch;
    no_claim=gzip corruption in the middle of a file."""
    p = tmp_path / "x.jsonl"
    p.write_text('{"a": 1}\n{"a": ')
    assert report._jsonl(p) == [{"a": 1}]
    res = _write_results(tmp_path)
    with gzip.open(res / "raw" / "1.jsonl.gz", "at") as fh:
        fh.write(json.dumps({"idx": 99, "repo": "z/z", "opts": {}, "responses": {}}) + "\n")
    text, _ = report.render(report.load(res))
    (tmp_path / "REPORT.md").write_text(text)
    assert verify.main(["--res", str(res), "--report", str(tmp_path / "REPORT.md")]) == 0


def test_rate_sleep_past_deadline_stops(monkeypatch, tmp_path):
    """protects=the job-wide deadline: a rate-limit sleep that would pass it raises DeadlineReached instead of
    sleeping into the job timeout; fails_when=the client sleeps; no_claim=GitHub's reset times."""
    import time as _t
    c = ghapi.Client(token="x")
    c.deadline = _t.time() + 10
    monkeypatch.setattr(_t, "sleep", lambda s: pytest.fail("slept"))
    with pytest.raises(ghapi.DeadlineReached):
        c._sleep(600)


def test_search_hits_of_other_repositories_dropped():
    """protects=§3.2 texts are the member's own (probe p1 showed repo: scope leaking around parentheses);
    fails_when=a repository-search hit from another repository becomes a text candidate of the member;
    no_claim=GitHub's parser."""
    own = {"kind": "issue", "url": "https://github.com/acme/agent/issues/1", "repo": "Acme/Agent", "number": 1,
           "title": "flaky LLM test", "body": "", "created_at": "2025-01-01T00:00:00Z"}
    other = dict(own, url="https://github.com/x/y/issues/2", repo="x/y")
    tx = T.member_texts("acme/agent", [], {"queries": [], "hits": [own, other]})
    assert [t["url"] for t in tx] == [own["url"]]


# ====================================================================================== leaf files outside git (parts.py)

def _parts_env(tmp_path, monkeypatch):
    import parts
    monkeypatch.setattr(parts, "RES", tmp_path)
    monkeypatch.setattr(parts, "DISC", tmp_path / "discovery")
    monkeypatch.setattr(parts, "CACHE", tmp_path / ".artifacts")
    monkeypatch.setattr(discover, "RES", tmp_path)
    monkeypatch.setattr(discover, "DISC", tmp_path / "discovery")
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    (tmp_path / "discovery").mkdir()
    (tmp_path / ".artifacts").mkdir()
    return parts


def _gz_lines(recs):
    import io
    b = io.BytesIO()
    with gzip.open(b, "wt") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return b.getvalue()


def _leaf(q, a):
    return {"query": q, "stratum": "S2", "a": a, "b": a, "items": [{"repo": f"o/{a}", "url": f"u{a}"}]}


def test_leaf_parts_index_and_read(tmp_path, monkeypatch):
    """protects=leaf files outside git: leaves are written per run under leaves_<family>/, the committed index holds
    their sha256 and line count, and the build reads the parts plus the pre-parts single file (a cut last line is
    skipped); fails_when=a leaf is written to the single file that outgrew GitHub's 100 MB limit, or a part is not read;
    no_claim=artifact retention."""
    parts = _parts_env(tmp_path, monkeypatch)
    assert parts.part_path("text", tmp_path / "discovery").name == "text-77.jsonl.gz"
    (tmp_path / "discovery" / "leaves_text.jsonl.gz").write_bytes(_gz_lines([_leaf("q", "1")]))
    p = parts.part_path("text", tmp_path / "discovery")
    p.parent.mkdir(parents=True)
    p.write_bytes(_gz_lines([_leaf("q", "1"), _leaf("q", "2")]) + gzip.compress(b'{"query": "q", "cut'))
    ix = parts.index("text")
    e = ix["text-77.jsonl.gz"]
    assert e["run_id"] == "77" and e["artifact"] == "agent-determinism-count-leaves-77" and e["lines"] >= 2
    assert e["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert json.loads((tmp_path / "discovery" / "leaf_parts_text.json").read_text()) == ix
    got = sorted(lf["a"] for lf in discover.read_leaves())
    assert got == ["1", "2"]  # deduplicated per (query, a, b); the cut line is dropped


def _zip(path, members):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        for n, b in members.items():
            z.writestr(n, b)


def test_restore_from_results_artifact(tmp_path, monkeypatch):
    """protects=no lost discovery work: a run whose leaf file could not be pushed is resumed from its results
    artifact (state, splits, pre-pass and leaves together), once, and never over a local state that is further;
    fails_when=the next run resumes from an older committed state, mixes state and leaves of different times, or
    restores twice; no_claim=the Actions API itself (downloads are faked by a cached zip)."""
    parts = _parts_env(tmp_path, monkeypatch)
    st = {"queries": {"q": {"nodes": 5, "stack": []}}, "started": "s"}
    _zip(tmp_path / ".artifacts" / "agent-determinism-count-results-9.zip", {
        "discovery_state_text.json": json.dumps(st), "discovery/splits_text.jsonl": "{}\n",
        "prepass_text.json": "{}", "discovery/leaves_text.jsonl.gz": _gz_lines([_leaf("q", "1")])})
    (tmp_path / "discovery_state_text.json").write_text(json.dumps({"queries": {"q": {"nodes": 2}}}))
    (tmp_path / "discovery" / "restore_text.json").write_text(json.dumps({"run_id": 9}))
    assert parts.restore("text") == 0
    assert json.loads((tmp_path / "discovery_state_text.json").read_text()) == st
    leaf = tmp_path / "discovery" / "leaves_text" / "text-9.jsonl.gz"
    ix = json.loads((tmp_path / "discovery" / "leaf_parts_text.json").read_text())
    assert ix["text-9.jsonl.gz"]["artifact"] == "agent-determinism-count-results-9"
    assert ix["text-9.jsonl.gz"]["artifact_path"] == "discovery/leaves_text.jsonl.gz" and leaf.exists()
    spec = json.loads((tmp_path / "discovery" / "restore_text.json").read_text())
    assert spec["restored_at"] and spec["nodes"] == 5 and spec["leaves"] == 1
    (tmp_path / "discovery_state_text.json").write_text("{}")
    assert parts.restore("text") == 0 and (tmp_path / "discovery_state_text.json").read_text() == "{}"  # once
    # a local state further than the artifact is never replaced
    (tmp_path / "discovery" / "restore_text.json").write_text(json.dumps({"run_id": 9}))
    (tmp_path / "discovery_state_text.json").write_text(json.dumps({"queries": {"q": {"nodes": 8}}}))
    assert parts.restore("text") == 1
    assert json.loads((tmp_path / "discovery_state_text.json").read_text())["queries"]["q"]["nodes"] == 8


def test_fetch_parts_checks_sha(tmp_path, monkeypatch):
    """protects=the build reads exactly the leaves the runs wrote: every indexed part missing here is taken from its
    artifact and its sha256 checked; fails_when=a changed or missing part is read silently; no_claim=network."""
    parts = _parts_env(tmp_path, monkeypatch)
    body = _gz_lines([_leaf("q", "1")])
    _zip(tmp_path / ".artifacts" / "agent-determinism-count-leaves-5.zip", {"text-5.jsonl.gz": body})
    ixp = tmp_path / "discovery" / "leaf_parts_text.json"
    e = {"run_id": "5", "artifact": "agent-determinism-count-leaves-5", "artifact_path": "text-5.jsonl.gz",
         "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "lines": 1}
    ixp.write_text(json.dumps({"text-5.jsonl.gz": e}))
    assert parts.fetch("text") == 0
    assert (tmp_path / "discovery" / "leaves_text" / "text-5.jsonl.gz").read_bytes() == body
    (tmp_path / "discovery" / "leaves_text" / "text-5.jsonl.gz").unlink()
    ixp.write_text(json.dumps({"text-5.jsonl.gz": {**e, "sha256": "0" * 64}}))
    assert parts.fetch("text") == 1


def test_leaf_files_never_committed():
    """protects=checkpoint commits stay under GitHub's 100 MB file limit; fails_when=the commit step adds a leaf file
    or the results artifact re-uploads earlier runs' leaf parts; no_claim=sizes of other result files."""
    import yaml
    script = (HERE / "commit_results.sh").read_text()
    own = [ln for ln in script.splitlines() if ln.strip().startswith('own="')][0]
    assert "leaves_" not in own and "leaf_parts_text.json" in own and "parts.py index" in script
    wf = yaml.safe_load((HERE.parent.parent / ".github/workflows/agent-determinism-count.yml").read_text())
    assert wf["permissions"] == {"contents": "write", "actions": "read"}
    ups = [s["with"] for s in wf["jobs"]["chunk"]["steps"] if str(s.get("uses", "")).startswith("actions/upload")]
    assert "!harness/agent_determinism_count/results/discovery/leaves_*/" in ups[0]["path"]
    assert ups[1]["path"].endswith("leaves_*/*-${{ github.run_id }}.jsonl.gz")


def test_discovery_pause(tmp_path, monkeypatch):
    """protects=the coordinator's market-protection pause: a discovery request does nothing while
    results/pause_<family>.json has a start and no end; fails_when=a paused family sends a search or marks its request
    done; no_claim=pauses of chunk requests."""
    import job
    monkeypatch.setattr(job, "HERE", tmp_path)
    (tmp_path / "results").mkdir()
    assert not job.paused("text")
    (tmp_path / "results" / "pause_text.json").write_text(json.dumps({"start": "2026-11-25T16:00:00Z"}))
    assert job.paused("text")
    (tmp_path / "results" / "pause_text.json").write_text(json.dumps({"start": "a", "end": "b"}))
    assert not job.paused("text")


def test_code_probe_merge_keeps_text_decisions(tmp_path, monkeypatch):
    """protects=S2/S3 keep running on the decisions they started with when the S1 code probes arrive;
    fails_when=merging the code probes changes a text decision or misses the code route; no_claim=GitHub's answers."""
    import probe
    old = {"text_route": "workflow", "issues_route": "workflow", "commits_route": "workflow", "issues_or_ok": True,
           "commits_or_ok": True, "dropped": [], "fixes": [], "code_route": None, "code_pending": True,
           "recording_packages": ["evalcraft"], "text_shapes": {"b-issues-pm": {"status": 200, "total_count": 5}}}
    (tmp_path / "probe_decisions.json").write_text(json.dumps(old))
    recs = [{"id": i, "kind": "code", "status": 200, "total_count": 7, "paths": ["a/tests/cassettes/x.yaml"]}
            for i in ("a1", "a2", "b-code-cassette", "b-code-recordings", "b-code-vcr", "b-code-pyproject",
                      "b-code-requirements", "b-code-packagejson")]
    (tmp_path / "probe_workflow_code.json").write_text(json.dumps({"route": "workflow", "results": recs}))
    out = probe.merge_code_decisions(tmp_path)
    assert out["code_route"] == "workflow" and out["code_pending"] is False
    for k, v in old.items():
        if k not in probe.CODE_KEYS:
            assert out[k] == v
    recs = [dict(r, status=403) for r in recs]
    (tmp_path / "probe_workflow_code.json").write_text(json.dumps({"route": "workflow", "results": recs}))
    (tmp_path / "probe_decisions.json").write_text(json.dumps(old))
    out = probe.merge_code_decisions(tmp_path)
    assert out["code_route"] is None and out["code_blocked"] and out["text_route"] == "workflow"


def test_code_request_waits_without_workflow_route(tmp_path, monkeypatch, capsys):
    """protects=the coordinator's constraint that S1 uses the workflow route while market reading uses the account
    token; fails_when=a code request searches or is marked done while the code route is not the workflow route;
    no_claim=the route GitHub would answer on."""
    import job
    import chunk
    res = tmp_path / "results"
    res.mkdir()
    (res / "probe_decisions.json").write_text(json.dumps({"code_route": "session"}))
    monkeypatch.setattr(job, "HERE", tmp_path)
    monkeypatch.setattr(chunk, "RES", res)
    monkeypatch.setenv("ADC_DONE", "requests_done_code")
    for i, req in enumerate(({"prepass": "code"}, {"population": True}, {"discovery": "code"})):
        rp = tmp_path / f"c{i}.json"
        rp.write_text(json.dumps(req))
        monkeypatch.setattr(sys, "argv", ["job.py", "--request", str(rp)])
        assert job.main() == 0
    assert not (res / "requests_done_code").exists()
    assert "left pending" in capsys.readouterr().out
    chunk.mark_done("c9.json", {"x": 1})
    assert (res / "requests_done_code" / "c9.json").exists()


def test_rate_limited_code_probe_never_drops_a_shape(tmp_path):
    """protects=§0.2b drop rule (a code shape is dropped on 0 results or an error, not on a rate-limit answer);
    fails_when=a 429 probe (b-code-recordings, 2026-11-26 03:32Z) drops path:recordings or a re-probe answering 200
    does not restore it; no_claim=GitHub's rate limits."""
    import probe
    base = {"code_route": None, "code_pending": True, "text_route": "workflow", "dropped": [], "fixes": []}

    def recs(rec_status, rec_total):
        out = []
        for i in ("a1", "a2", "b-code-cassette", "b-code-recordings", "b-code-vcr", "b-code-pyproject",
                  "b-code-requirements", "b-code-packagejson"):
            r = {"id": i, "kind": "code", "status": 200, "total_count": 5, "paths": []}
            if i == "b-code-recordings":
                r.update(status=rec_status, total_count=rec_total, rate_limited=rec_status == 429)
            out.append(r)
        return out
    old = dict(base, dropped=["api.openai.com path:recordings"], fixes=["code shape path:recordings: x -> dropped"])
    (tmp_path / "probe_decisions.json").write_text(json.dumps(old))
    (tmp_path / "probe_workflow_code.json").write_text(json.dumps({"results": recs(429, None)}))
    out = probe.merge_code_decisions(tmp_path)
    assert not any("path:recordings" in x for x in out["dropped"])
    assert out["code_reprobe"] == ["b-code-recordings"]
    (tmp_path / "probe_workflow_code.json").write_text(json.dumps({"results": recs(200, 3)}))
    out = probe.merge_code_decisions(tmp_path)
    assert out["dropped"] == [] and out["code_reprobe"] == []
    (tmp_path / "probe_workflow_code.json").write_text(json.dumps({"results": recs(200, 0)}))
    out = probe.merge_code_decisions(tmp_path)
    assert "api.openai.com path:recordings" in out["dropped"]


def test_discovery_time_limit_leaves_request_pending(tmp_path, monkeypatch):
    """protects=S2/S3 continuity: a discovery request stopped at max_minutes stays pending so the next run resumes it;
    fails_when=it is marked done before the family finished or reached its budget (d2, 2026-11-26 04:22Z);
    no_claim=how long a run lasts."""
    import job
    import chunk
    import discover
    import parts
    res = tmp_path / "results"
    res.mkdir()
    monkeypatch.setattr(job, "HERE", tmp_path)
    monkeypatch.setattr(chunk, "RES", res)
    monkeypatch.setattr(parts, "restore", lambda fam: 0)
    monkeypatch.setattr(discover, "prepass", lambda fam, route: 0)
    state = {}

    def fake_run(fam, route, mm, dl):
        (res / f"discovery_state_{fam}.json").write_text(json.dumps(state))
        return 0
    monkeypatch.setattr(discover, "run", fake_run)
    rp = tmp_path / "d9.json"
    rp.write_text(json.dumps({"discovery": "text", "max_minutes": 1}))
    monkeypatch.setattr(sys, "argv", ["job.py", "--request", str(rp)])
    assert job.main() == 0 and not (res / "requests_done" / "d9.json").exists()
    state.update(budget_reached="2026-11-26T10:54:28+00:00")
    assert job.main() == 0 and (res / "requests_done" / "d9.json").exists()


def test_session_route_answer_below_workflow_prepass_stops(tmp_path, monkeypatch):
    """protects=the route switch (coordinator 09:30Z): S1 resumes on the session route, and a session answer below the
    workflow route's pre-pass answer for the same root range stops discovery for a report; leaf records carry their
    route; fails_when=a lower session count is bisected on silently; no_claim=why the indexes differ."""
    monkeypatch.setattr(discover, "RES", tmp_path)
    monkeypatch.setattr(discover, "DISC", tmp_path / "discovery")
    keys = [d["key"] for d in R.discovery_queries() if d["family"] == "code"]
    pp = {k: {"family": "code", "stratum": "S1", "status": 200, "total_count": 0} for k in keys}
    (tmp_path / "prepass_code.json").write_text(json.dumps(pp))
    (tmp_path / "prepass_text.json").write_text(json.dumps({}))
    (tmp_path / "launch.json").write_text(json.dumps({"launch": "2026-11-26", "at": "x"}))
    monkeypatch.setattr(discover, "_client", lambda route: SearchFake("none"))
    assert discover.run("code", "session", 60, None) == 0  # equal answers (0 = 0): runs through
    assert all(lf["route"] == "session" for lf in discover.read_leaves())
    (tmp_path / "discovery_state_code.json").unlink()
    pp[keys[1]]["total_count"] = 5
    (tmp_path / "prepass_code.json").write_text(json.dumps(pp))
    assert discover.run("code", "session", 60, None) == 4
    st = json.loads((tmp_path / "discovery_state_code.json").read_text())
    assert st["route_check"]["query"] == keys[1] and st["route_check"]["workflow"] == 5
    assert st["route_check"]["session"] == 0 and not st["queries"][keys[1]]["done"]


def test_cut_gzip_member_and_session_part_in_git(tmp_path, monkeypatch):
    """protects=a cancelled job's leaf file and the work session's committed part: a gzip member cut mid-write keeps
    the leaves before it, and a session part (ADC_PART_ID) is indexed as committed to git, checked by sha256, never
    fetched from an artifact; fails_when=the build crashes on a cut member, or fetch looks for a missing artifact;
    no_claim=network."""
    parts = _parts_env(tmp_path, monkeypatch)
    p = parts.part_path("code", tmp_path / "discovery")
    p.parent.mkdir(parents=True)
    whole = _gz_lines([_leaf("q", "1")])
    p.write_bytes(whole + _gz_lines([_leaf("q", "2")])[:15])
    assert [lf["a"] for lf in discover.read_leaves()] == ["1"]
    p.unlink()
    monkeypatch.delenv("GITHUB_RUN_ID")
    monkeypatch.setenv("ADC_PART_ID", "session")
    sp = parts.part_path("code", tmp_path / "discovery")
    assert sp.name == "code-session.jsonl.gz"
    sp.write_bytes(whole)
    e = parts.index("code")["code-session.jsonl.gz"]
    assert e["artifact"] is None and e["in_git"] == "results/discovery/leaves_code/code-session.jsonl.gz"
    assert parts.fetch("code") == 0
    sp.write_bytes(whole + whole)
    assert parts.fetch("code") == 1


def test_build_streams_leaves_and_keeps_hit_order(tmp_path, monkeypatch):
    """protects=the build over ~1.2 GB of leaf parts: leaves are streamed (last record per (query, a, b) across parts),
    hits keep (stratum, query, a) order and the first hit per (url, query), whatever the file order; the candidates
    file leaves git with a sha256 index; fails_when=a re-run leaf is counted twice, hit order depends on file order, or
    candidates.jsonl.gz is committed; no_claim=memory use itself."""
    parts = _parts_env(tmp_path, monkeypatch)
    d = tmp_path / "discovery" / "leaves_text"
    d.mkdir(parents=True)

    def lf(q, a, items, **kw):
        return {"query": q, "stratum": "S2", "a": a, "b": a, "items": [{"repo": r, "url": u} for r, u in items], **kw}
    (d / "text-2.jsonl.gz").write_bytes(_gz_lines([lf("q", "9", [("o/x", "u9")]),
                                                   lf("q", "1", [("o/x", "u1"), ("o/x", "u1")], truncated=True,
                                                      total_count=50, read=10)]))
    (d / "text-3.jsonl.gz").write_bytes(_gz_lines([lf("q", "1", [("o/x", "u1"), ("o/y", "u2")])]))  # re-run of q/1
    got = list(discover.iter_leaves())
    assert len(got) == 2 and not any(g.get("truncated") for g in got)
    rows, orders, pool = discover.build(iter(got[::-1]), {"text": {}}, {})
    x = [r for r in rows if r["repo"] == "o/x"][0]
    assert [h["url"] for h in x["hits"]] == ["u1", "u9"] and pool["S2"]["candidates"] == 2
    assert pool["S2"]["truncated_leaves"] == 0
    script = (HERE / "commit_results.sh").read_text()
    own = [ln for ln in script.splitlines() if ln.strip().startswith('own="')][0]
    assert "candidates_index.json" in own and "candidates.jsonl.gz" not in own


def test_fetch_candidates_checks_sha(tmp_path, monkeypatch):
    """protects=chunk runs read exactly the built candidates: candidates.jsonl.gz is taken from the build artifact by
    its committed index and its sha256 checked; fails_when=a changed candidates file is read; no_claim=network."""
    parts = _parts_env(tmp_path, monkeypatch)
    assert parts.fetch_candidates() == 0  # no build yet
    body = _gz_lines([{"idx": 0, "repo": "o/x"}])
    _zip(tmp_path / ".artifacts" / "agent-determinism-count-candidates-8.zip", {"candidates.jsonl.gz": body})
    ix = {"run_id": "8", "artifact": "agent-determinism-count-candidates-8", "artifact_path": "candidates.jsonl.gz",
          "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "lines": 1}
    (tmp_path / "candidates_index.json").write_text(json.dumps(ix))
    assert parts.fetch_candidates() == 0 and (tmp_path / "candidates.jsonl.gz").read_bytes() == body
    (tmp_path / "candidates.jsonl.gz").unlink()
    (tmp_path / "candidates_index.json").write_text(json.dumps({**ix, "sha256": "0" * 64}))
    assert parts.fetch_candidates() == 1


def test_s3_extension_runs_only_uncovered_s3_queries(tmp_path, monkeypatch):
    """protects=the founder's S3 extension (2026-11-26): it runs only the S3 queries the 24 h budget left unstarted or
    unfinished (resuming the unfinished one's stack), stops 6 h after its own first request, keeps its own state,
    splits and leaf parts, and the build merges it; fails_when=an S2 or finished S3 query is searched again, the text
    state is rewritten, or the 24 h budget end stops the extension; no_claim=search results themselves."""
    parts = _parts_env(tmp_path, monkeypatch)
    monkeypatch.delenv("GITHUB_RUN_ID")
    monkeypatch.setenv("ADC_PART_ID", "session-1200")
    qs = [d for d in R.discovery_queries() if d["family"] != "code"]
    s2 = [d["key"] for d in qs if d["stratum"] == "S2"][0]
    s3 = [d["key"] for d in qs if d["stratum"] == "S3"]
    pp = {d["key"]: {"family": d["family"], "stratum": d["stratum"], "status": 200, "total_count": 0,
                     "at": "2026-11-25T10:54:28+00:00"} for d in qs}
    (tmp_path / "prepass_text.json").write_text(json.dumps(pp))
    (tmp_path / "prepass_code.json").write_text(json.dumps({}))
    (tmp_path / "launch.json").write_text(json.dumps({"launch": "2026-11-25", "at": "x"}))
    done = {"stack": [], "done": True, "capped": False, "prepass_total": 0, "nodes": 1, "leaves": 1, "leaf_total": 0}
    open_q = {"stack": [["2024-01-01", "2024-06-30"]], "done": False, "capped": False, "prepass_total": 0,
              "nodes": 3, "leaves": 2, "leaf_total": 0}
    text_st = {"started": "2026-11-25T10:54:28+00:00", "finished": None, "budget_reached": "2026-11-26T11:00:43",
               "queries": {s2: done, s3[0]: done, s3[1]: open_q}}
    (tmp_path / "discovery_state_text.json").write_text(json.dumps(text_st))
    fake = SearchFake("none")
    monkeypatch.setattr(discover, "_client", lambda route: fake)
    assert discover.run("text", "session", 60, None, ext=True) == 0
    asked = {urllib.parse.parse_qs(p.split("?")[1])["q"][0] for p in fake.paths}
    assert not any(q.startswith(s2) or q.startswith(s3[0]) for q in asked)
    assert any("2024-01-01..2024-06-30" in q for q in asked)  # the unfinished query's stack resumed
    assert json.loads((tmp_path / "discovery_state_text.json").read_text()) == text_st
    xs = json.loads((tmp_path / "discovery_state_s3ext.json").read_text())
    xe = xs["extension"]
    assert xs["finished"] and xe["resumed_from_text_state"] == [s3[1]]
    assert dt_hours(xe["first_request"], xe["hard_stop"]) == 6.0
    assert set(xs["queries"]) == set(s3[1:]) and (tmp_path / "discovery" / "splits_s3ext.jsonl").exists()
    assert (tmp_path / "discovery" / "leaves_s3ext" / "s3ext-session-1200.jsonl.gz").exists()
    assert parts.index("s3ext")["s3ext-session-1200.jsonl.gz"]["in_git"]
    # past the hard stop nothing more is asked
    xs["finished"], xs["queries"][s3[1]]["done"] = None, False
    xs["queries"][s3[1]]["stack"] = [["2024-01-01", "2024-06-30"]]
    xe["hard_stop"] = "2026-11-26T00:00:00+00:00"
    (tmp_path / "discovery_state_s3ext.json").write_text(json.dumps(xs))
    n = len(fake.paths)
    assert discover.run("text", "session", 60, None, ext=True) == 0 and len(fake.paths) == n
    assert json.loads((tmp_path / "discovery_state_s3ext.json").read_text())["extension"]["stopped_at_hard_stop"]


def dt_hours(a: str, b: str) -> float:
    import datetime as dt
    return (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 3600


def test_rebuild_keeps_earlier_candidate_idx():
    """protects=rows, raw records and orders refer to candidates by idx: a rebuild after the S3 extension keeps every
    earlier candidate's idx and numbers new ones after them; fails_when=a new repository sorts into the middle and
    shifts the idx of candidates already read; no_claim=hit content."""
    def lf(q, a, repo):
        return {"query": q, "stratum": "S3", "a": a, "b": a, "items": [{"repo": repo, "url": f"u-{repo}"}]}
    rows, orders, _ = discover.build([lf("q", "1", "o/b"), lf("q", "2", "o/d")], {}, {})
    prev = {r["repo"].lower(): r["idx"] for r in rows}
    rows2, orders2, pool2 = discover.build([lf("q", "1", "o/b"), lf("q", "2", "o/d"), lf("x", "1", "o/a")], {}, {},
                                           prev)
    got = {r["repo"]: r["idx"] for r in rows2}
    assert got == {"o/b": prev["o/b"], "o/d": prev["o/d"], "o/a": 2} and [r["idx"] for r in rows2] == [0, 1, 2]
    assert sorted(orders2["S3"]) == [0, 1, 2] and pool2["S3"]["candidates"] == 3


def test_extension_route_guard_tolerates_small_index_drift(tmp_path, monkeypatch):
    """protects=the coordinator's extension guard (11:31Z): a session total_count below the day-old workflow pre-pass
    stops the extension only when lower by more than 1% and by more than 5 hits; fails_when=251 vs 253 stops it, or
    a large drop passes; no_claim=S1's strict guard (test_session_route_answer_below_workflow_prepass_stops)."""
    monkeypatch.setattr(discover, "RES", tmp_path)
    monkeypatch.setattr(discover, "DISC", tmp_path / "discovery")
    qs = [d for d in R.discovery_queries() if d["family"] != "code"]
    s3 = [d["key"] for d in qs if d["stratum"] == "S3"][0]
    (tmp_path / "prepass_code.json").write_text("{}")
    (tmp_path / "launch.json").write_text(json.dumps({"launch": "2026-11-25", "at": "x"}))

    class Fake(SearchFake):
        def __init__(self, tc):
            super().__init__("none")
            self.tc = tc

        def get(self, path, search=None):
            self.paths.append(path)
            q = urllib.parse.parse_qs(path.split("?", 1)[1])["q"][0]
            tc = self.tc if q.endswith(" " + s3.split(" ", 1)[1]) else 0
            return 200, {"total_count": tc, "incomplete_results": False, "items": []}, {}
    for got, pre, rc in ((251, 253, 0), (900, 1000, 4), (6, 12, 4), (95, 100, 0), (51826, 52961, 0)):
        for f in ("discovery_state_s3ext.json", "discovery_state_text.json"):
            (tmp_path / f).unlink(missing_ok=True)
        pp = {d["key"]: {"family": d["family"], "stratum": d["stratum"], "status": 200,
                         "total_count": pre if d["key"] == s3 else 0, "at": "2026-11-25T10:54:28+00:00"} for d in qs}
        (tmp_path / "prepass_text.json").write_text(json.dumps(pp))
        (tmp_path / "discovery_state_text.json").write_text(json.dumps({"queries": {}}))
        fake = Fake(got)
        monkeypatch.setattr(discover, "_client", lambda route, f=fake: f)
        assert discover.run("text", "session", 60, None, ext=True) == (rc if got != pre else 0), (got, pre)


def test_watchdog_flags_stale_or_missing_text_run(tmp_path):
    import watchdog as W
    now = "2026-11-26T15:00:00Z"
    assert W.check("queued", None, now, ["r003.json"]) is None
    assert W.check("in_progress", "2026-11-26T14:45:00Z", now, []) is None
    assert "21 min" in W.check("in_progress", "2026-11-26T14:39:00Z", now, [])
    assert W.check("in_progress", "2026-11-26T14:31:00Z", now, [], 35) is None  # checkpoint commit, 30 min cadence
    assert "r003.json" in W.check("completed", None, now, ["r003.json"])  # run 45820191350, 12:34Z
    assert "no request pending" in W.check("completed", None, now, [])  # 16:40Z, nothing queued
    (tmp_path / "requests").mkdir()
    (tmp_path / "requests" / "n5.json").write_text("{}")
    assert W.queue_noop(tmp_path).name == "n6.json"
    (tmp_path / "results").mkdir()
    W.record_gap("12:34Z", "14:56Z", "x", tmp_path / "results")
    W.record_gap("12:34Z", "14:56Z", "x", tmp_path / "results")
    assert json.loads((tmp_path / "results" / "report_notes.json").read_text())["notes"] == ["Reading gap 12:34Z-14:56Z: x"]


def test_no_request_past_the_deadline_and_extension_stops_at_hard_stop(tmp_path, monkeypatch):
    """protects=the hard stop (coordinator 17:21Z: the S3 extension read one leaf 35 s past 17:20:43Z after a rate-limit
    sleep); fails_when=a request is sent once the client deadline has passed, or a deadline reached at the hard stop
    leaves the extension state without budget_reached; no_claim=the workflow job deadline (still raised to job.py)."""
    import time as _t
    import ghapi
    import discover
    c = ghapi.Client(token="x")
    c.deadline = _t.time() - 1
    try:
        c._wait("commits")
        raise AssertionError("request allowed past the deadline")
    except ghapi.DeadlineReached:
        pass
    monkeypatch.setattr(discover, "RES", tmp_path)
    sp = tmp_path / "discovery_state_s3ext.json"
    sp.write_text(json.dumps({"queries": {}, "extension": {"hard_stop": "2026-11-26T17:20:43+00:00"}}))

    def boom(*a, **k):
        raise ghapi.DeadlineReached("past")
    monkeypatch.setattr(discover, "_run", boom)
    assert discover.run("text", "session", 60, None, ext=True) == 0
    st = json.loads(sp.read_text())
    assert st["budget_reached"] and st["extension"]["stopped_at_hard_stop"]
    sp.write_text(json.dumps({"queries": {}, "extension": {"hard_stop": "2999-01-01T00:00:00+00:00"}}))
    try:
        discover.run("text", "session", 60, None, ext=True)
        raise AssertionError("a job deadline before the hard stop must reach job.py")
    except ghapi.DeadlineReached:
        pass


def test_client_counts_rate_limits_and_sleep_by_cause(monkeypatch):
    """protects=the per-chunk 429 count and sleep seconds in the done markers (coordinator 17:53Z, to see whether a
    shared search limit slows reading); fails_when=a rate-limited answer is not counted or its sleep is not added to
    rate_limit seconds; no_claim=the length of GitHub's reset windows."""
    import time as _t
    import ghapi
    c = ghapi.Client(token="x")
    answers = [(429, {"message": "rate limit"}, {"retry-after": "7"}), (200, {"items": []}, {})]
    monkeypatch.setattr(c, "_once", lambda path: answers.pop(0))
    monkeypatch.setattr(c, "_wait", lambda search: None)
    monkeypatch.setattr(_t, "sleep", lambda s: None)
    st, data, _ = c.get("repos/a/b")
    assert st == 200 and c.n_429 == 1 and c.slept["rate_limit"] >= 7
    assert c.slept_by.get("rate_limited_core", 0) >= 7  # by resource (chunk 8: 1,975 s with no 429)


def test_s3_old_new_pool_check_flags_disjoint_intervals():
    """protects=the S3 old/new pool check in REPORT (coordinator 2026-11-26 19:10Z, a check not a rule); fails_when=
    overlapping intervals are flagged, disjoint ones are not, or an empty pool is flagged; no_claim=which pool is
    right."""
    assert not R.intervals_disjoint(1, 72, 0, 0)
    assert not R.intervals_disjoint(2, 150, 3, 225)
    assert R.intervals_disjoint(0, 300, 40, 300)
    assert R.intervals_disjoint(40, 300, 0, 300)
