# APP1 notes: service back-end (GitHub App + HTTP API)

Audited: `fenvix-app@main` (ce69a6b): `github-app/` (all 48 files under `github-app/src` read in full; `openapi.gen.ts` is
the generated copy of the YAML), `openapi/fenvix-api.yaml`, `src/api` + `src/data` + `src/lib` (the dashboard client),
`docs/data-contract.md`, `docs/GITHUB-APP.md`, `supabase/migrations/0011-0017`, `infra/github-app/lib` (API Gateway,
runner image files, cache), and the engine side at `fenvix-engine-cli@claude/release-1` (529c160): `runner/`,
`release/`. Gaps: `APP1.gaps.jsonl` (129 entries). Everything below was run in `/home/user/audit/work/APP1/` on a copy
(`git archive HEAD` of fenvix-app); the repositories were not touched.

Labels: MEASURED = I ran it here; ESTIMATED = my arithmetic; DECLARED = a document says so.

## 1. The ten things the lead should know first

1. **The engine and the service are not connected.** No branch of the engine (62 remote branches checked) contains the
   string `v1/runner`; the released CLI has no login/upload. The only sender to the API is a Python script inside the
   service's own runner image, and it sends the run summary only (APP1-001..004).
2. **A customer's tests do not run in the engine on our machines.** The setup pull request changes only `runs-on:`; the
   machine only offers `fenvix-run`, which a workflow must call by name. An unchanged `pytest` step runs plain pytest.
   The pull request text says the opposite (APP1-005). Such a job is billed (APP1-006).
3. **The runner image is not release-1.** It pins engine commit `a20b93d7` (2026-11-18, not an ancestor of
   `claude/release-1`) and installs the detpy wheel only: no detjs, no fenvix-go, no JVM agent (APP1-007..010).
4. **Per-test results, receipts, defects, explorations, live progress: the server side is built and tested, the sending
   side does not exist** (APP1-002..004). In production the defect list, receipts, audit and nightly pages stay empty.
5. **Shadow mode exists only in the database.** Nothing in the engine reads `FENVIX_MODE`; a "shadow" run skips tests
   (APP1-011). Warm-ups can only answer "unsupported": `runner/warmup.sh` exists on no branch (APP1-012).
6. **The pull request comment has a whole-suite replay command and nothing else of the promise**: no seed, no order, no
   diverging event (APP1-017, -018). With two fenvix jobs on a pull request the later job overwrites the comment: a
   flaky failure turns into a green tick (APP1-019, MEASURED).
7. **Three project settings do nothing**: skip with proof, nightly exploration, test command (APP1-115, -089, -062).
8. **No money path**: no payment provider, no plan change, no quota, no gate at the end of the trial (APP1-098..101).
9. **The deployed fleet is in AWS eu-west-1 but named region "us"**; an organization that picks EU gets no machine
   (APP1-112).
