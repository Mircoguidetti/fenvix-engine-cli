"""AC2 tests. Each test states protects= / fails_when= / no_claim=.

Run: python3 -m pytest -q harness/db_serial_count/test_db_serial_count.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discover  # noqa: E402
import perworker  # noqa: E402
import pipeline  # noqa: E402
import rules as R  # noqa: E402
import status as S  # noqa: E402


def fs(files: dict[str, str]):
    """read/listdir over an in-memory repository."""
    def read(p):
        return files.get(p)

    def listdir(d):
        d = d or ""
        names = set()
        for p in files:
            parent, _, name = p.rpartition("/")
            if parent == d:
                names.add(name)
        return sorted(names) if names or d == "" else None
    return read, listdir


def check(cmd: str, files: dict | None = None, env: dict | None = None, wd: str = "", wf_text: str | None = None):
    read, listdir = fs(files or {})
    lines = R.resolve_command(cmd, wd, read, ".github/workflows/ci.yml", wf_text or cmd)
    assert lines, f"no runner line for {cmd}"
    return R.serial_check(lines[0], env or {}, read, listdir, ".github/workflows/ci.yml", wf_text or cmd)


# ------------------------------------------------------------------------------------------ §2.3 serial table

@pytest.mark.parametrize("cmd,files,env,serial,reason", [
    # Jest
    ("npx jest --runInBand", {}, {}, True, R.EXPLICIT),
    ("npx jest -w 1", {}, {}, True, R.EXPLICIT),
    ("npx jest -i", {}, {}, True, R.EXPLICIT),
    ("npx jest", {"jest.config.js": "module.exports = { maxWorkers: 1 }"}, {}, True, R.EXPLICIT),
    ("npx jest --maxWorkers=4", {}, {}, False, None),
    ("npx jest", {}, {}, False, None),
    # Vitest
    ("npx vitest run --no-file-parallelism", {}, {}, True, R.EXPLICIT),
    ("npx vitest run", {"vitest.config.ts": "export default { test: { fileParallelism: false } }"}, {}, True,
     R.EXPLICIT),
    ("npx vitest run", {"vitest.config.ts": "export default {}"}, {}, False, None),
    # Mocha
    ("npx mocha test/", {}, {}, True, R.DEFAULT),
    ("npx mocha --parallel test/", {}, {}, False, None),
    ("npx mocha test/", {".mocharc.json": '{"parallel": true}'}, {}, False, None),
    # node:test
    ("node --test --test-concurrency=1", {}, {}, True, R.EXPLICIT),
    ("node --test", {}, {}, False, None),
    # pytest
    ("pytest -x", {}, {}, True, R.DEFAULT),
    ("pytest -n 0", {}, {}, True, R.EXPLICIT),
    ("pytest -p no:xdist", {}, {}, True, R.EXPLICIT),
    ("pytest -n auto", {}, {}, False, None),
    ("pytest -n=0", {}, {}, True, R.EXPLICIT),
    ("pytest", {"pyproject.toml": '[tool.pytest.ini_options]\naddopts = ["-n", "auto"]\n'}, {}, False, None),
    ("pytest", {"pytest.ini": "[pytest]\naddopts = -n auto\n"}, {}, False, None),
    ("pytest", {"setup.cfg": "[tool:pytest]\naddopts = -nauto\n"}, {}, False, None),
    ("pytest", {}, {"PYTEST_ADDOPTS": "-n auto"}, False, None),
    ("pytest --dist loadfile", {}, {}, False, None),
    # Django
    ("python manage.py test", {}, {}, True, R.DEFAULT),
    ("python manage.py test --parallel 1", {}, {}, True, R.EXPLICIT),
    ("python manage.py test --parallel", {}, {"DJANGO_TEST_PROCESSES": "1"}, True, R.EXPLICIT),
    ("python manage.py test --parallel auto", {}, {}, False, None),
    ("python manage.py test --parallel", {}, {}, False, None),
    # Rails minitest
    ("bin/rails test", {}, {}, True, R.DEFAULT),
    ("bin/rails test", {"test/test_helper.rb": "class X\n  parallelize(workers: 1)\nend\n"}, {}, True, R.EXPLICIT),
    ("bin/rails test", {"test/test_helper.rb": "  parallelize(workers: :number_of_processors)\n"}, {}, False, None),
    ("bin/rails test", {"test/test_helper.rb": "  # parallelize(workers: :number_of_processors)\n"}, {}, True,
     R.DEFAULT),
    ("bin/rails test", {"test/test_helper.rb": "  parallelize(workers: :number_of_processors)\n"},
     {"PARALLEL_WORKERS": "1"}, True, R.EXPLICIT),
    # RSpec
    ("bundle exec rspec", {}, {}, True, R.DEFAULT),
    ("bundle exec rake spec", {}, {}, True, R.DEFAULT),
    ("bundle exec rspec --require knapsack", {}, {}, False, None),
    # Go
    ("go test -p 1 ./...", {}, {}, True, R.EXPLICIT),
    ("go test ./...", {}, {}, False, None),
    ("go test -parallel 1 ./...", {}, {}, False, None),
])
def test_serial_table(cmd, files, env, serial, reason):
    """protects=§2.3 table, one serial and one non-serial fixture per runner (Jest -w 1, pytest -n auto in addopts,
    Rails parallelize(workers: :number_of_processors), Go without -p 1); fails_when=a row's regex or config read
    changes its verdict; no_claim=real-world configs outside these shapes are classified correctly."""
    r = check(cmd, files, env)
    assert r["serial"] is serial
    if serial:
        assert r["reason"] == reason


def test_declared_overrides_explicit_only():
    """protects=`declared` rule; fails_when=a db comment within 5 lines does not turn explicit into declared, or turns
    default-serial into declared; no_claim=comment intent is understood."""
    wf = "steps:\n  # tests share one postgres database\n  - run: npx jest --runInBand\n"
    assert check("npx jest --runInBand", wf_text=wf)["reason"] == R.DECLARED
    wf2 = "steps:\n  # one shared database\n  - run: pytest\n"
    assert check("pytest", wf_text=wf2)["reason"] == R.DEFAULT
    far = "# shared db\n" + "x\n" * 7 + "npx jest --runInBand\n"
    assert check("npx jest --runInBand", wf_text=far)["reason"] == R.EXPLICIT


def test_head_n_does_not_parallelize_pytest():
    """protects=flags read only from the runner line; fails_when=`head -n 5` in the same step makes pytest
    parallel; no_claim=other piped tools are parsed."""
    cmds = [c for c in R.kept_commands("pytest -x | head -n 5") if R.is_runner_command(c)]
    assert cmds == ["pytest -x"]
    assert check(cmds[0])["serial"] is True


# ------------------------------------------------------------------------------------------ §2.2 steps

def test_install_dropped_and_npm_ci_kept_test():
    """protects=install-line drop; fails_when=`pip install pytest` is a test step or `npm ci && npm test` loses
    `npm test`; no_claim=every install spelling is caught."""
    assert [c for c in R.kept_commands("pip install pytest") if R.is_runner_command(c)] == []
    assert [c for c in R.kept_commands("pytest -x") if R.is_runner_command(c)] == ["pytest -x"]
    assert [c for c in R.kept_commands("npm ci && npm test") if R.is_runner_command(c)] == ["npm test"]
    assert [c for c in R.kept_commands("jest --version") if R.is_runner_command(c)] == []


def test_two_step_job_second_is_test_step():
    """protects=step selection; fails_when=the install step is chosen; no_claim=-."""
    job = {"steps": [{"run": "pip install pytest"}, {"run": "pytest -x"}], "services": {"pg": {"image": "postgres:16"}}}
    read, listdir = fs({})

    class Rp:
        pass
    rp = Rp()
    rp.read, rp.listdir = read, listdir
    steps = pipeline.test_steps(job, {}, rp, ".github/workflows/ci.yml", "")
    assert [s["index"] for s in steps] == [1]


def test_script_resolution_two_levels_and_unresolved():
    """protects=package script resolution; fails_when=2-level scripts do not reach the runner, a missing script is
    not `unresolved`, or extra args are lost; no_claim=workspace scripts are resolved."""
    pj = json.dumps({"scripts": {"test": "npm run test:db", "test:db": "prisma migrate reset --force && jest"}})
    r = check("npm test -- --runInBand", {"package.json": pj})
    assert r["kind"] == "jest" and r["serial"] and r["via"] == ["npm:test", "npm:test:db"]
    read, _ = fs({"package.json": json.dumps({"scripts": {}})})
    with pytest.raises(R.Unresolved):
        R.resolve_command("npm run test:e2e", "", read, "wf", "")
    read, _ = fs({"package.json": json.dumps({"scripts": {"test": "turbo run test"}})})
    with pytest.raises(R.Unresolved):
        R.resolve_command("npm test", "", read, "wf", "")
    read, _ = fs({"package.json": json.dumps({"scripts": {"test": "echo no tests"}})})
    assert R.resolve_command("npm test", "", read, "wf", "") == []


def test_make_tox_resolution():
    """protects=make/tox resolution (gate note 7); fails_when=a make target is not followed, a missing target is
    not unresolved; no_claim=complex Makefiles."""
    mk = "PYTEST ?= pytest\ntest: deps\n\t$(PYTEST) -x tests\ndeps:\n\techo deps\n"
    r = check("make test", {"Makefile": mk})
    assert r["kind"] == "pytest"
    read, _ = fs({"Makefile": "build:\n\techo\n"})
    with pytest.raises(R.Unresolved):
        R.resolve_command("make test", "", read, "wf", "")
    read, _ = fs({"Makefile": "test:\n\t$(RUNNER) x\n"})
    with pytest.raises(R.Unresolved):
        R.resolve_command("make test", "", read, "wf", "")
    tox = "[testenv]\ncommands =\n    pytest -n auto {posargs}\n"
    assert check("tox", {"tox.ini": tox})["serial"] is False


# ------------------------------------------------------------------------------------------ §2.1 database jobs

@pytest.mark.parametrize("img", ["postgres:16", "postgis/postgis:15-3.4", "cimg/postgres:14.0", "mysql:8",
                                 "mariadb:11", "mongo:7", "pgvector/pgvector:pg16", "timescale/timescaledb:latest-pg16",
                                 "bitnami/postgresql:16", "bitnami/mysql", "bitnami/mariadb", "bitnami/mongodb"])
def test_image_regex_accepts(img):
    """protects=image regex; fails_when=a listed image is rejected; no_claim=unlisted db images."""
    assert R.image_ok(img)


def test_image_regex_rejects_redis_and_matrix():
    """protects=image regex and matrix substitution; fails_when=redis passes or a matrix image is missed;
    no_claim=-."""
    assert not R.image_ok("redis:7")
    assert R.image_ok("library/postgres:15-alpine") and R.image_ok("docker.io/library/mysql:8")
    assert not R.image_ok("library/redis")
    job = {"strategy": {"matrix": {"include": [{"db": "postgres:15"}]}},
           "services": {"db": {"image": "${{ matrix.db }}"}}, "steps": []}
    assert R.db_job_evidence(job, {}, fs({})[0])


# ------------------------------------------------------------------------------------------ §3 matching

def test_job_matching_matrix_suffix_and_caller():
    """protects=job name matching; fails_when=`Test (${{ matrix.py }})` misses `Test (3.12)`, a plain job misses its
    matrix legs, or a reusable caller name misses; no_claim=-."""
    assert R.job_matches("Test (3.12)", "Test (${{ matrix.py }})")
    assert R.job_matches("test (ubuntu, 3.12)", "test")
    assert not R.job_matches("lint", "test")
    assert R.job_matches("ci (pg16) / test (3.12)", "test", caller="ci")
    assert R.job_matches("ci / test", "test", caller="ci")


def test_step_matching_named_unnamed_missing():
    """protects=step matching; fails_when=named, unnamed (prefix) or position cases pick the wrong step;
    no_claim=-."""
    ys = [{"name": "Setup"}, {"run": "pytest -x tests/a\necho"}, {"name": "Test ${{ matrix.x }}", "run": "pytest"},
          {"run": "pytest -x tests/a\nmore"}]
    api = [{"name": "Setup", "number": 1}, {"name": "Run pytest -x tests/a", "number": 2},
           {"name": "Test 1", "number": 3}, {"name": "Run pytest -x tests/a", "number": 4}]
    assert R.pick_api_step(api, ys, 2)["number"] == 3
    assert R.pick_api_step(api, ys, 1)["number"] == 2
    assert R.pick_api_step(api, ys, 3)["number"] == 4
    assert R.pick_api_step(api[:1], ys, 2) is None


def test_median_of_ten():
    """protects=median rule; fails_when=median is not mean of 5th and 6th of 10, or fewer than 10 gives a value;
    no_claim=-."""
    assert R.median10([float(x) for x in range(1, 11)]) == 5.5
    assert R.median10([1.0] * 9) is None


class FakeSrc:
    def __init__(self, responses):
        self.responses = responses

    def get(self, path):
        for k, v in self.responses.items():
            if path.startswith(k):
                return 200, v
        return 404, {}


def _jobs(conclusion, secs):
    return {"total_count": 1, "jobs": [{"name": "test", "conclusion": "success", "steps": [
        {"name": "Test", "number": 1, "conclusion": conclusion, "started_at": "2026-11-01T00:00:00Z",
         "completed_at": f"2026-11-01T00:{secs // 60:02d}:{secs % 60:02d}Z"}]}]}


def test_skipped_step_continues_to_older_runs():
    """protects=§3.3 skipped steps; fails_when=a skipped step gives a value or stops reading; no_claim=-."""
    runs = {"total_count": 12, "workflow_runs": [{"id": i, "event": "push"} for i in range(12)]}
    resp = {"repos/o/r/actions/workflows/ci.yml/runs": runs}
    resp["repos/o/r/actions/runs/0/jobs"] = _jobs("skipped", 0)
    for i in range(1, 12):
        resp[f"repos/o/r/actions/runs/{i}/jobs"] = _jobs("success", 700)
    t = [{"job_name": "test", "caller": None, "yaml_steps": [{"name": "Test"}], "idx": 0}]
    pipeline.time_file(FakeSrc(resp), "o/r", "main", ".github/workflows/ci.yml", t)
    assert len(t[0]["values"]) == 10 and t[0]["runs_seen"] == 11


def test_pull_request_runs_skipped():
    """protects=§3.1 event filter; fails_when=pull_request runs give values; no_claim=-."""
    runs = {"total_count": 2, "workflow_runs": [{"id": 0, "event": "pull_request"}, {"id": 1, "event": "push"}]}
    resp = {"repos/o/r/actions/workflows/ci.yml/runs": runs, "repos/o/r/actions/runs/0/jobs": _jobs("success", 5),
            "repos/o/r/actions/runs/1/jobs": _jobs("success", 7)}
    t = [{"job_name": "test", "caller": None, "yaml_steps": [{"name": "Test"}], "idx": 0}]
    pipeline.time_file(FakeSrc(resp), "o/r", "main", ".github/workflows/ci.yml", t)
    assert t[0]["values"] == [7.0]


class RepoSrc:
    """A fake repository behind the contents/runs API for run_candidate."""

    def __init__(self, files, runs_by_file):
        self.files, self.runs = files, runs_by_file

    def get(self, path):
        p, _, q = path.partition("?")
        if p == "repos/o/r":
            return 200, {"full_name": "o/r", "owner": "o", "fork": False, "archived": False,
                         "pushed_at": "2026-11-20T00:00:00Z", "default_branch": "main"}
        if p.startswith("repos/o/r/contents/"):
            fp = p[len("repos/o/r/contents/"):]
            names = sorted({x[len(fp) + 1:].split("/")[0] for x in self.files if x.startswith(fp + "/")})
            if names:
                return 200, [{"name": n, "type": "file"} for n in names]
            if fp in self.files:
                return 200, {"type": "file", "text": self.files[fp]}
            return 404, {}
        if "/actions/workflows/" in p:
            f = p.split("/actions/workflows/")[1].split("/")[0]
            return 200, {"total_count": 10, "workflow_runs": [{"id": f"{f}-{i}", "event": "push"} for i in range(10)]
                         if f in self.runs else []}
        if "/actions/runs/" in p:
            rid = p.split("/actions/runs/")[1].split("/")[0]
            f = rid.rsplit("-", 1)[0]
            return 200, _jobs("success", self.runs[f])
        return 404, {}


WF_OK = """on: push
jobs:
  test:
    services:
      db:
        image: postgres:16
    steps:
      - name: Test
        run: bundle exec rspec
