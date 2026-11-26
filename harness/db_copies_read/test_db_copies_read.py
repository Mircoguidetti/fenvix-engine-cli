"""Unit tests for db-copies-read (pytest, run locally; not in release CI).

Every test states its card: protects=<observable>; fails_when=<wrong result rejected>; no_claim=<what green does
not prove; which fixtures stand in for what>. Fixtures are hand-written JSON shaped like the GitHub REST responses
(issues, commits, commit diffs, pull files, contents, trees); the derivation tests use the real db-serial-count data
at 85b36b2452df through ``git show`` and need that commit in the local object store.
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build as B  # noqa: E402
import derive as D  # noqa: E402
import ghapi  # noqa: E402
import job as J  # noqa: E402
import lines as LN  # noqa: E402
import report as RP  # noqa: E402
import rules as R  # noqa: E402


# ============================================================================================ helpers
class FakeTransport:
    def __init__(self, answers):
        self.answers = list(answers)
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)
        return self.answers.pop(0) if self.answers else (200, {"x-ratelimit-remaining": "4000",
                                                               "x-ratelimit-limit": "5000"}, {})


def client(answers=(), clock_start=1_000_000.0):
    t = {"now": clock_start}
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t["now"] += s

    c = ghapi.Client("tok", sleep=sleep, clock=lambda: t["now"], transport=FakeTransport(answers))
    return c, sleeps


def b64(s):
    return {"encoding": "base64", "content": base64.b64encode(s.encode()).decode()}


ROW = {"repo": "o/r", "html_url": "https://github.com/o/r", "default_branch": "main", "file": ".github/workflows/ci.yml",
       "job": "test", "median_s": 900.0, "kind": "pytest", "reason": "default-serial", "wd": "", "step_index": 3,
       "runner_line": "pytest -q", "runner_src": ".github/workflows/ci.yml", "via": [], "step_commands": ["pytest -q"],
       "other_ge10_pairs": []}


def make_repo(tmp, row=None, files=None, issues=(), commits=(), diffs=None, comments=(), pullfiles=None, meta=None):
    """Write every stage of one repository under tmp/raw/ the way job.py stores them."""
    row = dict(ROW, **(row or {}))
    files = files if files is not None else {row["file"]: "jobs:\n  test:\n    steps:\n      - run: pytest -q\n"}
    base = tmp / "raw" / J.slug(row["repo"])
    m = {"default_branch": "main", "stargazers_count": 3, "has_issues": True, "owner": {"type": "User"}}
    m.update(meta or {})
    J.jdump(base / "meta.json.gz", {"responses": [{"path": "repos/o/r", "status": 200, "headers": {}, "data": m}]})
    J.jdump(base / "contributors.json.gz", {"responses": [{"path": "x", "status": 200, "headers": {
        "link": '<https://api.github.com/repositories/1/contributors?per_page=1&anon=1&page=7>; rel="last"'}, "data": [{}]}]})
    tree = [{"path": p, "type": "blob"} for p in files] + [{"path": ".github", "type": "tree"}]
    J.jdump(base / "tree.json.gz", {"responses": [{"path": "t", "status": 200, "headers": {}, "data": {"tree": tree}}]})
    paths = list(files)
    J.jdump(base / "files.json.gz", {"responses": [{"path": f"c/{p}", "status": 200, "headers": {}, "data": b64(t)}
                                                   for p, t in files.items()], "paths": paths, "not_fetched": [],
                                     "info": {}})
    J.jdump(base / "issues.json.gz", {"responses": [{"path": "i", "status": 200, "headers": {}, "data": list(issues)}],
                                      "mode": "issues"})
    J.jdump(base / "commits.json.gz", {"responses": [{"path": "c", "status": 200, "headers": {}, "data": list(commits)}]})
    J.jdump(base / "pathcommits.json.gz", {"responses": [], "files": []})
    J.jdump(base / "diffs.json.gz", {"responses": [{"path": f"repos/o/r/commits/{s}", "status": 200, "headers": {},
                                                    "data": {"sha": s, "files": f}} for s, f in (diffs or {}).items()]})
    J.jdump(base / "comments.json.gz", {"responses": [{"path": "cm", "status": 200, "headers": {}, "data": list(comments)}]})
    J.jdump(base / "pullfiles.json.gz", {"responses": [{"path": f"repos/o/r/pulls/{n}/files?per_page=100", "status": 200,
                                                        "headers": {}, "data": f} for n, f in (pullfiles or {}).items()]})
    return row


def issue(n, title, body="", pull=False, state="open", merged_at=None, created="2025-03-01T00:00:00Z", user=None):
    d = {"number": n, "title": title, "body": body, "state": state, "created_at": created,
         "user": user or {"login": "dev", "type": "User"}, "html_url": f"https://github.com/o/r/{'pull' if pull else 'issues'}/{n}"}
    if pull:
        d["pull_request"] = {"merged_at": merged_at}
    return d


def commit(sha, message, date="2025-03-01T00:00:00Z", user=None):
    return {"sha": sha, "commit": {"message": message, "author": {"date": date, "name": "dev"}},
            "author": user or {"login": "dev", "type": "User"}, "html_url": f"https://github.com/o/r/commit/{sha}"}


def items_for(tmp, **kw):
    row = make_repo(tmp, **kw)
    t, items = B.build_repo(tmp, row, {"state": "done"})
    return t, items


def by_url(items, url):
    return [i for i in items if i["url"] == url][0]


# ============================================================================================ client (+6)
def test_client_refuses_search_in_every_path_form():
    """protects=no search request leaves the client; fails_when=any of '/search/code?q=x', 'search/code?q=x' or the
    full api.github.com URL reaches the transport; no_claim=the fake transport stands in for the network; it does
    not prove the workflow log is free of search lines (requests.log check does)."""
    c, _ = client()
    for p in ("/search/code?q=x", "search/code?q=x", "https://api.github.com/search/issues?q=x"):
        with pytest.raises(ghapi.SearchRefused):
            c.get(p)
    assert c._transport.paths == [] and c.n_requests == 0


def test_client_has_no_session_route():
    """protects=a missing token is an error, never a `gh api` session-route read; fails_when=a client is built without
    a token or a use_gh path exists; no_claim=none beyond protects."""
    with pytest.raises(RuntimeError):
        ghapi.Client("")
    assert not hasattr(ghapi.Client, "use_gh") and "subprocess" not in Path(ghapi.__file__).read_text()


def test_client_long_reset_pauses_instead_of_sleeping():
    """protects=no sleep above 600 s; a longer wait becomes a checkpoint (Pause); fails_when=the client sleeps until a
    reset 3,000 s away; no_claim=fake clock and transport; the job's checkpoint write is not exercised here."""
    reset = 1_000_000 + 3000
    c, sleeps = client([(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset),
                               "x-ratelimit-limit": "5000"}, {"message": "API rate limit exceeded"})])
    with pytest.raises(ghapi.Pause):
        c.get("repos/o/r")
    assert all(s <= 600 for s in sleeps)


