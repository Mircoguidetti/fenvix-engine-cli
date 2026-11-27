"""Tests for the test-quality count (spec AC2). Every fixture is synthetic: no network.

Each test states protects= (the rule it guards), fails_when= (the regression it catches), no_claim= (what it does not
show). Debug workflow requests may only name repositories listed in DEBUG_REPOS.
"""
from __future__ import annotations

import gzip
import json
import random
import sys
import textwrap
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discover  # noqa: E402
import ghapi  # noqa: E402
import history  # noqa: E402
import pipeline  # noqa: E402
import report  # noqa: E402
import rules as R  # noqa: E402
import verify  # noqa: E402

# Repositories a debug request (workflow route, non-search REST reads) may name: the tools' own repositories.
DEBUG_REPOS = ["stryker-mutator/stryker-js", "sourcefrog/cargo-mutants", "infection/infection", "boxed/mutmut"]


# ============================================================================================== helpers

def mut(cmd: str, files: dict | None = None, hit_files=()):
    """Resolve one workflow command; returns (tools, unresolved names, Res)."""
    files = files or {}
    ctx = R.Ctx(lambda p: files.get(p), sorted(files), hit_files)
    res = R.Res()
    R.Resolver(ctx).resolve(cmd, "", 0, [], res)
    return [m["tool"] for m in res.mutations], [u["name"] for u in res.unresolved], res


def ts(minute: float, base: str = "2026-06-01T10:00:00Z") -> str:
    import datetime as dt
    t = dt.datetime.fromisoformat(base.replace("Z", "+00:00")) + dt.timedelta(minutes=minute)
    return t.isoformat().replace("+00:00", "Z")


def api_job(name, minutes, conclusion="success", steps=None, start=0.0):
    steps = steps or [("Run mutation", "success", minutes)]
    out, t = [], start
    for i, (sn, sc, sm) in enumerate(steps):
        out.append({"name": sn, "number": i + 1, "conclusion": sc, "started_at": ts(t), "completed_at": ts(t + sm)})
        t += sm
    return {"id": random.randint(1, 10 ** 9), "name": name, "status": "completed", "conclusion": conclusion,
            "started_at": ts(start), "completed_at": ts(start + minutes), "html_url": f"https://x/job/{name}",
            "steps": out}


class FakeGH:
    """A request source answering by path pattern (trimmed shapes, as pipeline.trim stores them)."""

    def __init__(self, files: dict, meta: dict | None = None, runs: dict | None = None, jobs: dict | None = None,
                 commits: dict | None = None, details: dict | None = None, at_ref: dict | None = None,
                 pulls: dict | None = None, issues: dict | None = None, branch="main"):
        self.files, self.runs, self.jobs = files, runs or {}, jobs or {}
        self.commits, self.details, self.at_ref = commits or {}, details or {}, at_ref or {}
        self.pulls, self.issues = pulls or {}, issues or {}
        self.meta = {"full_name": "o/r", "fork": False, "archived": False, "pushed_at": "2026-10-01T00:00:00Z",
                     "default_branch": branch, "owner": "o", **(meta or {})}
        self.calls: list[str] = []

    def get(self, path: str, search: str | None = None):
        self.calls.append(path)
        p, _, q = path.partition("?")
        qs = urllib.parse.parse_qs(q)
        if p == "repos/o/r":
            return 200, self.meta
        if "/git/trees/" in p:
            return 200, {"truncated": False, "paths": sorted(self.files)}
        if "/contents/" in p:
            fp = urllib.parse.unquote(p.split("/contents/", 1)[1])
            ref = qs.get("ref", ["main"])[0]
            src = self.files if ref == self.meta["default_branch"] else self.at_ref.get(ref, {})
            if fp in src and src[fp] is not None:
                return 200, {"type": "file", "path": fp, "text": src[fp]}
            return 404, {"message": "Not Found"}
        if p.endswith("/runs"):
            f = p.split("/workflows/", 1)[1].split("/")[0]
            if self.runs.get(f) == "error":
                return 500, {"message": "Server Error"}
            rs = self.runs.get(f, [])
            if "event" in qs:
                rs = [r for r in rs if r.get("event") == qs["event"][0]]
            return 200, {"total_count": len(rs), "workflow_runs": rs[:100]}
        if p.endswith("/jobs"):
            rid = int(p.split("/runs/", 1)[1].split("/")[0])
            js = self.jobs.get(rid, [])
            return 200, {"total_count": len(js), "jobs": js}
        if p.endswith("/pulls"):
            return 200, self.pulls.get(p.split("/commits/")[1].split("/")[0], [])
        if p.endswith("/commits"):
            page = int(qs.get("page", ["1"])[0])
            return 200, self.commits.get(qs["path"][0], [])[(page - 1) * 100:page * 100]
        if "/commits/" in p:
            return 200, self.details[p.rsplit("/", 1)[1]]
        if p.startswith("search/issues"):
            return 200, self.issues.get(qs["q"][0], {"total_count": 0, "items": []})
        raise AssertionError(f"unexpected path {path}")


def runs_of(n: int, start_id: int = 1, event="push"):
    return [{"id": start_id + i, "event": event, "created_at": ts(-i * 60), "conclusion": "success"} for i in range(n)]


WF_MUT = textwrap.dedent("""\
    name: ci
    on: [push]
    jobs:
      mutation:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v4
          - name: Run mutation
            run: npx stryker run
    """)


def cand(**kw):
    return {"idx": 0, "repo": "o/r", "html_url": "https://github.com/o/r", "terms": ["A stryker"], "files": [], **kw}


# ============================================================================================== §2.3 matching

@pytest.mark.parametrize("cmd,tool", [
    ("npx stryker run", "stryker"), ("dotnet stryker", "stryker"),
    ("XDEBUG_MODE=coverage ./vendor/bin/infection --threads=4", "infection"),
    ("cargo mutants --in-diff x.diff", "cargo-mutants"), ("./gradlew pitest", "pitest"),
    ("cosmic-ray exec cfg.toml session.sqlite", "cosmic-ray"), ("bundle exec mutant run", "mutant"),
    ("php -d memory_limit=-1 vendor/bin/infection --threads=max", "infection")])
def test_mutation_commands_match(cmd, tool):
    """protects=§2.3 table rows for each tool; fails_when=a real mutation command of the spec fixtures is not
    recognised; no_claim=coverage of every flag combination a project may use."""
    assert mut(cmd)[0] == [tool]


def test_maven_profile_execution_matches():
    """protects=§2.3 PIT (Maven) lifecycle phase with an execution in an activated profile; fails_when=`mvn -Pmutation
    verify` with the profile's pitest-maven execution is not linked; no_claim=parent POM inheritance."""
    pom = """<project xmlns="http://maven.apache.org/POM/4.0.0"><profiles><profile><id>mutation</id><build><plugins>
      <plugin><groupId>org.pitest</groupId><artifactId>pitest-maven</artifactId><executions><execution>
      <goals><goal>mutationCoverage</goal></goals></execution></executions></plugin></plugins></build></profile>
      </profiles></project>"""
    tools, _, res = mut("mvn -Pmutation verify", {"pom.xml": pom})
    assert tools == ["pitest"] and res.mutations[0]["wrapped"] is True
    assert mut("mvn verify", {"pom.xml": pom})[0] == []  # profile not activated


@pytest.mark.parametrize("cmd", [
    "npm i -D @stryker-mutator/core", "dotnet tool install -g dotnet-stryker", "cargo binstall cargo-mutants",
    "composer require --dev infection/infection", "./gradlew build -x pitest", "cosmic-ray init cfg.toml s.sqlite",
    "stryker init", "mutmut results", "cargo install cargo-mutants"])
