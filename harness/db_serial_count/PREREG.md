# PREREG: public count of serial, database-bound test suites (database copies idea)

Committed before any data (AC1). Spec: rev 5 (gate 7/10, `20261124-db-serial-count-gate-rev5.md`, founder "manda"
2026-11-24), with the twelve rev-5 gate notes applied. Launch date: **2026-11-24**. Any change after this commit is
listed in `REPORT.md` under "Changes after PREREG" before any result.

## Decision line (founder, fixed)

By 1 Dec 2026, if fewer than 20 public repositories have a serial, database-bound test step of 10 minutes or more
(median of their last 10 successful runs on the default branch) and no per-worker database, the idea is dropped;
otherwise it goes to a /plan-ceo-review. CONTINUE needs 20 actual repositories; DROP needs a conservative upper
estimate below 20 (§5); otherwise NO DECISION.

## Constants

- `WINDOW_START` = launch date - 90 days = **2026-08-26** (used by every chunk; also the `pushed_at` staleness cut).
- Seed: `random.Random(1)`.
- z = 1.96, z² = 3.8416.
- User-Agent `fenvix-research`; sleep when `X-RateLimit-Remaining` < 50 until reset; code search <= 9 requests/min.
- PyYAML 6.0.2 (`requirements.txt`).

## §0 Route

Probe query `postgres jest path:.github/workflows` from the workflow (`GITHUB_TOKEN`) and from the work session
(`gh api -X GET search/code`); raw JSON committed. The route with the larger `total_count` runs discovery (if they
differ, both recorded). The workflow route does all non-search reads. Neither HTTP 200 -> REPORT first line `BLOCKED`.
Workflow triggers on `push` to `claude/db-serial-count` only, `paths: harness/db_serial_count/requests/**`
(gate note 3); a run processes only request files added by the push (`git diff --diff-filter=A before..sha`).

## §1 Discovery (verbatim)

Queries: for each database term D in {postgres, mysql, mariadb, mongo} and each runner term R in {jest, vitest,
mocha, "node --test", pytest, tox, nox, "manage.py", rspec, "rails test", rake, "go test", "npm test", "yarn test",
"pnpm test", "make test"}: `D R path:.github/workflows`. Each query starts as one range `size:0..400000` and is
bisected (`size:a..m`, `size:m+1..b`) until every split has `total_count` <= 1,000 or is a single size value. Every
split records `total_count`, `incomplete_results`, results read (<=1,000, all pages) and
`truncated = total_count > 1000 or incomplete_results`. Candidates = distinct repositories over all splits, one list
(each row keeps the DxR pairs that found it, as a report column only). Order: sort the list by `html_url`, then
`random.Random(1).shuffle(list)` once; candidates are read in that order. Leaf splits = the final splits of the
bisection (no parent range counts). A leaf with `incomplete_results: true` is retried up to 3 times and its largest
`total_count` kept; a leaf still incomplete is marked `incomplete`.

**Interpretation (PREREG, spec):** covered runners are those listed; PHPUnit/Laravel, Maven/Gradle and other stacks
are not covered and are printed as a limit next to the decision.

Exclusions (from `GET /repos/{r}`): fork; archived; owner in {github, microsoft, anthropics, openai, mircoguidetti};
`pushed_at` older than 90 days (before `WINDOW_START`).

## §2 Per-candidate exact checks (verbatim, fetched files, contents API at the default branch)

