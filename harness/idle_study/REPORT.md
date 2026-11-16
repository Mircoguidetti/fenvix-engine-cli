# Idle share and baseline flakiness of whole-stack test suites

Measurement for Move 4, "Virtual time for the whole stack" (`fenvix-brain-cli/sessions/2026-11-16-fable-olix-moves/REPORT.md`).
Question: how much of an integration or e2e suite's wall time is waiting (every process blocked), which a whole-stack
virtual clock could skip; and how much of the suites' flakiness needs cross-process control.

Measured 2026-11-16 on GitHub Actions hosted runners (4 vCPU, 15 GiB; Ubuntu 26.04, Ubuntu 24.04 for karakeep),
branch `claude/loving-maxwell-58mv2w` of `Mircoguidetti/fenvix-engine-cli`, workflow `.github/workflows/idle-study.yml`.
Raw per-repository results: `harness/idle_study/results/*.json`; tables printed by `lib/aggregate.py`.

## Headline

- **Median idle share across 19 repositories: 0%** (MEASURED; 1 - CPU-busy/wall, clamped at 0, median over runs
  then over repositories). Median all-blocked share, the lower bound of time in which no process ran at all:
  **3%** (MEASURED).
- The suites are CPU-bound, not wait-bound: the median suite kept **2.76 cores** busy on average on a 4-core runner
  (MEASURED). Most projects already fill the machine with test workers (pytest-xdist, Django `--parallel`, vitest and
  Playwright workers), and browser e2e suites spend 21% to 85% of their CPU inside Chromium (MEASURED, per-process
  sampling).
- Switching the projects' own parallelism off does not reveal hidden waiting: serial runs of 9 parallel suites show
  median idle share 0% and median all-blocked share 3% (MEASURED). The test process itself is busy almost all
  of the time.
- Idle share above 15%: misskey, nodebb, uptime-kuma. Above 40%: nodebb. These are serial suites whose tests contain real sleeps,
  polling or server-side delays (MEASURED shares; the cause is ESTIMATED from the suites, not traced).
- Baseline flakiness is rare: **6 flaky tests** among 37,543 distinct tests and 212,080 test executions,
  in 3 of 19 repositories, retries off (MEASURED). **All 6 need cross-process control** (browser vs server,
  test runner vs app server under load, two test-worker processes on one filesystem); none is in-process (MEASURED
  classification of every flaky test; the sample is small).

## Decision rule

Proposed rule (ESTIMATED, from the Move 4 brief): median idle share above 40% makes whole-stack virtual time the main
investment after Block 3; below 15% the case rests on reproducibility alone.

**Result: 0%, below 15%. By the proposed rule the case for whole-stack virtual time rests on reproducibility
alone; time compression is not a reason to make it the main investment.** The second half of the evidence points the
same way: the little baseline flakiness there is sits across processes, which is exactly what Level 2 would make
reproducible and Levels 0/1 cannot reach. So the measured prize of Move 4 is cross-process reproducibility, not speed.

Two qualifications, both ESTIMATED: (a) speed can still come from virtual time in the minority of serial suites that
wait (3 of 19 here, 29% to 67% idle), and from failing runs, where a timeout is pure waiting (etherpad's flaky run
spent 90 s on one Playwright timeout, MEASURED); (b) a deterministic VM that serialises all processes on one core
would make the CPU-bound majority slower, not faster: their CPU-busy time is 1.04 to 3.9 times their wall time
(MEASURED), so a serial box needs that much more wall time unless it runs several cores deterministically.

## Repositories

20 public applications (not libraries), 10 Python and 10 Node/TypeScript, each pinned to its default-branch commit
of 2026-11-16 (a few days earlier for repositories without commits that day). Each suite runs the way the project's
own CI runs it (same services, same command, same test parallelism), with two deliberate changes: retries off
(`--retries=0` for Playwright, `--retry=0` for vitest in immich, `-p no:rerunfailures` for pytest) and JUnit output on.
Where CI shards a suite over several jobs, one shard is measured (stated in the Suite column). "App" is the language
of the application under test; the e2e suites of fastapi-template and redash are TypeScript Playwright suites
driving Python applications.