def test_not_mutation_commands(cmd):
    """protects=§2.2 install filter and §2.3 "not a mutation run" column; fails_when=an install or setup command is
    counted as a mutation run; no_claim=commands outside the table."""
    tools, unres, _ = mut(cmd)
    assert tools == [] and unres == []


def test_mvn_test_with_verify_binding_is_not_mutation():
    """protects=§2.3 phase ordering; fails_when=`mvn test` is linked although the execution is bound to verify;
    no_claim=custom phases."""
    pom = """<project><build><plugins><plugin><artifactId>pitest-maven</artifactId><executions><execution>
      <phase>verify</phase><goals><goal>mutationCoverage</goal></goals></execution></executions></plugin></plugins>
      </build></project>"""
    assert mut("mvn test", {"pom.xml": pom})[0] == []
    assert mut("mvn -B verify", {"pom.xml": pom})[0] == ["pitest"]
    assert mut("./mvnw package", {"pom.xml": pom})[0] == []


def test_maven_plugin_management_only_is_unresolved():
    """protects=§2.3 pluginManagement rule; fails_when=a pluginManagement-only pitest-maven is called no-mutation;
    no_claim=what the child modules actually declare."""
    pom = """<project><build><pluginManagement><plugins><plugin><artifactId>pitest-maven</artifactId></plugin>
      </plugins></pluginManagement></build></project>"""
    tools, unres, _ = mut("mvn verify", {"pom.xml": pom})
    assert tools == [] and unres == ["pitest in pluginManagement"] and R.has_term(unres[0], name=True)


@pytest.mark.parametrize("cmd", ["poetry run mutmut run", "python -m mutmut run", "npx -y stryker run",
                                 "node_modules/.bin/stryker run", "dotnet tool run dotnet-stryker",
                                 "cargo +nightly mutants", "./gradlew pitestDebug", "uv run mutmut run",
                                 "env CI=1 npx --yes stryker run"])
def test_prefixes_are_stripped(cmd):
    """protects=§2.2 prefix stripping; fails_when=a runner prefix hides the mutation command; no_claim=prefixes not
    in the PREREG list."""
    assert len(mut(cmd)[0]) == 1


def test_yarn_bare_stripped_only_when_not_a_script():
    """protects=gate note 5 (resolve before strip; `yarn <x>` stripped only when not a script); fails_when=`yarn
    mutate` skips the package.json script or `yarn stryker run` is not matched; no_claim=yarn berry plugins."""
    pj = json.dumps({"scripts": {"mutate": "stryker run --concurrency 4"}})
    t, _, res = mut("yarn mutate", {"package.json": pj})
    assert t == ["stryker"] and res.mutations[0]["via"] == ["yarn:mutate|package.json"]
    assert mut("yarn stryker run", {"package.json": json.dumps({"scripts": {}})})[0] == ["stryker"]


# ============================================================================================== §2.4 resolution

def test_npm_script_resolves_to_stryker():
    """protects=§2.4 npm scripts; fails_when=`npm run test:mutation` is not followed into package.json;
    no_claim=pre/post hooks."""
    files = {"package.json": json.dumps({"scripts": {"test:mutation": "stryker run"}})}
    assert mut("npm run test:mutation", files)[0] == ["stryker"]


def test_make_any_target_resolves():
    """protects=§2.4 make generalised to any target (not only make test*); fails_when=`make mutation` is ignored;
    no_claim=pattern rules or includes."""
    files = {"Makefile": "mutation:\n\tpoetry run mutmut run --paths-to-mutate src\n"}
    assert mut("make mutation", files)[0] == ["mutmut"]


def test_shell_script_resolves():
    """protects=§2.4 shell-script resolution; fails_when=`bash ci/mutate.sh` running mutmut is not linked;
    no_claim=sourced files or functions."""
    files = {"ci/mutate.sh": "#!/bin/bash\n# run mutation tests\nset -e\nmutmut run\n"}
    tools, _, res = mut("bash ci/mutate.sh", files)
    assert tools == ["mutmut"] and R.via_paths(res.mutations[0]["via"]) == ["ci/mutate.sh"]
    assert mut("./ci/mutate.sh", files)[0] == ["mutmut"]


def test_composer_rake_just_task_resolvers():
    """protects=§2.4 new resolvers (composer with @refs, Rakefile, justfile, Taskfile); fails_when=a mutation command
    behind one of them is missed; no_claim=dynamic task definitions."""
    composer = json.dumps({"scripts": {"mutation": "@infect", "infect": ["@php vendor/bin/infection --min-msi=80"]}})
    assert mut("composer mutation", {"composer.json": composer})[0] == ["infection"]
    assert mut("composer run-script mutation", {"composer.json": composer})[0] == ["infection"]
    rake = "task :mutant do\n  sh 'bundle exec mutant run --since main'\nend\n"
    assert mut("bundle exec rake mutant", {"Rakefile": rake})[0] == ["mutant"]
    just = "mutants:\n    cargo mutants --in-place\n"
    assert mut("just mutants", {"justfile": just})[0] == ["cargo-mutants"]
    tf = "version: '3'\ntasks:\n  mutation:\n    cmds:\n      - go-mutesting ./...\n"
    assert mut("task mutation", {"Taskfile.yml": tf})[0] == ["go-mutesting"]


def test_resolution_depth_limit():
    """protects=§2.4 three-level limit; fails_when=resolution recurses without limit; no_claim=what lies deeper."""
    pj = json.dumps({"scripts": {"a": "npm run b", "b": "npm run c", "c": "npm run d", "d": "stryker run"}})
    tools, unres, _ = mut("npm run a", {"package.json": pj})
    assert tools == [] and unres


def _row_for(workflow: str, files: dict | None = None, hit_files=(), runs=None, jobs=None):
    fs = {".github/workflows/ci.yml": workflow, **(files or {})}
    gh = FakeGH(fs, runs=runs, jobs=jobs)
    return pipeline.run_candidate(gh, cand(files=list(hit_files)), {"no_history": True}), gh


def test_missing_mutation_script_is_unresolved_but_lint_is_ignored():
    """protects=§2.6 unresolved only with a tool term; fails_when=a missing `test:mutation` script reads as
    no-mutation, or a missing `lint` script makes the row uncertain; no_claim=scripts in other workspaces."""
    wf = "on: [push]\njobs:\n  t:\n    runs-on: x\n    steps:\n      - run: npm run test:mutation\n"
    row, _ = _row_for(wf, {"package.json": json.dumps({"scripts": {}})})
    assert row["mclass"] == "unresolved" and row["cls"] == "uncertain"
    wf2 = "on: [push]\njobs:\n  t:\n    runs-on: x\n    steps:\n      - run: npm run lint\n"
    row2, _ = _row_for(wf2, {"package.json": json.dumps({"scripts": {}})})
    assert row2["mclass"] == "no-mutation" and row2["cls"] == "not-running"


def test_gradle_check_with_pitest_dependency_is_unresolved():
    """protects=§2.3 Gradle wiring rule; fails_when=`./gradlew check` with `check.dependsOn pitest` is called
    no-mutation; no_claim=whether pitest really runs in that build."""
    files = {"build.gradle": "plugins { id 'info.solidsoft.pitest' }\ncheck.dependsOn pitest\n"}
    tools, unres, _ = mut("./gradlew check", files)
    assert tools == [] and len(unres) == 1 and "pitest" in unres[0]
    assert mut("./gradlew check -x pitest", files) [1] == []