@pytest.mark.parametrize("limit,pause_at,go_at", [(5000, 999, 1001), (1000, 199, 201)])
def test_client_rate_floor_is_20_percent_of_observed_limit(limit, pause_at, go_at):
    """protects=the 20% floor relative to X-RateLimit-Limit; fails_when=the client keeps going at 999/5,000 or
    199/1,000, or pauses at 1,001/5,000 or 201/1,000; no_claim=fake headers; real headers come from GitHub."""
    c, _ = client([(200, {"x-ratelimit-remaining": str(go_at), "x-ratelimit-limit": str(limit)}, {}),
                   (200, {"x-ratelimit-remaining": str(pause_at), "x-ratelimit-limit": str(limit)}, {})])
    c.get("repos/o/r")  # observes go_at
    c.get("repos/o/r")  # allowed: go_at is above the floor; observes pause_at
    with pytest.raises(ghapi.Pause):
        c.get("repos/o/r")


def test_client_retries_rate_limit_403():
    """protects=a rate-limit 403 waits and retries within the cap; fails_when=it is returned or treated as an access
    stop; no_claim=fake transport; secondary-limit timing on GitHub is not modelled."""
    c, sleeps = client([(403, {"retry-after": "30"}, {"message": "You have exceeded a secondary rate limit"}),
                        (200, {"x-ratelimit-remaining": "4000", "x-ratelimit-limit": "5000"}, {"ok": 1})])
    st, data, _ = c.get("repos/o/r")
    assert st == 200 and data == {"ok": 1} and c.n_requests == 2 and 31 in sleeps


def test_client_access_403_is_a_stop():
    """protects=an access 403 (not rate limit) stops the read (§5); fails_when=it is retried or returned as data;
    no_claim=fake transport."""
    c, _ = client([(403, {"x-ratelimit-remaining": "4000", "x-ratelimit-limit": "5000"},
                    {"message": "Resource not accessible by integration"})])
    with pytest.raises(ghapi.AccessDenied):
        c.get("repos/o/r")


def test_checkpoint_reference_is_last_committed_success():
    """protects=gate M1 with the bot-commit transport: the reference is the newest successful run whose results commit
    is in history, and a checkpoint from any other run is refused; fails_when=a successful run without a results
    commit becomes the reference, or a stale checkpoint is accepted; no_claim=fake runs listing and commit lookup."""
    runs = {"workflow_runs": [{"id": 3, "run_number": 3, "conclusion": "success"},
                              {"id": 2, "run_number": 2, "conclusion": "success"},
                              {"id": 1, "run_number": 1, "conclusion": "success"}]}
    c, _ = client([(200, {}, runs)])
    c.remaining, c.limit = 100, 5000  # below the floor: the own-repo reference call still goes out
    ref = J.reference_run(c, "me/x", "4", committed=lambda r: r in ("1", "2"))
    assert ref == "2" and c.n_requests == 1
    assert J.checkpoint_ok({"run_id": "2"}, "2") and not J.checkpoint_ok({"run_id": "1"}, "2")
    assert not J.checkpoint_ok(None, "2") and J.checkpoint_ok(None, None) and not J.checkpoint_ok({"run_id": "1"}, None)


# ============================================================================================ matching (+8)
def test_db_does_not_match_feedback():
    """protects=whole-word terms; fails_when='db' matches inside 'feedback'; no_claim=none beyond protects."""
    assert R.terms_in("thanks for the feedback", R.DBSERIAL) == []


def test_test_does_not_match_latest():
    """protects=whole-word terms; fails_when='test' matches inside 'latest'; no_claim=none beyond protects."""
    assert R.terms_in("upgrade to the latest version", R.TEST) == []


def test_race_condition_does_not_match_trace():
    """protects=phrase matching; fails_when='race condition' matches 'trace condition'; no_claim=none beyond protects."""
    assert R.terms_in("stack trace condition", R.FAILURE) == []


def test_locked_does_not_match_blocked():
    """protects=whole-word terms; fails_when='locked' matches inside 'blocked'; no_claim=none beyond protects."""
    assert R.terms_in("the build is blocked", R.FAILURE) == []