10. **What is solid** (so nobody re-audits it): webhook signature check (HMAC-SHA256 over raw bytes, constant time,
    SHA-1 refused); delivery de-duplication by `X-GitHub-Delivery`; session verification (JWKS, issuer, audience,
    asymmetric algorithms only); organization membership checked on every call in the same transaction, row level
    security as a second barrier; **no IDOR found** (the suite's cross-organization tests pass, see section 5); request
    validation against the contract on every dashboard operation; per-machine credentials bound to runner, repository,
    run and attempt; secrets in SSM only, none committed.

## 2. Three-way endpoint table (implemented / specified / called)

"Implemented" = a route exists in `github-app/src` (dashboard routes are generated from the contract and fail at start
when a handler is missing: `github-app/src/api/server.ts:193-194`). "Specified" = in `openapi/fenvix-api.yaml`.
"Called" = the dashboard client (`src/data/api.ts`) or, for runner routes, a machine-side script.

Dashboard operations (tag `dashboard`, all under `/v1`, all: Supabase session token; `W` = needs `X-Fenvix-Workspace`,
membership checked, 404 if not a member; `A` = owner or admin only, 403 for a member):

| # | method path | operationId | impl | spec | called by dashboard | auth |
|---|---|---|---|---|---|---|
| 1 | GET /me | getMe | yes | yes | yes | session |
| 2 | GET /organizations | listOrganizations | yes | yes | yes | session |
| 3 | POST /organizations | createOrganization | yes | yes | yes | session |
| 4 | GET /organization | getOrganization | yes | yes | **no** (APP1-063) | W |
| 5 | PUT /organization | renameOrganization | yes | yes | yes | W A |
| 6 | POST /organization/leave | leaveOrganization | yes | yes | yes | W |
| 7 | GET /organization/members | listMembers | yes | yes | yes | W |
| 8 | PUT /organization/members/{userId} | changeMemberRole | yes | yes | yes | W A |
| 9 | DELETE /organization/members/{userId} | removeMember | yes | yes | yes | W A |
| 10 | GET /organization/invitations | listInvitations | yes | yes | yes | W A |
| 11 | POST /organization/invitations | createInvitation | yes | yes | yes | W A (20/day, 429) |
| 12 | POST /organization/invitations/{id}/revoke | revokeInvitation | yes | yes | yes | W A |
| 13 | POST /invitations/accept | acceptInvitation | yes | yes | yes | session |
| 14 | GET /settings | getSettings | yes | yes | yes | W |
| 15 | PUT /settings | saveSettings | yes | yes | yes | W A |
| 16 | GET /overview | getOverview | yes | yes | yes | W |
| 17 | GET /projects | listProjects | yes | yes | yes | W |
| 18 | GET /projects/{projectId} | getProject | yes | yes | yes | W |
| 19 | PUT /projects/{projectId}/settings | saveProjectSettings | yes | yes | yes | W A |
| 20 | GET /projects/{projectId}/runs | listRuns | yes | yes | yes | W (page, pageSize; `since`: up to 20,000) |
| 21 | GET /projects/{projectId}/skip-share | getSkipShareSeries | yes | yes | yes | W |
| 22 | GET /projects/{projectId}/explorations | listExplorations | yes | yes | yes | W (limit 120) |
| 23 | GET /projects/{projectId}/audit | getAudit | yes | yes | yes | W |
| 24 | GET /projects/{projectId}/setup-change | getSetupChange | yes | yes | yes | W |
| 25 | GET /activity | listActivity | yes | yes | yes | W |
| 26 | GET /runs/{runId} | getRun | yes | yes | yes (twice: plain and If-None-Match) | W |
| 27 | GET /runs/{runId}/tests | listTestResults | yes | yes | yes | W (page, pageSize) |
| 28 | GET /runs/{runId}/files | listRunFiles | yes | yes | yes | W |
| 29 | GET /receipts/{receiptId} | getSkipReceipt | yes | yes | yes | W |
| 30 | GET /defects | listDefects | yes | yes | yes | W (no paging, APP1-071) |
| 31 | GET /defect-families | listDefectFamilies | yes | yes | yes | W (no paging) |
| 32 | GET /defects/{defectId} | getDefect | yes | yes | yes | W |
| 33 | GET /usage/months | listUsageMonths | yes | yes | yes | W |
| 34 | GET /usage/{month} | getUsage | yes | yes | yes | W |
| 35 | GET /usage/{month}/csv | exportUsage | yes | yes | yes | W |
| 36 | GET /plans | listPlans | yes | yes | yes | W |
| 37 | GET /billing | getBilling | yes | yes | yes | W |
| 38 | GET /github | getGitHubConnection | yes | yes | yes | W |
| 39 | POST /github/install-link | createInstallLink | yes | yes | yes | W A |
| 40 | POST /github/installations/complete | completeGitHubInstall | yes | yes | yes | session (the database checks person, role, single use) |
| 41 | GET /github/repositories | listGitHubRepositories | yes | yes | yes | W (no paging, APP1-072) |
| 42 | POST /github/repositories/{repositoryId}/setup-pull-request | openSetupPullRequest | yes | yes | yes | W A |

Runner operations (tag `runner`; auth: per-machine credential `fxr1.<payload>.<HMAC-SHA256>`, 24 h, bound to runner
name + repository + run + attempt, or to one warm-up):

| method path | impl | spec | called by | note |
|---|---|---|---|---|
| POST /runner/summaries | yes (`app.ts:121`) | yes | `infra/github-app/lib/runner/files/fenvix-summary-poster` | the only record a job sends |
| POST /runner/warmups | yes (`app.ts:225`) | yes | `.../fenvix-warmup-report` | the executor `runner/warmup.sh` does not exist (APP1-012) |
| POST /runner/progress | yes (`app.ts:177`) | yes | **nobody** (APP1-003) | |
| POST /runner/results | yes (`app.ts:192`) | yes | **nobody** (APP1-002) | |
| POST /runner/explorations | yes (`app.ts:211`) | yes | **nobody** (APP1-004) | refused for a per-job credential; only a demo machine's credential qualifies |

Implemented, not in the contract:

| method path | called by | gap |
|---|---|---|
| GET /healthz (`app.ts:99`) | the deploy check (`deploy/cli.mjs:216`) | APP1-064 |
| POST /webhooks/github (`app.ts:103`) | GitHub | APP1-065 |
| GET /github/setup (`app.ts:276`) | the browser, sent by GitHub after an install | APP1-066 |
| OPTIONS /v1/* (`api/server.ts:156`) | the browser (CORS preflight) | none |

Mismatches, in one place: 1 operation specified + implemented + never called (GET /organization); 3 runner operations
specified + implemented + never called by anything; 3 routes implemented + called + not specified; 0 operations called by
the dashboard that the server lacks (the client is typed from the same YAML and `npm run api:check` passes: MEASURED).
Operations the product needs and nobody has, each its own gap: API keys / public API (APP1-067), defect state
(APP1-068), delete/export (APP1-069, -123), plan change and payment (APP1-098, -099), unlink an installation
(APP1-122), trace upload (APP1-080), bundle upload/download (APP1-086), a result intake for runs that are not on our
machines (APP1-048).

Qualities that hold for all 42 dashboard operations (from `github-app/src/api/server.ts`):

| quality | what the code does |
|---|---|
| authentication | `Authorization: Bearer <Supabase access token>`, verified with `jose` against the project's JWKS; algorithms ES256, RS256, EdDSA only; issuer `<supabaseUrl>/auth/v1`; audience `authenticated`; expiry enforced when the claim is present (not required; revocation not checked: APP1-076); HS256 projects fail (APP1-129) |
| authorization | organization from `X-Fenvix-Workspace` (UUID); membership and role read in the request's own transaction (`server.ts:221-228`); non-member = 404 with the same text as "does not exist"; `x-fenvix-role: admin` = owner or admin, else 403; every query also filters `workspace_id = $1`; row level security repeats both checks as `fenvix_api` (no BYPASSRLS) |
| input validation | every params/query/header/body validated with ajv against the contract, no coercion in bodies, unknown fields refused (400 `validation_failed` with `field`) |
| error format | `{ "error": { "code", "message", "field"? } }`; codes: unauthenticated 401, forbidden 403, not_found 404, conflict 409, validation_failed 400/413/415, rate_limited 429, unavailable 503, github_not_configured 503, internal 500. Gateway-made errors differ (APP1-077) |
| pagination | `page`/`pageSize` on runs and tests only; everything else unpaged (APP1-071..074) |
| rate limiting | none per caller; stage throttle 50 rps / burst 100 shared with webhooks and runners (APP1-070) |
| request size | 64 KB body limit (dashboard API); runner: 64 KB progress, 6 MB results/explorations, 4 MB warm-ups, 32 MB summaries (not reachable through the gateway: APP1-015); webhooks 26 MB (same: APP1-037) |
| CORS | origin of `DASHBOARD_URL` plus `API_CORS_ORIGINS`; deployed: `https://console.fenvix.dev` only; no credentials (bearer header, `credentials: "omit"` in the client); preflight answered by the Lambda; `Vary: Origin`; `Cache-Control: no-store` by default (APP1-078) |
| idempotency | none (APP1-075); the runner intake is idempotent by natural keys |
| versioning | `/v1` prefix and `info.version 1.0.0`; no deprecation rule; runner records carry no schema version (APP1-016) |

## 3. Paid-service features, one by one

| feature | state | where |
|---|---|---|
| (a) memory across runs: traces/fingerprints uploaded, stored, compared | **missing** (run rows, per-test outcomes and receipts have a server side; traces have none; nothing is sent anyway) | APP1-080, -081, -002 |
| (b) defect deduplication | **partial**: upsert by (project, test id, fingerprint), occurrences counted once per run, re-opened when seen again; families by cause tests; never fed in production; never closed | APP1-083..085, -068, -002 |
| (c) replay bundles stored, shared, downloadable, retention | **missing** (a defect row keeps order, seed and a command as text) | APP1-086, -087 |
| (d) PR comment | **partial**: one comment updated in place, replay command for pytest; no seed/order/divergence; overwritten across jobs | APP1-017..022, -127 |
| (e) exploration: scheduling, machines, ingestion | ingestion **exists** (one a day per project, 90 nights kept); scheduling and machines **missing** | APP1-088..093, -004 |
| (f) shared cache service | **exists for our machines only**: one private machine, tokens signed per job, organization = installation, write only for trusted default-branch runs; no quota, backup or eviction | APP1-094..097 |
| (g) usage metering, plans, billing, trial, license keys | metering **exists** (one usage event per job, units = held minutes / 10, warm-ups not billed); plans are rows with prices; trial = 30 days shadow, one per GitHub account; **no** billing provider, plan change, quota, license key | APP1-098..106, -006, -011 |
| (h) runner orchestration | **partial**: SQS queue, one EC2 instance per job with a just-in-time runner, idle watchdog, reaper, regions us/eu by placement; no microVM, no phoenixNAP, 4 machines, one size, region mislabelled in the deployed settings | APP1-107..114, -026 |
| (i) API keys for CI/CLI/agents | **missing** | APP1-067 |
| (j) audit log | **missing** (tables dropped in 0014) | APP1-120 |
| (k) notifications (e-mail, Slack) | **missing** (a setting is stored, nothing sends) | APP1-116..119 |
| (l) data deletion/export on uninstall or request | **missing** | APP1-121..123, -069 |
| (m) multi-language | Python only end to end; Node and Go are enum values without a sender; JVM has no value at all | APP1-008..010, -049..057 |

## 4. How the App learns about a run (as built)

1. GitHub sends `workflow_job` (queued / in_progress / completed); only jobs whose labels include `fenvix` count
   (`service.ts:389`).
2. queued: the worker asks GitHub for a just-in-time runner and starts one EC2 machine with the job's own credentials
   in its user data (only for an installation linked to an organization).
3. in_progress: a `ci_runs` row (status running) and a check run "in progress".
4. The machine's job-completed hook copies `$RUNNER_TEMP/fenvix/summary.json`, if the job wrote one, to a spool; the
   poster sends it to `POST /v1/runner/summaries`.
5. completed + summary (or 10 minutes without one, the sweep): the run row is finished, one usage event is written,
   the check run is completed, the pull request comment is created or updated.

Nothing else reports a run: not the CLI, not a GitHub Action, not another CI (APP1-048).

Webhook events: handled = installation (created, deleted, suspend, unsuspend, new_permissions_accepted through the
upsert), installation_repositories (added, removed), push, pull_request (any action: state and head tracked),
workflow_job; `ping` answered; everything else 202 `ignored` and not recorded (MEASURED, probe A below).
Token handling: App JWT RS256, iat 60 s back, 9 minutes; installation tokens cached in memory per function instance,
renewed 5 minutes before expiry, forgotten on suspend/delete; a warm-up's checkout token is scoped to one repository,
contents read. Private key, webhook secret, client secret, state key, runner token: SSM SecureString, read per function
by exact name, reloaded every 5 minutes; no machine holds a fleet secret. Commit statuses are not used (check runs only).

## 5. Tests I ran (MEASURED, in the scratch copy)

- `cd github-app && npm ci && npm test` with `TEST_DATABASE_URL` pointing at a scratch Postgres 16 I started in my work
  folder (port 54629): typecheck clean; unit **135 pass, 0 fail**; integration **133 pass, 0 fail, "skipped 0"**, but
  two suites did not run: `﹣ dashboard API: every operation, real tokens, real database # no local Supabase` and
  `﹣ dashboard API: the shared cache of each repository (warm-ups)` (they need Docker, absent here). Log:
  `/home/user/audit/work/APP1/npm-test.log` (APP1-124).
- Those two suites again, with a stand-in for Supabase Auth I wrote (`work/APP1/fakeauth/server.mjs`: sign-up that
  inserts into `auth.users`, ES256 tokens, JWKS): **32 pass, 0 fail**, including "ids of another organization answer
  404", "an organization's lists hold none of another organization's rows", "row level security, the second barrier",
  "every operation marked admin: a member is refused", "CORS: the dashboard's origin only". Log:
  `work/APP1/api-tests.log`. This is not the real Supabase Auth server: the real-GoTrue run happens only in the
  repository's CI.
- `npm run api:check` (contract vs generated client types): matches. `npm run test:unit` (dashboard, 66 tests): pass.
  `npm run test:rls` against a second scratch database: API, CI, CI-explore, GH, warm RLS all OK.
- A first attempt with only `github-app/` copied failed 3 unit files (`ERR_MODULE_NOT_FOUND ... src/data/ci.ts`): the
  package imports the dashboard's `src/data` and `openapi/` from the repository root, so it cannot be tested or built
  alone. Not a product gap; noted for whoever packages it.

Covered only by fakes, never against the real thing: every GitHub REST call and the OAuth exchange
(`tests/helpers/fake-github.ts`, answers checked against GitHub's OpenAPI description; webhooks are GitHub's recorded
examples with our values); EC2, SQS, S3, SSM (`tests/helpers/memory-aws.ts`); the machine scripts (stand-in HTTP
server); Supabase Auth (real GoTrue in CI only). `github-app/recordings/e2e.json` is recorded from the fake, not from
github.com (its `about` field says so). The App itself has not been created on GitHub (APP1-038).

## 6. Secrets and configuration

- Nothing secret is committed: `git ls-files | grep -iE '\.env|\.pem|secret|\.key$'` gives the two `.env.example`
  files and three source files about secrets; a scan for private-key headers and token shapes outside tests found
  nothing. `infra/github-app/cdk.json:16` holds the AWS account id (an identifier, not a credential).
- Variables read in `github-app/src` (about 55): API_CORS_ORIGINS API_DATABASE_URL CACHE_SIGNING_KEY CACHE_SIGNING_KEY_PARAM
  DASHBOARD_URL DB_POOL_MAX DEMO_MAX_HOURS DEMO_REPOSITORY DEREGISTER_DEMO_RUNNERS FENVIX_ENV FENVIX_MACHINE_*
  FENVIX_RUNS_ON GITHUB_API_URL GITHUB_APP_DATABASE_URL GITHUB_APP_ID GITHUB_APP_PRIVATE_KEY(_FILE) GITHUB_APP_SLUG
  GITHUB_CLIENT_ID GITHUB_CLIENT_SECRET GITHUB_OAUTH_URL GITHUB_TIMEOUT_MS GITHUB_WEBHOOK_SECRET GITHUB_WEB_URL HOST
  LOG_LEVEL NODE_ENV ONBOARDING_BRANCH ONBOARD_ALL_REPOSITORIES OVERFLOW_BUCKET PORT REAP RUNNER_LAUNCH_TEMPLATE_ID
  RUNNER_MAX_RUNNING RUNNER_MODE RUNNER_PLACEMENT RUNNER_TOKEN RUNNER_TOKEN_PREVIOUS SECRETS_TTL_SECONDS SSM_PREFIX
  STATE_SIGNING_KEY SUMMARY_WAIT_SECONDS SUPABASE_JWKS_URL SUPABASE_URL SWEEP_SECONDS WARMUP_* (11) WORK_LOG
  WORK_QUEUE_URL. `github-app/.env.example` names 14 of them (APP1-126).
- A missing variable: the node server prints `Configuration error: <NAME> is required` (never a value) and exits 1
  (`server.ts:5-10`); a Lambda throws at cold start and tries again on the next call (`runtime.ts:81-104`); a missing SSM
  parameter is named (`secrets.ts:58-62`). With `GITHUB_APP_ID` empty (the deployed state) every App route answers
  `503 github_not_configured`, `/healthz` says `github: not_configured`, the worker leaves messages for the dead-letter
  queue, and the dashboard API's GitHub operations answer 503 while the rest works. URLs must be https in production;
  secrets have minimum lengths (webhook secret 20, state key and runner token 32); the App key must be RSA.

## 7. Evidence appendix (commands and trimmed real output)

### APP1-001, -002, -003, -004, -012 (no client of the runner API; no warm-up executor)

```
$ cd /home/user/fenvix-engine-cli && git grep -n "v1/runner" origin/claude/release-1
(no output)
$ for b in $(git branch -r | grep -v HEAD); do n=$(git grep -c "v1/runner" $b | wc -l); [ "$n" != 0 ] && echo "$b $n"; done
(no output; 62 remote branches)
$ for b in $(git branch -r | grep -v HEAD); do git ls-tree -r --name-only $b | grep -q "runner/warmup" && echo $b; done
(no output)
$ cd /home/user/fenvix-app && grep -rln "runner/results\|runner/progress\|runner/explorations" --exclude-dir=node_modules .
./src/api/schema.d.ts ./github-app/src/api/openapi.gen.ts ./github-app/src/service.ts ./github-app/src/work.ts
./github-app/src/app.ts ./github-app/README.md ./github-app/tests/integration/{warmup,review-r016,review-r016b,connect-flow}.test.ts
./openapi/fenvix-api.yaml ./docs/{REPORT-dashboard-wiring-3,REPORT-dashboard-wiring,REPORT-warm-cache-install-3,GITHUB-APP,data-contract}.md
$ grep -n "runner/\|URL" infra/github-app/lib/runner/files/*   # senders: fenvix-summary-poster (summaries), fenvix-warmup-report (warmups)
```

### APP1-007 (image pins another engine)

```
$ git -C /home/user/fenvix-engine-cli log -1 --format='%H %ad %s' --date=iso a20b93d7f840b23f71c73c03efdaee3d6a233252
a20b93d7... 2026-11-18 14:31:07 +0000 R-008c: REPORT-4 (...)
$ git merge-base --is-ancestor a20b93d7... origin/claude/release-1 && echo ancestor || echo "NOT ancestor of release-1"
NOT ancestor of release-1
$ git branch -r --contains a20b93d7...   # all-runners, audit-reruns, node-cache-proof, review-r008d, review-r013, ..., shared-cache
```

### APP1-011, -013 (machine settings nobody reads)

```
$ cd /home/user/audit/engine && grep -rn "FENVIX_MODE" . | grep -v "^./target\|^./.git/"
(no output)
$ grep -rn "FENVIX_MODE\|FENVIX_REGION\|FENVIX_CACHE_ACCESS\|FENVIX_MACHINE\b\|FENVIX_KIND\|shadow" runner/ release/ python/detpy
python/detpy/_proof.py:477 ... (the word "shadow" in a comment about sys.path) ; python/detpy/distid.py:157 (same)
```

### Probes (my test file `work/APP1/app/github-app/tests/audit/probe.test.ts`, the repository's own harness, fake GitHub, scratch database; full output `work/APP1/probe.log`)

Probe A (APP1-025, -027..033, -036): one signed delivery per event.

```
check_run.rerequested: 202 {"ok":true,"ignored":"check_run"}      check_suite.rerequested: 202 {"ok":true,"ignored":"check_suite"}
workflow_run.completed: 202 ignored     repository.renamed|deleted|transferred|archived: 202 ignored
installation_target.renamed: 202 ignored     marketplace_purchase.purchased: 202 ignored
member.removed: 202 ignored     organization.member_removed: 202 ignored     github_app_authorization.revoked: 202 ignored
merge_group.checks_requested, issue_comment.created, delete, create, public, meta.deleted: 202 ignored
deliveries_recorded_for_ignored_events: 0
```

Probe B/C (APP1-002, -011, -014, -017, -018, -019, -020, -023, -024, -084): one pull request, two fenvix jobs of the
same run; job 601 "test (3.12)" sends the fixture summary with one flaky test, job 602 "test (3.13)" the all-pass one.

```
after job 601: comments = 1
<!-- fenvix:run-summary -->
### ❌ fenvix · 0 of 56 tests skipped with proof · under 0.1 min (0.0 s) saved · 1 failed (1 flaky, reproducible)
| Skipped with proof | **0** ([receipts](https://app.fenvix.test/projects/<id>/runs/<id>)) |
### Flaky tests, explained
Each failed in the suite and passed when run alone: another test leaves state behind (order-dependent). ...
- `tests/test_cart.py::test_default_currency_is_eur`
  - replay: `python -m pytest --det --det-urandom -p no:cacheprovider -q -rN --tb=short  # whole suite, same order: fails again`
  - find the test that breaks it: `detpy repro tests/test_cart.py::test_default_currency_is_eur --seed fixed`
<sub>CI / test (3.12) · commit `1111111` · Check run · Run on fenvix · Job log · this comment is updated on every run</sub>

after job 602: comments = 1
### ✅ fenvix · 46 of 56 tests skipped with proof · under 0.1 min (0.2 s) saved · no failures
<sub>CI / test (3.13) · ...</sub>

check_runs: [{"name":"fenvix","conclusion":"failure",...,"annotations":null,"actions":null},
             {"name":"fenvix","conclusion":"success",...,"annotations":null,"actions":null}]
check text (flaky job): "... Engine: detpy 0.1.0."
ci_defects rows: 0      ci_test_results rows: 0
ci_runs: [{"number":1,"status":"failed","tests_total":56,"tests_failed":1,"tests_flaky_defects":1,"mode":"shadow"},
          {"number":2,"status":"passed","tests_total":56,"tests_failed":0,"tests_flaky_defects":0,"mode":"shadow"}]
```

(The organization is in its trial, so the App records `shadow`; the second summary reused 46 of 56 tests.)

Probe E (APP1-006): a fenvix job that never posts a summary, then the sweep.

```
check: {"conclusion":"neutral","title":"No fenvix summary: the job ended before the tests reported", ...}
usage_event: [{"billable":true,"reason":"no_summary","test_minutes_ran":0, ...}]   run_row: [{"status":"passed","tests_total":0,"mode":"shadow"}]
```

Probe F (APP1-121): `installation.deleted`.

```
before: {"runs":3,"projects":1,"usage":3,"summaries":2}
after:  {"runs":3,"projects":1,"usage":3,"summaries":2,"marked_deleted":true,"still_linked":true}
```

Probe G (APP1-035): the same signed `installation.created` body under delivery ids replay-1, replay-1, replay-2, sent
after the uninstall of probe F.

```
statuses: [202,202,202]   deliveries: replay-1 processed, replay-2 processed   gh_installations.deleted_at: null
```

Probe H (APP1-050, -051, -058): `analyzeWorkflow` + `chooseTestJob` on a one-job workflow named `test`.

```
./gradlew test | mvn -B verify | mvn test | gradle check | ./mvnw test | sbt test | bazel test //... : choice=change language=null runner=null
npx playwright test | npx cypress run | npx mocha | node --test | deno test | nx test | turbo run test : choice=change language=null runner=null
cargo test | dotnet test | bundle exec rspec | phpunit | ginkgo -r | gotestsum ./... | make test      : choice=change language=null runner=null
bun test: language=node runner=null     npm test: language=node runner=null     python -m unittest: language=python runner=null
go test ./...: go / go test     pytest -n auto, tox -e py312: python / pytest     npx jest: node / jest     npx vitest run, pnpm exec vitest: node / vitest
```

### Grep-based entries

```
APP1-062/-089/-115: grep -rn "nightly_exploration\b|skip_with_proof|test_command" github-app/src (without openapi.gen.ts) => github-app/src/api/data.ts:117-121 only
APP1-068: grep for 'fixed' in github-app/src and supabase/migrations (without the column check) => github-app/src/api/data.ts:299 only
APP1-088: grep -rn explor infra/github-app/lib/*.ts infra/github-app/lib/runner/files github-app/src/{warmup,runners,lambda} => one comment (runners/credentials.ts:23)
APP1-098: grep -rniE 'stripe|paddle|invoice' github-app/src github-app/package.json => no match
APP1-103: grep -rn "baseline_median|baseline_runs_sampled" github-app/src => no match
APP1-105: grep -rli license github-app/src supabase/migrations/001[1-7]* => openapi.gen.ts only (info.license)
APP1-118: grep -rniE 'slack|hooks\.' github-app/src => no match
APP1-034/-043: grep -rn "hook/deliveries|x-ratelimit" github-app/src => no match
APP1-045..047: grep -rliE 'circleci|jenkins|buildkite|azure|gitlab|bitbucket' github-app/src openapi supabase/migrations => no file
APP1-039: git ls-files | grep -i manifest => nothing
APP1-122: grep -rn "workspace_id = null|set workspace_id" github-app/src supabase/migrations/001[3-7]* => only the two link functions (0013:243, 0014:480)
```

## 8. Could not check

- **Anything against real GitHub**: the App does not exist (no App id in the deploy settings) and I have no
  installation to test with. Whether GitHub accepts the just-in-time runner call with the documented permission set,
  how the check run and comment render, and whether `Request user authorization during installation` sends the browser
  to `/github/setup` as the document says: UNKNOWN.
- **The live deployment** (`github.fenvix.dev`): I did not call it (audit only, no outside traffic). Whether the
  gateway throttle, the 6 MB limits and the CORS behaviour are as the code and AWS documents say: READ only.
- **A real runner machine**: no AWS access. Job start latency per machine, whether the idle watchdog and reaper work,
  whether the image builds from the pinned commit today: UNKNOWN. The image scripts were read, not run.
- **Real Supabase Auth**: Docker cannot run here, so the two API suites ran against my stand-in (section 5). Whether
  the production project signs with ES256 (APP1-129) is UNKNOWN.
- **Sizes behind APP1-015 and APP1-073** are ESTIMATED (about 80 bytes per test in `outcomes`, about 1 KB per run row),
  not measured on a large suite.
- **`origin/claude/dashboard-vercel`** (2 commits ahead of main): read only as a diff stat; it adds a CORS unit test
  and a switch for the AWS dashboard stack, and changes nothing under `github-app/src`.
- **The dashboard pages** (what each screen does with empty data) and **the deploy pipeline** are other agents' areas;
  I read them only where the API contract needed it.
- Whether the other language shells in release-1 (detjs, fenvix-go, the JVM agent) can write a `summary.json` of the
  shape the service parses was not tested: nothing would send it (APP1-008..010), and the parser needs `tests`,
  `reused_with_proof` and, for a project to exist, `language`/`test_runner` or a `detpy==`/`detjs@` distribution.

## 9. Contradictions between documents and code

- `github-app/src/onboarding/onboard.ts:34` (the text customers read in the pull request): "The tests run on a fenvix
  machine, inside the fenvix engine". False for an unchanged workflow (APP1-005).
- `docs/data-contract.md:374-376`: "`runner/fenvix-run`, which wraps the job's test command in the engine (`detpy` for
  Python/pytest, `detjs` for Node vitest/jest). It sends four kinds of records to the App". fenvix-run wraps nothing by
  itself, runs pytest only, and sends nothing; one record kind is sent, by another script (APP1-002..005, -008).
- `docs/data-contract.md` "What the machine receives": "The runner runs the engine in that mode" (FENVIX_MODE). Nothing
  reads it (APP1-011).
- `docs/GITHUB-APP.md:1-36` describes points 4 to 7 (results, progress, explorations, trial) in the present tense; the
  sending half does not exist.
- brain `DECISIONS.md` 2026-11-18 pricing (units = baseline test minutes) versus `0015_review_r016.sql:171-172`
  (units = held machine minutes) (APP1-102).
- brain `DECISIONS.md` 2026-11-18 "customer runners on phoenixNAP from the first customer, each job in its own
  Firecracker microVM" versus an EC2-instance-per-job launcher (APP1-109, -110).
- brain `DECISIONS.md` 2026-11-18 "a US customer's code and data stay in the US" versus `cdk.json` (fleet in eu-west-1
  named "us") (APP1-112).
- brain `PRODUCT.md` "How it is delivered" still says "We do not sell runners; runner vendors are channels", replaced by
  `DECISIONS.md` 2026-11-17; the service follows the decision, the promise in the audit brief follows PRODUCT.md
  (APP1-048).
- `github-app/tests/fixtures/runner/README.md`: the fixtures come from engine branch `claude/runner-prototype-ee21he`,
  commit 03a8613; the image pins `a20b93d7`; release-1 is `529c160`. Three engine versions are in play.