def test_stryker_conf_with_unknown_binary_step_is_uncertain():
    """protects=§2.6 tool-present-unlinked via a step name; fails_when=a repository with stryker.conf.js and a step
    named `Mutation tests` running an unknown binary is not-running; no_claim=tool config files as a term source (they
    are not one: without the step name the row is no-mutation)."""
    wf = ("on: [push]\njobs:\n  t:\n    runs-on: x\n    steps:\n      - name: Mutation tests\n"
          "        run: ./tools/mut-runner --all\n")
    files = {"stryker.conf.js": "module.exports = {mutate: ['src/**']}"}
    row, _ = _row_for(wf, files)
    assert row["mclass"] == "tool-present-unlinked" and row["cls"] == "uncertain"
    assert row["term_hits"][0]["kind"] == "step-name"
    row2, _ = _row_for(wf.replace("Mutation tests", "Checks"), files)
    assert row2["mclass"] == "no-mutation"


def test_conditional_terms_infection_composer_and_ruby_mutant():
    """protects=§2.5 conditional terms (infection anywhere in a composer.json script, mutant only with a Gemfile naming
    it); fails_when=either gate is removed or inverted; no_claim=other files."""
    wf = "on: [push]\njobs:\n  t:\n    runs-on: x\n    steps:\n      - run: composer qa\n"
    comp = json.dumps({"scripts": {"qa": ["phpstan", "echo infection skipped"]}})
    row, _ = _row_for(wf, {"composer.json": comp})
    assert row["mclass"] == "tool-present-unlinked"
    wf2 = "on: [push]\njobs:\n  t:\n    runs-on: x\n    steps:\n      - run: echo mutant later\n"
    assert _row_for(wf2)[0]["mclass"] == "no-mutation"
    assert _row_for(wf2, {"Gemfile": "gem 'mutant-rspec'\n"})[0]["mclass"] == "tool-present-unlinked"


def test_stryker_only_in_package_json_is_no_mutation():
    """protects=§2.6 no-mutation for dependency-only tools; fails_when=a devDependency without a workflow reaching it
    makes the row uncertain; no_claim=local developer use of the tool."""
    wf = "on: [push]\njobs:\n  t:\n    runs-on: x\n    steps:\n      - run: npm test\n"
    pj = json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"@stryker-mutator/core": "^8"}})
    row, _ = _row_for(wf, {"package.json": pj})
    assert row["mclass"] == "no-mutation"


def test_graphql_mutation_string_is_not_a_tool_term():
    """protects=§2.5 generic `mutation` excluded; fails_when=a GraphQL mutation in a workflow makes the row uncertain;
    no_claim=job names (where `mutation` does count)."""
    wf = ("on: [push]\njobs:\n  deploy:\n    runs-on: x\n    steps:\n      - run: |\n"
          "          curl -d '{\"query\": \"mutation { createRelease(id: 1) { id } }\"}' https://api.example\n")
    row, _ = _row_for(wf)
    assert row["mclass"] == "no-mutation" and not row["term_hits"]
    assert R.has_term("Mutation tests", name=True) and not R.has_term("mutation { x }")


# ============================================================================================== §2.7 frequency

@pytest.mark.parametrize("on,expected", [
    ("on: [push]", "every-change"), ("on:\n  schedule:\n    - cron: '0 3 * * *'", "scheduled"),
    ("on:\n  push:\n    tags: ['v*']", "manual"), ("on: [workflow_run]", "other"),
    ("on:\n  push:\n    branches: [main]\n    tags: ['v*']", "every-change")])
def test_frequency(on, expected):
    """protects=§2.7 frequency classes incl. tags-only push; fails_when=a tags-only push counts as every-change or a
    schedule is missed; no_claim=path filters."""
    wf = R.load_yaml(on + "\njobs: {}\n")
    assert R.frequency(R.events(wf)) == expected


def test_job_if_event_name_filters_frequency():
    """protects=§2.7 job-level `if:` on github.event_name; fails_when=a mutation job gated to schedule in a
    push+schedule workflow is called every-change; no_claim=other if expressions (flagged if-complex)."""
    evs = {"push", "schedule"}
    assert R.frequency(R.if_filter("github.event_name == 'schedule'", evs)[0]) == "scheduled"
    assert R.if_filter("${{ github.event_name != 'schedule' }}", evs) == ({"push"}, False)
    assert R.if_filter("github.ref == 'refs/heads/main'", evs) == (evs, True)


# ============================================================================================== §2.8 running, §3 duration

def test_skipped_mutation_step_is_no_evidence():
    """protects=§2.8 and gate note 6; fails_when=a run whose mutation step was skipped counts as running or gives a
    value; no_claim=jobs that never started."""
    jobs = {1: [api_job("mutation", 3, steps=[("Set up job", "success", 1), ("Run mutation", "skipped", 0)])]}
    row, _ = _row_for(WF_MUT, runs={"ci.yml": runs_of(1)}, jobs=jobs)
    assert row["status"] == "configured-not-running" and row["cls"] == "not-running"


def test_fifty_runs_without_the_job_and_more_left_is_uncertain():
    """protects=§2.8 runs cap; fails_when=a job not seen in the 50 newest runs (more remaining) is called
    configured-not-running; no_claim=older runs."""
    runs = runs_of(60)
    jobs = {r["id"]: [api_job("lint", 1, steps=[("Lint", "success", 1)])] for r in runs}
    row, gh = _row_for(WF_MUT, runs={"ci.yml": runs}, jobs=jobs)
    assert row["cls"] == "uncertain" and row["jobs"][0]["targets"][0]["inspected"] == 50
    assert sum(1 for c in gh.calls if c.endswith("jobs?per_page=100&page=1")) == 50


def test_medians():
    """protects=§3 median rule; fails_when=the even case does not average the middle values or 2 values give a median;
    no_claim=robustness to outliers."""
    assert R.median_upto10([10, 40, 20]) == 20
    assert R.median_upto10([10, 40, 20, 30]) == 25
    assert R.median_upto10([10, 40]) is None
    assert R.median_upto10(list(range(1, 13))) == 5.5  # only the first 10 values


def test_two_values_is_too_few_runs_and_pain_unknown():
    """protects=§3 too_few_runs -> §4.5 pain unknown; fails_when=a running repository with 2 timed runs gets pain no;
    no_claim=history results."""
    runs = runs_of(2)
    jobs = {r["id"]: [api_job("mutation", 12)] for r in runs}
    row, _ = _row_for(WF_MUT, runs={"ci.yml": runs}, jobs=jobs)
    assert row["cls"] == "running" and row["duration"]["too_few_runs"]
    row["history"] = {"done": True, "candidates": [], "requests": 1}
    row["issues"] = {"done": True, "candidates": []}
    assert R.pain_of(row, {})[0] == "unknown"


def test_longest_leg_vs_sum_of_legs():
    """protects=§3 run value = longest leg, machine minutes = sum; fails_when=a 2-leg matrix run is summed into the
    duration; no_claim=legs with different step layouts."""
    wf = WF_MUT.replace("runs-on: ubuntu-latest", "runs-on: ubuntu-latest\n    strategy:\n      matrix:\n"
                        "        shard: [1, 2]")
    runs = runs_of(3)
    jobs = {r["id"]: [api_job("mutation (1)", 20), api_job("mutation (2)", 35)] for r in runs}
    row, _ = _row_for(wf, runs={"ci.yml": runs}, jobs=jobs)
    b = row["duration"]["best"]
    assert b["median_min"] == 35 and b["machine_min"] == 55 and row["duration"]["pain"]


