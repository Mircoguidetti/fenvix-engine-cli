DONE

# DB serial count: REPORT

Printed by `python3 harness/db_serial_count/report.py` from the committed raw rows (`results/`). Rules: `PREREG.md`.

## Changes after PREREG (listed before any result)

Each line: change, justification. All were made before any §2-§5 result (row) existed.

1. **Route (§0):** the workflow route's `search/code` with `GITHUB_TOKEN` answered HTTP 429 ("try again in 2.04s",
   `X-RateLimit-Remaining` 10) on the first attempt (run 45450935955); discovery runs on the work-session route
   (HTTP 200, total_count 4,488), which the §0 rule picks when only one route returns 200. Re-probe results are in
   `routes.md`.
2. **§4 split across routes (replaces PREREG interpretation 14):** the work session's proxy refuses REST reads of
   third-party repositories (HTTP 403 "GitHub access to this repository is not enabled for this session"), and the
   workflow token is throttled on code search. §4 code searches run in the work session
   (`perworker.py search`); the hit files are fetched and evaluated in the workflow (request
   `{"chunk": n, "perworker": true}`). Same rules, different route.
3. **Reusable workflows (replaces PREREG interpretation 11):** a `workflow_call` callee with a local caller is timed
   through each caller's runs; a callee that also has its own triggers is also timed through its own runs; a callee
   with no local caller and no other trigger is `unsupported` (the spec's "caller from another repository"), not
   `too_few_runs`. Justification: matches the spec text; the PREREG interpretation would have hidden these as
   not qualifying.
4. **Package-script arguments:** `npm test -- --runInBand` / `yarn test --runInBand` append the extra arguments to the
   last command of the resolved script (what npm/yarn do), so the runner line carries them. Justification: the flag
   regexes apply to "the line that invokes the runner, after script resolution".
5. **§4 working directory per repository:** a hit counts if it is under the working directory of any of the
   repository's pairs with median >= 10.0 minutes. Justification: §4 runs once per repository.
6. **U while §4 is pending:** a row with median >= 10.0 whose §4 check is not finished counts in U's numerator (as
   uncertain) until §4 completes. Justification: conservative for DROP.
7. **Debug run:** request 3 runs the pipeline on 8 named repositories (`results/debug/`) to check the code against
   the live API; these rows are not candidates and are never counted.
8. **Image prefixes:** `IMAGE_RE` is applied after removing a `docker.io/` (or `index.docker.io/`) registry prefix and
   the official-image prefix `library/`. Found in the debug run: saleor/saleor uses `library/postgres:15-alpine`,
   which is the official `postgres` image and the anchored regex missed.
9. **`COMPOSE_FILE`:** for a `docker compose ... up` step without `-f`, the files named in the step/job/workflow env
   `COMPOSE_FILE` (colon-separated) are read before the default names. Found in the debug run: PostHog/posthog sets
   `COMPOSE_FILE: docker-compose.dev.yml:docker-compose.profiles.yml`. Compose `extends` is not followed (limit).
10. **Limit noted, rule unchanged:** databases started by a bare `docker run ... postgres` (e.g. forem/forem) are not
    database jobs under §2.1; they are not counted (listed under limits).

## Decision

`CONTINUE: 20 repositories meet the line.`

- qualifying by reason: declared 0, explicit 3, default-serial 17
- read 4685, qualifying 20, uncertain 314, pending §4 0, not qualifying 4351 (per_worker 11, hand check failed 4), excluded 3265
- U (Wilson 95% upper bound of (qualifying + uncertain + pending) / read) = 0.079016; N_upper = 267207; U x N_upper = 21113.66; DROP needs >= 300 read, no incomplete leaf (none incomplete), U x N_upper < 20; DROP reachable at q = 0 after 51322 reads
- DROP frame: keyword-discoverable, indexed public repositories with a database term and a runner term in the same workflow file (GitHub legacy code search, default branches)
- covered runners: Jest, Vitest, Mocha, node:test, pytest (incl. tox/nox), Django manage.py test, Rails minitest, RSpec, Go; not covered: PHPUnit/Laravel, Maven/Gradle, others

## Pool and feasibility

`pool: 157761 candidates, N_upper 267207, N_files 179718, rate limit 5000/h, estimated REST requests 1183208 (7.5 per candidate observed in chunk 1), fits 24 h: no, DROP reachable at q = 0 after 51322 reads`

Discovery: route `session`, started 2026-11-24T17:47:31+00:00, finished 2026-11-25T07:46:27+00:00; 954 split searches, 509 leaves, 0 truncated, 0 incomplete; distinct (repo, path) 179718 + 0 unread in truncated leaves = N_files 179718.

## Funnel

### Discovery per query

