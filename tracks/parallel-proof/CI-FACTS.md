# CI pytest facts for 11 repositories (pinned commits)

Method: each repo was fetched at the exact pinned commit (`git fetch --depth 1 origin <full sha>`, full checkout) and read locally; counts come from `git grep` over the whole tree at that commit. Every fact below is **DECLARED** (read from the repo's config at the pinned sha) unless marked **UNKNOWN** or **EXTERNAL** (defined outside the repo / not pinned by it). Line numbers refer to the pinned commit.

| repo | full sha |
|---|---|
| apache/airflow | 56bbac12ad9853865c7fff24230994643d91c168 |
| ansible-collections/community.general | 63fe14d2aa6ac026825ffb805a5c8a08a97855ba |
| esphome/esphome | 141789d2400fb9f465d95263167c367a79aa8277 |
| deepset-ai/haystack | 050a979caca073da3b6d62662b766fb804575ebf |
| DataDog/integrations-core | 5bedd04ea3a726071903a753be0b265b70e4a539 |
| BerriAI/litellm | 17e6ea8cb7d4bf1c090e2aaa35d94116ef5ecd6c |
| mlflow/mlflow | c365f861ff68cd85d8be17103748d60c3d14c63e |
| getmoto/moto | 96f50b1aa902eccb0a3763b80f37d7af265d9130 |
| PrefectHQ/prefect | 5e8ca118fc514ffe9ab3355ea5cf1c28c347de11 |
| pydantic/pydantic-ai | 62e7b66c9f4da5c788eb360e49522a98e8fa0c86 |
| huggingface/transformers | a2a53c3be2828dfb0c4f89648a406e58d31d1230 |

## Summary table

Counts: "xdist_group" = occurrences of `xdist_group` in the tree; "worker_id uses" = uses of the pytest-xdist `worker_id` fixture / `PYTEST_XDIST_WORKER` env var (domain-level `worker_id` names excluded; raw counts in each section).

| repo | pytest cmd in CI (unit) | -n | --dist | xdist pinned version | sharding / matrix | jobs per CI run (unit) | runner | xdist_group markers | worker_id uses | evidence paths |
|---|---|---|---|---|---|---|---|---|---|---|
| apache/airflow | `breeze testing core-tests/providers-tests` -> `pytest ... --durations=100 --maxfail=50 --timeouts-order=moi --setup/execution/teardown-timeout ... -rfEX [-n N]` in docker | Non-DB: `-n <cpu_count>` (breeze `--parallelism` default); DB: no xdist (pool of serial pytest per test type, own DB container each) | none (default load) | `>=3.5.0` (devel-common); uv.lock 3.8.0 | by test type (core 2 slices, 1 on RunsOn; providers per provider) x Python 3.11-3.14 x DB backend versions, selective checks | UNKNOWN exact (data-dependent; 10 unit job templates in ci-amd.yml each a matrix) | RunsOn self-hosted AWS spot (cpu 8+16 or 32+64) or public `ubuntu-22.04` | 0 | 0 | `scripts/ci/testing/run_unit_tests.sh`, `dev/breeze/src/airflow_breeze/utils/run_tests.py:577-645`, `.github/workflows/run-unit-tests.yml:159-243`, `dev/breeze/src/airflow_breeze/global_constants.py:40-67,571,1084-1091` |
| community.general | `ansible-test units` via nox (`nox -e ansible-test-units-<core>-<py>`); pytest line built by ansible-test (EXTERNAL: `pytest -r a -n auto ... -p no:cacheprovider` + forked plugin) | EXTERNAL `-n auto` (ansible-test) | EXTERNAL none | not in repo (EXTERNAL ansible-test requirement, unpinned) | ansible-core version x Python version | 15 unit jobs on Azure (3+3+3+6); GHA nox matrix count UNKNOWN (external reusable workflow) | Azure Pipelines `pool: Standard` + container; GHA (external) | 0 | 0 | `.azure-pipelines/azure-pipelines.yml:55-149`, `tests/utils/shippable/nox.sh`, `antsibull-nox.toml [sessions.ansible_test_units]`, `.github/workflows/nox.yml:28` |
| esphome/esphome | `pytest -vv --cov-report=xml --tb=native --durations=30 -n auto tests --ignore=tests/integration/` | auto | none (load) ; integration: worksteal | 3.8.0 (`requirements_test.txt:13`) | Python 3.12-3.15 x ubuntu/macOS/windows minus 2; integration: up to 5 duration-balanced buckets (custom, `integration_test_durations.json`) | 10 unit + up to 5 integration | `ubuntu-latest`, `macOS-latest`, `windows-latest`; integration `ubuntu-24.04` | 0 | 1 `PYTEST_XDIST_WORKER` (+1 `_COUNT`) | `.github/workflows/ci.yml:314-361,398-560`, `requirements_test.txt`, `script/determine-jobs.py:111`, `tests/integration/conftest.py:107,128-131` |
| deepset-ai/haystack | `hatch run test:unit` = `pytest --cov="haystack" -m "not integration" test` | none (serial) | n/a | not a dependency | OS ubuntu/windows/macos, single Python 3.11 | 3 unit (+3 integration) | `ubuntu-latest`, `windows-latest`, `macos-latest` | 0 | 0 | `.github/workflows/tests.yml:117-150`, `pyproject.toml:135-155,184` |
| DataDog/integrations-core | `ddev -v test --cov --junit <target> --pytest-args '-k "not fips"'` -> `hatch env run -- pytest -vv --benchmark-skip --cov ... {args:tests}` | none (serial) | n/a | not a dependency | one job per integration (changed ones on PR); hatch env matrix run sequentially inside a job | PR: changed integrations only; full: 221 Linux + 20 Windows test-target jobs | `ubuntu-22.04` (221/221 in test-all.yml) | 0 | 0 (51 raw hits are metric tags) | `.github/workflows/test-target.yml:318-321`, `.github/actions/setup-test-target-scripts/src/run-unit-integration-tests.sh:25-42`, `ddev/src/ddev/plugin/external/hatch/environment_collector.py:162-167`, `.github/workflows/test-all.yml` |
| BerriAI/litellm | `uv run --no-sync pytest <paths> --tb=short -vv --maxfail=10 -n W --dist=D --reruns R --reruns-delay 1 --timeout=120 --rerun-except "from pytest-timeout" --durations=20 --cov=...` | 4 (34 shards), 8 (4), 2 (4), none (2) | loadscope (41), load (2), worksteal (1) | 3.8.0 (`pyproject.toml:232`, uv.lock) | 44 hand-written path shards, Python 3.12 (one 3.10), coverage of dirs asserted | 44 unit shards (+ other jobs) | `ubuntu-latest` (40), `ubuntu-latest-16-cores` (4) | 20 (16 files; 8 in tests/unit, not honored under loadscope/load/worksteal) | 60 `PYTEST_XDIST_WORKER` in 48 files (41 = skip `importlib.reload` under xdist) | `.github/workflows/test-unit.yml:125-1145`, `pyproject.toml:225-256,462`, `uv.lock:9213` |
| mlflow/mlflow | `uv run --no-sync pytest --serial=exclude -n auto --dist loadscope --splits=6 --group=G --quiet --requires-ssh --ignore-flavors ... tests` + `pytest --serial=only --splits=4 ...` | auto (parallel shards); none (serial shards) | loadscope | unpinned (`requirements/test-requirements.txt:8`) | custom round-robin `--splits/--group` (conftest), 6 parallel + 4 serial | 10 in `python` job; 28 jobs in master.yml | `ubuntu-24.04` | 0 | 1 `PYTEST_XDIST_WORKER` | `.github/workflows/master.yml:73-148`, `tests/conftest.py:67-130,152-248,688-699,1208`, `pyproject.toml:567-577` |
| getmoto/moto | `make test-only`: serial `pytest -sv -rs --cov ... ./tests/ <excludes>` + serial `-m requires_clean_slate` + `pytest ... -n 4 <PARALLEL_TESTS> --dist loadscope -m "not requires_clean_slate"` | 4 (subset dirs only) | loadscope | unpinned (`requirements-tests.txt:7`) | Python 3.10-3.15 x {decorator mode, server mode} | 12 | `ubuntu-latest` | 0 | 0 | `Makefile:6-40`, `.github/workflows/tests_decoratormode.yml`, `tests_servermode.yml`, `build.yml:160-170`, `pyproject.toml:5-11` |
| PrefectHQ/prefect | `uv run pytest <sel> -m "not windows" --numprocesses auto (SQLite) / logical (Postgres) --maxprocesses 6 --dist worksteal --disable-docker-image-builds --exclude-service kubernetes --exclude-service docker --durations 26 --splits N --group G --splitting-algorithm least_duration --durations-path ... --store-durations --clean-durations` | auto/logical, `--maxprocesses 6` | worksteal | `>=3.6.1`; uv.lock 3.8.0 (pytest-split 0.11.0) | pytest-split by duration: SQLite 8 groups, Postgres 18 groups, x Python 3.11-3.15 | ~141 (40 SQLite + 90 Postgres + 5 docker + 6 misc) | `ubuntu-latest` | 0 | 4 `worker_id` fixture uses (per-worker SQLite file / Postgres DB / docker labels) | `.github/workflows/python-tests.yaml:52-330,769`, `pyproject.toml:155-163,271-299`, `uv.lock:5631,5655`, `tests/conftest.py:424-453` |
| pydantic/pydantic-ai | `uv run [--package X] [coverage run -m] pytest --durations=100 -n logical --dist=loadgroup --ignore=tests/durable_exec -m "not temporal"`; all-extras adds module-level shard `--ignore`s + `--store-durations` | logical | loadgroup | `>=3.6.1`; uv.lock 3.8.0 (pytest-split 0.11.0 for durations only) | Python 3.11-3.15 x 5 install shapes; all-extras 2-3 module shards by duration (custom `shard_durations.py`); durable-exec, lowest-versions jobs | `test`: 25 (main/merge queue) / 12 (PR); all-extras 11/9; total UNKNOWN (classify-dependent) | `vars.CI_LINUX_RUNNER` or else `ubuntu-latest` (var value UNKNOWN); all-extras default `ubuntu-24.04` | 79 (71 files) | 2 `PYTEST_XDIST_WORKER` reads (+4 monkeypatch) | `.github/workflows/ci.yml:716-882,1005-1200,1267-1392,1437-1555`, `pyproject.toml:281-288,596-`, `uv.lock:8743,8755`, `.github/scripts/shard_durations.py` |
| huggingface/transformers | Public CI EXTERNAL (`huggingface/transformers-ci@main`); in-repo CircleCI generator (private mirrors only): `python3 -m pytest -m '<marker>' -n 4 ... --reruns 5 --reruns-delay 2 --only-rerun '(...)' --max-worker-restart=0 -vvv -rsfE --random-order-bucket=module --random-order-seed=$CIRCLE_BUILD_NUM` | in-repo: 4 (`8 // 2`); EXTERNAL GHA: 8 | none (load); doc tests loadfile | unpinned (`setup.py:115`) | in-repo: CircleCI parallelism 2-8 per job, `circleci tests split --split-by=timings`; EXTERNAL: up to 8 shards per job, deterministic chunk split, 14 jobs | UNKNOWN for pin (external, floating `@main`) | in-repo: CircleCI `resource_class: large`; EXTERNAL: self-hosted `group: aws-m8i-l-cache` | 0 | 3 `PYTEST_XDIST_WORKER` | `.circleci/config.yml:21-34,150-160`, `.circleci/create_circleci_config.py:35-41,101-130,172-247,300-440`, `.github/workflows/pr-ci-caller.yml:22-24`, `setup.py:109-116`, `conftest.py:70`, `src/transformers/testing_utils.py:2857,5289` |

Other plugin usage at a glance: pytest-randomly: none of the 11 repos use it in CI (transformers uses pytest-random-order). pytest-rerunfailures: airflow (marker-level), haystack (marker-level), litellm (`--reruns 0|2` per shard), transformers (`--reruns 5 --only-rerun`), prefect integrations only, mlflow uses its own conftest `flaky(attempts=3)` implementation. pytest-split: prefect (splitting), pydantic-ai (durations recording only). pytest-shard: transformers vLLM downstream workflow only. pytest-test-groups: none.

---

## apache/airflow @ 56bbac12ad9853865c7fff24230994643d91c168

**1. Pytest commands (DECLARED).** `.github/workflows/ci-amd.yml` (and ci-arm.yml) call the reusable `.github/workflows/run-unit-tests.yml`, whose step (`:243`) runs `./scripts/ci/testing/run_unit_tests.sh "${TEST_GROUP}" "${TEST_SCOPE}"`. That script runs breeze inside the CI docker image:
```
breeze testing core-tests --run-in-parallel --run-db-tests-only                        # TEST_SCOPE=DB
breeze testing core-tests --use-xdist --skip-db-tests --no-db-cleanup --backend none   # TEST_SCOPE=Non-DB
breeze testing core-tests --run-in-parallel                                            # TEST_SCOPE=All (lowest-direct-resolution jobs)
```
(same for `providers-tests`). breeze builds the pytest args in `dev/breeze/src/airflow_breeze/utils/run_tests.py` `generate_args_for_pytest` (`:577-603, 644-645`):
```
pytest <test-type folders> --verbosity=0 --strict-markers --durations=100 --maxfail=50 --color=yes --junitxml=<file> \
  --timeouts-order=moi --setup-timeout=<max(test_timeout, MIN)> --execution-timeout=<test_timeout> --teardown-timeout=<...> \
  --disable-warnings -rfEX [--skip-db-tests|--run-db-tests-only] [-n <parallelism or auto>  # only with --use-xdist] \
  [--cov=airflow ... | --no-cov]
```
`--test-timeout` default 60 s (`dev/breeze/src/airflow_breeze/commands/testing_commands.py:610-616`). `--parallelism` default `mp.cpu_count()` (`dev/breeze/src/airflow_breeze/commands/common_options.py:342-348`), so Non-DB runs `-n <cpu_count>`. No `--dist` flag (xdist default `load`). `--run-in-parallel` (DB scope) does NOT use xdist: breeze's `_run_tests_in_pool` (`testing_commands.py:386-440`) runs one serial pytest per test type, each in its own docker-compose project with its own DB container, `parallelism` at a time. `pyproject.toml:1001-1016` `[tool.pytest] addopts`: `--tb=short -rasl --verbosity=2 -p no:flaky -p no:nose -p no:legacypath --disable-warnings --asyncio-mode=strict --ignore-glob=**/tests/system/*`. No global `--reruns` (rerunfailures used via `@pytest.mark.flaky(reruns=...)`).

**2. Deps (DECLARED).** `devel-common/pyproject.toml:140-152`: `pytest>=9.0.0`, `pytest-xdist>=3.5.0`, `pytest-rerunfailures>=13.0,!=16.0`, `pytest-timeouts>=1.2.1`, pytest-asyncio, pytest-cov, pytest-custom-exit-code, pytest-instafail, pytest-mock, pytest-unordered, pytest-icdiff. `uv.lock:22442-22443` pytest-xdist 3.8.0, `:22408` pytest-rerunfailures 16.7, `:22421` pytest-timeouts 1.2.1 (the CI image installs with Airflow constraints; exact image version UNKNOWN). No randomly, split, shard.

**3. Sharding (DECLARED).** Split by test type, not by duration: core types `Always, API, CLI, Core, Serialization, Other` (`global_constants.py:391-397`) are grouped into `NUMBER_OF_CORE_SLICES = 2` jobs (1 on RunsOn runners) (`global_constants.py:1084-1091`, `selective_checks.py:2084-2092`); providers split into per-provider test types. `run-unit-tests.yml:165-168` matrix = python-versions x backend-versions x test-type slices; Python `["3.11","3.12","3.13","3.14"]` (`global_constants.py:571`), Postgres `["14".."18"]` (`:575`), selective checks narrow these per PR (exact job count per run UNKNOWN, data-dependent). ci-amd unit jobs: tests-{postgres,mysql,sqlite}-{core,providers} (DB), tests-non-db-{core,providers}, tests-with-lowest-direct-resolution-{core,providers}. Runners: public `["ubuntu-22.04"]` (`global_constants.py:40`) or self-hosted RunsOn AWS spot runners `runs-on={run_id}/env=flex/family=m8a+m8i+m7a+m7i+m6i/.../cpu={0}/ram={1}` (`:50-63`), with sizes `cpu 8+16 / ram 32+128` for DB core jobs and `cpu 32+64 / ram 128+256` for providers and Non-DB jobs (`ci-amd.yml:905-1121`). `max-parallel` 256 on RunsOn else 20 (`run-unit-tests.yml:164`).

**4. xdist_group / worker_id (DECLARED).** `xdist_group`: 0; `worker_id`: 0; `PYTEST_XDIST_WORKER`: 0; `testrun_uid`: 0 (git grep full tree). xdist detection only via `config.option.dist` / `workerinput` (`devel-common/src/tests_common/pytest_plugin.py:2114-2116`, skips DB `clear_all()` under xdist).

**5. Serial-engine notes (DECLARED).** DB tests (`@pytest.mark.db_test` / `pytestmark`, 1062 occurrences in 503 files) are never run under xdist in CI: they run serially per test type with a dedicated DB container; Non-DB tests use xdist with `--backend none`. pytest-timeouts per-phase timeouts (60 s default). `-p no:xdist`: 0; `-p no:flaky` in addopts.

---

## ansible-collections/community.general @ 63fe14d2aa6ac026825ffb805a5c8a08a97855ba

**1. Pytest commands.** The repo never calls pytest directly (git grep for `pytest` outside .py files: only docs/README hits). Units run through `ansible-test units` driven by antsibull-nox:
- Azure Pipelines (`.azure-pipelines/azure-pipelines.yml:81-149`): stages `units_2_20`, `units_2_21`, `units_2_22`, `units_devel` with targets like `ansible-test-units-2.20-3.9`; entry point `tests/utils/shippable/nox.sh` runs `nox --reuse-existing-virtualenvs --no-install -e "${nox_session}" -- ${COVERAGE}` (last line). DECLARED.
- GitHub Actions `.github/workflows/nox.yml:28` uses the external reusable workflow `ansible-community/antsibull-nox/.github/workflows/reusable-nox-matrix.yml@main` with `exclude-tags: remote, no-gha, heavy`. DECLARED (contents of the external workflow not in this repo).
- Session config `antsibull-nox.toml` `[sessions.ansible_test_units]` `include_devel = true`, `split_by_python_version = true`, core_python_versions 2.19: 3.8/3.11/3.13; 2.20: 3.9/3.12/3.14; 2.21: 3.9/3.12/3.14; 2.22: 3.10/3.13/3.15. DECLARED.
- The actual pytest command line is built by ansible-test in ansible-core (EXTERNAL, not in this repo, not pinned by this repo). For reference, ansible/ansible devel `test/lib/ansible_test/_internal/commands/units/__init__.py:249-274`: `pytest -r a -n <num_workers or 'auto'> --color yes -p no:cacheprovider -c <ansible-test default.ini> --junit-xml ... --strict-markers --rootdir ... --confcutdir ...` plus plugins `ansible_pytest_collections`, `ansible_forked` (each test forked). No `--dist` flag (xdist default `load`). Fetched from ansible devel, not pinned: treat as EXTERNAL/UNKNOWN for the exact version used.

**2. Deps.** No xdist in this repo's requirement files (`tests/unit/requirements.txt`, `tests/utils/constraints.txt` only pin pytest-mock>=1.4.0). pytest-xdist comes from ansible-test's own `units.txt` requirement (external; unpinned in ansible devel `test/lib/ansible_test/_data/requirements/units.txt`). No randomly/rerunfailures/split. UNKNOWN pinned version.

**3. Sharding (DECLARED).** One job per (ansible-core version x Python version): Azure units stages have 3+3+3+6 = 15 unit jobs (`azure-pipelines.yml:81-149`); runner: Azure DevOps `pool: Standard` (`azure-pipelines.yml:58`) in container `quay.io/ansible/azure-pipelines-test-container:8.0.0` (`:55`). GHA reusable nox matrix also runs sessions (job count generated externally: UNKNOWN). Change detection on PRs (`ANTSIBULL_CHANGE_DETECTION`). No duration-based split.

**4. xdist_group / worker_id (DECLARED).** 0 / 0 (git grep full tree). 4 conftest.py files under tests/unit.

**5. Serial-engine notes.** ansible-test runs each test in a forked subprocess (`ansible_forked` plugin, external). Nothing in repo marks tests serial; `-p no:xdist`: 0.

---

## esphome/esphome @ 141789d2400fb9f465d95263167c367a79aa8277

**1. Pytest commands (DECLARED).** `.github/workflows/ci.yml` job `pytest` (`:314-361`):
```
pytest -vv --cov-report=xml --tb=native --durations=30 -n auto tests --ignore=tests/integration/     # ci.yml:356 (windows) and :361 (ubuntu/macOS)
```
`pyproject.toml:55-66` `[tool.pytest.ini_options]` `testpaths=["tests"]`, `addopts = ["--cov=esphome", "--cov-branch"]`. No `--dist` (default load), no randomly/reruns.
Integration tests (separate job `integration-tests`, `ci.yml:398-560`):
```
pytest -vv --no-cov --tb=native --durations=30 -n auto --dist worksteal --timeout=1800 --junitxml=junit-integration.xml "${test_files[@]}"   # ci.yml:535
pytest -vv --no-cov --tb=native -n auto --dist worksteal --timeout=600 --lf --lfnf=none tests/integration || true   # ci.yml:560 re-run of failures with debug symbols
```
Local script `script/integration_test:10`: `pytest -vvs --no-cov --tb=native -n 0 --timeout=1800 tests/integration/`. Downstream smoke check `ci.yml:1680`: `pytest -q -n auto --maxfail=5 --durations=30 --no-cov ...` (in a checked-out device-builder repo, not esphome tests).

**2. Deps (DECLARED).** `requirements_test.txt:13` `pytest-xdist==3.8.0`; also `pytest==9.2.0`, `pytest-timeout==2.4.0`, `pytest-asyncio==1.5.0`, `pytest-cov==7.1.0`, `pytest-mock==3.17.0`, `pytest-codspeed==5.0.4`. No randomly/rerunfailures/split/shard.

**3. Sharding (DECLARED).** Unit job matrix (`ci.yml:316-334`): python 3.12/3.13/3.14/3.15 x os ubuntu-latest/macOS-latest/windows-latest, excluding 3.13 on windows and macOS = 10 jobs per run (gated by `determine-jobs` `core-ci`). Integration tests: custom duration-balanced buckets computed by `script/determine-jobs.py:111` `INTEGRATION_TESTS_SPLIT_BUCKETS = 5` (`INTEGRATION_TESTS_SPLIT_THRESHOLD = 10`, target weight 360 s) from recorded per-file durations in `tests/integration/integration_test_durations.json` (updated by `.github/workflows/sync-integration-durations.yml` via `script/update_integration_test_durations.py`); up to 5 integration jobs on `ubuntu-24.04` (`ci.yml:400`). No pytest-split plugin.

**4. xdist_group / worker_id (DECLARED).** `xdist_group`: 0; `worker_id` fixture: 0; `PYTEST_XDIST_WORKER`: 1 use (`tests/integration/conftest.py:131`, per-worker library cache dir), plus `PYTEST_XDIST_WORKER_COUNT` at `:107` (caps compile -j per worker). `testrun_uid`: 0.

**5. Serial-engine notes (DECLARED).** Only session-scoped fixture in tests/: `tests/integration/conftest.py:128` `shared_library_cache` (per-xdist-worker dir). Integration conftest reserves TCP ports with `socket.bind(("", 0))` (`:188-218`, `reserved_tcp_port`, `unused_tcp_port`) and uses `fcntl.flock` to serialize shared builds across workers (`:547`). `-p no:xdist`: 0.

---

## deepset-ai/haystack @ 050a979caca073da3b6d62662b766fb804575ebf

**1. Pytest commands (DECLARED).** `.github/workflows/tests.yml:149-150` job `unit-tests` runs `hatch run test:unit`; `pyproject.toml:150` `[tool.hatch.envs.test.scripts]`:
```
unit = 'pytest --cov="haystack" -m "not integration" {args:test}'
```
Integration jobs (`tests.yml:241,275,303`) run `hatch run test:integration-only-fast` = `pytest --maxfail=5 -m "integration and not slow" {args:test}` (`pyproject.toml:152`); `slow.yml:102` runs `integration-only-slow`. `[tool.pytest.ini_options]` (`pyproject.toml:184-196`): `addopts = "--strict-markers"`, `log_cli = true`, `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "class"`. No `-n`, no `--dist`: the suite runs serially in a single process.

**2. Deps (DECLARED).** `pyproject.toml:137-141` (hatch `test` env deps): `pytest<9.2`, pytest-bdd, pytest-cov, pytest-asyncio, `pytest-rerunfailures` (unpinned). pytest-xdist: not a dependency (0 hits for `xdist` in the whole repo). No randomly/split/shard. Rerunfailures is used per-test via `@pytest.mark.flaky(reruns=3, reruns_delay=5|10)` (4 uses under test/), not a global `--reruns` flag.

**3. Sharding (DECLARED).** Unit matrix `os: ubuntu-latest, windows-latest, macos-latest` (`tests.yml:126-131`), single Python `PYTHON_VERSION: "3.11"` (`tests.yml:32`) = 3 unit jobs per run; 3 integration jobs (ubuntu/macos/windows). `timeout-minutes: 30` for unit job. No duration split.

**4. xdist_group / worker_id (DECLARED).** 0 / 0.

**5. Serial-engine notes (DECLARED).** Already serial (no xdist). No `scope="session"` fixtures under test/ (git grep 0). Asyncio fixture loop scope = class.

---

## DataDog/integrations-core @ 5bedd04ea3a726071903a753be0b265b70e4a539

**1. Pytest commands (DECLARED).** Each integration is tested in its own job of the reusable workflow `.github/workflows/test-target.yml` (`:318-321` "Run Unit & Integration tests" runs `run-unit-integration-tests.sh`). `.github/actions/setup-test-target-scripts/src/run-unit-integration-tests.sh:25,37,42`:
```
ddev -v test --cov --junit "$INPUT_TARGET" --pytest-args "$PYTEST_ARGS"     # PYTEST_ARGS += ' -k "not fips"' by default
```
`ddev test` (`ddev/src/ddev/cli/test/__init__.py:233,279-315`) runs `python -m hatch env run --env <env>... -- test-cov --junit-xml junit/test-unit-$HATCH_ENV_ACTIVE.xml --junit-prefix <target> <pytest args>`. The `test-cov` script is injected by ddev's hatch plugin, `ddev/src/ddev/plugin/external/hatch/environment_collector.py:162-167`:
```
pytest -vv --benchmark-skip --cov <pkg> --cov tests --cov-config=../.coveragerc --cov-report= --cov-append {args:tests}
```
No `-n`, no `--dist`: each integration's suite runs serially per hatch environment (envs run one after another). No randomly/reruns/timeout flags (step-level `timeout-minutes: 60` default, `test-target.yml:98-101`). Flaky tests run separately with `pytest-args: -m flaky` (`run-unit-integration-tests.sh:46`).

**2. Deps (DECLARED).** `datadog_checks_dev/pyproject.toml:35-40`: `pytest==9.0.3`, pytest-asyncio>=1.3.0, pytest-benchmark[histogram]>=5.2.3, pytest-cov>=7.1.0, pytest-memray>=1.8.0, pytest-mock>=3.15.1; pytest11 plugin `datadog_checks.dev.plugin.pytest`. pytest-xdist: not used anywhere (0 hits for `xdist` in the repo). No randomly/rerunfailures/split/shard.

**3. Sharding (DECLARED).** Sharding is per integration (per target), not per test: PRs use `compute-matrix.yml` (changed integrations only, `pr-test.yml:30-54`); full runs use `.github/workflows/test-all.yml` with 221 `test-target.yml` jobs, all `runner: '["ubuntu-22.04"]'` (221/221), plus `test-all-windows.yml` (20 jobs). Within a job, hatch env matrix entries (Python version x service version) run sequentially. No duration split.

**4. xdist_group / worker_id (DECLARED).** `xdist_group`: 0. pytest `worker_id`/`PYTEST_XDIST_WORKER`/`testrun_uid`: 0 (the 51 raw `worker_id` hits are metric tag names in check code, log pipelines and fixtures data, e.g. `celery/assets/logs/celery.yaml:19`, `prefect/tests/test_unit.py:20`, not the xdist fixture).

**5. Serial-engine notes (DECLARED).** Heavy session-scope environments: 228 `conftest.py` files define `dd_environment` (usually docker-compose via `datadog_checks.dev.docker_run`), and the plugin's autouse session fixture `dd_environment_runner` (`datadog_checks_dev/datadog_checks/dev/plugin/pytest.py:74`) spins it up; 375 `scope='session'|"session"` fixtures in conftest files. Services bind fixed host ports from compose files, which assumes one session per job. `-p no:xdist`: 0.

---

## BerriAI/litellm @ 17e6ea8cb7d4bf1c090e2aaa35d94116ef5ecd6c

**1. Pytest commands (DECLARED).** `.github/workflows/test-unit.yml` job `unit` (`:125-1160`), step "Run tests" (`:1090-1145`), env `MAX_FAILURES: "10"`, `TEST_TIMEOUT_SECONDS: "120"`, `COVERAGE_CORE: sysmon`:
```
xdist_args=(-n "${WORKERS}" --dist="${DIST}")        # only if WORKERS != 0  (:1129-1131)
uv run --no-sync pytest "${pytest_args[@]}" --tb=short -vv --maxfail="${MAX_FAILURES}" "${xdist_args[@]}" \
  --reruns "${RERUNS}" --reruns-delay 1 --timeout="${TEST_TIMEOUT_SECONDS}" --rerun-except "from pytest-timeout" \
  --durations=20 --cov=./litellm --cov=./litellm/enterprise/litellm_enterprise --cov-report=xml:coverage.xml --cov-config=pyproject.toml   # :1133-1144
```
Per-shard values from the matrix (44 shards): `workers` 4 (34 shards), 8 (4 shards, on `ubuntu-latest-16-cores`), 2 (4 shards), 0 = no xdist (2 shards: `key-generation`, `lens-python-310`); `dist` loadscope (41), load (2: `enterprise-repositories-secrets`, `enterprise-managed-files`), worksteal (1: `proxy-utils`); `reruns` 0 (29) or 2 (15); per-step `timeout-minutes` 15/20/60. Other jobs: `openai-sdk-compat` (`:1431`) `pytest <files> --tb=short -q` (serial); `redis-compat` (`:1542-1548`) `pytest ... --tb=short -vv -rs -p no:rerunfailures -p no:pytest-retry --timeout=120 --durations=20` (serial). `[tool.pytest.ini_options]` (`pyproject.toml:462`): no addopts; `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "session"`, marker `no_parallel`.
Integration tests (`test-integration.yml`, via `.github/scripts/ci/run_integration.sh` -> `tests/integration/run.py:164`) use `--dist=loadgroup` when workers > 1.

**2. Deps (DECLARED).** `pyproject.toml` `[dependency-groups] dev` (default group, `:437 default-groups = ["dev"]`): `pytest==9.0.3` (:225), `pytest-xdist==3.8.0` (:232), `pytest-rerunfailures==15.1` (:250), `pytest-timeout==2.4.0` (:254), `pytest-asyncio==1.3.0`, `pytest-socket==0.8.1`, `pytest-recording==0.13.4`, `pytest-cov==5.0.0`; group `ci`: `pytest-retry==1.7.0`, `pytest-codspeed==4.3.0`. `uv.lock:9213-9214` pytest-xdist 3.8.0. No pytest-randomly, pytest-split, pytest-shard.

**3. Sharding (DECLARED).** Hand-written path-based shards: 44 matrix entries in `test-unit.yml` job `unit`, coverage of every test dir enforced by `.github/scripts/assert_ci_coverage.py --shards` (`:124`). Python 3.12 for 43 shards, 3.10 for `lens-python-310`. Runner `${{ matrix.runner || 'ubuntu-latest' }}` (`:129`): 40 on `ubuntu-latest`, 4 on `ubuntu-latest-16-cores` (larger runner). Integration workflow runs on `ubuntu-latest-16/32/64-cores` (`test-integration.yml:46`). No duration-based split.

**4. xdist_group / worker_id (DECLARED).** `@pytest.mark.xdist_group`: 20 occurrences in 16 files (8 in tests/unit, e.g. `tests/unit/proxy/test_proxy_cli.py:155` `xdist_group("proxy_cli")`, `tests/unit/proxy/test_proxy_utils.py:32`; rest in tests/integration, plus auto-assignment in `tests/integration/conftest.py:195-201` when `--dist loadgroup`). Note: unit shards use loadscope/load/worksteal, under which xdist_group markers are not honored. `PYTEST_XDIST_WORKER`: 60 occurrences in 48 test files (41 are the same idiom `worker_id = os.environ.get("PYTEST_XDIST_WORKER", None)` used to skip `importlib.reload(litellm)` under xdist, e.g. `tests/unit/caching/test_llm_caching_handler.py:441`). `worker_id` word: 171 raw hits / 78 files, mostly domain code (proxy worker heartbeat etc.); pytest `worker_id` fixture parameter: not found; `tests/e2e/claude_code/conftest.py:499` per-worker shard file. `testrun_uid`: 0.

**5. Serial-engine notes (DECLARED).** Marker `no_parallel` ("run sequentially", `pyproject.toml`) used 2 times. Session fixtures in tests/unit conftests: `tests/unit/conftest.py:361,366`, `tests/unit/enterprise/conftest.py:17`, `tests/unit/proxy/mcp_server/conftest.py:15`, `tests/unit/proxy/proxy_server/conftest.py:75,90`. Test-isolation via `importlib.reload(litellm)` when not under xdist. `-p no:xdist`: 0; `-p no:rerunfailures` in redis-compat job.

---

## mlflow/mlflow @ c365f861ff68cd85d8be17103748d60c3d14c63e

**1. Pytest commands (DECLARED).** `.github/workflows/master.yml` job `python` (`:73-148`):
```
COMMON_ARGS=(--splits="$SPLITS" --group="$GROUP" --quiet --requires-ssh --ignore-flavors --ignore=tests/examples --ignore=tests/evaluate --ignore=tests/genai --ignore=tests/docker tests)
uv run --no-sync pytest --serial=exclude -n auto --dist loadscope "${COMMON_ARGS[@]}"     # :146  parallel shards
uv run --no-sync pytest --serial=only "${COMMON_ARGS[@]}"                                 # :148  serial shards (no xdist)
```
`pyproject.toml:567-577` `[tool.pytest] addopts = ["-p", "no:legacypath", "--strict-markers", "--color=yes", "--durations=10", "--showlocals", "--no-header", "-v"]`. Other master.yml jobs (all serial, no `-n`): `models` `:292` `pytest --splits=$SPLITS --group=$GROUP tests/models`; `evaluate` `:327`; `genai` `:382,397` `pytest tests/genai ...`; `pyfunc` `:436` `pytest --splits=$SPLITS --group=$GROUP --durations=30 ...`; `database` `:189` runs `pytest -q tests/store/... tests/db` inside a docker-compose service per DB; `python-skinny` via `./dev/run-python-skinny-tests.sh`. No `--reruns`/randomly/timeout flags on the command line.

**2. Deps (DECLARED).** `requirements/test-requirements.txt:3-8`: `pytest==9.1.1`, pytest-asyncio, pytest-repeat, pytest-cov, pytest-timeout, `pytest-xdist` (unpinned; `requirements/constraints.txt:1` pins only `pytest==9.1.1`). (`uv.lock:7051-7052` has pytest-xdist 3.8.0 and pytest-rerunfailures 12.0, but as transitive deps of `deepeval`, not the CI install path.) No pytest-randomly/split/shard. `--splits/--group` is a custom option in `tests/conftest.py:152-170,233-248,697-699` that does round-robin `items[(group - 1) :: splits]` (not by duration, not pytest-split). Reruns: custom `pytest_runtest_protocol` in `tests/conftest.py:~492-530` honoring `@pytest.mark.flaky(attempts=3)` (54 uses in tests/).

**3. Sharding (DECLARED).** `python` job matrix (`master.yml:84-94`): 6 parallel shards (`mode: parallel, splits: 6`) + 4 serial shards (`mode: serial, splits: 4`) = 10 jobs on `ubuntu-24.04`, `timeout-minutes: 120`. Whole `master.yml` = 28 jobs (python-skinny 1, python 10, database 4 [postgresql/mysql/mssql/sqlite], java 1, flavors 1, models 3, evaluate 2, genai 2, pyfunc 4), all `ubuntu-24.04`. Single Python version per job (`.github/actions/setup-python`).

**4. xdist_group / worker_id (DECLARED).** `xdist_group`: 0. pytest `worker_id` fixture: 0 (18 raw `worker_id` hits in 5 files are multiprocessing/test-data variables, e.g. `tests/store/tracking/test_secret_cache.py:416`). `PYTEST_XDIST_WORKER`: 1 (`tests/conftest.py:1208`, build the dev wheel once across workers under a `FileLock`). `testrun_uid`: 0.

**5. Serial-engine notes (DECLARED).** `_XDIST_SERIAL_PATHS` (`tests/conftest.py:104-125`, 20 path prefixes such as `tests/server/test_handlers.py`, `tests/projects/`, `tests/server/jobs/`, `tests/db/`) are "NOT safe to run under pytest-xdist and must run serially (`-n0`)" (`:67`); selected via custom `--serial=exclude|only|include` (`:170`, `:688-695`). 7 `scope="session"` fixtures in tests conftests. `-p no:xdist`: 0.

---

## getmoto/moto @ 96f50b1aa902eccb0a3763b80f37d7af265d9130

**1. Pytest commands (DECLARED).** Unit-test workflows (`.github/workflows/tests_decoratormode.yml:46`, `tests_servermode.yml:105`, both called from `build.yml:162,168`) run `make test-only`. `Makefile:31-40`:
```
pytest -sv -rs --cov=moto --cov-report xml ./tests/ $(TEST_EXCLUDE)          # serial, everything except PARALLEL_TESTS
pytest -sv -rs ./tests/test_xray                                               # serial, no coverage
pytest -sv --cov=moto --cov-report xml --cov-append ./tests/ -m requires_clean_slate   # serial
MOTO_CALL_RESET_API=false pytest -sv --cov=moto --cov-report xml --cov-append -n 4 $(PARALLEL_TESTS) --dist loadscope -m "not requires_clean_slate"
```
- Decorator mode (`Makefile:12-13`): `PARALLEL_TESTS := ./tests/test_batch ./tests/test_dynamodb ./tests/test_ec2 tests/test_s3/ ./tests/test_sqs`; all other test dirs run serially.
- Server mode (`Makefile:8-10`, `TEST_SERVER_MODE=true`): parallel set adds test_acm, test_acmpca, test_amp, test_awslambda; tests run against a MotoServer docker container started in `tests_servermode.yml:77` on port 5000.
- So: `-n 4`, `--dist loadscope`, only for a subset of directories; no randomly / reruns / timeout flags. `pyproject.toml:5-6` `addopts = "--color=yes"`.
- Other workflows: `tests_without_docker.yml:44` `pytest tests` (serial; nightly cron + dispatch only); `tests_real_aws.yml:63` `pytest -sv -n auto --dist loadfile ... -m aws_verified --durations 100` (manual, real AWS); `tests_proxymode.yml:53`, `test_sqs.yml:55`, `dockertests.yml` use plain `pytest -sv` on specific dirs.

**2. Deps (DECLARED).** `requirements-tests.txt:7` `pytest-xdist` (unpinned), pulled in by `requirements-dev.txt` (`-r requirements-tests.txt`). Also pytest-order, pytest-cov; `pytest!=9.0.0`. No pytest-randomly, rerunfailures, split, shard (grep: 0 hits).

**3. Sharding (DECLARED).** No test-file sharding. Matrix: python-version 3.10, 3.11, 3.12, 3.13, 3.14, 3.15 (6) for each of `tests_decoratormode.yml:10` and `tests_servermode.yml:10`, so 12 unit-test jobs per CI run (plus proxymode/CDK/SDK workflows). Runner `ubuntu-latest` (`tests_decoratormode.yml:6`).

**4. xdist_group / worker_id (DECLARED).** `xdist_group`: 0. `worker_id` / `PYTEST_XDIST_WORKER` / `testrun_uid`: 0 (git grep over the full tree).

**5. Serial-engine notes (DECLARED).** Marker `requires_clean_slate` ("requires a clean slate, so no parallel testing", `pyproject.toml:10`) used 54 times under tests/; those tests run in a dedicated serial pytest call. `MOTO_CALL_RESET_API=false` for the parallel run. Server mode depends on an external MotoServer container (one per job, shared by all workers). Only session-scoped fixture: `tests/test_ec2/conftest.py:28` `valid_ami` (no server). `-p no:xdist`: 0.

---

## PrefectHQ/prefect @ 5e8ca118fc514ffe9ab3355ea5cf1c28c347de11

**1. Pytest commands (DECLARED).** `.github/workflows/python-tests.yaml` ("Unit tests"):
- `run-tests` (SQLite, `:159-174`), `PYTEST_SELECTION: tests/server/ tests/events/server`:
```
uv run pytest $PYTEST_SELECTION -m "not windows" --numprocesses auto --maxprocesses 6 --dist worksteal \
  --disable-docker-image-builds --exclude-service kubernetes --exclude-service docker --durations 26 \
  --splits "$DURATION_GROUP_COUNT" --group "${{ matrix.group }}" --splitting-algorithm least_duration \
  --durations-path "$duration_path" --store-durations --clean-durations
```
- `run-canonical-tests` (Postgres 14, `:312-327`), `PYTEST_SELECTION: tests --ignore=tests/typesafety`: same flags but `--numprocesses logical --maxprocesses 6 --dist worksteal`.
- `run-docker-tests` (`:769-776`): `uv run pytest tests --ignore=tests/typesafety ... --numprocesses auto --maxprocesses 6 --dist worksteal --disable-docker-image-builds --only-service docker --durations 26`.
- `run-typesafety-test` (`:810`) `uv run pytest tests/typesafety ...`.
- `profile-tests-with-logfire` (`:565`, only on `repository_dispatch`): `--numprocesses auto --maxprocesses 6 --dist worksteal` over 8 module groups.
`pyproject.toml:271-299` `[tool.pytest.ini_options]` `addopts = "-rfEs"`, `testpaths = ["tests"]`, pytest-env vars `PREFECT_TESTING_TEST_MODE=1` etc. No randomly. Reruns only in `integration-package-tests.yaml:127-128` (`--reruns 2 --reruns-delay 5`, integration packages, not core unit tests).

**2. Deps (DECLARED).** `pyproject.toml:155-163` dev group: `pytest>=9,<10`, `pytest-asyncio>=1.1,<1.5`, `pytest-cov>=6.0`, `pytest-env>=1.1.5`, `pytest-flakefinder>=1.1.0`, `pytest-split>=0.11,<1.0`, `pytest-timeout>=2.3.1`, `pytest-xdist>=3.6.1`. Locked in `uv.lock` (`uv sync --locked` in CI): pytest-xdist 3.8.0 (`uv.lock:5655-5656`), pytest-split 0.11.0 (`:5631-5632`), pytest-timeout 2.4.0. pytest-rerunfailures only in `src/integrations/prefect-ray/pyproject.toml:44`.

**3. Sharding (DECLARED).** pytest-split by duration (`--splitting-algorithm least_duration`) using a `test-durations.json` baseline artifact produced by `prepare-*-test-durations` jobs and merged back by `save-*-test-durations` (cache key prefix `pytest-split-v1-python-3.12-...`). Matrices: `run-tests` 8 groups x Python 3.11/3.12/3.13/3.14/3.15 x sqlite = 40 jobs (`:96-107`); `run-canonical-tests` 18 groups x 5 Python x postgres:14 = 90 jobs (`:281-285`); `run-docker-tests` 5 jobs; plus typesafety, verify-test-selection, prepare/save durations (4). About 141 jobs per PR run of this workflow, all `runs-on: ubuntu-latest`, `timeout-minutes: 15`. Service containers redis:latest (6379) and postgres (5432) per job.

**4. xdist_group / worker_id (DECLARED).** `xdist_group`: 0. pytest `worker_id` fixture used in 4 places: `tests/conftest.py:426` (session autouse `generate_test_database_connection_url`: `prefect_{worker_id}.db` for SQLite, `<db>_tests_{worker_id}` Postgres database per worker, `:448,453`), `tests/fixtures/docker.py:37,55` (docker client / cleanup labelled per worker), `tests/docker/test_registry_pushes.py:39`. The other ~105 `worker_id` hits (12 files) are Prefect "worker" domain objects. `PYTEST_XDIST_WORKER`, `testrun_uid`: 0.

**5. Serial-engine notes (DECLARED).** Session fixture `hosted_api_server` (`src/prefect/testing/fixtures.py:68-69`) starts a Prefect API server subprocess (uvicorn) on a port from `unused_tcp_port_factory`, socket bound up-front to avoid xdist port races; autouse `use_hosted_api_server` (`:179-180`). Per-worker databases as above. Marker `clear_db` (253 references) clears tables. `--exclude-service docker/kubernetes` service markers. 21 `scope="session"` fixtures in tests + src/prefect/testing. `-p no:xdist`: 0.

---

## pydantic/pydantic-ai @ 62e7b66c9f4da5c788eb360e49522a98e8fa0c86

**1. Pytest commands (DECLARED).** `.github/workflows/ci.yml`:
- job `test` (`:716-882`):
```
uv run ${{ matrix.install.command }} "${extra[@]}" "${runner[@]}" --durations=100 -n logical --dist=loadgroup \
  --ignore=tests/durable_exec -m "not temporal" ${{ matrix.install.paths }}          # :880-881
```
  where `runner` is `coverage run -m pytest` when `COLLECT_COVERAGE` (Python 3.14) else `pytest`.
- job `test-all-extras` (`:1005-1200`): `shard_durations.py select --durations <baseline> --shards "$SPLITS" --shard "$SHARD" --exclude tests/durable_exec` produces `--ignore` args, then
```
uv run --all-packages --all-extras --no-extra mcp-tasks "${runner[@]}" --durations=100 -n logical --dist=loadgroup \
  --ignore=tests/durable_exec -m "not temporal" "${shard_args[@]}" "${test_paths[@]}" \
  --store-durations --clean-durations --durations-path "$RUNNER_TEMP/test-durations.json"   # :1195-1197
```
- job `test-durable-exec` (`:1267`): `... --durations=20 -n logical --dist=loadgroup tests/durable_exec` (`:1382`) and `... -n logical --dist=loadgroup -m temporal "${temporal_modules[@]}"` (`:1392`).
- job `test-lowest-versions` (`:1437`): `--durations=100 -n logical --dist=loadgroup` (`:1555`), 2 shards by module.
- `docs-only` job (`:689-697`): `uv run --no-sync pytest ... -n logical --dist=loadgroup`.
`pyproject.toml:596-` `[tool.pytest.ini_options]`: no `addopts`; `anyio_mode = "auto"`, `xfail_strict = true`, `faulthandler_timeout = 120`, `filterwarnings = ["error", ...]`. No `--reruns`, no randomly (only `tests/durable_exec/test_temporal_skip_gating.py:74` passes `-p no:randomly` to a sub-pytest), no `--timeout` flag (per-test budget `PYTEST_TEST_BUDGET_SECONDS` via conftest, marker `slow(reason)`).

**2. Deps (DECLARED).** `pyproject.toml:281-288` dev group: `pytest>=9.0.3`, pytest-codspeed, pytest-examples, pytest-mock, pytest-pretty, `pytest-xdist>=3.6.1`, `pytest-split>=0.11.0`. `uv.lock:8755-8756` pytest-xdist 3.8.0; `uv.lock:8743-8744` pytest-split 0.11.0 (used only for `--store-durations`; splitting itself is the repo's module-level `.github/scripts/shard_durations.py`, `:169-170` explains why not pytest-split's per-test split). No randomly, rerunfailures, shard.

**3. Sharding (DECLARED).** `test` matrix: python 3.11-3.15 x install {pydantic-ai-slim, pydantic-evals, pydantic-ai-harness, pydantic-clai2, standard} = 25 cells on main/merge queue; on `pull_request` the excludes leave 3.13 and 3.14 with all 5 installs, 3.11 and 3.15 with `standard` only, no 3.12 = 12 cells (`:729-800`). `test-all-extras`: python 3.11-3.15 x shard [1,2] + (3.11, shard 3) = 11 jobs, PR excludes 3.12 = 9 (`:1016-1026`); shards are duration-balanced by test module from the baseline uploaded by the latest `main` run (`test-durations-baseline` job `:919`). `test-durable-exec` python 3.11-3.14 (+ includes), `test-lowest-versions` python 3.11-3.14 x 2 shards, plus many other test jobs (examples, harness integrations with localstack/mongodb/postgres/redis/k8s, windows). Exact total per run: UNKNOWN (depends on `classify` outputs). Runner: `${{ vars.CI_LINUX_RUNNER || 'ubuntu-latest' }}` (`:720`), `ubuntu-24.04` default for test-all-extras (`:1012`); the value of the repo variable `CI_LINUX_RUNNER` is UNKNOWN (not in the repo). `timeout-minutes: 20` (`test`), 15 (`test-durable-exec`).

**4. xdist_group / worker_id (DECLARED).** `xdist_group`: 79 occurrences in 71 files (by name: harness-temporal 24, prefect 14, harness-dbos 14, temporal-durability 7, httpx_free_run 5, dbos 4, ~10 singletons). They are effective because every CI pytest call uses `--dist=loadgroup`. pytest `worker_id` fixture: 0. `PYTEST_XDIST_WORKER`: 6 in 3 files (`tests/refactor_capture.py:315,458` per-worker capture file name; `tests/test_examples.py:494`; plus monkeypatching in tests). `testrun_uid`: 0.

**5. Serial-engine notes (DECLARED).** Temporal dev server started by a module-scoped fixture `WorkflowEnvironment.start_local` (`tests/durable_exec/temporal/conftest.py:109-116`), grouped per xdist_group so each group shares one server. Session-scoped fixtures: `tests/clai2/conftest.py:83`, `tests/clai2/browser/conftest.py:40`. Marker `subprocess(reason)` (cost guard), `temporal` marker routes tests to their own job. `-p no:xdist`: 0.

---

## huggingface/transformers @ a2a53c3be2828dfb0c4f89648a406e58d31d1230

**Where CI runs (DECLARED).** `.circleci/config.yml:150-160`: for the public repo (`git_url == https://github.com/huggingface/transformers`) the CircleCI workflow is a `noop` job ("CircleCI is disabled for the public repo — using GitHub Actions for CI"); the full CircleCI pipeline (`fetch_tests` -> `create_circleci_config.py` continuation) runs only for other (private) mirrors and only when the commit message contains `[run-circleci]` (`:21-34`). PR CI for the public repo is `.github/workflows/pr-ci-caller.yml:22-24`: `uses: huggingface/transformers-ci/.github/workflows/pr-ci_dynamic_caller_example.yml@main`, i.e. an EXTERNAL repo at a floating `@main` ref, not pinned by this commit.

**1. Pytest commands.**
- In-repo (DECLARED, CircleCI generator, private-mirror path) `.circleci/create_circleci_config.py:35-41,172-182,247`:
```
python3 -m pytest -m '<marker>' -n {max(1, pytest_num_workers // 2)} -p no:warning -o junit_family=xunit1 --junitxml=test-results/junit.xml \
  --reruns 5 --reruns-delay 2 --only-rerun '(OSError|Timeout|ConnectionError|...)' \
  --max-worker-restart=0 -vvv -rsfE --random-order-bucket=module --random-order-seed=${CIRCLE_BUILD_NUM:-0} --make-reports=tests_<name> $(cat splitted_tests.txt)
```
  `pytest_num_workers` default 8 (`:101`) so `-n 4`; `repo_utils` uses 4 -> `-n 2`; doc tests `-n 1` with `--dist=loadfile` (`:428-430`). No `--dist` for the main jobs (xdist default `load`). Installs a patched pytest fork `git+https://github.com/ydshieh/pytest.git@8.4.1-ydshieh` and `pytest-random-order` (`:128-130`).
- Public GHA PR CI (EXTERNAL, not pinned; read from `huggingface/transformers-ci` main = c740ae2df90c at research time, `pr-ci_reusable_test_job.yml:610-690`): same flags but `-n $PYTEST_NUM_WORKERS` with default `pytest_num_workers: 8` (`:101-107`), `--random-order-seed=${GITHUB_RUN_NUMBER:-0}`, wrapped in `configure-ci-otel`. Treat as UNKNOWN for the pinned commit.
- `pyproject.toml:84-` `[tool.pytest.ini_options]` `addopts = "--doctest-glob='**/*.md'"`, `log_cli = 1`, pytest-env `env = [...]`.

**2. Deps (DECLARED).** `setup.py:109-116` (testing extra): `pytest>=7.2.0,<9.0.0`, pytest-asyncio>=1.2.0, `pytest-random-order`, `pytest-rerunfailures<16.0`, pytest-timeout, pytest-env, `pytest-xdist` (unpinned), pytest-order. No pytest-randomly (docs mention only). pytest-shard only in `vllm-ci-caller.yml` (downstream vLLM tests). No pytest-split.

**3. Sharding.** In-repo CircleCI generator (DECLARED): CircleCI `parallelism` per job 6/8/4/2 (`create_circleci_config.py:300-440`: torch 6, generate 6, tokenization 8, processors 8, pipelines_torch 4, exotic_models 4, non_model 6, training/TP/EP/FSDP 6, peft 2), split with `circleci tests split --split-by=timings` (`:218-221`), `resource_class` default `large` (`:103`); tests selected by `utils/tests_fetcher.py` (PR-impacted files only). Public GHA (EXTERNAL, UNKNOWN for pin): 14 reusable test jobs, `parallelism: 8` used as a cap, shard count `min(8, ceil(files/2))` with a deterministic chunk split (not timings), runner self-hosted `runs-on: group: aws-m8i-l-cache`, container `huggingface/transformers-torch-light` with `--shm-size=16gb`.

**4. xdist_group / worker_id (DECLARED).** `xdist_group`: 0. pytest `worker_id` fixture: 0. `PYTEST_XDIST_WORKER`: 3 uses: `conftest.py:70` (per-worker fallback-event log file), `src/transformers/testing_utils.py:2857` (`pytest_xdist_worker_id()`), `:5289` (per-worker JSON output file). `testrun_uid`: 0. `get_torch_dist_unique_port`/`pytest_xdist_worker_id` referenced 16 times in 5 test files (now binds port 0, `testing_utils.py:2862-2873`).

**5. Serial-engine notes (DECLARED).** Random test order via pytest-random-order (bucket=module, seed = build number) and reruns on flaky patterns are part of the CI command. `--max-worker-restart=0`. Heavy model downloads from the HF Hub (hub cache prefetch `utils/fetch_hub_objects_for_ci.py`). `-p no:xdist`: 0.