def test_job_wall_time_not_step_time():
    """protects=§3 interpretation (job wall time); fails_when=the 26-minute mutation step is used instead of the
    34-minute job; no_claim=queue time."""
    runs = runs_of(3)
    jobs = {r["id"]: [api_job("mutation", 34, steps=[("Set up job", "success", 8),
                                                      ("Run mutation", "success", 26)])] for r in runs}
    row, _ = _row_for(WF_MUT, runs={"ci.yml": runs}, jobs=jobs)
    assert row["duration"]["max_median_min"] == 34 and row["duration"]["pain"]
    assert row["duration"]["best"]["step_min"] == 26


def test_cancelled_at_timeout_gives_value_expression_timeout_does_not():
    """protects=§3 lower-bound values and CHANGES.md 9 (stopped at timeout = running evidence, timed_out like
    cancelled); fails_when=a leg cancelled at its 60-minute timeout is dropped, a job always killed at its timeout
    reads configured-not-running, or a `${{ }}` timeout gives a value; no_claim=step-level timeouts."""
    leg = api_job("mutation", 60, conclusion="cancelled", steps=[("Run mutation", "cancelled", 60)])
    st = [leg["steps"][0]]
    ev = R.leg_eval(leg, st, 60.0)
    assert ev["value_s"] == 3600 and ev["lower_bound"] and ev["evidence"]
    to = api_job("mutation", 60, conclusion="timed_out", steps=[("Run mutation", "cancelled", 60)])
    assert R.leg_eval(to, [to["steps"][0]], 60.0)["value_s"] == 3600
    assert R.leg_eval(leg, st, None)["value_s"] is None and not R.leg_eval(leg, st, None)["evidence"]
    assert R.timeout_of({}, {"timeout-minutes": "${{ inputs.t }}"}) is None
    assert R.timeout_of({"timeout-minutes": 45}, {"timeout-minutes": 90}) == 45
    assert R.timeout_of({}, {}) == 360
    short = api_job("mutation", 20, conclusion="cancelled", steps=[("Run mutation", "cancelled", 20)])
    assert R.leg_eval(short, [short["steps"][0]], 60.0)["value_s"] is None


def test_two_running_jobs_take_the_maximum():
    """protects=§3 repository duration = max median over running jobs; fails_when=the first or the mean job is used;
    no_claim=non-running jobs."""
    wf = WF_MUT + ("  mutation2:\n    runs-on: ubuntu-latest\n    steps:\n      - name: Run mutation\n"
                   "        run: npx stryker run --mutate src/b\n")
    runs = runs_of(3)
    jobs = {r["id"]: [api_job("mutation", 12), api_job("mutation2", 41)] for r in runs}
    row, _ = _row_for(wf, runs={"ci.yml": runs}, jobs=jobs)
    assert row["duration"]["max_median_min"] == 41


def test_jobs_trim_keeps_job_times():
    """protects=gate note 1 (trimmer keeps job started_at/completed_at/status); fails_when=the job times are dropped
    and every §3 value is lost; no_claim=step trimming."""
    d = {"total_count": 1, "jobs": [{"id": 1, "name": "m", "status": "completed", "conclusion": "success",
                                     "started_at": "a", "completed_at": "b", "html_url": "u", "steps": []}]}
    j = pipeline.trim("repos/o/r/actions/runs/1/jobs?per_page=100&page=1", d)["jobs"][0]
    assert (j["started_at"], j["completed_at"], j["status"]) == ("a", "b", "completed")


def test_reusable_workflow_followed_through_caller_and_unsupported_without_caller():
    """protects=§2.6 workflow_call via caller, gate note 2 unsupported; fails_when=a called mutation job is timed on
    its own file or a callee without caller is not uncertain; no_claim=remote reusable workflows."""
    callee = ("on: [workflow_call]\njobs:\n  mut:\n    runs-on: x\n    steps:\n      - name: Run mutation\n"
              "        run: npx stryker run\n")
    caller = "on: [pull_request]\njobs:\n  call:\n    uses: ./.github/workflows/mut.yml\n"
    runs = runs_of(3)
    jobs = {r["id"]: [api_job("call / mut", 31)] for r in runs}
    gh = FakeGH({".github/workflows/mut.yml": callee, ".github/workflows/ci.yml": caller},
                runs={"ci.yml": runs}, jobs=jobs)
    row = pipeline.run_candidate(gh, cand(), {"no_history": True})
    assert row["cls"] == "running" and row["jobs"][0]["freq"] == "every-change"
    assert row["jobs"][0]["targets"][0]["run_file"] == ".github/workflows/ci.yml"
    gh2 = FakeGH({".github/workflows/mut.yml": callee})
    row2 = pipeline.run_candidate(gh2, cand(), {"no_history": True})
    assert row2["jobs"][0]["status"] == "unsupported" and row2["cls"] == "uncertain"


def test_uses_action_is_a_mutation_step():
    """protects=§2.3 uses-action rule; fails_when=a stryker action step is not a mutation step or not listed;
    no_claim=what the action runs."""
    wf = "on: [push]\njobs:\n  m:\n    runs-on: x\n    steps:\n      - uses: someone/stryker-action@v1\n"
    row, _ = _row_for(wf, runs={"ci.yml": []})
    assert row["mclass"] == "has-mutation-job" and row["uses_actions"][0]["uses"] == "someone/stryker-action@v1"


# ============================================================================================== exclusions

def test_exclusions_and_maintainers():
    """protects=§1 exclusions (fork, archived, stale, maintainer); fails_when=an excluded candidate is read as a counted
    row; no_claim=maintainer rows are still listed as information."""
    gh = FakeGH({}, meta={"fork": True})
    assert pipeline.run_candidate(gh, cand())["cls"] == "excluded"
    gh = FakeGH({}, meta={"pushed_at": "2025-12-31T23:59:59Z"})
    assert pipeline.run_candidate(gh, cand())["excluded"] == ["stale"]
    gh = FakeGH({".github/workflows/ci.yml": WF_MUT}, meta={"owner": "Stryker-Mutator"},
                runs={"ci.yml": runs_of(1)}, jobs={1: [api_job("mutation", 5)]})
    row = pipeline.run_candidate(gh, cand())
    assert row["cls"] == "excluded" and row["cls_if_counted"] == "running" and "history" not in row


# ============================================================================================== §4 history

def _commit(sha, files, message="ci: tweak", date="2025-03-01T00:00:00Z", parent="p" + "0" * 39):
    return {"sha": sha, "message": message, "date": date, "parents": [parent], "html_url": f"https://c/{sha}",
            "files": [{"filename": f, "status": st, "previous_filename": None, "patch": patch, "has_patch": True}
                      for f, st, patch in files]}


def _running_row(extra_files=None):
    runs = runs_of(3)
    jobs = {r["id"]: [api_job("mutation", 10)] for r in runs}
    return {".github/workflows/ci.yml": WF_MUT, **(extra_files or {})}, {"ci.yml": runs}, jobs


def test_history_cap_300_gives_pain_unknown():
    """protects=§4 300-request cap; fails_when=history keeps requesting past 300 or a capped repository gets pain no;
    no_claim=which commits were left unread."""
    files, runs, jobs = _running_row()
    shas = [f"{i:040x}" for i in range(1, 400)]
    gh = FakeGH(files, runs=runs, jobs=jobs,
                commits={".github/workflows": [{"sha": s, "date": "2025-01-01T00:00:00Z"} for s in shas]},
                details={s: _commit(s, [("README.md", "modified", "+x")]) for s in shas})
    row = pipeline.run_candidate(gh, cand())
    h = row["history"]
    assert h["capped"] and h["requests"] == 300 and not h["done"]
    row["issues"] = {"done": True, "candidates": []}
    assert R.pain_of(row, {})[0] == "unknown"