"""


def test_second_workflow_file_qualifies():
    """protects=every (file, db job) pair in path order; fails_when=a repository whose first db workflow is
    fast is not found through its second file; no_claim=-."""
    files = {".github/workflows/a.yml": WF_OK, ".github/workflows/b.yml": WF_OK}
    row = pipeline.run_candidate(RepoSrc(files, {"a.yml": 30, "b.yml": 900}),
                                 {"idx": 0, "repo": "o/r", "html_url": "u"})
    assert row["cls"] == "candidate_ge10"
    assert [p["stage"] for p in row["pairs"]] == ["below_10", "ge_10"]


def test_unrelated_file_with_db_term_is_checked():
    """protects=gate note 5 (every workflow file with a db term); fails_when=a file not returned by search is
    skipped; no_claim=-."""
    files = {".github/workflows/z-other.yml": WF_OK, ".github/workflows/lint.yml": "on: push\njobs: {}\n"}
    row = pipeline.run_candidate(RepoSrc(files, {"z-other.yml": 900}), {"idx": 0, "repo": "o/r", "html_url": "u"})
    assert row["cls"] == "candidate_ge10"


# ------------------------------------------------------------------------------------------ §4 per-worker

@pytest.mark.parametrize("term,path,text,hit", [
    ("JEST_WORKER_ID", "test/setup.ts", "const db = `app_${process.env.JEST_WORKER_ID}`; DATABASE_URL", True),
    ("PYTEST_XDIST_WORKER", "conftest.py", "name = os.environ['PYTEST_XDIST_WORKER']  # database", True),
    ("testcontainers", "tests/conftest.py", "from testcontainers.postgres import PostgresContainer", True),
    ("pglite", "test/setup.ts", "import { PGlite } from '@electric-sql/pglite'", True),
    ("parallelize", "test/test_helper.rb", "  parallelize(workers: :number_of_processors)", True),
    ("parallelize", "test/test_helper.rb", "  parallelize(workers: 1)", False),
    ("parallelize", "test/test_helper.rb", "  # parallelize(workers: 4)", False),
    ("\"CREATE DATABASE\" TEMPLATE", "spec/setup.sql", "CREATE DATABASE test_1 TEMPLATE app_template", True),
    ("JEST_WORKER_ID", "test/setup.ts", "console.log(process.env.JEST_WORKER_ID)", False),
])
def test_perworker_rules(term, path, text, hit):
    """protects=§4 counting rules; fails_when=a rule does not flip its fixture to per_worker or a non-counting
    file counts; no_claim=all per-worker schemes are detected."""
    assert perworker.counts(term, text) is hit


def test_perworker_off_path_hit_ignored():
    """protects=§4 path filter; fails_when=a hit outside the job's working directory or outside test/spec/
    conftest/setup paths is fetched; no_claim=-."""
    assert perworker.path_ok("test/setup.ts", "")
    assert not perworker.path_ok("src/db.ts", "")
    assert not perworker.path_ok("other/test/setup.ts", "web")
    assert perworker.path_ok("web/test/setup.ts", "web")


# ------------------------------------------------------------------------------------------ §1 / §5

def test_shuffled_order_unique_and_stable():
    """protects=§1 order; fails_when=the order repeats a repository, differs between runs, or is not one list;
    no_claim=-."""
    leaves = [{"query": "postgres jest", "d": "postgres", "r": "jest", "a": 0, "b": 10, "total_count": 3, "read": 3,
               "items": [{"repo": f"o/r{i % 5}", "repo_url": f"https://github.com/o/r{i % 5}", "path": f"p{i}"}
                         for i in range(12)]},
              {"query": "mysql rspec", "d": "mysql", "r": "rspec", "a": 0, "b": 10, "total_count": 1, "read": 1,
               "items": [{"repo": "o/r1", "repo_url": "https://github.com/o/r1", "path": "x"}]}]
    o1, s1 = discover.build(leaves)
    o2, _ = discover.build(leaves)
    assert [r["repo"] for r in o1] == [r["repo"] for r in o2]
    assert len({r["repo"] for r in o1}) == len(o1) == 5
    assert "mysql x rspec" in next(r for r in o1 if r["repo"] == "o/r1")["pairs"]


def test_n_upper_ignores_parents_and_uses_max():
    """protects=N_upper definition (gate note 12); fails_when=parent ranges are summed or read > total_count is
    ignored; no_claim=-."""
    splits = [{"leaf": False, "total_count": 5000}, {"leaf": True, "total_count": 900, "read": 900},
              {"leaf": True, "total_count": 10, "read": 12}]
    assert R.n_upper(splits) == 912


def test_drop_check():
    """protects=DROP rule; fails_when=q=0, r=300, N=1000 (U x N ~ 12.6) is not DROP, N=2000 (~25) is DROP, an
    uncertain row is not in U's numerator, or an incomplete leaf allows DROP; no_claim=-."""
    d = R.drop_check(0, 0, 300, 1000, False)
    assert d["drop"] and abs(d["estimate"] - 12.6) < 0.1
    assert not R.drop_check(0, 0, 300, 2000, False)["drop"]
    assert abs(R.drop_check(0, 0, 300, 2000, False)["estimate"] - 25.3) < 0.1
    assert R.drop_check(0, 1, 300, 1000, False)["U"] > d["U"]
    assert not R.drop_check(0, 0, 300, 1000, True)["drop"]
    assert not R.drop_check(0, 0, 299, 10, False)["drop"]
    assert R.drop_reachable(1000) == 300
    assert R.drop_reachable(100000) == 19205