| query | root total_count | leaves | sum leaf max(total_count, read) | results read | truncated leaves |
|---|---|---|---|---|---|
| `postgres jest path:.github/workflows` | 4480 | 10 | 4736 | 4734 | 0 |
| `postgres vitest path:.github/workflows` | 13952 | 24 | 14280 | 14088 | 0 |
| `postgres mocha path:.github/workflows` | 204 | 1 | 229 | 229 | 0 |
| `postgres "node --test" path:.github/workflows` | 7440 | 15 | 7780 | 7417 | 0 |
| `postgres pytest path:.github/workflows` | 57728 | 90 | 61421 | 60924 | 0 |
| `postgres tox path:.github/workflows` | 1122 | 6 | 1079 | 1079 | 0 |
| `postgres nox path:.github/workflows` | 215 | 1 | 229 | 229 | 0 |
| `postgres "manage.py" path:.github/workflows` | 12128 | 24 | 12562 | 12477 | 0 |
| `postgres rspec path:.github/workflows` | 5280 | 14 | 5652 | 5652 | 0 |
| `postgres "rails test" path:.github/workflows` | 1840 | 9 | 1817 | 1817 | 0 |
| `postgres rake path:.github/workflows` | 7768 | 15 | 6916 | 6916 | 0 |
| `postgres "go test" path:.github/workflows` | 22560 | 37 | 25569 | 25386 | 0 |
| `postgres "npm test" path:.github/workflows` | 48832 | 76 | 50811 | 50246 | 0 |
| `postgres "yarn test" path:.github/workflows` | 2052 | 9 | 2135 | 2135 | 0 |
| `postgres "pnpm test" path:.github/workflows` | 14400 | 26 | 14986 | 14787 | 0 |
| `postgres "make test" path:.github/workflows` | 5568 | 14 | 6623 | 6469 | 0 |
| `mysql jest path:.github/workflows` | 746 | 1 | 800 | 800 | 0 |
| `mysql vitest path:.github/workflows` | 1108 | 5 | 1249 | 1249 | 0 |
| `mysql mocha path:.github/workflows` | 132 | 1 | 172 | 172 | 0 |
| `mysql "node --test" path:.github/workflows` | 868 | 1 | 900 | 900 | 0 |
| `mysql pytest path:.github/workflows` | 4168 | 11 | 4777 | 4708 | 0 |
| `mysql tox path:.github/workflows` | 390 | 1 | 400 | 400 | 0 |
| `mysql nox path:.github/workflows` | 81 | 1 | 81 | 81 | 0 |
| `mysql "manage.py" path:.github/workflows` | 1428 | 8 | 1409 | 1391 | 0 |
| `mysql rspec path:.github/workflows` | 813 | 1 | 840 | 840 | 0 |
| `mysql "rails test" path:.github/workflows` | 174 | 1 | 188 | 188 | 0 |
| `mysql rake path:.github/workflows` | 966 | 1 | 1000 | 1000 | 0 |
| `mysql "go test" path:.github/workflows` | 3308 | 9 | 3712 | 3686 | 0 |
| `mysql "npm test" path:.github/workflows` | 4528 | 11 | 4842 | 4842 | 0 |
| `mysql "yarn test" path:.github/workflows` | 355 | 1 | 400 | 400 | 0 |
| `mysql "pnpm test" path:.github/workflows` | 804 | 1 | 900 | 900 | 0 |
| `mysql "make test" path:.github/workflows` | 1134 | 7 | 1388 | 1388 | 0 |
| `mariadb jest path:.github/workflows` | 141 | 1 | 159 | 159 | 0 |
| `mariadb vitest path:.github/workflows` | 330 | 1 | 331 | 331 | 0 |
| `mariadb mocha path:.github/workflows` | 36 | 1 | 36 | 36 | 0 |
| `mariadb "node --test" path:.github/workflows` | 261 | 1 | 261 | 247 | 0 |
| `mariadb pytest path:.github/workflows` | 964 | 1 | 964 | 924 | 0 |
| `mariadb tox path:.github/workflows` | 147 | 1 | 175 | 175 | 0 |
| `mariadb nox path:.github/workflows` | 12 | 1 | 12 | 12 | 0 |
| `mariadb "manage.py" path:.github/workflows` | 174 | 1 | 179 | 179 | 0 |
| `mariadb rspec path:.github/workflows` | 68 | 1 | 68 | 68 | 0 |
| `mariadb "rails test" path:.github/workflows` | 19 | 1 | 19 | 19 | 0 |
| `mariadb rake path:.github/workflows` | 117 | 1 | 119 | 119 | 0 |
| `mariadb "go test" path:.github/workflows` | 721 | 1 | 800 | 800 | 0 |
| `mariadb "npm test" path:.github/workflows` | 674 | 1 | 700 | 700 | 0 |
| `mariadb "yarn test" path:.github/workflows` | 116 | 1 | 135 | 135 | 0 |
| `mariadb "pnpm test" path:.github/workflows` | 187 | 1 | 200 | 200 | 0 |
| `mariadb "make test" path:.github/workflows` | 250 | 1 | 270 | 270 | 0 |
| `mongo jest path:.github/workflows` | 1226 | 7 | 1282 | 1281 | 0 |
| `mongo vitest path:.github/workflows` | 1126 | 6 | 1094 | 982 | 0 |
| `mongo mocha path:.github/workflows` | 349 | 1 | 366 | 366 | 0 |
| `mongo "node --test" path:.github/workflows` | 451 | 1 | 451 | 432 | 0 |
| `mongo pytest path:.github/workflows` | 5232 | 12 | 4998 | 4898 | 0 |
| `mongo tox path:.github/workflows` | 202 | 1 | 226 | 226 | 0 |
| `mongo nox path:.github/workflows` | 53 | 1 | 53 | 53 | 0 |
| `mongo "manage.py" path:.github/workflows` | 239 | 1 | 246 | 246 | 0 |
| `mongo rspec path:.github/workflows` | 179 | 1 | 192 | 192 | 0 |
| `mongo "rails test" path:.github/workflows` | 15 | 1 | 15 | 15 | 0 |
| `mongo rake path:.github/workflows` | 236 | 1 | 291 | 291 | 0 |
| `mongo "go test" path:.github/workflows` | 1764 | 8 | 1809 | 1800 | 0 |
| `mongo "npm test" path:.github/workflows` | 9552 | 17 | 9786 | 9662 | 0 |
| `mongo "yarn test" path:.github/workflows` | 730 | 1 | 787 | 787 | 0 |
| `mongo "pnpm test" path:.github/workflows` | 763 | 1 | 800 | 800 | 0 |
| `mongo "make test" path:.github/workflows` | 472 | 1 | 500 | 500 | 0 |

### Candidates

- candidates in pool: 157761; taken in §1 order so far: 7950
- excluded: 3265 (fork 0, archived 1, owner 0, stale 3265; a row can have several)
- read: 4685
- database job found: 3336
- uncertain rows: 314 (unresolved 283, unsupported 4, error 27)
- test step found: 2439
- serial: 1772
- timed (10 runs): 704
- >= 10 min: 35
- per_worker: 11
- qualifying: 20

## Per stack

| stack | qualifying | median step minutes (median, Q1-Q3) | declared / explicit / default-serial |
|---|---|---|---|
| Go | 2 | 12.0 (11.6-12.5) | 0 / 2 / 0 |
| Node/Jest | 1 | 11.2 (11.2-11.2) | 0 / 1 / 0 |
| Node/Mocha | 1 | 10.2 (10.2-10.2) | 0 / 0 / 1 |
| Python/Django | 1 | 32.3 (32.3-32.3) | 0 / 0 / 1 |
| Python/pytest | 15 | 23.0 (12.5-29.7) | 0 / 0 / 15 |

## Qualifying list