| Name | Repository @ commit | App | Suite | Services in the box |
|---|---|---|---|---|
| fastapi-template | [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) @ `77e550a73b` | python | e2e: Playwright (TS) against FastAPI backend in docker compose | backend, Postgres, Mailpit, Playwright runner container |
| redash | [getredash/redash](https://github.com/getredash/redash) @ `f561a53dc5` | python | e2e: Playwright (TS) against Flask server, worker, scheduler in docker compose | server, worker, scheduler, Postgres x2, Redis, MySQL, maildev, http fixture |
| healthchecks | [healthchecks/healthchecks](https://github.com/healthchecks/healthchecks) @ `6c05a7adf2` | python | integration: Django test runner on Postgres | Postgres (runner's system service) |
| bookwyrm | [bookwyrm-social/bookwyrm](https://github.com/bookwyrm-social/bookwyrm) @ `e4744b69aa` | python | integration: pytest -n 3 (Django) on Postgres | Postgres 17 |
| ctfd | [CTFd/CTFd](https://github.com/CTFd/CTFd) @ `485d59e7bf` | python | integration: pytest -n auto (Flask) on Postgres + Redis | Postgres, Redis |
| netbox | [netbox-community/netbox](https://github.com/netbox-community/netbox) @ `3f446d10ca` | python | integration: Django test --parallel on Postgres + Redis | Postgres 18, Redis 8 |
| kinto | [Kinto/kinto](https://github.com/Kinto/kinto) @ `207191e071` | python | integration: pytest on Postgres + Redis + memcached | Postgres, Redis, memcached |
| zou | [cgwire/zou](https://github.com/cgwire/zou) @ `9d1fd95bf9` | python | integration: pytest -n logical + integration-marked tests on Postgres + Redis + Meilisearch | Postgres 18, Redis 7, Meilisearch |
| mealie | [mealie-recipes/mealie](https://github.com/mealie-recipes/mealie) @ `3d639dd5ea` | python | integration: pytest -n auto (FastAPI) on Postgres + LDAP | Postgres, OpenLDAP |
| litestar-fullstack | [litestar-org/litestar-fullstack](https://github.com/litestar-org/litestar-fullstack) @ `90e074e123` | python | integration: pytest with pytest-databases (Postgres, Redis containers started by the suite) | Postgres, Redis (started by the tests) |
| outline | [outline/outline](https://github.com/outline/outline) @ `5e6cc0f191` | node | integration: vitest server projects (shard 1/3) on Postgres | Postgres (runner's system service) |
| uptime-kuma | [louislam/uptime-kuma](https://github.com/louislam/uptime-kuma) @ `e6ea9509e6` | node | e2e: Playwright against the app server | app server (SQLite), browser |
| etherpad | [ether/etherpad-lite](https://github.com/ether/etherpad-lite) @ `263e4a5b59` | node | e2e: Playwright (chromium) against the Etherpad server | Etherpad server (dirty DB), browser |
| nodebb | [NodeBB/NodeBB](https://github.com/NodeBB/NodeBB) @ `8a5db4f12a` | node | integration: mocha on Redis | Redis 8 |
| actual | [actualbudget/actual](https://github.com/actualbudget/actual) @ `abe8ea7851` | node | e2e: Playwright against the built web client (shard 1/3) | static server, browser |
| rallly | [lukevella/rallly](https://github.com/lukevella/rallly) @ `e96c4c5c1d` | node | e2e: Playwright against Next.js (shard 1/3) on Postgres + Mailpit | Next.js server, Postgres 18, Mailpit, browser |
| misskey | [misskey-dev/misskey](https://github.com/misskey-dev/misskey) @ `8fe4596d7d` | node | e2e: vitest API e2e against the backend on Postgres + Redis | Postgres 18, Redis 8 |
| karakeep | [karakeep-app/karakeep](https://github.com/karakeep-app/karakeep) @ `bcc4b90a2a` | node | e2e: vitest against the app stack in docker compose | web, workers, Meilisearch, headless Chrome, sandbox (compose) |
| immich | [immich-app/immich](https://github.com/immich-app/immich) @ `f932212299` | node | e2e: vitest server + CLI e2e against docker compose stack | immich-server, Postgres (vectorchord), Redis |
| documenso | [documenso/documenso](https://github.com/documenso/documenso) @ `3462785230` | node | e2e: Playwright api + license projects and ui shard 1/6, against the Remix server on Postgres + Inbucket + MinIO | Remix server, Postgres, Inbucket, MinIO, browser |

Not measured: redash. (its job, five Playwright runs against the full compose stack, was still running when this report was written; the table is updated if it lands)

## Method

Per repository, one GitHub Actions job (`lib/run_repo.sh`):

1. Clone at the pinned commit; `setup()` in `repos/<name>.sh` installs dependencies, builds and starts the services
   the project's CI starts (Actions service containers become `docker run`, compose stacks stay compose). Setup is
   not measured.
2. Baseline: 20 s of sampling with services up and idle (runner agent noise: median 0.02 cores, MEASURED).
3. 5 to 8 runs of the test command (`run_tests()`), each preceded by `reset()` where the project needs a clean stack
   (compose `down -v` and re-seed for fastapi-template and redash). W = wall time of the test command itself.
4. During each run a root sampler (`lib/sampler.py`) reads every 0.5 s: `/proc/stat` for the whole VM
   (busy = user + nice + system + irq + softirq; iowait and steal apart), `cpu.stat` of the test command's own
   cgroup, of a cgroup for harness-started servers and of every Docker container; every 2 s it reads the CPU time of
   every process for attribution by command name. The VM runs nothing but this job, so VM-wide busy time is the CPU
   of the test runner, browser, app servers, databases and queues together, plus runner-agent noise (kept in: it
   lowers the idle share by about 1 point, the conservative direction; the JSON also has "net" figures).
5. Per-test outcomes from JUnit XML (from the Django `-v 2` log for healthchecks and netbox).

Two idle measures per run:

- **Idle share = 1 - B/W**, B = CPU-busy seconds summed over all CPUs, the measure the brief asked for. If the box
  executes one instruction stream at a time (as a deterministic VM does) it needs at least B seconds, so at most
  1 - B/W of the wall time can be skipped. Negative when the suite keeps more than one core busy on average; the
  compressible share is then 0 (headline figures are clamped at 0; tables show the raw value).
- **All-blocked share (lower bound)** = sum over 0.5 s intervals of max(0, 1 - busy cores in the interval) / W. In
  an interval where the box used b < 1 cores, at least (1 - b) of it had no process on any CPU, whatever the
  overlap. It bounds from below the time a multi-core virtual clock could skip without serialising anything. For
  results recorded before this field existed it is computed from run 1 at 1 s resolution, which can only lower it.

Each figure is the median over the repository's runs; summary lines are medians over repositories.

Serial variant: because at least 11 of the 20 suites run tests in parallel by their own configuration (pytest-xdist,
Django `--parallel`, vitest or Playwright workers), the parallel integration suites and actual were
also measured with the project's test parallelism switched off (`-n 0`, no `--parallel`, `--maxWorkers=1`,
`E2E_WORKERS=1`; 2 or 3 runs each). A deterministic box that serialises execution sees roughly this, and it shows
whether waiting hides behind parallel workers.

Flakiness: a test is flaky when it both passed and failed across the runs of one job (same VM, same commit, same
setup). Tests failing in every run are counted apart as "always failing" (none occurred).

## Results: idle share

All numbers MEASURED (GitHub Actions, 2026-11-16), medians over runs.

| Repository | App | Suite | Runs | Wall (s) | CPU-busy (s) | Mean busy cores | Idle share 1 - B/W | All-blocked share (lower bound) | Tests | Flaky | Always failing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fastapi-template | python | e2e: Playwright (TS) against FastAPI backend in docker compose | 6 | 46 | 54 | 1.17 | -17% | 28% | 62 | 0 | 0 |
| redash | python | e2e: Playwright (TS) against Flask server, worker, scheduler in docker compose | 0 | - | - | - | - | - | not run | - | - |
| healthchecks | python | integration: Django test runner on Postgres | 8 | 36 | 38 | 1.04 | -4% | 2% | 1785 | 0 | 0 |
| bookwyrm | python | integration: pytest -n 3 (Django) on Postgres | 6 | 198 | 579 | 2.92 | -192% | 3% | 1431 | 0 | 0 |
| ctfd | python | integration: pytest -n auto (Flask) on Postgres + Redis | 6 | 494 | 1829 | 3.71 | -271% | 0% | 747 | 1 | 0 |
| netbox | python | integration: Django test --parallel on Postgres + Redis | 5 | 568 | 1999 | 3.51 | -251% | 0% | 14816 | 0 | 0 |
| kinto | python | integration: pytest on Postgres + Redis + memcached | 6 | 88 | 340 | 3.88 | -288% | 1% | 2468 | 0 | 0 |
| zou | python | integration: pytest -n logical + integration-marked tests on Postgres + Redis + Meilisearch | 6 | 300 | 986 | 3.29 | -229% | 2% | 4338 | 0 | 0 |
| mealie | python | integration: pytest -n auto (FastAPI) on Postgres + LDAP | 6 | 140 | 386 | 2.76 | -176% | 1% | 3895 | 0 | 0 |
| litestar-fullstack | python | integration: pytest with pytest-databases (Postgres, Redis containers started by the suite) | 6 | 83 | 283 | 3.40 | -240% | 9% | 577 | 0 | 0 |
| outline | node | integration: vitest server projects (shard 1/3) on Postgres | 6 | 41 | 115 | 2.82 | -182% | 3% | 1160 | 0 | 0 |
| uptime-kuma | node | e2e: Playwright against the app server | 6 | 278 | 192 | 0.69 | 31% | 43% | 71 | 0 | 0 |
| etherpad | node | e2e: Playwright (chromium) against the Etherpad server | 6 | 148 | 238 | 1.59 | -59% | 17% | 289 | 1 | 0 |
| nodebb | node | integration: mocha on Redis | 6 | 206 | 67 | 0.33 | 67% | 73% | 3230 | 0 | 0 |
| actual | node | e2e: Playwright against the built web client (shard 1/3) | 6 | 201 | 760 | 3.78 | -278% | 2% | 74 | 0 | 0 |
| rallly | node | e2e: Playwright against Next.js (shard 1/3) on Postgres + Mailpit | 6 | 74 | 140 | 1.88 | -88% | 3% | 66 | 0 | 0 |
| misskey | node | e2e: vitest API e2e against the backend on Postgres + Redis | 5 | 380 | 266 | 0.71 | 29% | 41% | 1201 | 0 | 0 |
| karakeep | node | e2e: vitest against the app stack in docker compose | 6 | 212 | 665 | 3.15 | -215% | 4% | 228 | 0 | 0 |
| immich | node | e2e: vitest server + CLI e2e against docker compose stack | 6 | 106 | 216 | 2.04 | -104% | 4% | 374 | 0 | 0 |
| documenso | node | e2e: Playwright api + license projects and ui shard 1/6, against the Remix server on Postgres + Inbucket + MinIO | 5 | 528 | 850 | 1.76 | -76% | 5% | 731 | 4 | 0 |

repositories measured: 19
- idle share 1 - B/W, clamped at 0: median 0%, quartiles 0% / 0%, min 0%, max 67%
- all-blocked share (lower bound): median 3%, quartiles 2% / 17%, min 0%, max 73%
-   e2e (9): idle clamped: median 0%, quartiles 0% / 0%, min 0%, max 31%
-   e2e (9): all-blocked: median 5%, quartiles 4% / 28%, min 2%, max 43%
-   integration (10): idle clamped: median 0%, quartiles 0% / 0%, min 0%, max 67%
-   integration (10): all-blocked: median 2%, quartiles 1% / 3%, min 0%, max 73%
-   python apps (9): idle clamped: median 0%, quartiles 0% / 0%, min 0%, max 0%
-   node apps (10): idle clamped: median 0%, quartiles 0% / 29%, min 0%, max 67%
- median mean-busy-cores: 2.76
- test executions: 212080; distinct tests 37543; flaky 6

### Serial variant (MEASURED)

| Repository | Runs | Wall (s) | CPU-busy (s) | Mean busy cores | Idle share 1 - B/W | All-blocked share (lower bound) | Wall vs parallel | Tests |
|---|---|---|---|---|---|---|---|---|
| actual | 3 | 433 | 830 | 1.92 | -92% | 1% | x2.2 | 74 |
| bookwyrm | 3 | 385 | 385 | 1.00 | 0% | 3% | x1.9 | 1431 |
| ctfd | 2 | 1244 | 1249 | 1.00 | -0% | 2% | x2.5 | 747 |
| kinto | 3 | 116 | 110 | 0.95 | 5% | 8% | x1.3 | 2468 |
| litestar-fullstack | 3 | 245 | 299 | 1.22 | -22% | 12% | x2.9 | 577 |
| mealie | 3 | 360 | 372 | 1.03 | -3% | 3% | x2.6 | 3895 |
| netbox | 2 | 1268 | 1340 | 1.06 | -6% | 0% | x2.2 | 14781 |
| outline | 3 | 63 | 77 | 1.22 | -22% | 6% | x1.5 | 1160 |
| zou | 3 | 562 | 750 | 1.33 | -33% | 2% | x1.9 | 4338 |

- serial variant: median idle share 0%, median all-blocked 3%
- per repository, serial where measured else as configured (19): median idle share 0%, quartiles 0% / 0%
  all-blocked: median 4%, quartiles 2% / 17%

Serial runs use less CPU in total than parallel ones (kinto 110 s against 340 s, MEASURED): worker start-up, per-worker
collection and database cloning are part of what parallel suites spend. In the serial integration suites the test
command's own process tree alone uses 0.71 to 1.12 cores on average (mealie lowest, outline highest; MEASURED, cgroup
`cpu.stat`), and the databases run beside it: the time goes to compute in the test process (ORM, serialisation,
fixtures, app code called in-process), not to waiting on the database.

### Where the CPU goes (one run per repository, MEASURED)

| Repository | CPU-busy (s), one run | Browser processes | Docker containers (DBs, queues, app servers in compose) | Test command's process tree |
|---|---|---|---|---|
| fastapi-template | 55 | 25% | 93% | n/a |
| healthchecks | 36 | 0% | 0% | 78% |
| bookwyrm | 580 | 0% | 5% | n/a |
| ctfd | 1821 | 0% | 12% | n/a |
| netbox | 2087 | 0% | 18% | n/a |
| kinto | 345 | 0% | 1% | n/a |
| zou | 967 | 0% | 17% | n/a |
| mealie | 388 | 0% | 16% | n/a |
| litestar-fullstack | 279 | 0% | 4% | n/a |
| outline | 115 | 0% | 0% | n/a |
| uptime-kuma | 191 | 51% | 0% | n/a |
| etherpad | 249 | 41% | 0% | 92% |
| nodebb | 67 | 0% | 3% | n/a |
| actual | 759 | 85% | 0% | n/a |
| rallly | 140 | 54% | 1% | n/a |
| misskey | 270 | 0% | 19% | n/a |
| karakeep | 691 | 21% | 60% | n/a |
| immich | 213 | 0% | 78% | 13% |
| documenso | 999 | 44% | 2% | n/a |

Browser shares come from per-process sampling every 2 s and miss short-lived processes; container shares come from
cgroup counters and are exact. In fastapi-template the Playwright browser runs inside a container, so it is counted
in both columns. "n/a": run recorded before the test-command cgroup worked (see caveats).

## Results: baseline flakiness

Runs per repository: 5 to 8 (main configuration). Distinct tests: 37,543; test executions: 212,080 (MEASURED).
Flaky tests: 6, in etherpad (1), documenso (4) and ctfd (1). Always-failing tests: 0. 16 of 19 measured
repositories had no flaky test in 5 to 8 retry-free runs (MEASURED).

Every flaky test was classified by reading its failure message and test code (MEASURED sample = all of them):

| Repository | Test | Failed runs | Failure | Class |
|---|---|---|---|---|
| etherpad | `tests/frontend-new/specs/embed_value.spec.ts::embed links › when read only option is set › the embed as iframe code is a` | 1 of 6 | `beforeEach` timed out after 90 s waiting for the pad editor iframe (`ace_outer`) the server renders | cross-process: browser vs Etherpad server |
| ctfd | `tests.test_views::test_user_can_access_files` | 1 of 6 | `FileExistsError` on a fixed upload directory created by a test in another xdist worker | cross-process: two test-worker processes on a shared filesystem |
| documenso | `admin/email-transports/email-transport-claims.spec.ts::[ADMIN][EMAIL_TRANSPORT]: updating a subscription claim WITH back` | 2 of 5 | `locator.click: Element is outside of the viewport` on a dropdown option whose list was still laying out | cross-process: test runner vs browser rendering |
| documenso | `api/trpc/admin/admin-find-documents.spec.ts::[ADMIN][TRPC][FIND_DOCUMENTS]: non-admin user is rejected with 401` | 1 of 5 | `apiRequestContext.get: read ECONNRESET` from the app server while 10 API workers hit it | cross-process: test runner vs app server under load |
| documenso | `api/trpc/admin/admin-find-documents.spec.ts::[ADMIN][TRPC][FIND_DOCUMENTS]: recipient prefix with numeric value matches ` | 1 of 4 | `apiRequestContext.get: read ECONNRESET` from the app server while 10 API workers hit it | cross-process: test runner vs app server under load |
| documenso | `api/trpc/admin/admin-search.spec.ts::[ADMIN][TRPC][SEARCH]: non-admin authenticated user is rejected with 401` | 1 of 4 | `apiRequestContext.get: read ECONNRESET` from the app server while 10 API workers hit it | cross-process: test runner vs app server under load |

Split: **6 of 6 cross-process, 0 in-process** (MEASURED, n = 6: too small for a rate, enough
to say the in-process share is not dominant in these suites). The ctfd case sits at the edge: the two parties are
pytest-xdist worker processes of the test runner itself, racing on a shared upload directory; a box that runs the
workers under one deterministic scheduler, or a serial run, removes it.

Not counted as flaky: 18 mealie tests failed in serial runs 2 and 3 after passing in run 1. Cause: the harness does not
reset the database between serial runs, and those tests assume a fresh database (the parallel configuration
recreates it per worker). This is a harness artifact (MEASURED), recorded in `results/mealie--serial.json`.

What the projects declare: their CI configs retry failed tests (documenso Playwright 4 times, immich vitest 4 times,
fastapi-template and uptime-kuma Playwright 2 times, redash and actual Playwright once; DECLARED, the projects'
config files at the pinned commits). Retries were off here; immich showed 0 flaky tests in 6 runs (MEASURED).
Retries in CI mean the projects pay for flakiness with reruns rather than seeing red builds; this sample does not say
how often those retries fire (UNKNOWN).

## Caveats

- Hardware: 4-vCPU hosted runners. On larger machines parallel suites would leave more cores idle but would not
  create more all-blocked time; on smaller machines the idle shares would fall further (ESTIMATED).
- Runs per repository (5 to 8) are enough for idle shares (run-to-run spread is a few points, MEASURED) but small for
  flakiness: a test that fails 1 run in 100 is unlikely to show. The flaky count is a floor.
- Sampling resolution is 0.5 s. The all-blocked figure is a lower bound by construction; waits shorter than 0.5 s that
  overlap with work elsewhere are invisible to both measures.
- One shard was measured where CI shards the suite (outline 1/3, actual 1/3, rallly 1/3, documenso ui 1/6 plus the api
  projects). Shards of the same suite are similar in kind; idle shares were not measured on the other shards.
- documenso runs 1 and 3 stopped early after failures in the api project (52 s and 48 s against about 550 s); the
  median uses the full runs.
- Test-command cgroup attribution worked from the second iteration of the harness; earlier results attribute CPU
  only through per-process sampling ("n/a" in the CPU table). VM-wide totals, which carry every number above, are
  unaffected.
- The suites ran on the runner as each project's CI does, not inside a deterministic box; the idle share is an upper
  bound of what virtual time could compress, not a measurement of virtual time.
- Repository choice: popular, actively maintained applications with integration or e2e suites in CI that a session
  could reproduce in one job. Suites built around external services, long soak tests, or much larger monorepos may
  wait more; this sample says nothing about them (UNKNOWN).

## Reproduce

Edit `harness/idle_study/run.json` (`only`: repository names, empty for all; `variant`: `""` or `"serial"`; `runs`:
override) and push it to `claude/loving-maxwell-58mv2w`; each job commits `results/<name>[--serial].json`.
`python3 harness/idle_study/lib/aggregate.py` prints the tables.