def test_excluded_not_counted_as_read():
    """protects=§5 read count; fails_when=an excluded candidate increments read; no_claim=-."""
    rows = [{"idx": 0, "cls": "excluded"}, {"idx": 1, "cls": "not_qualifying"}, {"idx": 2, "cls": "uncertain"},
            {"idx": 3, "cls": "candidate_ge10", "perworker": {"per_worker": False}, "handcheck": None}]
    c = S.counts(rows)
    assert c["read"] == 3 and c["excluded"] == 1 and c["uncertain"] == 1 and c["qualifying"] == 1


def test_compose_file_env():
    """protects=compose detection via -f, default names and COMPOSE_FILE (CHANGES.md 9); fails_when=a compose
    postgres is missed or a compose file without a database counts; no_claim=compose `extends` is followed."""
    comp = "services:\n  db:\n    image: postgres:16\n"
    read, _ = fs({"docker-compose.dev.yml": comp, "docker-compose.yml": "services:\n  r:\n    image: redis\n"})
    job = {"env": {"COMPOSE_FILE": "docker-compose.dev.yml"}, "steps": [{"run": "docker compose up -d"}]}
    assert R.db_job_evidence(job, {}, read)
    assert not R.db_job_evidence({"steps": [{"run": "docker compose up -d"}]}, {}, read)
    assert R.db_job_evidence({"steps": [{"run": "docker-compose -f docker-compose.dev.yml up -d"}]}, {}, read)