def test_pytest_n_forms_are_parallel_tokens():
    """protects=both flag forms on pytest lines; fails_when='-n auto' or '-n=4' is missed; no_claim=none beyond protects."""
    assert R.flag_tokens("pytest -n auto tests/") == [("parallel", "-n auto")]
    assert R.flag_tokens("python -m pytest -n=4") == [("parallel", "-n=4")]


def test_n_inside_no_cov_is_not_a_token():
    """protects=token boundaries; fails_when='-n' inside '--no-cov' matches; no_claim=none beyond protects."""
    assert R.flag_tokens("pytest --no-cov tests") == []


def test_go_p1_forms_are_serial():
    """protects=-p scoped to go test lines, both forms; fails_when='-p=1' or '-p 1' on a go test line is missed;
    no_claim=none beyond protects."""
    assert R.flag_tokens("go test -count=1 -p=1 ./...") == [("serial", "-p=1")]
    assert R.flag_tokens("go test -p 1 ./...") == [("serial", "-p 1")]


def test_pytest_p_plugin_flag_never_matches():
    """protects=pytest's -p (plugin loading) is not a go serial token; fails_when='-p no:warnings' matches;
    no_claim=none beyond protects."""
    assert R.flag_tokens("timeout 85m pytest x -q -p no:warnings --durations=30") == []


# ============================================================================================ rules on fixtures (+14)
def test_p1_speed_and_test_counted(tmp_path):
    """protects=P1 = speed term + test term, counted; fails_when=it is not counted; no_claim=hand-written issue JSON
    stands in for the /issues listing."""
    _, items = items_for(tmp_path, issues=[issue(1, "Test suite takes too long on CI")])
    i = items[0]
    assert "P1" in i["rules"] and i["counted"] and i["quote"] == "Test suite takes too long on CI"


def test_p1_needs_a_test_term(tmp_path):
    """protects=P1 needs both lists; fails_when=a speed term alone matches; no_claim=fixture JSON."""
    _, items = items_for(tmp_path, issues=[issue(1, "Page load is slow")])
    assert items == []


def test_p1_db_is_second_figure_only(tmp_path):
    """protects=P1-db flagged without changing what is counted; fails_when=P1-db is missing or alters the counted rule
    set; no_claim=fixture JSON."""
    _, items = items_for(tmp_path, issues=[issue(1, "Database tests are slow")])
    i = items[0]
    assert i["p1_db"] and i["counted_rules"] == ["P1"]


def test_p2_diff_merged_is_apart(tmp_path):
    """protects=a merged '-n auto' pull is a P2 attempt reported apart; fails_when=it is counted; no_claim=pull files
    JSON stands in for /pulls/{n}/files."""
    pf = {5: [{"filename": ".github/workflows/ci.yml", "patch": "@@\n-      run: pytest\n+      run: pytest -n auto\n"}]}
    _, items = items_for(tmp_path, issues=[issue(5, "ci: use xdist", pull=True, state="closed",
                                                 merged_at="2025-03-02T00:00:00Z")], pullfiles=pf)
    i = items[0]
    assert i["rules"] == ["P2-diff"] and i["p2"] and not i["counted"]


def test_p2_text_merged_pull_is_apart(tmp_path):
    """protects=P2-text (parallel + test term) on a merged pull is apart; fails_when=it is counted; no_claim=fixture."""
    _, items = items_for(tmp_path, issues=[issue(6, "Run tests in parallel", pull=True, state="closed",
                                                 merged_at="2025-03-02T00:00:00Z")])
    i = items[0]
    assert i["rules"] == ["P2-text"] and i["p2"] and not i["counted"]


def test_p3_revert_by_sha_counted(tmp_path):
    """protects=a P2 commit later reverted (message names its sha) is P3, counted; fails_when=the revert is missed;
    no_claim=fixture commit listing."""
    cs = [commit("abc1234def", "Run pytest with xdist workers in parallel", "2025-03-01T00:00:00Z"),
          commit("fff9999", "Revert abc1234 parallel tests", "2025-03-05T00:00:00Z")]
    _, items = items_for(tmp_path, commits=cs)
    i = by_url(items, "https://github.com/o/r/commit/abc1234def")
    assert "P3-revert" in i["rules"] and i["counted"]


def test_p3_closed_unmerged_pull_counted_after_its_files_are_fetched(tmp_path):
    """protects='Enable pytest-xdist' closed unmerged: matched by title/body, its pull files queued first, then P3
    counted; fails_when=it is not queued for files or not counted; no_claim=fixture JSON; queue order is the job's
    pullfile_queue over the stored listing."""
    pr = issue(7, "Enable pytest-xdist", pull=True, state="closed", merged_at=None)
    stage = {"mode": "issues", "responses": [{"data": [issue(8, "Fix typo in tests", pull=True), pr]}]}
    assert J.pullfile_queue(stage)[0] == 7
    pf = {7: [{"filename": "requirements-dev.txt", "patch": "@@\n+pytest-xdist==3.6.1\n"}]}
    _, items = items_for(tmp_path, issues=[pr], pullfiles=pf)
    i = items[0]
    assert {"P2-text", "P2-diff", "P3-closed"} <= set(i["rules"]) and i["counted"]


def test_p3_text_counted(tmp_path):
    """protects=P3-text = failure + database/serial + parallel terms, counted; fails_when=it is missed; no_claim=fixture."""
    _, items = items_for(tmp_path, issues=[issue(9, "parallel tests deadlock on the database")])
    i = items[0]
    assert "P3-text" in i["rules"] and i["counted"]