def test_patch_without_term_or_flag_fetches_nothing():
    """protects=§4.1 fetch only when a patch line touches a tool term or a flag; fails_when=every workflow commit
    triggers two contents requests; no_claim=detection of changes hidden outside the patch."""
    files, runs, jobs = _running_row()
    s = "a" * 40
    gh = FakeGH(files, runs=runs, jobs=jobs, commits={".github/workflows": [{"sha": s, "date": "2025-01-01"}]},
                details={s: _commit(s, [(".github/workflows/ci.yml", "modified", "-  node: 18\n+  node: 20")])})
    row = pipeline.run_candidate(gh, cand())
    assert not any("?ref=" + s in c or "?ref=p000" in c for c in gh.calls)
    assert row["history"]["changes"] == [] and row["history"]["done"]


def test_duration_pain_runs_no_history():
    """protects=§4 history only without duration pain; fails_when=history requests are spent on a repository already
    in pain; no_claim=history of such repositories."""
    files, runs, _ = _running_row()
    jobs = {r["id"]: [api_job("mutation", 45)] for r in runs["ci.yml"]}
    gh = FakeGH(files, runs=runs, jobs=jobs)
    row = pipeline.run_candidate(gh, cand())
    assert row["duration"]["pain"] and "history" not in row
    assert not any("/commits" in c for c in gh.calls)
    assert R.pain_of(row, {}) == ("yes", ["duration"])


BASE = textwrap.dedent("""\
    on: [push, pull_request]
    jobs:
      mutation:
        runs-on: x
        steps:
          - name: Run mutation
            run: npx stryker run
    """)


@pytest.mark.parametrize("after,kind", [
    (BASE.replace("on: [push, pull_request]", "on:\n  schedule:\n    - cron: '0 2 * * *'"), "moved-off-change"),
    (BASE.replace("npx stryker run", "npx stryker run --incremental"), "narrowed"),
    (BASE.replace("npx stryker run", "npx stryker run --shard 1/4"), "cut"),
    (BASE.replace("runs-on: x", "runs-on: x\n    if: false"), "disabled"),
])
def test_each_history_kind_flips_a_yaml_pair(after, kind):
    """protects=§4.1 narrowing kinds on parent/commit workflow pairs; fails_when=one of the four kinds is not
    detected; no_claim=the reason (recall filter and hand read decide pain)."""
    out = R.compare_workflow(R.load_yaml(BASE), R.load_yaml(after))
    assert kind in out["kinds"]


def test_unrelated_diff_is_no_change():
    """protects=§4.1 precision; fails_when=an unrelated edit is a narrowing change; no_claim=semantic equivalence."""
    after = BASE.replace("runs-on: x", "runs-on: ubuntu-24.04")
    assert R.compare_workflow(R.load_yaml(BASE), R.load_yaml(after)) == {"kinds": [], "removed": [], "added": []}
    assert R.compare_patch("-  timeout: 10\n+  timeout: 20", "stryker.config.json") == []


def test_job_moved_to_new_nightly_workflow_is_moved_off_change():
    """protects=§4.1 cross-file move in one commit; fails_when=a job moved from ci.yml to a new
    nightly-mutation.yml is called disabled or nothing; no_claim=moves spread over unrelated pull requests."""
    files, runs, jobs = _running_row()
    files[".github/workflows/ci.yml"] = WF_MUT.replace("on: [push]", "on: [push]")
    nightly = BASE.replace("on: [push, pull_request]", "on:\n  schedule:\n    - cron: '0 2 * * *'")
    ci_after = "on: [push, pull_request]\njobs:\n  test:\n    runs-on: x\n    steps:\n      - run: npm test\n"
    s, parent = "b" * 40, "c" * 40
    gh = FakeGH(files, runs=runs, jobs=jobs,
                commits={".github/workflows": [{"sha": s, "date": "2025-05-01T00:00:00Z"}]},
                details={s: _commit(s, [(".github/workflows/ci.yml", "modified", "-          run: npx stryker run"),
                                        (".github/workflows/nightly-mutation.yml", "added", "+run: npx stryker run")],
                                    message="Move mutation tests to nightly, they take 40 minutes", parent=parent)},
                at_ref={parent: {".github/workflows/ci.yml": BASE},
                        s: {".github/workflows/ci.yml": ci_after, ".github/workflows/nightly-mutation.yml": nightly}})
    row = pipeline.run_candidate(gh, cand())
    ch = row["history"]["changes"]
    assert ch and ch[0]["kinds"] == ["moved-off-change"]
    assert row["history"]["candidates"][0]["reasons"]  # "minutes", "take" match


def test_reason_regex():
    """protects=§4.2 recall filter (with gate note 11 terms); fails_when="too slow"/"CI minutes" are missed or
    "mutation score" matches; no_claim=precision (hand read decides)."""
    assert R.reason_match("mutation tests too slow")
    assert R.reason_match("save CI minutes on PRs")
    assert R.reason_match("reduce time of the mutation job") and R.reason_match("speeds up CI")
    assert not R.reason_match("improve mutation score")


def test_complaint_only_issue_is_information_not_pain():
    """protects=§4.4/§4.5 only `confirmed` texts are pain; fails_when=a complaint-only issue gives pain yes;
    no_claim=the hand reader's judgement itself."""
    row = {"repo": "o/r", "cls": "running", "duration": {"pain": False},
           "history": {"done": True, "candidates": []},
           "issues": {"done": True, "candidates": [{"id": "issue:5", "date": "2025-02-01T00:00:00Z"}]}}
    assert R.pain_of(row, {})[0] == "unknown"  # not yet hand-read
    hr = {("o/r", "issue:5"): {"verdict": "information"}}
    assert R.pain_of(row, hr)[0] == "no"
    hr = {("o/r", "issue:5"): {"verdict": "confirmed"}}
    assert R.pain_of(row, hr)[0] == "yes"
    old = dict(row, issues={"done": True, "candidates": [{"id": "issue:5", "date": "2023-12-31T00:00:00Z"}]})
    assert R.pain_of(old, hr)[0] == "no"


def test_issue_queries_shape():
    """protects=§4.3 query form (4 OR operators, created filter, one per tool plus mutation); fails_when=a query exceeds
    GitHub's operator limit or misses the tool; no_claim=search relevance."""
    qs = history.issue_queries("o/r", ["stryker", "mutmut"])
    assert qs == [f"repo:o/r {t} (slow OR timeout OR minutes OR hours OR expensive) created:>=2024-01-01 {k}"
                  for t in ("stryker", "mutmut", "mutation") for k in ("is:issue", "is:pull-request")]
    assert all(q.count(" OR ") == 4 for q in qs)


# ============================================================================================== §5 decision

def _c(**kw):
    base = {"running": 0, "pain_yes": 0, "pain_unknown": 0, "uncertain": 0, "read": 300, "N": 1000,
            "all_read": False, "any_truncated": False, "any_incomplete": False, "handcheck_ok": True}
    return {**base, **kw}


def test_wilson_and_drop_estimates():
    """protects=§5 DROP (b) arithmetic; fails_when=the Wilson bound or the N scaling is wrong; no_claim=the choice of
    z = 1.96."""
    assert R.wilson_upper(0, 300) == pytest.approx(0.01264, abs=1e-5)
    d = R.decide(_c(N=1000))
    assert d["kind"] == "DROP" and d["U_R_N"] == pytest.approx(12.6, abs=0.1)
    d = R.decide(_c(N=9000))
    assert d["kind"] == "KEEP READING" and d["U_P_N"] == pytest.approx(113.8, abs=0.1)
    assert R.drop_reachable(1000) == 300 and R.drop_reachable(9000) == 1725