| repository | stack | reason | median step min | last run | wrapped | sharded | workflow / job |
|---|---|---|---|---|---|---|---|
| https://github.com/trustedoss/trusca | Python/pytest | default-serial | 12.0 | 2026-11-24 | no | yes | `.github/workflows/ci.yml` / `test-integration-shards` |
| https://github.com/XChain-Platform/xchain-indexer | Node/Mocha | default-serial | 10.2 | 2026-11-22 | no | no | `.github/workflows/ci.yml` / `integration` |
| https://github.com/smartcontractkit/chainlink-aptos | Go | explicit | 11.1 | 2026-11-20 | no | no | `.github/workflows/aptos-relayer.yml` / `test` |
| https://github.com/nikhilvdev/healix | Python/pytest | default-serial | 14.2 | 2026-09-20 | no | no | `.github/workflows/ci.yml` / `test` |
| https://github.com/delentia-labs/Delentia-OS | Python/pytest | default-serial | 115.3 | 2026-11-25 | no | no | `.github/workflows/ci.yml` / `test` |
| https://github.com/zmadon8/Quill | Python/Django | default-serial | 32.3 | 2026-11-25 | no | no | `.github/workflows/ci.yml` / `test` |
| https://github.com/abhinavrathee/RetryRail | Python/pytest | default-serial | 29.5 | 2026-09-05 | no | no | `.github/workflows/ci.yml` / `python-quality` |
| https://github.com/tina4stack/tina4-python | Python/pytest | default-serial | 17.6 | 2026-11-24 | no | yes | `.github/workflows/test.yml` / `test` |
| https://github.com/kutschersteffen-cmd/Agentic-Research-Pipeline | Python/pytest | default-serial | 42.5 | 2026-11-25 | no | no | `.github/workflows/ci.yml` / `backend` |
| https://github.com/brunolnetto/sose | Python/pytest | default-serial | 13.0 | 2026-11-25 | no | no | `.github/workflows/ci.yml` / `coverage` |
| https://github.com/mudassir709/Football-AI-tactical-Analyst | Python/pytest | default-serial | 10.5 | 2026-11-23 | no | no | `.github/workflows/ci.yml` / `system` |
| https://github.com/SR2501/hoops-gm | Python/pytest | default-serial | 23.0 | 2026-09-24 | no | no | `.github/workflows/ci.yml` / `postgres` |
| https://github.com/Ashfaque386/TradingOS-2.0 | Python/pytest | default-serial | 24.9 | 2026-11-25 | no | no | `.github/workflows/ci.yml` / `backend` |
| https://github.com/penghaibin9/saas | Python/pytest | default-serial | 25.1 | 2026-11-06 | no | yes | `.github/workflows/main-canonical-release-gate.yml` / `backend-full-regression` |
| https://github.com/bertalan/mpmv | Python/pytest | default-serial | 29.9 | 2026-11-25 | no | no | `.github/workflows/ci.yml` / `e2e` |
| https://github.com/Deodat-Lawson/LaunchStack | Node/Jest | explicit | 11.2 | 2026-11-24 | no | no | `.github/workflows/CI.yml` / `check` |
| https://github.com/MadeByGFK/StackSift | Python/pytest | default-serial | 11.4 | 2026-11-20 | no | no | `.github/workflows/tests.yml` / `test` |
| https://github.com/elavoaiservice/alphagasiq | Python/pytest | default-serial | 11.9 | 2026-09-17 | no | no | `.github/workflows/ci.yml` / `backend-tests` |
| https://github.com/GetStream/Agents | Go | explicit | 13.0 | 2026-11-25 | no | no | `.github/workflows/integration.yml` / `integration` |
| https://github.com/eddiezgq/freecad-ai-parts | Python/pytest | default-serial | 59.6 | 2026-11-25 | no | no | `.github/workflows/ci.yml` / `test` |

## per_worker exclusions

- https://github.com/nucleoid/continuum: src/fixtures/test-helpers.ts ["CREATE DATABASE" TEMPLATE]: await pool.query(`CREATE DATABASE ${quote(name)} TEMPLATE ${quote(source)}`);; src/storage/embedding-logical-restore.test.ts ["CREATE DATABASE" TEMPLATE]: await maintenance.query(`CREATE DATABASE ${quote(database)} TEMPLATE template0`);; src/storage/coordination-final-remediation-review-2-integration.test.ts ["CREATE DATABASE" TEMPLATE]: await maintenance.query(`CREATE DATABASE ${quoteRole(databaseName)} TEMPLATE template0`);
- https://github.com/Abrechen2/TravStats: backend/jest.setup.ts [JEST_WORKER_ID]: const workerId = Number(process.env.JEST_WORKER_ID);; backend/src/__tests__/testHarness.test.ts [JEST_WORKER_ID]: expect(name).toMatch(new RegExp(`_w${process.env.JEST_WORKER_ID}$`));; backend/src/services/sharing/federation/__tests__/peerDatabase.ts ["CREATE DATABASE" TEMPLATE]: * than copied from the run's database: `CREATE DATABASE … TEMPLATE` refuses a source with open
- https://github.com/DupeisTaken/shbs-peer-tutoring-website: scripts/scheduling-profile/group-plan.spec.ts ["CREATE DATABASE" TEMPLATE]: assert.match(reset?.run ?? "", /CREATE DATABASE shbs_performance_test TEMPLATE template0 ENCODING 'UTF8'/);; src/test/database-guard-subprocess.test.ts ["CREATE DATABASE" TEMPLATE]: `CREATE DATABASE "${rejectedDbName}" TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'`,; scripts/recovery-transfer-journal-postgres.test.ts ["CREATE DATABASE" TEMPLATE]: `CREATE DATABASE "${name}" TEMPLATE template0 ENCODING 'UTF8'`,
- https://github.com/moisturicer/IRIS: backend/apps/tests/test_parallel.py [PYTEST_XDIST_WORKER]: "    Path(__file__).with_suffix('.' + name).write_text(os.environ['PYTEST_XDIST_WORKER'])\n"
- https://github.com/chaw1/datakeel: tests/db_templates.py ["CREATE DATABASE" TEMPLATE]: connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{source}"')); tests/dataset_store/test_version_order.py ["CREATE DATABASE" TEMPLATE]: f"CREATE DATABASE \"{name}\" TEMPLATE template0 ENCODING 'UTF8' "
- https://github.com/suleymanozkeskin/horsies: core/src/workflow_engine/port_tests/stack_margin.rs ["CREATE DATABASE" TEMPLATE]: /// at its `CREATE DATABASE ... TEMPLATE`.
- https://github.com/CosmaNeura/cosmaneura-os: tests/integration/test_scheduling_patient_restore.py ["CREATE DATABASE" TEMPLATE]: # Fail before subprocess or CREATE DATABASE unless inside the established guard.
- https://github.com/qontinui/qontinui-web: backend/tests/api/test_ui_bridge_states_routes.py [PYTEST_XDIST_WORKER]: if os.environ.get("PYTEST_XDIST_WORKER") and request.config.getoption(; backend/tests/test_coordconv_00_production_shape.py ["CREATE DATABASE" TEMPLATE]: which ``CREATE DATABASE ... TEMPLATE`` requires. It is dropped when the
- https://github.com/gokhanng/agentsozluk: tests/integration/a5-migration-timeouts.test.ts ["CREATE DATABASE" TEMPLATE]: await integrationDatabase.$executeRaw`CREATE DATABASE "agent_sozluk_a5_lock_test" TEMPLATE template0`;; tests/integration/a5-phase-sql.test.ts ["CREATE DATABASE" TEMPLATE]: await integrationDatabase.$executeRaw`CREATE DATABASE "agent_sozluk_a5_probe_test" TEMPLATE template0`;; tests/integration/nightly-backup-format.test.ts ["CREATE DATABASE" TEMPLATE]: sql("postgres", `CREATE DATABASE "${name}" TEMPLATE template0`);
- https://github.com/vbcherepanov/total-agent-memory: tests/pg_support.py ["CREATE DATABASE" TEMPLATE]: """A reachable server. ``admin_url`` may create databases and roles."""; tests/test_db_check.py ["CREATE DATABASE" TEMPLATE]: admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8' LOCALE_PROVIDER icu "
- https://github.com/spatiumnorth/spatiumddi: backend/tests/conftest.py [PYTEST_XDIST_WORKER]: xdist exposes ``PYTEST_XDIST_WORKER`` per worker process (``gw0``,