def test_p4_runinband_added_on_jest_counted(tmp_path):
    """protects=adding --runInBand (Jest is parallel by default) is P4, counted; fails_when=it is missed; no_claim=commit
    diff JSON stands in for /commits/{sha}."""
    d = {"a1": [{"filename": "package.json", "patch": '@@\n-    "test": "jest"\n+    "test": "jest --runInBand"\n'}]}
    _, items = items_for(tmp_path, commits=[commit("a1", "ci: stabilise")], diffs=d)
    i = items[0]
    assert "P4" in i["rules"] and i["counted"]


def test_p4_go_p1_added_counted(tmp_path):
    """protects=adding 'go test -p=1' is P4, counted; fails_when=it is missed; no_claim=fixture diff."""
    d = {"a2": [{"filename": ".github/workflows/ci.yml", "patch": "@@\n-  run: go test ./...\n+  run: go test -p=1 ./...\n"}]}
    _, items = items_for(tmp_path, commits=[commit("a2", "ci: one package at a time")], diffs=d)
    assert "P4" in items[0]["rules"] and items[0]["counted"]


def test_bot_author_excluded(tmp_path):
    """protects=bot items never count; fails_when=a [bot] P1 item counts; no_claim=fixture."""
    _, items = items_for(tmp_path, issues=[issue(1, "Tests are slow", user={"login": "ci[bot]", "type": "Bot"})])
    assert items[0]["excluded_reason"] == "bot" and not items[0]["counted"]


def test_bump_pytest_xdist_excluded(tmp_path):
    """protects=dependency bumps (including pytest-xdist) never count; fails_when=a 'Bump pytest-xdist' pull matches as
    an attempt that counts or is kept; no_claim=fixture."""
    _, items = items_for(tmp_path, issues=[issue(2, "Bump pytest-xdist from 3.5 to 3.6 for parallel tests", pull=True,
                                                 state="closed")])
    assert items[0]["excluded_reason"] == "dependency-bump" and not items[0]["counted"]


def test_match_only_in_code_block_excluded(tmp_path):
    """protects=text terms inside triple backticks are ignored; fails_when=a log pasted in a code block makes P1;
    no_claim=fixture."""
    body = "See output:\n```\ntests took 40 minutes, slow\n```\n"
    _, items = items_for(tmp_path, issues=[issue(3, "Output attached", body)])
    assert items == []


def test_item_before_2024_excluded(tmp_path):
    """protects=items created before 2024-01-01 are excluded (gate M5); fails_when=an old P1 item counts; no_claim=fixture."""
    _, items = items_for(tmp_path, issues=[issue(4, "Slow tests", created="2023-12-31T23:59:59Z")])
    assert items[0]["excluded_reason"] == "before-2024" and not items[0]["counted"]


# ============================================================================================ diff priority (+1)
def test_diff_priority_message_matched_first(tmp_path):
    """protects=with 50 path-listed and 3 message-matched commits the 40 diffs include the 3, field truncated;
    fails_when=message-matched commits are dropped; no_claim=fake client returns empty diffs."""
    path_cs = [commit(f"p{i:02d}", f"edit ci {i}", f"2025-0{1 + i % 9}-1{i % 9}T00:00:00Z") for i in range(50)]
    msg_cs = [commit(f"m{i}", "tests are slow, speed up", "2024-02-01T00:00:00Z") for i in range(3)]
    commits_stage = {"responses": [{"data": msg_cs + path_cs[:5]}]}
    path_stage = {"responses": [{"data": path_cs}]}
    c, _ = client()
    out = J.Reader(c, tmp_path).s_diffs("o/r", ROW, commits_stage, path_stage)
    got = [e["path"].rsplit("/", 1)[1] for e in out["responses"]]
    assert len(got) == 40 and {"m0", "m1", "m2"} <= set(got) and out["truncated"]
    assert out["left_out_message_matched"] == 0 and out["left_out_path_listed"] == 13


# ============================================================================================ levels (+10)
WF = ".github/workflows/ci.yml"


def level_of(tmp, kind, runner, files):
    row = {"kind": kind, "runner_line": runner, "runner_src": WF}
    t, _ = items_for(tmp, row=row, files=files)
    return t


def test_level_django_manage_test_builtin_off(tmp_path):
    """protects=manage.py test without --parallel and no settings default = built-in/off with an evidence line;
    fails_when=level or state differ or the evidence line is missing; no_claim=fixture files; settings detection
    needs the job's settings_module info, given here."""
    files = {WF: "steps:\n  - run: python manage.py test\n", "manage.py": "import django\n",
             "requirements.txt": "Django==5.0\n", "app/settings.py": "DEBUG = False\n"}
    row = make_repo(tmp_path, row={"kind": "django", "runner_line": "python manage.py test", "runner_src": WF}, files=files)
    st = J.jload(tmp_path / "raw/o__r/files.json.gz")
    st["info"]["settings_module"] = "app/settings.py"
    J.jdump(tmp_path / "raw/o__r/files.json.gz", st)
    t, _ = B.build_repo(tmp_path, row, {"state": "done"})
    assert (t["level"], t["state"], t["free_off"]) == ("built-in", "off", "yes")
    assert t["off_evidence"] == {"file": WF, "line": 2, "text": "  - run: python manage.py test"}