def test_uncertain_counts_in_both_numerators_and_unknown_in_up():
    """protects=§5 conservative numerators; fails_when=uncertain rows or pain unknown are left out of the upper bounds;
    no_claim=the size of the effect."""
    a = R.decide(_c(N=9000, read=1000))
    b = R.decide(_c(N=9000, read=1000, uncertain=5))
    assert b["U_R"] > a["U_R"] and b["U_P"] > a["U_P"]
    c = R.decide(_c(N=9000, read=1000, pain_unknown=5))
    assert c["U_P"] > a["U_P"] and c["U_R"] == a["U_R"]


def test_truncated_leaf_blocks_drop_a_and_adds_to_n():
    """protects=§5 DROP (a) needs no truncated leaf; §1 N adds unread hits; fails_when=a truncated frame gives DROP (a)
    or N ignores unread hits; no_claim=DROP (b), which may still apply."""
    leaves = [{"query": "A stryker", "a": 0, "b": 10, "total_count": 1500, "read": 2, "truncated": True,
               "incomplete": False, "items": [{"repo": "a/x", "repo_url": "u", "path": "p"},
                                              {"repo": "b/y", "repo_url": "v", "path": "q"}]}]
    _, pool = discover.build(leaves)
    assert pool["candidates"] == 2 and pool["N"] == 2 + 1498
    d = R.decide(_c(read=50, all_read=True, any_truncated=True, N=pool["N"]))
    assert d["kind"] != "DROP"
    d = R.decide(_c(read=50, all_read=True, N=60, running=3))
    assert d["kind"] == "DROP" and d["line"].startswith("DROP: whole frame read")


def test_continue_needs_actual_counts():
    """protects=§5 CONTINUE on actual rows only; fails_when=estimates or unknown pain trigger CONTINUE;
    no_claim=the hand check outcome."""
    assert R.decide(_c(running=100, pain_yes=20))["line"] == "CONTINUE: 100 running, 20 with time pain."
    assert R.decide(_c(running=100, pain_yes=19, pain_unknown=50, N=100000))["kind"] != "CONTINUE"
    assert R.decide(_c(running=100, pain_yes=20, handcheck_ok=False))["kind"] == "CONTINUE-pending-handcheck"