## AC4 hand checks

From `handcheck.jsonl` (last record per repository and category; evidence printed by `handcheck_show.py` from the committed raw responses). qualifying: pass = the >= 10 min step is serial and uses the database; a fail makes the row not qualifying. serial_reject: the first 10 rows (in §1 order) rejected at the serial stage; pass = the step really runs tests concurrently. per_worker: pass = the §4 hit is a per-worker database.

### qualifying: 20 pass, 5 fail

- FAIL sbomify/sbomify: FAIL: ci-cd.yml job tests, step Run tests (lines 169-178) runs docker compose exec tests sh -c "uv run pytest --tb=short -n auto --dist loadscope ..." (xdist), so it is not serial. The rule tokenizes the runner line with shell quoting, so the whole quoted sh -c argument is one token and -n auto inside it is never seen. Recomputed median 944.5 s matches the row. No rule changed; defect listed in limits.
- FAIL DEFTileu/aelys: FAIL: not database-bound. ci.yml job backend has service postgres:16, but the ge_10 step (number 13, 'Run PYTHONPATH=backend .venv/bin/pytest -q backend/tests', median 645 s recomputed by exact step name) sets no database variable. backend/app/core/config.py defaults database_url to sqlite+aiosqlite, and backend/tests/conftest.py sets none, so it runs on SQLite. The Postgres suites run in later steps gated on AELYS_TEST_*_POSTGRES_ADMIN_URL, all well under 10 min. Serial (no -n). No rule changed: job-level service detection is a known limit.
- FAIL TIM-Intelegence-market/tim-ai-platform: FAIL: ci.yml job test, step Run test suite with coverage (lines 66-79) runs two pytest commands: first the main suite with -n 4 --dist loadgroup (xdist, read correctly as not serial), then only tests marked serial (read as serial). The rules call a step serial when any runner line in it is serial, so the step's 609 s median (recomputed, equal to the row) mostly measures the parallel run. Postgres service and TIM_DURABLE_TEST_DATABASE_URL are real. Not a serial step of 10 min. No rule changed; mixed-step limit listed in limits.
- FAIL plur-ai/plur: FAIL: not a serial step. ci.yml job test, step pnpm test = vitest run over a multi-project vitest.config.ts: 10 projects, of which only cli-spawn and core-pglite (the Postgres/PGLite files) set fileParallelism: false; the other projects, including about 107 core files per the config's own comment, run fully parallel. The rule took fileParallelism: false found anywhere in the config as the suite's setting. Recomputed median 986.5 s matches the row. No rule changed; multi-project config limit listed in limits.
- FAIL spatiumnorth/spatiumddi: FAIL: not serial. ci.yml job backend-test-shard, step Run tests (line 570) runs python -m pytest "$@" -n auto --splits 12 --group N (xdist inside each shard). The rule's matched line was 'pytest reports', a shell comment inside the run block that mentions pytest (TEST_RE matches prose in comments), and that line has no -n. Recomputed longest-shard median 1599 s matches the row. No rule changed; defect listed in limits.
- PASS trustedoss/trusca: ci.yml test-integration-shards (display 'test (backend-integration, shard N)'): postgres:17.2-alpine service; step runs plain pytest (no -n) in apps/backend; pyproject.toml has no addopts -n and states CI does not run pytest-xdist. Longest shard leg per run over the 10 newest runs: 646,654,696,710,717,719,723,724,778,778 -> median 718.0 s (matches). Sharded across 3 jobs, each serial: flag only.
- PASS XChain-Platform/xchain-indexer: ci.yml job integration: mariadb:11.4 service; step 'Run the integration tier' runs npm run test:integration:ci = mocha --no-config --timeout 120000 --exit 'test/integration/**/*.test.js' (no --parallel; --no-config so .mocharc.yml is ignored). Step durations over the 10 newest runs: 334,450,462,566,610,620,620,629,630,638 -> median 615.0 s (matches).
- PASS smartcontractkit/chainlink-aptos: aptos-relayer.yml job test (display 'Integration Tests'): postgres:16 service, TEST_DB_URL set; step 'Run tests' = cd relayer && go test -count=1 -p=1 -tags=integration ./... (explicit -p=1). Durations over the 10 newest runs: 610,632,652,663,667,667,684,685,749,825 -> median 667.0 s (matches).
- PASS nikhilvdev/healix: ci.yml job test (matrix python 3.10-3.13): postgres:16 service, HEALIX_TEST_POSTGRES_URL set; unnamed step 'run: pytest --cov' (no -n); pyproject.toml has no -n/addopts parallelism. Longest matrix leg per run over the 10 newest runs: 133,271,318,778,842,865,873,889,1169,1197 -> median 853.5 s (matches). Last run 2026-09-20 (inside window).
- PASS delentia-labs/Delentia-OS: ci.yml job test (display 'Tests (Python X)', matrix 3.10-3.12): postgres:16-alpine service (plus an ollama service); step 'Run tests' = python -m pytest --cov=... -v (no -n); pyproject addopts '-v --tb=short --continue-on-collection-errors --import-mode=importlib' (no -n). Longest leg per run, 10 newest runs: 5141,5630,6711,6826,6886,6949,7116,7135,7185,7272 -> median 6917.5 s (matches). Rule passes; caveat for the report: the YAML comment says Postgres serves only the audit-chain tests and the job also waits on a real LLM, so the database is not what makes this suite slow.
- PASS zmadon8/Quill: ci.yml job test: service postgres:18; step Tests runs plain `python manage.py test` (no --parallel, so Django runs serially); 10 recomputed step durations give median 1940 s, equal to the row; per-worker §4 hit was a docs .md file, read, no evidence.
- PASS abhinavrathee/RetryRail: ci.yml job python-quality: service postgres:16.15, RETRYRAIL_TEST_DATABASE_URL set; step Test with coverage runs plain uv run pytest (no -n; addopts has none). Caveat: the same step first runs retryrail-v4-blind-reproduce, which is in the step time; the YAML comment says the suite alone takes about 31 min. 10 recomputed durations give median 1769 s, equal to the row. Valid only if §4 finds no per-worker database.
- PASS tina4stack/tina4-python: test.yml job test: services postgres:16, postgis, mysql:8, mssql, mongo:7 (plus redis, valkey, memcached, rabbitmq, greenmail); step Run tests (lines 419-442) runs pytest tests/ as 4 pytest-split groups in a plain sequential for loop, no -n, no xdist in pyproject. 10 recomputed durations give median 1059 s, equal to the row. Caveat: the suite also exercises many non-database services. Valid only if §4 finds no per-worker database.
- PASS kutschersteffen-cmd/Agentic-Research-Pipeline: ci.yml job backend (wd backend): service pgvector/pgvector:pg16 plus opensearch and neo4j, ARP_TEST_POSTGRES_DSN set; step Pytest runs plain pytest -q --cov (no -n; backend/pyproject.toml has no addopts -n). 10 recomputed durations give median 2552.5 s, equal to the row. Caveat (as with Delentia-OS): the YAML comment says only the opt-in integration suites use Postgres and every other test is DB-free, so the database is a small part of the step time. Valid only if §4 finds no per-worker database.
- PASS brunolnetto/sose: ci.yml job coverage: service postgres:19, SOSE_TEST_POSTGRES_DSN set; step Run authoritative coverage suite runs plain python -m pytest --cov (no -n; no xdist in pyproject; parallel = true there is [tool.coverage.run]). addopts loads tests.support.pytest_auto_postgres, which (public raw GET) only finds or starts one Postgres and sets the DSN, so there is no per-worker database. 10 recomputed durations give median 782 s, equal to the row. Side note: step Analyze codebase quality was also read as serial pytest because TEST_RE matched pytest-report.json (the same hyphen word-boundary defect as datakeel); it does not affect this row. Valid only if §4 finds no per-worker database.
- PASS mudassir709/Football-AI-tactical-Analyst: ci.yml job system: docker compose --profile app starts the whole platform (compose postgres:17-alpine); step Run the system tests runs plain python -m pytest tests/system -v (no -n). 10 recomputed durations give median 631 s, equal to the row (just above 600). Caveat: these are black-box HTTP system tests against the platform, which processes a video clip with AI models; Postgres is behind the app, and the step time is likely dominated by video inference rather than the database. Valid only if §4 finds no per-worker database.
- PASS SR2501/hoops-gm: ci.yml job postgres (wd backend): service postgres:16-alpine, TEST_DATABASE_URL set; step Full suite against Postgres runs plain pytest (addopts -q --strict-markers -m 'not live_smoke', no -n). Recomputed longest leg per run, 10 newest runs: median 1378 s, equal to the row. Valid only if §4 finds no per-worker database.
- PASS Ashfaque386/TradingOS-2.0: ci.yml job backend: service postgres:16-alpine (plus redis); step pytest (with coverage) runs plain pytest -q --cov with DATABASE_URL set to the service (no -n; backend/pyproject.toml has no addopts -n). 10 recomputed durations give median 1496.5 s, equal to the row. Valid only if §4 finds no per-worker database.
- PASS penghaibin9/saas: main-canonical-release-gate.yml job backend-full-regression (wd backend, 12 file shards): service mysql:8.0, TEST_DATABASE_URL to MySQL; step Run every backend test in this shard runs timeout 85m pytest <shard files> -q (no -n; backend/pytest.ini has none). Longest shard per run, 10 newest runs: median 1504 s, equal to the row. Side note: TEST_RE also matched the text raise SystemExit('empty pytest shard') in the shard-selection step (no effect on this row). Valid only if §4 finds no per-worker database.
- PASS bertalan/mpmv: ci.yml job e2e: service postgres:17; step Pytest (e2e) runs uv run pytest -m e2e (no -n; addopts -ra --strict-markers). Django settings mpmv.settings.test use the default Postgres DATABASES with TEST NAME test_mpmv (public raw GET), and the e2e tests are transactional Playwright tests. 10 recomputed durations give median 1792.5 s, equal to the row. Note: the repo's unit/integration jobs use xdist (-n auto --dist loadgroup) with pytest-django per-worker databases, but the e2e step itself is serial. Valid only if §4 finds no per-worker database.
- PASS Deodat-Lawson/LaunchStack: CI.yml job check: service pgvector/pgvector:pg16, job-level DATABASE_URL to it; step Web tests runs jest --runInBand --forceExit (explicit serial). The web suite includes real-Postgres integration tests (apps/web/__tests__/*/testDb.ts and *.integration.test.ts use LAUNCHSTACK_TEST_DATABASE_URL ?? DATABASE_URL, read by public raw GET and 2 code-search GETs), so the step is database-bound. 10 recomputed durations give median 672 s, equal to the row. Valid only if §4 finds no per-worker database.
- PASS MadeByGFK/StackSift: tests.yml job test: service postgres:16, job-level TEST_POSTGRES_URL used by several web tests (code search: test_batch_postgres_concurrency, test_account_migrations, test_shared_rate_limit, ...); step Run tests runs python -m pytest tests/ src/web/tests/ -v (no -n; no xdist in requirements-dev; no pytest.ini, no addopts in pyproject). 10 recomputed durations give median 683 s, equal to the row. Valid only if §4 finds no per-worker database.
- PASS elavoaiservice/alphagasiq: ci.yml job backend-tests: service postgres:16 plus an RLS role created in a prior step; step Run full test suite runs plain pytest (no -n; only pytest and pytest-asyncio installed; pytest.ini has no addopts -n). 10 recomputed durations give median 717 s, equal to the row. Caveat (as with Delentia-OS / Agentic-Research-Pipeline): most tests use in-memory SQLite; only tests/db/test_rls.py hits the Postgres service, so the database is a small part of the step time. Valid only if §4 finds no per-worker database.
- PASS GetStream/Agents: integration.yml job integration (wd acceleration, 6 package groups): service postgres:19-alpine (plus redis), wired in through internal/config/testing.yaml by the prior step; step Test runs go test -tags integration -p 1 -count=1 (packages one at a time: explicit serial under the Go rule). Longest group per run, 10 newest runs: median 778 s, equal to the row. Caveat: -p 1 serializes packages; tests inside a package may still use t.Parallel, which the rule does not inspect. Valid only if §4 finds no per-worker database.
- PASS eddiezgq/freecad-ai-parts: ci.yml job test: service pgvector/pgvector:pg16, job env FAP_TEST_DATABASE_URL points at it; step 'schema 校验、单元测试与数据库测试' (schema checks, unit and database tests) runs python -m pytest -v -rf with no -n; pyproject [tool.pytest.ini_options] has no addopts -n and pytest-xdist is not a dependency (serial by default). Recomputed median of the 10 newest runs 3574 s, equal to the row. Caveat: the step also runs the non-DB unit tests; the DB share is not measured. Valid only if §4 finds no per-worker database.

### serial_reject: 8 pass, 2 fail

- FAIL defiventurers/articweb3: passport-first33.yml job passport-first33 (postgres:16 service): four node --test steps, none with --test-concurrency 1, so the rule rejects them (applied as written). Two of them (frontend/public/early/heritage-launch.test.mjs; frontend/tests/early-entry.test.cjs) name a single file: node:test then runs one file process and its top-level tests in order, which is serial in practice. The other two (5 files; npm test -> 3 files) do run files concurrently. Reject correct for 2 of 4 steps: rule limit (single-file node --test counted as not serial).
- FAIL k4zann/Tengrinews: ci.yml job check (mongo:8.0 service): step 1 go test -race ./... (no -p 1, several packages: parallel, reject correct); step 2 go test -race -count=1 -v -run Integration ./internal/mongostore names one package, which is serial in practice (Go runs a package's tests in order unless t.Parallel). The rule rejects it only because -p 1 is absent: rule limit (single-package go test counted as not serial).
- PASS hamza442-ali/backend_DepEase: backend.yml job node (mongo:7 service): npm test -> node --test tests/*.test.js tests/unit/*.test.js and npm run test:integration -> node --test tests/integration/*.test.js; globs over several files, no --test-concurrency 1: files run concurrently. Reject correct.
- PASS Werewolf365/BNB26_arey_yaar_Internal_Round: ci.yml job integration (postgres:16-alpine service): go test -run TestPostgresIntegration ./apps/api/... without -p 1: packages run in parallel under the Go rule. Reject correct by the rule. Caveat: the committed evidence does not show how many packages hold TestPostgresIntegration; if only one does, the step is serial in practice (same Go-rule limit).
- PASS staqsIO/metrc-manager-3000-keyservice: ci.yml job test (postgres:16-alpine service): npm test -> node --test "test/*.test.js" (several files), no --test-concurrency 1: files run concurrently. Reject correct.
- PASS NiltonCarlosdawg/Kambaback: ci.yml job backend (postgres:16-alpine service): npm test -> npm run test:db && jest --coverage --watchAll=false in KambApi; no --runInBand/-i/--maxWorkers 1, KambApi/jest.config.js has no maxWorkers (its own comment mentions 5 workers starting at once). Jest runs workers in parallel. Reject correct.
- PASS drifthoundhq/drifthound: ci.yml job test (postgres service): bin/rails test and bin/rails test:system; test/test_helper.rb line 9 uncommented parallelize(workers: :number_of_processors), no PARALLEL_WORKERS in the workflow. Parallel. Reject correct.
- PASS KibouAkari/vector: application-ci.yml job build (postgres:16-alpine service): node --test on several *.integration.test.mjs files, no --test-concurrency 1: files run concurrently. Reject correct.
- PASS FDuser123-coding/Turgon: ci.yml jobs test and connectors (postgres:16 service): go test -race ./... and connector go test commands, no -p 1: packages in parallel. Reject correct.
- PASS inferedge-ai/evalkit: ci.yml job python (postgres:17 service): uv run pytest -n 4 (xdist, 4 workers); pyproject addopts "-m 'not e2e'" has no -n override. Parallel. Reject correct.

### per_worker: 3 pass, 7 fail

- FAIL DupeisTaken/shbs-peer-tutoring-website: All three counted hits are single tests that create one scratch database from template0 (a guard test, a recovery test, and an assertion on a reset script's SQL); none is a shared fixture or setup keyed on a worker. Exclusion not supported by the evidence (rule over-excludes). Verdict kept as per_worker (no rule change); reported as an AC4 failure.
- FAIL moisturicer/IRIS: Only evidence: backend/apps/tests/test_parallel.py writes os.environ['PYTEST_XDIST_WORKER'] to a file (an xdist self-test); no database is created per worker, and CI runs pytest without -n. Exclusion not supported (rule over-excludes). Verdict kept as per_worker (no rule change); reported as an AC4 failure.
- FAIL suleymanozkeskin/horsies: FAIL (over-exclusion). §4 verdict per_worker rests on core/src/workflow_engine/port_tests/stack_margin.rs line 104, a Rust doc comment ('every later test of this process failed at its CREATE DATABASE ... TEMPLATE'). The per-process template databases belong to the Rust core's own tests; the ge_10 job (coverage.yml, coverage) runs the Python suite: unit and integration pytest plus scripts/run_e2e_suite.sh, one pytest per file in a plain loop, no -n. Serial hand check passed (median 2216 s recomputed). Verdict kept; no rule changed.
- FAIL CosmaNeura/cosmaneura-os: FAIL (over-exclusion). §4 verdict per_worker rests on tests/integration/test_scheduling_patient_restore.py line 177: CREATE DATABASE <clone> TEMPLATE template0, one empty clone database made inside a single restore test, not a database per worker. The ge_10 step (scripts/check-backend-local.py) runs one Postgres and, per profile, one python -m pytest with no -n, sequentially. Serial hand check passed (median 1132.5 s recomputed). Verdict kept; no rule changed.
- FAIL qontinui/qontinui-web: FAIL (over-exclusion). §4 evidence: (1) tests/api/test_ui_bridge_states_routes.py line 1647 reads PYTEST_XDIST_WORKER only to skip a coverage check under some xdist modes; (2) tests/test_coordconv_00_production_shape.py builds one alembic template per test process and clones it with CREATE DATABASE ... TEMPLATE per scenario: a database copy per scenario, not per worker. The ge_10 step (backend-ci.yml test, 6 file shards) runs poetry run pytest with no -n. Serial hand check passed (median 1406.5 s recomputed). Verdict kept; no rule changed.
- FAIL gokhanng/agentsozluk: FAIL (over-exclusion). §4 evidence is 4 integration tests (a5-migration-timeouts, a5-phase-sql, nightly-backup-format, reviewed-migration-profile) that each create one named scratch database with CREATE DATABASE ... TEMPLATE template0 for a migration/backup scenario: per-test scratch databases, not a database per worker. vitest runs with fileParallelism: false and sequence.concurrent: false. Serial hand check passed (median 653 s recomputed). Verdict kept; no rule changed.
- FAIL vbcherepanov/total-agent-memory: FAIL (over-exclusion, strictly). §4 evidence: tests/pg_support.py fixture fresh_database creates a new database per test with CREATE DATABASE ... TEMPLATE template0, and tests/test_db_check.py creates one scratch database in a single test. That is a fresh database per test, not per worker; there is no xdist in the job. Note for the idea: this repo already makes a database per test, as qontinui-web does per scenario. Serial hand check passed (median 856.5 s recomputed). Verdict kept; no rule changed.
- PASS nucleoid/continuum: src/fixtures/test-helpers.ts: pool.query(`CREATE DATABASE ${name} TEMPLATE ${source}`) - a shared fixture that clones a template database per test/worker. Exclusion correct.
- PASS Abrechen2/TravStats: backend/jest.setup.ts reads JEST_WORKER_ID and testHarness.test.ts asserts the database name ends in _w${JEST_WORKER_ID}: one database per Jest worker. Exclusion correct.
- PASS chaw1/datakeel: per_worker verdict confirmed: tests/db_templates.py creates a database per worker with CREATE DATABASE ... TEMPLATE, and the Makefile target check-pytest runs scripts.run_pytest, which calls pytest.main with xdist -n <workers>. Separately, the serial classification was wrong: TEST_RE matched 'pytest' inside the make target name check-pytest, so the Makefile was never resolved. No rule changed; this defect is listed in limits.

## Chunks

- chunk 4: 150 candidates, 1125 requests (7.5 per candidate), 14.1 min, rate limit 5000/h, stopped: None
- chunk 5: 150 candidates, 1035 requests (6.9 per candidate), 27.1 min, rate limit 5000/h, stopped: None
- chunk 6: 150 candidates, 1069 requests (7.13 per candidate), 10.5 min, rate limit 5000/h, stopped: None
- chunk 7: 150 candidates, 912 requests (6.08 per candidate), 9.5 min, rate limit 5000/h, stopped: None
- chunk 8: 150 candidates, 971 requests (6.47 per candidate), 31.3 min, rate limit 5000/h, stopped: None
- chunk 9: 150 candidates, 982 requests (6.55 per candidate), 10.4 min, rate limit 5000/h, stopped: None
- chunk 10: 150 candidates, 1012 requests (6.75 per candidate), 10.0 min, rate limit 5000/h, stopped: None
- chunk 11: 150 candidates, 1060 requests (7.07 per candidate), 34.4 min, rate limit 5000/h, stopped: None
- chunk 12: 150 candidates, 1180 requests (7.87 per candidate), 11.2 min, rate limit 5000/h, stopped: None
- chunk 13: 150 candidates, 958 requests (6.39 per candidate), 9.4 min, rate limit 5000/h, stopped: None
- chunk 14: 150 candidates, 1332 requests (8.88 per candidate), 37.2 min, rate limit 5000/h, stopped: None
- chunk 15: 150 candidates, 1121 requests (7.47 per candidate), 13.6 min, rate limit 5000/h, stopped: None
- chunk 16: 150 candidates, 930 requests (6.2 per candidate), 9.0 min, rate limit 5000/h, stopped: None
- chunk 17: 150 candidates, 893 requests (5.95 per candidate), 32.3 min, rate limit 5000/h, stopped: None
- chunk 18: 150 candidates, 1139 requests (7.59 per candidate), 12.5 min, rate limit 5000/h, stopped: None
- chunk 19: 150 candidates, 849 requests (5.66 per candidate), 9.2 min, rate limit 5000/h, stopped: None
- chunk 20: 150 candidates, 1007 requests (6.71 per candidate), 10.2 min, rate limit 5000/h, stopped: None
- chunk 21: 150 candidates, 1131 requests (7.54 per candidate), 12.1 min, rate limit 5000/h, stopped: None
- chunk 22: 150 candidates, 889 requests (5.93 per candidate), 22.5 min, rate limit 5000/h, stopped: None
- chunk 23: 150 candidates, 890 requests (5.93 per candidate), 8.6 min, rate limit 5000/h, stopped: None
- chunk 24: 150 candidates, 897 requests (5.98 per candidate), 9.7 min, rate limit 5000/h, stopped: None
- chunk 25: 150 candidates, 1016 requests (6.77 per candidate), 10.2 min, rate limit 5000/h, stopped: None
- chunk 26: 150 candidates, 914 requests (6.09 per candidate), 32.1 min, rate limit 5000/h, stopped: None
- chunk 30: 150 candidates, 1094 requests (7.29 per candidate), 17.1 min, rate limit 5000/h, stopped: None
- chunk 31: 150 candidates, 1229 requests (8.19 per candidate), 25.5 min, rate limit 5000/h, stopped: None
- chunk 32: 150 candidates, 984 requests (6.56 per candidate), 10.7 min, rate limit 5000/h, stopped: None
- chunk 33: 150 candidates, 909 requests (6.06 per candidate), 9.4 min, rate limit 5000/h, stopped: None
- chunk 34: 150 candidates, 958 requests (6.39 per candidate), 33.1 min, rate limit 5000/h, stopped: None
- chunk 35: 150 candidates, 1060 requests (7.07 per candidate), 10.5 min, rate limit 5000/h, stopped: None
- chunk 36: 150 candidates, 1158 requests (7.72 per candidate), 11.5 min, rate limit 5000/h, stopped: None
- chunk 37: 150 candidates, 912 requests (6.08 per candidate), 32.1 min, rate limit 5000/h, stopped: None
- chunk 38: 150 candidates, 985 requests (6.57 per candidate), 10.2 min, rate limit 5000/h, stopped: None
- chunk 39: 150 candidates, 864 requests (5.76 per candidate), 8.9 min, rate limit 5000/h, stopped: None
- chunk 40: 150 candidates, 919 requests (6.13 per candidate), 12.7 min, rate limit 5000/h, stopped: None
- chunk 41: 150 candidates, 908 requests (6.05 per candidate), 24.2 min, rate limit 5000/h, stopped: None
- chunk 42: 150 candidates, 965 requests (6.43 per candidate), 10.7 min, rate limit 5000/h, stopped: None
- chunk 43: 150 candidates, 931 requests (6.21 per candidate), 10.1 min, rate limit 5000/h, stopped: None
- chunk 44: 150 candidates, 1268 requests (8.45 per candidate), 36.6 min, rate limit 5000/h, stopped: None
- chunk 45: 150 candidates, 1402 requests (9.35 per candidate), 13.0 min, rate limit 5000/h, stopped: None
- chunk 46: 150 candidates, 1872 requests (12.48 per candidate), 43.4 min, rate limit 5000/h, stopped: None
- chunk 47: 150 candidates, 1029 requests (6.86 per candidate), 11.7 min, rate limit 5000/h, stopped: None
- chunk 48: 150 candidates, 1011 requests (6.74 per candidate), 10.3 min, rate limit 5000/h, stopped: None
- chunk 49: 150 candidates, 973 requests (6.49 per candidate), 34.0 min, rate limit 5000/h, stopped: None
- chunk 50: 150 candidates, 1240 requests (8.27 per candidate), 13.9 min, rate limit 5000/h, stopped: None
- chunk 51: 150 candidates, 898 requests (5.99 per candidate), 8.2 min, rate limit 5000/h, stopped: None
- chunk 52: 150 candidates, 968 requests (6.45 per candidate), 31.6 min, rate limit 5000/h, stopped: None
- chunk 53: 150 candidates, 887 requests (5.91 per candidate), 8.9 min, rate limit 5000/h, stopped: None
- chunk 54: 150 candidates, 1054 requests (7.03 per candidate), 9.7 min, rate limit 5000/h, stopped: None
- chunk 55: 150 candidates, 1383 requests (9.22 per candidate), 36.3 min, rate limit 5000/h, stopped: None
- chunk 56: 150 candidates, 994 requests (6.63 per candidate), 9.8 min, rate limit 5000/h, stopped: None
- chunk 57: 150 candidates, 1011 requests (6.74 per candidate), 34.4 min, rate limit 5000/h, stopped: None
- chunk 58: 150 candidates, 2109 requests (14.06 per candidate), 32.6 min, rate limit 5000/h, stopped: None
- chunk 59: 150 candidates, 977 requests (6.51 per candidate), 27.1 min, rate limit 5000/h, stopped: None

## Limits

- Default branches only; GitHub Actions only; public repositories indexed by legacy code search only.
- Truncated leaves (listed above) hide files: the count is a lower bound; N_upper counts file hits, so the DROP estimate errs toward not dropping.
- Runners not covered: PHPUnit/Laravel, Maven/Gradle, others. Covered: Jest, Vitest, Mocha, node:test, pytest (incl. tox/nox), Django manage.py test, Rails minitest, RSpec, Go.
- Rule limits found by the hand checks (no rule was changed; each can move a row either way):
  - the runner regex also matches after a hyphen and in prose (echo, comments, SystemExit text), so a flag in a comment can decide a step (spatiumddi);
  - shlex tokenizing hides flags inside a quoted `sh -c "..."`, e.g. pytest `-n` there is not seen (sbomify, counted serial, hand check failed);
  - the database is detected per job, not per step: a serial step in a database job can run no database tests (aelys: SQLite step);
  - a step with several runner lines is serial if any of them is serial (tim-ai-platform);
  - Vitest multi-project configs: a per-project `fileParallelism` setting is read as global (plur);
  - Go: `-p 1` serializes packages but `t.Parallel` inside a package is not inspected; a single-package `go test` without `-p 1` is counted not serial although it runs in order (Tengrinews);
  - node:test: a single-file `node --test` is counted not serial although it runs one file in order (articweb3);
  - §4 over-excludes: a database created per test or per scenario (`CREATE DATABASE ... TEMPLATE`, fresh-database fixtures), worker-id skip guards and doc comments count as per-worker evidence (7 of 10 per_worker hand checks failed); these rows stay excluded, so the qualifying count is a lower bound.
- Process: commits from 2026-11-25 22:36Z on are authored under the founder's git identity at the coordinator's instruction (GitHub shows them Unverified); earlier commits were not rewritten. Commit trailers name the agent session.