1. **Workflow and job:** fetch every matched workflow file of the repository (path order), parse YAML. Database jobs =
   jobs with a `services:` entry whose `image` (after substituting `${{ matrix.X }}` with each value of the job's
   `strategy.matrix.X`) matches
   `^(postgres|postgis/postgis|cimg/postgres|mysql|mariadb|mongo|pgvector/pgvector|timescale/|bitnami/(postgresql|mysql|mariadb|mongodb))`,
   or a step whose `run:` matches `docker[ -]compose .*up` with such a service in the compose file (`-f <file>`
   targets, else `docker-compose.yml`, `docker-compose.yaml`, `compose.yml`, `compose.yaml` in the working
   directory), or `systemctl start (postgresql|mysql)` / `service (postgresql|mysql) start` /
   `/etc/init.d/(postgresql|mysql) start`, or a step `uses:` of `ankane/setup-postgres`, `ankane/setup-mysql`,
   `ankane/setup-mongodb`, `harmon758/postgresql-action`, `ikalnytskyi/action-setup-postgres`,
   `shogo82148/actions-setup-mysql`, `supercharge/mongodb-github-action`; matrix images include values from
   `strategy.matrix.include`. Every (file, database job) pair is checked in order (files by path, jobs in file order);
   a job with no runner step -> next job; a workflow with `on: workflow_call` is checked through its caller (a job
   `uses: ./.github/workflows/<file>` in any workflow of the repository, found by listing `.github/workflows` with the
   contents API; §3.1 then reads runs of the caller's workflow file), with API job names
   `<caller job> / <callee job>`; a caller from another repository -> `unsupported`. The repository's result is the
   first pair that qualifies; if none qualifies, the furthest stage any pair reached.
   - Gate note 5: list `.github/workflows` for every candidate and check every file that contains a database term
     (a truncated leaf can hide the qualifying file).
2. **Test steps:** split each step's `run:` into commands on newlines, `&&`, `||`, `;` and `|` (outside quotes); drop
   every command matching
   `\b(pip3?|python3? -m pip|uv pip|poetry|gem|bundle|npm|yarn|pnpm|apt(-get)?|brew|go)\s+(install|i|add|ci|get|mod download)\b`
   and every command where the runner word is followed by `--help`/`--version`; then every step with a remaining
   command that matches a runner command, in order, is a candidate test step (the job qualifies if any candidate step
   qualifies in §2.3 and §3):
   `\b(jest|vitest|mocha|pytest|python -m pytest|tox|nox|manage\.py test|rspec|rails test|bin/rails test|rake (test|spec)\b|go test|node --test|make test[\w-]*)\b`,
   or `\b(npm|yarn|pnpm)\b( run)? (test[\w:-]*)\b`. `make` targets are resolved in the `Makefile`, `tox`/`nox` in
   `tox.ini`/`noxfile.py` commands, `rake test|spec` maps to Rails minitest / RSpec, all up to 3 levels like package
   scripts. For a package-manager script, resolve the script in the job's `working-directory` `package.json` (root if
   none), recursively through `npm run`/`yarn`/`pnpm` up to 3 levels; a script not found (workspaces, monorepo tools)
   -> `unresolved`, reported, not counted.
   - Gate note 7: a target that resolves to no runner command = not a test step; a missing or variable-only target =
     unresolved.
   - Gate note 8: working-directory precedence: step > job `defaults.run` > workflow `defaults.run` > root.