def test_level_pytest_django_with_xdist_plugin_installed_off(tmp_path):
    """protects=pytest-django + pytest-xdist without -n = plugin-installed/off; fails_when=otherwise; no_claim=fixture."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n",
                                                   "requirements.txt": "django\npytest-django\npytest-xdist\n"})
    assert (t["level"], t["state"], t["free_off"]) == ("plugin-installed", "off", "yes")


def test_level_pytest_django_without_xdist_partial(tmp_path):
    """protects=pytest-django without xdist = plugin-partial, not counted; fails_when=free_off yes; no_claim=fixture."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n", "requirements.txt": "django\npytest-django\n"})
    assert t["level"] == "plugin-partial" and t["free_off"] == "no"


def test_level_django_without_pytest_django_not_installed(tmp_path):
    """protects=Django project without pytest-django = plugin-not-installed; fails_when=otherwise; no_claim=fixture."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n", "requirements.txt": "django\npytest\n"})
    assert t["level"] == "plugin-not-installed" and t["free_off"] == "no"


def test_django_named_in_a_comment_is_not_a_dependency(tmp_path):
    """protects=a dependency file comment naming django does not make a Django project (tina4-python bug); fails_when=
    the comment counts; no_claim=fixture pyproject."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n",
                                                   "pyproject.toml": "[project]\n# bottle / django / flask: competitors\n"})
    assert not t["django_project"] and t["level"] == "none"


def test_settings_module_named_in_manage_py_is_fetched(tmp_path):
    """protects=the settings module named by os.environ.setdefault in manage.py is fetched (Quill bug); fails_when=it
    stays unfetched; no_claim=fake transport serves the tree and contents."""
    files = {".github/workflows/ci.yml": "  - run: python manage.py test\n", "requirements.txt": "Django>=5.1\n",
             "manage.py": 'os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")\n',
             "config/settings.py": "DEBUG = False\n"}

    def tr(p):
        name = urllib.parse.unquote(p.split("/contents/")[1].split("?")[0])
        return 200, {}, b64(files[name]) if name in files else {}
    c, _ = client()
    c._transport = lambda p: (tr(p) if "/contents/" in p else (404, {}, {}))
    tree = {"responses": [{"data": {"tree": [{"path": p, "type": "blob"} for p in files] + [{"path": "config", "type": "tree"}]}}]}
    row = dict(ROW, kind="django", runner_line="python manage.py test")
    out = J.Reader(c, tmp_path).s_files("o/r", row, {"default_branch": "main"}, tree)
    assert out["info"]["settings_module"] == "config/settings.py" and "config/settings.py" in out["paths"]


def test_django_detected_by_manage_py_only(tmp_path):
    """protects=a manage.py in the tree makes a Django project; fails_when=it is not detected; no_claim=fixture."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n", "manage.py": "",
                                                   "requirements.txt": "pytest\n"})
    assert t["django_project"] and t["django_why"] == "manage.py in tree"


def test_level_pytest_sqlalchemy_none(tmp_path):
    """protects=pytest without Django = none, n/a; fails_when=otherwise; no_claim=fixture."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n", "requirements.txt": "SQLAlchemy\nasyncpg\n"})
    assert (t["level"], t["state"]) == ("none", "n/a") and "SQLAlchemy" in t["orms"]


def test_level_go_none(tmp_path):
    """protects=Go = none; fails_when=otherwise; no_claim=fixture."""
    t = level_of(tmp_path, "go", "go test -p 1 ./...", {WF: "  - run: go test -p 1 ./...\n", "go.mod": "module x\n"})
    assert t["level"] == "none"


def test_level_jest_prisma_none(tmp_path):
    """protects=Jest + Prisma = none; fails_when=otherwise; no_claim=fixture."""
    t = level_of(tmp_path, "jest", "jest --runInBand", {WF: "  - run: jest --runInBand\n",
                                                        "package.json": '{"dependencies": {"@prisma/client": "5"}}'})
    assert t["level"] == "none" and "Prisma" in t["orms"]


def test_addopts_n_auto_is_on(tmp_path):
    """protects='addopts = -n auto' makes state on (reported as a rule miss, not off); fails_when=state off;
    no_claim=fixture."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n", "pytest.ini": "[pytest]\naddopts = -n auto\n",
                                                   "requirements.txt": "django\npytest-django\npytest-xdist\n"})
    assert t["state"] == "on" and t["free_off"] == "no"


def test_per_test_testcase_is_a_note(tmp_path):
    """protects=per-test isolation (TestCase) recorded as a note, not counted; fails_when=no note or free_off changes;
    no_claim=fixture conftest only (test files are not fetched)."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n", "conftest.py": "from django.test import TestCase\n",
                                                   "requirements.txt": "sqlalchemy\n"})
    assert t["per_test_notes"] and t["per_test_notes"][0]["file"] == "conftest.py" and t["free_off"] == "no"


# ============================================================================================ lines.py (+6)
def _lines(pain, free, incomplete=False, reject=None):
    table = [{"repo": f"r{i}", "status": "incomplete" if (incomplete and i == 0) else "done",
              "free_off": "yes" if i < free else "no"} for i in range(20)]
    items = [{"repo": f"r{i}", "url": f"u{i}", "counted": True, "counted_rules": ["P1"], "p1_db": False}
             for i in range(pain)]
    hand = [{"repo": f"r{i}", "url": f"u{i}", "counted": True, "decision": "pass"} for i in range(pain)]
    recheck = [{"url": u, "answer": "reject"} for u in (reject or [])]
    return LN.compute(table, items, hand, recheck)


@pytest.mark.parametrize("pain,free,out", [(5, 5, "CONTINUE TO DESIGN"), (4, 4, "BACK TO LIST"),
                                           (5, 4, "SPLIT (pain holds)"), (4, 5, "SPLIT (free_off holds)")])