def test_excluded_not_counted_as_read(tmp_path):
    """protects=§1 exclusions never counted as read; fails_when=an excluded row increases `read`; no_claim=excluded rows
    are absent from the report (they are listed)."""
    res = tmp_path / "results"
    res.mkdir()
    rows = [{"idx": 0, "repo": "a/x", "cls": "excluded", "excluded": ["fork"]},
            {"idx": 1, "repo": "b/y", "cls": "not-running", "mclass": "no-mutation"}]
    (res / "rows.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    x = report.compute(report.load(res))
    assert x["c"]["read"] == 1 and x["c"]["excluded"] == 1


def test_shuffled_order_is_stable_and_unique():
    """protects=§1 order (sort by html_url, Random(1).shuffle once); fails_when=two builds differ or a repository repeats
    across queries; no_claim=randomness quality."""
    items = [{"repo": f"o/r{i}", "repo_url": f"https://github.com/o/r{i}", "path": "x"} for i in range(50)]
    leaves = [{"query": "A stryker", "a": 0, "b": 1, "total_count": 50, "read": 50, "truncated": False,
               "items": items},
              {"query": "B stryker filename:package.json", "a": 0, "b": 1, "total_count": 50, "read": 50,
               "truncated": False, "items": items[::-1]}]
    o1, _ = discover.build(leaves)
    o2, _ = discover.build(list(reversed(leaves)))
    assert [r["repo"] for r in o1] == [r["repo"] for r in o2]
    assert len({r["repo"] for r in o1}) == len(o1) == 50
    assert o1[0]["terms"] == ["A stryker", "B stryker filename:package.json"]
    expect = sorted(o1, key=lambda r: r["html_url"])
    random.Random(1).shuffle(expect)
    assert [r["repo"] for r in o1] == [r["repo"] for r in expect]


# ============================================================================================== AC1 / AC3 / AC5

def test_no_search_without_budget_free_file(tmp_path, monkeypatch):
    """protects=AC1 / rule 9 (no search before "search budget free"); fails_when=discovery or the probe can start
    without the recorded coordinator message; no_claim=the message's authenticity."""
    monkeypatch.setattr(discover, "BUDGET_FREE", tmp_path / "missing.json")
    with pytest.raises(SystemExit):
        discover.require_budget_free()


def test_client_get_only_pacing_and_retry_seconds(monkeypatch):
    """protects=AC5 (GET only; code <= 9/min, issues <= 25/min; 429 waits parsed as f2e649b); fails_when=a non-GET
    method is built, pacing is faster than the limits, or a millisecond wait is read as seconds; no_claim=GitHub's
    actual limits."""
    assert ghapi.GAPS["code"] >= 60 / 9 and ghapi.GAPS["issues"] >= 60 / 25
    assert ghapi.retry_seconds("try again in 581.6ms", {"retry-after": "581"}) == pytest.approx(2.5816)
    assert ghapi.retry_seconds("try again in 7.9s", {}) == pytest.approx(9.9)
    assert ghapi.retry_seconds("", {"retry-after": "30"}) == 30
    seen = []

    class Resp:
        status, headers = 200, {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=60):
        seen.append(req.get_method())
        return Resp()

    monkeypatch.setattr(ghapi.urllib.request, "urlopen", fake_urlopen)
    c = ghapi.Client(token="t", pace=0)
    c.get("repos/o/r")
    assert seen == ["GET"]
    with pytest.raises(ValueError):
        c.get("search/code?q=x", search="commits")


def test_debug_repos_only():
    """protects=launch rule (fixture reads only on repositories named in the tests); fails_when=a debug request file
    names another repository; no_claim=non-debug chunks."""
    for p in (HERE / "requests").glob("debug*.json"):
        assert set(json.loads(p.read_text())["repos"]) <= set(DEBUG_REPOS)


def test_verify_replays_rows_and_report(tmp_path, monkeypatch):
    """protects=AC3 (verify.py re-derives rows from raw responses and re-prints REPORT.md); fails_when=a row edited by
    hand or a stale REPORT.md passes; no_claim=correctness of the rules themselves."""
    res = tmp_path / "results"
    (res / "raw").mkdir(parents=True)
    files, runs, jobs = _running_row()
    gh = FakeGH(files, runs=runs, jobs={r["id"]: [api_job("mutation", 45)] for r in runs["ci.yml"]})
    monkeypatch.setattr(pipeline, "trim", lambda path, d: d)  # FakeGH already answers in trimmed shapes
    live = pipeline.LiveSource(type("C", (), {"get": lambda self, p, search=None: (*gh.get(p, search), {})})())
    c0 = cand()
    row = pipeline.run_candidate(live, c0, {})
    (res / "candidates.jsonl").write_text(json.dumps(c0) + "\n")
    (res / "rows.jsonl").write_text(json.dumps(row, sort_keys=True) + "\n")
    with gzip.open(res / "raw" / "1.jsonl.gz", "wt") as f:
        f.write(json.dumps({"idx": 0, "repo": "o/r", "opts": {}, "responses": live.responses}) + "\n")
    rp = tmp_path / "REPORT.md"
    monkeypatch.setattr(report, "HERE", tmp_path)
    rp.write_text(report.render(report.load(res)))
    assert verify.main(res, rp) == 0
    bad = dict(row, cls="not-running")
    (res / "rows.jsonl").write_text(json.dumps(bad, sort_keys=True) + "\n")
    assert verify.main(res, rp) == 1
    (res / "rows.jsonl").write_text(json.dumps(row, sort_keys=True) + "\n")
    rp.write_text(rp.read_text().replace("running 1", "running 2", 1))
    assert verify.main(res, rp) == 1


# ============================================================================================== review fixes (pass 1)

@pytest.mark.parametrize("cmd", ["npm --prefix web run test:mutation", "yarn --cwd web test:mutation",
                                 "pnpm -C web run test:mutation", "npm run --prefix=web test:mutation"])
def test_pm_options_with_values_before_subcommand(cmd):
    """protects=§2.4 npm/yarn/pnpm resolution with leading value options; fails_when=`--prefix web` hides the script
    (row no-mutation); no_claim=every package-manager option."""
    files = {"web/package.json": json.dumps({"scripts": {"test:mutation": "stryker run"}})}
    assert mut(cmd, files)[0] == ["stryker"]


def test_pm_filter_is_monorepo_unresolved():
    """protects=§2.6 conservative monorepo handling; fails_when=`pnpm --filter web test:mutation` reads no-mutation;
    no_claim=resolution across workspace packages."""
    tools, unres, _ = mut("pnpm --filter web test:mutation", {"package.json": json.dumps({"scripts": {}})})
    assert tools == [] and unres == ["test:mutation"]


def test_maven_errors_flag_takes_no_value():
    """protects=§2.3 Maven option parsing; fails_when=`mvn -B -e verify` skips the phase after -e; no_claim=other
    options."""
    pom = """<project><build><plugins><plugin><artifactId>pitest-maven</artifactId><executions><execution>
      <goals><goal>mutationCoverage</goal></goals></execution></executions></plugin></plugins></build></project>"""
    assert mut("mvn -B -e verify", {"pom.xml": pom})[0] == ["pitest"]


def test_maven_profile_with_activation_is_unresolved():
    """protects=CHANGES.md 10 (profile activated by default/property); fails_when=a pitest execution in an
    activeByDefault profile reads no-mutation; no_claim=whether the profile is active on CI."""
    pom = """<project><profiles><profile><id>pit</id><activation><activeByDefault>true</activeByDefault></activation>
      <build><plugins><plugin><artifactId>pitest-maven</artifactId><executions><execution><goals>
      <goal>mutationCoverage</goal></goals></execution></executions></plugin></plugins></build></profile></profiles>
      </project>"""
    tools, unres, _ = mut("mvn verify", {"pom.xml": pom})
    assert tools == [] and unres == ["pitest in maven profile pit"] and R.has_term(unres[0], name=True)


def test_gradle_multiline_wiring_is_unresolved():
    """protects=§2.3 Gradle wiring across a line break; fails_when=`check.dependsOn(\n 'pitest')` is missed;
    no_claim=wiring in buildSrc."""
    files = {"build.gradle.kts": "tasks.check {\n  dependsOn(\n    \"pitest\"\n  )\n}\n"}
    assert len(mut("./gradlew check", files)[1]) == 1


def test_extensionless_script_outside_trimmed_tree_is_read():
    """protects=Repo.read fallback for paths the trimmed tree drops; fails_when=`bash ci/mutate` (no .sh) reads as
    missing and the row is no-mutation; no_claim=binary files."""
    wf = "on: [push]\njobs:\n  m:\n    runs-on: x\n    steps:\n      - name: Run mutation\n        run: bash ci/mutate\n"
    gh = FakeGH({".github/workflows/ci.yml": wf}, runs={"ci.yml": runs_of(1)}, jobs={1: [api_job("m", 5)]})
    orig = gh.get

    def get(path, search=None):
        if "/git/trees/" in path:
            return 200, {"truncated": False, "paths": [".github/workflows/ci.yml"]}  # trimmed: ci/mutate dropped
        if path.startswith("repos/o/r/contents/ci%2Fmutate?") or path.startswith("repos/o/r/contents/ci/mutate?"):
            return 200, {"type": "file", "path": "ci/mutate", "text": "npx stryker run\n"}
        return orig(path, search)
    gh.get = get
    row = pipeline.run_candidate(gh, cand(), {"no_history": True})
    assert row["cls"] == "running"


def test_nested_reusable_workflow_chain():
    """protects=§2.6 workflow_call followed to the root caller (two levels); fails_when=runs are listed on the middle
    workflow and the row reads not-running; no_claim=remote reusable workflows."""
    top = "on: [push]\njobs:\n  ci:\n    uses: ./.github/workflows/mid.yml\n"
    mid = "on: [workflow_call]\njobs:\n  m:\n    uses: ./.github/workflows/mut.yml\n"
    mutw = ("on: [workflow_call]\njobs:\n  mut:\n    runs-on: x\n    steps:\n      - name: Run mutation\n"
            "        run: npx stryker run\n")
    runs = runs_of(3)
    gh = FakeGH({".github/workflows/top.yml": top, ".github/workflows/mid.yml": mid,
                 ".github/workflows/mut.yml": mutw}, runs={"top.yml": runs},
                jobs={r["id"]: [api_job("ci / m / mut", 40)] for r in runs})
    row = pipeline.run_candidate(gh, cand(), {"no_history": True})
    assert row["cls"] == "running" and row["duration"]["max_median_min"] == 40
    assert row["jobs"][0]["targets"][0]["run_file"] == ".github/workflows/top.yml"


def test_configured_not_running_with_unlinked_item_is_uncertain():
    """protects=gate note 2 (configured-not-running + unresolved/unlinked item -> uncertain); fails_when=the extra
    clause is dropped; no_claim=which item hides the run."""
    jobs = {1: [api_job("mutation", 3, steps=[("Run mutation", "skipped", 0)])]}
    wf = WF_MUT + "  legacy:\n    runs-on: x\n    steps:\n      - name: mutation tests (legacy)\n        run: ./tools/mut-runner\n"
    row, _ = _row_for(wf, runs={"ci.yml": runs_of(1)}, jobs=jobs)
    assert row["status"] == "uncertain" and row["cls"] == "uncertain"


@pytest.mark.parametrize("case", ["yaml", "runs500", "on"])
def test_error_paths_are_uncertain(case):
    """protects=§5 uncertain for API/YAML errors and unparsable on:; fails_when=any of them reads not-running;
    no_claim=the error's cause."""
    if case == "yaml":
        row, _ = _row_for("jobs:\n  mutation-tests:\n    steps: [\n      - run: npm run test:mutation\n")
    elif case == "runs500":
        row, _ = _row_for(WF_MUT, runs={"ci.yml": "error"})
    else:
        row, _ = _row_for(WF_MUT.replace("on: [push]", "on: [1, 2]"))
    assert row["cls"] == "uncertain"


def test_schedule_only_job_lists_schedule_runs_push_schedule_does_not():
    """protects=§2.8 `event=schedule` only when the job is reachable only by schedule; fails_when=a push+schedule
    job lists only scheduled runs; no_claim=other events."""
    wf = WF_MUT.replace("on: [push]", "on: [push, schedule]")
    runs = runs_of(3, event="push")
    row, gh = _row_for(wf, runs={"ci.yml": runs}, jobs={r["id"]: [api_job("mutation", 5)] for r in runs})
    assert row["cls"] == "running" and not any("event=schedule" in c for c in gh.calls)
    wf2 = WF_MUT.replace("on: [push]", "on:\n  schedule:\n    - cron: '0 1 * * *'")
    _, gh2 = _row_for(wf2, runs={"ci.yml": runs})
    assert any("event=schedule" in c for c in gh2.calls)


def test_other_mutation_job_uncertain_makes_pain_unknown():
    """protects=§4.5 conservative pain when a second mutation job could not be read; fails_when=pain is `no` while a
    second (possibly long) job failed or hit the runs cap; no_claim=its real duration."""
    other = ("on: [push]\njobs:\n  slow:\n    runs-on: x\n    steps:\n      - name: Run mutation\n"
             "        run: npx stryker run --all\n")
    runs = runs_of(3)
    gh = FakeGH({".github/workflows/ci.yml": WF_MUT, ".github/workflows/nightly.yml": other},
                runs={"ci.yml": runs, "nightly.yml": "error"},
                jobs={r["id"]: [api_job("mutation", 3)] for r in runs})
    row = pipeline.run_candidate(gh, cand(), {"no_history": True})
    assert row["cls"] == "running" and row["duration"]["other_uncertain"]
    row["history"] = {"done": True, "candidates": []}
    row["issues"] = {"done": True, "candidates": []}
    assert R.pain_of(row, {}) == ("unknown", ["another mutation job uncertain"])


def test_pain_unknown_reasons_and_case():
    """protects=§4.5 unknown reasons (history-error, issues not run) and case-insensitive hand-read keys;
    fails_when=a history error or a missing issues search gives pain no, or `O/R` misses its verdict;
    no_claim=reason wording."""
    base = {"repo": "o/r", "cls": "running", "duration": {"pain": False},
            "history": {"done": True, "candidates": [], "errors": ["commit abc: HTTP 502"]},
            "issues": {"done": True, "candidates": []}}
    assert R.pain_of(base, {})[0] == "unknown"
    no_issues = dict(base, history={"done": True, "candidates": []})
    no_issues.pop("issues")
    assert R.pain_of(no_issues, {}) == ("unknown", ["issues search not run"])
    upper = dict(base, repo="O/R", history={"done": True, "candidates": []},
                 issues={"done": True, "candidates": [{"id": "issue:5", "date": "2025-01-01"}]})
    assert R.pain_of(upper, {("o/r", "issue:5"): {"verdict": "confirmed"}})[0] == "yes"


def test_decision_guards():
    """protects=§5 guards (DROP b needs >= 300 read and no incomplete leaf; DROP a needs no incomplete leaf; budget ->
    NO DECISION); fails_when=any guard is dropped; no_claim=the thresholds' choice."""
    assert R.decide(_c(read=299, N=1000))["kind"] == "KEEP READING"
    assert R.decide(_c(read=300, N=1000, any_incomplete=True))["kind"] != "DROP"
    assert R.decide(_c(read=50, all_read=True, any_incomplete=True, N=60))["kind"] != "DROP"
    assert R.decide(_c(N=9000, budget_over=True))["kind"] == "NO DECISION"


def test_all_read_needs_every_candidate(tmp_path):
    """protects=§5 DROP (a) `every candidate read`; fails_when=all_read is true with a candidate unread;
    no_claim=excluded handling."""
    res = tmp_path / "results"
    res.mkdir()
    (res / "candidates.jsonl").write_text(json.dumps({"idx": 0, "repo": "a/x"}) + "\n" +
                                          json.dumps({"idx": 1, "repo": "b/y"}) + "\n")
    (res / "rows.jsonl").write_text(json.dumps({"idx": 0, "repo": "a/x", "cls": "not-running"}) + "\n")
    assert report.compute(report.load(res))["c"]["all_read"] is False


def test_handcheck_stop_rule_and_override():
    """protects=AC4 (>2 of 20 random running fail -> rule fix; reclassification applied); fails_when=the threshold or
    the override is lost; no_claim=sample choice."""
    smp = {"running": ["a/1", "a/2", "a/3"], "not-running": []}
    hc = {("a/1", "running"): {"ok": False}, ("a/2", "running"): {"ok": False}, ("a/3", "running"): {"ok": True}}
    assert report.handcheck_status(smp, hc)["stop"] is False
    hc[("a/3", "running")] = {"ok": False}
    assert report.handcheck_status(smp, hc)["stop"] is True
    rows = [{"repo": "a/1", "cls": "running"}]
    out = report.apply_handcheck(rows, {("a/1", "pain-yes"): {"ok": False, "reclass": {"pain": "no"}}})
    assert report.pain(out[0], {}) == ("no", ["hand check"])


def _hist_row(files, details, at_ref, commits_path=".github/workflows", extra=None):
    runs = runs_of(3)
    gh = FakeGH(files, runs={"ci.yml": runs}, jobs={r["id"]: [api_job("mutation", 10)] for r in runs},
                commits={commits_path: [{"sha": k, "date": v["date"]} for k, v in details.items()], **(extra or {})},
                details=details, at_ref=at_ref)
    return pipeline.run_candidate(gh, cand())


def test_history_removed_job_is_disabled():
    """protects=§4.1 `disabled` by removal (not added elsewhere); fails_when=deleting the mutation job is no change;
    no_claim=the reason (recall filter)."""
    s_, parent = "d" * 40, "e" * 40
    after = "on: [push, pull_request]\njobs:\n  test:\n    runs-on: x\n    steps:\n      - run: npm test\n"
    files = {".github/workflows/ci.yml": WF_MUT}
    det = {s_: _commit(s_, [(".github/workflows/ci.yml", "modified", "-        run: npx stryker run")],
                       message="drop mutation job, too slow", parent=parent)}
    row = _hist_row(files, det, {parent: {".github/workflows/ci.yml": BASE}, s_: {".github/workflows/ci.yml": after}})
    ch = row["history"]["changes"]
    assert ch and ch[0]["kinds"] == ["disabled"] and row["history"]["candidates"]


def test_history_script_file_change_is_seen():
    """protects=gate note 8 (script files reached in §2.4 are history paths); fails_when=a removed mutation command in
    ci/mutate.sh is not seen; no_claim=script semantics."""
    wf = WF_MUT.replace("npx stryker run", "bash ci/mutate.sh")
    files = {".github/workflows/ci.yml": wf, "ci/mutate.sh": "npx stryker run --incremental\n"}
    s_ = "f" * 40
    det = {s_: _commit(s_, [("ci/mutate.sh", "modified", "-mutmut run\n+echo skipped")], message="mutation too slow")}
    row = _hist_row(files, det, {}, commits_path="ci/mutate.sh")
    assert "ci/mutate.sh" in row["history"]["paths"]
    assert row["history"]["changes"][0]["kinds"] == ["disabled"]


def test_chunk_with_workflow_issues_route_needs_budget_free(tmp_path, monkeypatch):
    """protects=AC1 for the chunk path (issues searches from the workflow); fails_when=a chunk request with
    issues_route=workflow can run before the budget-free file; no_claim=session-route chunks (no search)."""
    import chunk as CH
    monkeypatch.setattr(discover, "BUDGET_FREE", tmp_path / "missing.json")
    with pytest.raises(SystemExit):
        CH.run_chunk({"chunk": 1, "candidates": [], "issues_route": "workflow"})


def test_client_retries_rate_limited_pages_until_they_return(monkeypatch):
    """protects=CHANGES.md 19 (no page skipped for a 429); fails_when=seven secondary 429s in a row end the request
    as a failed page; no_claim=the length of each wait."""
    monkeypatch.setattr(ghapi.time, "sleep", lambda s: None)
    c = ghapi.Client(use_gh=True)
    answers = [(429, {"x-ratelimit-remaining": "10"}, {"message": "secondary rate limit"})] * 7 + \
        [(200, {}, {"total_count": 1, "items": []})]
    monkeypatch.setattr(c, "_once", lambda path: answers.pop(0))
    st, data, _ = c.get("search/code?q=x", search="code")
    assert st == 200 and data["total_count"] == 1 and c.n_rate_limited == 7 and not answers