3. **Serial** (flag regexes apply only to the line that invokes the runner, after script resolution, plus the
   runner's config file):

| Runner | Config read | Serial when | Reason |
|---|---|---|---|
| Jest | the file named by `--config`/`-c` if given, else `jest.config.{js,ts,cjs,mjs,json}` or `package.json` `jest` in the job's `working-directory` | command `--runInBand\|(^\|\s)-i(\s\|$)\|--maxWorkers[= ]1\b\|(^\|\s)-w[= ]?1\b`, or config `maxWorkers["']?\s*:\s*["']?1\b` | `explicit` |
| Vitest | `vitest.config.*`, `vite.config.*` | command `--no-file-parallelism\|--fileParallelism[= ]false\|--maxWorkers[= ]1\b`, or `--poolOptions\.(threads\|forks)\.single(Thread\|Fork)`, or config `fileParallelism\s*:\s*false\|singleFork\s*:\s*true\|singleThread\s*:\s*true\|maxWorkers\s*:\s*1\b` | `explicit` |
| Mocha | `.mocharc.{js,cjs,json,yml,yaml}`, `package.json` `mocha` | no `--parallel`/`-p` in the runner line and no `"?parallel"?\s*:\s*true` in config | `default-serial` |
| node:test | none | command `--test-concurrency[= ]1\b` | `explicit` |
| pytest | `addopts` of `pytest.ini` `[pytest]`, `pyproject.toml` `[tool.pytest.ini_options]`, `setup.cfg` `[tool:pytest]`, `tox.ini` `[pytest]`; workflow/job/step `env` `PYTEST_ADDOPTS` | serial when `-p no:xdist` is present, or when every `(^\|\s)(-n\s*(\S+)\|--numprocesses[= ](\S+))` value in the runner line, `addopts` and `PYTEST_ADDOPTS` is `0` (or there is none and no `--dist`) | `default-serial` when none; `explicit` for `-n 0` / `-p no:xdist` |
| Django | env `DJANGO_TEST_PROCESSES` (read only when `--parallel` has no value) | `manage.py test` without `--parallel`; or `--parallel[= ]1\b`; or bare `--parallel` with `DJANGO_TEST_PROCESSES=1` | `default-serial`; `explicit` otherwise |
| Rails minitest | `test/test_helper.rb` (comment lines ignored), env `PARALLEL_WORKERS` | no uncommented `parallelize(` line, or `parallelize(workers: 1)`, or `PARALLEL_WORKERS=1` | `default-serial` / `explicit` |
| RSpec | none | command without `parallel_rspec\|turbo_tests\|parallel_tests\|knapsack` | `default-serial` |
| Go | none | `go test` with `-p[= ]1\b` | `explicit` (without `-p 1` Go runs packages in parallel: not serial) |

`declared` overrides `explicit` only (never `default-serial`) when a comment line (`#`, `//`, `/*`, `*`) within 5
lines of the explicit serial setting matches
`\b(db|database|postgres|postgresql|mysql|mongo|shared|isolation|race|conflict|deadlock)\b` (case-insensitive).

Gate note 6: pytest `-n`: tokenize (shlex for strings, elements for TOML lists) and accept `-n[= ]?V`
(`-n auto`, `-nauto`, `-n=0`, `--numprocesses=4`, `--numprocesses 4`).

## §3 Duration (verbatim)

1. Runs: `GET /repos/{r}/actions/workflows/{file}/runs?branch=<default>&status=success&created=>=<WINDOW_START>&per_page=100`,
   newest first, paginated; runs whose `event` starts with `pull_request` are skipped. **Interpretation (PREREG,
   spec):** the 90-day window bounds "last 10 runs"; `WINDOW_START` = 2026-08-26.
2. Jobs: `GET /actions/runs/{id}/jobs?per_page=100` (paginate). The job pattern = the YAML job's `name:` (or key) with
   each `${{ ... }}` replaced by `.*`, anchored; an API job matches when its full `name`, or its `name` with one
   trailing ` (...)` removed, matches the pattern; it must have `conclusion: success`. Matrix legs: per run, the longest
   test-step duration over the legs. Gate note 9: matrix callers: the job-name pattern is built from caller and callee,
   with `( \(.*\))?` allowed after the caller: `^<caller>( \(.*\))? / <callee>$` (callee also with the one trailing
   ` (...)` removal).
3. Step: the API step whose `name` matches the YAML step's `name:` (each `${{ ... }}` as `.*`, anchored); for an unnamed
   step, the API name starting with `Run ` + the first 40 characters of the `run:` first line; when several steps
   match, the one at the same position among matches in step order. Duration = `completed_at - started_at`, only for
   a step with `conclusion: success`. A run without such a step gives no value; runs are read until 10 give a value or
   the window ends.
4. Median: exactly 10 runs with a step value, sorted; median = mean of the 5th and 6th values. Fewer than 10 ->
   `too_few_runs`, reported, not counted.

## §4 Per-worker database (verbatim; only for candidates that pass §2 and §3 with median >= 10.0 minutes)

Code search `repo:<r>` once per term: `JEST_WORKER_ID`, `VITEST_POOL_ID`, `VITEST_WORKER_ID`, `PYTEST_XDIST_WORKER`,
`TEST_ENV_NUMBER`, `testcontainers`, `pglite`, `parallelize`, `"CREATE DATABASE" TEMPLATE`; the first 100 hits per
term (one page). Only hit files under the job's `working-directory` (root if none) and under a path containing
`test`, `spec`, `conftest` or `setup` are fetched. A hit counts when: an env-var term's file matches
`\b(database|db|connection|schema|DATABASE_URL)\b`; `testcontainers`/`pglite` is imported (`from testcontainers`,
`import .*testcontainers`, `require\(['"](@testcontainers|testcontainers)`, `from ['"]@electric-sql/pglite`,
`gem ['"]testcontainers`); an uncommented `parallelize\(` has `workers:` other than `1`;
`CREATE DATABASE \S+ (WITH )?TEMPLATE` appears. Any counting hit -> `per_worker`, excluded from the line and listed.

## §5 Stop rule and budget (verbatim)

Order: §1's shuffled list. Exclusions are applied as each candidate is read and an excluded candidate is not counted
as read. For every other candidate, `read` += 1 and its row is one of: `qualifying` (database-bound, serial any
reason, step median >= 10.0 minutes, not `per_worker`); `uncertain` (`unresolved`, `unsupported`, or an API/YAML
error after one retry); `not qualifying` (every other result, including `too_few_runs`: **Interpretation (PREREG,
spec)**).

- **CONTINUE** when 20 repositories qualify and all 20 pass the hand check of AC4; a repository failing the hand check
  becomes `not qualifying` and reading continues.
- **DROP** when at least 300 candidates have been read, no leaf split is `incomplete`, and U x N_upper < 20, where
  U = the Wilson 95% upper bound (z = 1.96) of (qualifying + uncertain) / read, and N_upper = the sum over leaf splits
  only of max(`total_count`, results read) (gate note 12). Each query's root `total_count` is recorded as a
  cross-check. Checked after each chunk.
- **NO DECISION** when discovery exceeds 48 h, or the 24 h reading budget (counted from the end of discovery) ends
  first, or a leaf split stays `incomplete`. Gate note 4: an incomplete leaf only disables DROP; reading continues
  toward CONTINUE until the 24 h budget ends.

Printed after discovery: `pool: <candidates> candidates, N_upper <n>, N_files <f>, rate limit <X-RateLimit-Limit>/h,
estimated REST requests <k x candidates>, fits 24 h: yes|no, DROP reachable at q = 0 after <max(300,
floor(3.8416*N_upper/20 - 3.8416) + 1)> reads` (gate notes 1, 2, 11), with
N_files = distinct (repo, path) over all leaves + sum of max(0, total_count - results read) over truncated leaves,
k = 11 before chunk 1, then the requests per candidate observed in chunk 1. Next to the DROP line, the DROP frame
(gate note 10): keyword-discoverable, indexed repositories with a database term and a runner term in the same
workflow file.

Execution: §2/§3 in the workflow, request `requests/<n>.json` = `{"chunk": n, "candidates": [up to 150]}`; discovery
chunk request `{"chunk": n, "discovery": true}` resumed from `discovery_state.json` (gate note 3) if the workflow
route runs discovery. After each chunk the work session runs §4 on rows with median >= 10.0, updates the count and the
DROP check, then pushes the next request.

## Interpretations (open choices, fixed here before data)

1. **Database term** (gate note 5): a workflow file is checked when its text matches
   `(?i)postgres|mysql|mariadb|mongo|postgis|pgvector|timescale` or `docker[ -]compose .*up` (compose-started databases
   carry no database term in the workflow). Every listed `.yml`/`.yaml` file is fetched (needed to find callers of
   `workflow_call` files); files are checked in path order.
2. **Row class when no pair qualifies:** if any pair is `unresolved`, `unsupported` or `error`, the row is `uncertain`
   (it could hide a qualifying pair; conservative for DROP); otherwise the furthest stage reached:
   `no_db_job` < `no_test_step` < `not_serial` < `too_few_runs` < `below_10`. The furthest stage of all pairs is kept as
   a separate column for the funnel.
3. **Monorepo tools:** a package script whose body runs `turbo`, `lerna`, `nx`, `npm -w/--workspace(s)`,
   `yarn workspaces`, `yarn workspace`, `pnpm -r/--recursive/--filter` (or `-F`) is `unresolved`, not "no runner".
   Any other resolved body without a runner command is not a test step (gate note 7).
4. **Make:** the target's recipe lines (tab-indented lines after `target:`) and its prerequisite targets are resolved
   recursively (`make X`, `$(MAKE) X` and prerequisites count as one level each, up to 3 levels). A recipe line whose
   command word is a variable (`$(V)`, `${V}`) is substituted from a `V = | ?= | := ...` assignment in the Makefile; an
   unassigned variable makes the target `unresolved` when no other line runs a runner. A missing target ->
   `unresolved`. `-C <dir>` changes the directory of the resolved Makefile.
5. **tox:** `tox` without `-e` reads `[testenv]` `commands`; `tox -e a,b` reads `[testenv:a]` (falling back to
   `[testenv]`) for each. `tox.ini` missing -> `unresolved`. **nox:** `session.run("a", "b", ...)` string literals
   inside the session function (`-s/--session/-e` names, all sessions if none) form the runner line; non-literal
   arguments are dropped; `noxfile.py` missing -> `unresolved`.
6. **Runner identity** on a resolved runner line: the first of `manage.py test` (Django), `rails test`/`rake test`
   (Rails minitest), `rake spec`/`rspec` (RSpec), `go test` (Go), `node --test` (node:test), `vitest`, `jest`, `mocha`,
   `pytest` matching the line.
7. **Jest/Vitest config files** are read in the job's working directory (or the `--config` path, relative to it).
   `package.json` `jest` / `mocha` keys are read as JSON and searched as text with the config regex.
8. **Comment proximity for `declared`:** the 5 lines before and after the line holding the explicit setting, in the
   file where the setting was found (workflow file, script-holding file or config file). `package.json` has no
   comments.
9. **Repository 404/451** on `GET /repos/{r}` after one retry -> `uncertain` (`error`), per §5.
10. **Optional file 404** (configs, Makefile, compose file) is "absent", not an error; a missing
    `.github/workflows` listing (404) means no workflow -> `no_db_job`.
11. **Reusable workflow callers:** callee `on: workflow_call` with no caller in the repository -> the callee's own
    runs are read (it has none of its own, so it ends `too_few_runs`). The caller's `strategy.matrix` names are
    covered by `( \(.*\))?`.
12. **Timing per (file, job):** runs and jobs responses are shared between the steps of a file; per run the value of a
    YAML step is the longest successful duration over the matching API jobs (matrix legs); median per step; the pair's
    timing is the step with the largest median among its serial candidate steps.
13. **`wrapped`/`sharded` flags** are report columns only.
14. **§4 file reads** (a few per qualifying candidate) are made from the work session with `gh api` (5000/h), next to
    the §4 code searches.