def test_lines_outcomes(pain, free, out):
    """protects=the memo's lines and the SPLIT naming; fails_when=any of 5/5, 4/4, 5/4, 4/5 prints another outcome;
    no_claim=synthetic table and hand-check rows."""
    assert _lines(pain, free)["outcome"] == out


def test_lines_incomplete_row():
    """protects=an incomplete row gives INCOMPLETE and no outcome; fails_when=an outcome is printed; no_claim=synthetic."""
    assert _lines(9, 9, incomplete=True)["outcome"] == "INCOMPLETE"


def test_lines_recheck_reject_lowers_count():
    """protects=a coordinator reject leaves the count; fails_when=5 pain stays 5 after one reject; no_claim=synthetic."""
    r = _lines(5, 5, reject=["u0"])
    assert len(r["pain"]) == 4 and r["outcome"] == "SPLIT (free_off holds)"


# ============================================================================================ report.py (+5)
def _report_fixture(tmp, quote_override=None, off_text=None, deps="django\npytest-django\npytest-xdist\n"):
    files = {WF: "  - run: pytest -q\n", "requirements.txt": deps}
    row = make_repo(tmp, files=files, issues=[issue(1, "Tests are too slow")])
    t, items = B.build_repo(tmp, row, {"state": "done"})
    if off_text is not None:
        t["off_evidence"]["text"] = off_text
    if quote_override is not None:
        items[0]["quote"] = quote_override
    table = [t] + [{"repo": f"x/{i}", "status": "done", "runner": "go", "level": "none", "free_off": "no",
                    "median_s": 700.0} for i in range(19)]
    (tmp / "table.jsonl").write_text("".join(json.dumps(x) + "\n" for x in table))
    (tmp / "items.jsonl").write_text("".join(json.dumps(x) + "\n" for x in items))
    (tmp / "handcheck.jsonl").write_text(json.dumps({"repo": "o/r", "url": items[0]["url"], "rule": "P1",
                                                      "counted": True, "decision": "pass", "reason": "slow tests"}) + "\n")
    return table


def test_report_fails_on_quote_not_in_raw(tmp_path):
    """protects=AC 3 quote presence; fails_when=a quote absent from the stored raw text passes; no_claim=fixture raw."""
    _report_fixture(tmp_path, quote_override="this text is nowhere")
    with pytest.raises(RP.CheckFailed):
        RP.build(tmp_path, False)


def test_report_fails_on_off_line_not_in_file(tmp_path):
    """protects=AC 4 evidence line presence; fails_when=an evidence line that is not in the stored file passes;
    no_claim=fixture raw."""
    _report_fixture(tmp_path, off_text="  - run: pytest -n auto")
    with pytest.raises(RP.CheckFailed):
        RP.build(tmp_path, False)


def test_report_fails_when_plugin_installed_lacks_xdist(tmp_path):
    """protects=AC 4 dependency check for plugin-installed; fails_when=a row claims plugin-installed with no
    pytest-xdist in a stored dependency file; no_claim=the row's plugin_deps is tampered to simulate the bug."""
    table = _report_fixture(tmp_path)
    table[0]["plugin_deps"]["pytest-xdist"] = []
    (tmp_path / "table.jsonl").write_text("".join(json.dumps(x) + "\n" for x in table))
    with pytest.raises(RP.CheckFailed):
        RP.build(tmp_path, False)


def test_report_fails_when_stack_summary_not_20():
    """protects=the per-stack summary sums to 20; fails_when=19 rows pass; no_claim=synthetic rows."""
    table = [{"repo": f"r{i}", "runner": "pytest", "level": "none", "free_off": "no", "median_s": 600.0}
             for i in range(19)]
    with pytest.raises(RP.CheckFailed):
        RP.per_stack(table, set())


def test_report_names_most_common_stack_with_ties():
    """protects=the most common stack among pain/free_off rows, ties listed in full; fails_when=one of two tied stacks
    is dropped; no_claim=synthetic rows."""
    table = ([{"repo": f"a{i}", "runner": "pytest", "level": "none", "free_off": "no", "median_s": 600.0} for i in range(10)]
             + [{"repo": f"b{i}", "runner": "django", "level": "built-in", "free_off": "yes", "median_s": 600.0}
                for i in range(2)]
             + [{"repo": f"c{i}", "runner": "go", "level": "none", "free_off": "no", "median_s": 600.0} for i in range(8)])
    rows, line = RP.per_stack(table, {"a0", "a1"})
    assert "django/built-in, pytest/none (2 repositories each)" in line and rows[-1].startswith("| total | | 20 |")


# ============================================================================================ derivation (+6, real data)
@pytest.fixture(scope="module")
def derived(tmp_path_factory):
    src = D.copy_files(tmp_path_factory.mktemp("dsc"))
    return D.derive(src)


def _row(d, name):
    return [r for r in d["repos"] if r["repo"] == name][0]


def test_derivation_counts_and_names(derived):
    """protects=the 20 equal REPORT's list with the stated class counts (AC 2); fails_when=any count or name differs;
    no_claim=real data at 85b36b2452df; needs PyYAML 6.0.2 and that commit locally."""
    assert D.check(derived) == [] and len(derived["repos"]) == 20


def test_derivation_healix_median(derived):
    """protects=pair-level median, not the step timing list; fails_when=healix is not 853.5 s; no_claim=real data."""
    assert _row(derived, "nikhilvdev/healix")["median_s"] == 853.5


def test_derivation_step_index_runner_lines(derived):
    """protects=the runner line is the step_index step's pytest line, not an earlier serial step (median 0.0 / null);
    fails_when=saas or hoops-gm take another step; no_claim=real data."""
    assert _row(derived, "penghaibin9/saas")["runner_line"].startswith("timeout 85m pytest ")
    assert _row(derived, "penghaibin9/saas")["step_index"] == 4
    assert _row(derived, "SR2501/hoops-gm")["runner_line"] == "pytest" and _row(derived, "SR2501/hoops-gm")["step_index"] == 7


def test_derivation_two_pair_repositories(derived):
    """protects=the ge_10 pair with the larger median is used and the other recorded; fails_when=the smaller pair is
    chosen or the other is lost; no_claim=real data."""
    f = _row(derived, "eddiezgq/freecad-ai-parts")
    a = _row(derived, "kutschersteffen-cmd/Agentic-Research-Pipeline")
    assert (f["job"], f["median_s"]) == ("test", 3574.0) and f["other_ge10_pairs"][0]["job"] == "factory"
    assert (a["job"], a["median_s"]) == ("backend", 2552.5) and a["other_ge10_pairs"][0]["job"] == "e2e"


def test_derivation_tina4_not_echo(derived):
    """protects=tina4-python's runner line is the pytest command, not its echo (gate M2); fails_when=the echo line is
    taken; no_claim=real data."""
    assert _row(derived, "tina4stack/tina4-python")["runner_line"].startswith("uv run pytest tests/")


def test_derivation_xchain_runner_from_package_json(derived):
    """protects=xchain-indexer's runner line is the mocha line from package.json (gate M2); fails_when=the npm run line
    or the workflow file is taken; no_claim=real data."""
    x = _row(derived, "XChain-Platform/xchain-indexer")
    assert x["runner_line"] == "mocha --no-config --timeout 120000 --exit 'test/integration/**/*.test.js'"
    assert x["runner_src"] == "package.json"



# ============================================================================================ review fixes (+12)
def test_second_request_in_same_run_accepts_own_checkpoint():
    """protects=a run that processes two request files keeps going after the first wrote its checkpoint (review
    finding: the second was refused as stale and the whole run lost); fails_when=a checkpoint from the current run is
    refused; no_claim=checkpoint_ok only; the workflow loop is not run."""
    assert J.checkpoint_ok({"run_id": "7"}, "5", current="7")
    assert not J.checkpoint_ok({"run_id": "6"}, "5", current="7")


def test_request_errors_found_before_any_get():
    """protects=an unknown repository, a bad redo stage or a bound above 2,280 refuses the request before a GET;
    fails_when=any passes; no_claim=validation only."""
    rows = {"o/r": {}}
    assert J.request_errors({"repos": ["o/r"]}, rows, 1500) == []
    assert J.request_errors({"repos": ["x/y"]}, rows, 1500)
    assert J.request_errors({"repos": ["o/r"], "redo": {"o/r": ["meta"]}}, rows, 1500)
    assert J.request_errors({"repos": ["o/r"]}, rows, 2281)


def test_client_ceiling_pauses_inside_a_repository():
    """protects=the 2,280 bound holds per request, not only between repositories; fails_when=a request is sent at the
    ceiling; no_claim=fake transport."""
    c, _ = client()
    c.ceiling = 2
    c.get("repos/o/r")
    c.get("repos/o/r")
    with pytest.raises(ghapi.Pause):
        c.get("repos/o/r")
    assert c.n_requests == 2


def test_client_rate_limit_retries_are_capped():
    """protects=repeated secondary-limit answers end in a checkpoint, not endless retries; fails_when=a fourth retry is
    sent; no_claim=fake transport with short waits."""
    rl = (403, {"retry-after": "1"}, {"message": "secondary rate limit"})
    c, _ = client([rl] * 10)
    with pytest.raises(ghapi.Pause):
        c.get("repos/o/r")
    assert c.n_requests == ghapi.RATE_LIMIT_RETRIES + 1


@pytest.mark.parametrize("line", ["pytest -nauto", "pytest -n4", "addopts = -n auto"])
def test_attached_and_config_n_forms_are_parallel(line):
    """protects=-nauto, -n4 and an addopts -n are parallel tokens; fails_when=any is missed (would turn an 'on' row
    into 'off'); no_claim=none beyond protects."""
    assert [p for p, _ in R.flag_tokens(line)] == ["parallel"]


def test_addopts_list_form_is_on(tmp_path):
    """protects=addopts written as a TOML list ["-n", "auto"] makes state on; fails_when=state off (inflates
    free_off); no_claim=fixture pyproject."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n",
                                                   "pyproject.toml": '[tool.pytest.ini_options]\naddopts = ["-n", "auto"]\n',
                                                   "requirements.txt": "django\npytest-django\npytest-xdist\n"})
    assert t["state"] == "on" and t["free_off"] == "no"


def test_pytest_addopts_env_is_on(tmp_path):
    """protects=PYTEST_ADDOPTS: -n auto in the workflow makes state on; fails_when=state off; no_claim=fixture."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "env:\n  PYTEST_ADDOPTS: -n auto\nsteps:\n  - run: pytest -q\n",
                                                   "requirements.txt": "django\npytest-django\npytest-xdist\n"})
    assert t["state"] == "on"


def test_manage_parallel_one_is_serial():
    """protects=manage.py test --parallel 1 is serial; fails_when=it reads parallel (state on, free_off undercounted);
    no_claim=none beyond protects."""
    assert R.flag_tokens("python manage.py test --parallel 1") == [("serial", "--parallel 1")]


def test_worker_count_tuning_is_not_a_revert(tmp_path):
    """protects=changing -n auto to -n 4 later is not a reverted parallel attempt; fails_when=the earlier item gets
    P3-revert; no_claim=fixture diffs."""
    d = {"a1": [{"filename": "pytest.ini", "patch": "@@\n-addopts = -q\n+addopts = -q -n auto\n"}],
         "a2": [{"filename": "pytest.ini", "patch": "@@\n-addopts = -q -n auto\n+addopts = -q -n 4\n"}]}
    cs = [commit("a1", "ci: xdist", "2025-01-01T00:00:00Z"), commit("a2", "ci: four workers", "2025-02-01T00:00:00Z")]
    _, items = items_for(tmp_path, commits=cs, diffs=d)
    first = by_url(items, "https://github.com/o/r/commit/a1")
    assert "P3-revert" not in first["rules"]


def test_counted_item_without_hand_check_is_incomplete():
    """protects=a counted item with no hand-check decision gives INCOMPLETE; fails_when=it is silently a fail;
    no_claim=synthetic rows."""
    table = [{"repo": f"r{i}", "status": "done", "free_off": "no"} for i in range(20)]
    items = [{"repo": "r0", "url": "u0", "counted": True, "counted_rules": ["P1"], "p1_db": False}]
    assert LN.compute(table, items, [], [])["outcome"] == "INCOMPLETE"


def test_locate_needs_more_than_the_runner_word():
    """protects=off evidence is not any line that merely contains 'pytest'; fails_when=a pip install line is taken for
    'pytest --cov -q'; no_claim=none beyond protects."""
    text = "pip install pytest-xdist\nrun: something else\n"
    assert B.locate(text, "pytest --cov -q") is None
    assert B.locate("  - run: pytest\n", "pytest") == {"line": 1, "text": "  - run: pytest"}


def test_run_repo_unavailable_and_incomplete_resume(tmp_path):
    """protects=a 404 repository is unavailable with no further reads; a 5xx stage is incomplete and the next run
    resumes only that stage; fails_when=either path records the wrong state or re-reads done stages; no_claim=fake
    reader methods stand in for GitHub."""
    class Fake(J.Reader):
        def __init__(self, results, meta_status=200, fail=None):
            super().__init__(None, results)
            self.meta_status, self.fail, self.calls = meta_status, fail, []

        def s_meta(self, repo, row):
            self.calls.append("meta")
            return {"responses": [{"path": "m", "status": self.meta_status, "headers": {},
                                   "data": {"default_branch": "main", "archived": False}}]}

        def __getattribute__(self, name):
            if name.startswith("s_") and name != "s_meta":
                stage = name[2:]

                def f(*a, **k):
                    self.calls.append(stage)
                    if stage == self.fail:
                        raise J.Incomplete(stage)
                    return {"responses": []}
                return f
            return object.__getattribute__(self, name)

    cp = J.new_checkpoint()
    assert J.run_repo(Fake(tmp_path, meta_status=404), "o/gone", ROW, cp) == "unavailable"
    assert cp["repos"]["o/gone"]["state"] == "unavailable"
    cp = J.new_checkpoint()
    r1 = Fake(tmp_path, fail="issues")
    assert J.run_repo(r1, "o/r", ROW, cp) == "incomplete" and cp["repos"]["o/r"]["stages"]["issues"] == "incomplete"
    r2 = Fake(tmp_path)
    assert J.run_repo(r2, "o/r", ROW, cp) == "done"
    assert r2.calls[0] == "issues" and "meta" not in r2.calls


# ============================================================================================ review cycle 2 (+6)
def test_multiline_addopts_list_is_on(tmp_path):
    """protects=a TOML addopts list spread over lines with "-n", "auto" makes state on and cites the addopts line;
    fails_when=state off; no_claim=fixture pyproject."""
    py = '[tool.pytest.ini_options]\naddopts = [\n    "-n",\n    "auto",\n]\n'
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "  - run: pytest -q\n", "pyproject.toml": py,
                                                   "requirements.txt": "django\npytest-django\npytest-xdist\n"})
    assert t["state"] == "on" and t["on_evidence"][0]["file"] == "pyproject.toml"


def test_n_after_a_pipe_is_not_pytest():
    """protects=`pytest -q | tail -n50` has no parallel token; fails_when=tail's -n50 reads as pytest -n;
    no_claim=none beyond protects."""
    assert R.flag_tokens("pytest -q | tail -n50") == []


@pytest.mark.parametrize("a,b", [("-n auto", "-n4"), ("-n auto", "-nauto"), ("-n 4", "--numprocesses=8")])
def test_flag_family_same_for_n_forms(a, b):
    """protects=worker-count and spelling changes stay one flag family (no false P3 revert); fails_when=families
    differ; no_claim=none beyond protects."""
    assert R.flag_family(a) == R.flag_family(b) == "-n"


def test_commented_pytest_addopts_is_ignored(tmp_path):
    """protects=a commented-out PYTEST_ADDOPTS line does not make state on; fails_when=it does; no_claim=fixture."""
    t = level_of(tmp_path, "pytest", "pytest -q", {WF: "# PYTEST_ADDOPTS: -n auto\n  - run: pytest -q\n",
                                                   "requirements.txt": "django\npytest-django\npytest-xdist\n"})
    assert t["state"] == "off"


def test_locate_follows_backslash_continuation():
    """protects=a backslash-continued runner command is located at its first line; fails_when=None (would turn an
    off row into unknown); no_claim=none beyond protects."""
    text = "steps:\n  run: pytest \\\n    --cov -q tests/\n"
    assert B.locate(text, "pytest --cov -q tests/") == {"line": 2, "text": "  run: pytest \\"}
