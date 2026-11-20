# APP2 notes: data, infrastructure, deploy, security and operations of the service (fenvix-app)

Agent `APP2`. Gaps: `/home/user/audit/findings/APP2.gaps.jsonl` (167 entries, `APP2-001` to `APP2-167`). Scratch:
`/home/user/audit/work/APP2/` (logs named below are there; the batch files that generate the JSONL are in
`gaps/`). No matrix: this area owns no matrix cells.

## 0. What the lead should know first

1. **`main` of fenvix-app moved during the audit.** It was `ce69a6b` when the audit started and was fast-forwarded to
   `c59d913` at 08:34:35 UTC (`git reflog`: "merge origin/main: Fast-forward"; PR #19 = the two commits of
   `claude/dashboard-vercel`). Every finding is written against **`main` at `c59d913`**: the dashboard is on Vercel and
   the AWS dashboard stack is behind the switch `FENVIX_DASHBOARD_ON_AWS` (off). The task text ("`dashboard-vercel`, 2
   commits ahead") is therefore out of date: that branch is merged. Tests were run on both commits (section 4).
2. **The hosted service does not deliver the paid part of the promise today.** Read together: APP2-039, 040, 041, 043,
   044, 045 (the machines run a Python-only engine from an old pinned commit, nothing wraps the customer's test
   command, shadow mode and per-test results have no sender, exploration does not exist) and APP2-125 to 131 (nobody
   can pay, choose a plan or be limited). The dashboard, API and database are built for records that no component
   produces.
3. **Contradictions between decisions and code** (each is an entry):
   - Region: decision "US customer's code and data stay in the US"; code deploys one fleet in `eu-west-1` and labels it
     `us`; `eu` has no fleet (APP2-035, 036, 037, 100).
   - Trial gate: decision "our machine-minutes at or under 35% of baseline"; code "would have skipped at least 35% of
     test time" (APP2-132).
   - Run unit: decision "10 baseline test minutes, fixed per repository"; code "minutes the machine was held / 10 per
     job" (APP2-134, DECIDE).
   - Runners: decision "customer runners on phoenixNAP from the first customer, each job in its own Firecracker
     microVM"; main has per-job EC2 machines and a spike that never ran (APP2-047, 048, 097).
   - Pricing page of the landing: plans by number of runs, exploration included; decision and database: run units,
     Monorepo plan, exploration as an add-on (APP2-141).
4. **Claims found false** on the landing `/security` page (fenvix-landing `content/security.md`,
   `security/index.html`): API keys exist (APP2-104); the App is least privilege / reads-only list (APP2-105); "never
   pushes to a branch" (APP2-106); "defect bundles with traces" are kept (APP2-107); skip receipts "Today" (APP2-108);
   retention "set per plan" (APP2-109). The sign-in page links Terms and Privacy pages that do not exist, on
   `fenvix.com` (APP2-101).
5. **Two security holes in the shared cache** (same installation, different repositories): read by pull-request code
   (APP2-092) and write by another repository's default-branch job (APP2-093). Both follow from the token carrying
   only `org` and `w`, and the namespace being a URL segment.
6. **What is sound** (checked, no gap): the browser roles `anon`/`authenticated` have no right on any table (RAN);
   the API connects as `fenvix_api` (no BYPASSRLS), never with the service-role key (`grep service_role` finds only
   the deploy's check that the anon key is not one); a signed-in user of organization A reads 0 rows of organization
   B through `fenvix_api` (RAN); every `security definer` function sets `search_path = public, pg_temp`; IAM policies
   have no `Action: *` and every `Resource: *` is either a Describe/List call or carries a condition; the deploy role
   is trusted only for `deploy.yml` on `refs/heads/main` by immutable ids; production npm dependencies have 0 known
   vulnerabilities (RAN).

## 1. Could not check

| What | Why |
|---|---|
| The real AWS account: what is deployed, the CloudFront hold, whether a runner image exists, the alarm's e-mail, real Lambda cold starts, real job start time | no AWS credentials here; everything about AWS is from code, config and the repository's reports (marked READ or DOC) |
| The real Supabase project: its region, plan, backups/PITR, auth providers actually enabled, redirect URLs, SMTP, automatic account linking, JWT expiry, default privileges of `supabase_admin` | settings of the Supabase dashboard, not in any repository (APP2-032, 122, 151) |
| The Vercel project: environment variables per environment, the Hobby plan, whether production builds wait for checks | Vercel dashboard only; taken from `docs/DEPLOY-VERCEL.md` (DOC) |
| Whether `https://fenvix.com/terms` and `/privacy` exist | `curl` through the proxy returned no answer (`fenvix.com/terms -> 000`); the gap rests on the repositories having no such pages and on the domain being `fenvix.com`, not `fenvix.dev` |
| github-app integration tests (`npm run test:integration`), `scripts/local-supabase/up.sh`, `scripts/e2e-real-api.mjs` | need Docker (Supabase Postgres image + GoTrue); `docker ps` => "failed to connect to the docker API ... no such file or directory" |
| `deploy/test/database.test.mjs` case "migrations on the local Supabase" | skipped by the suite itself (no local Supabase, same Docker reason): the 1 skipped test in section 4 |
| actionlint, cfn-lint (`infra/bootstrap/lint.py`, `cfn-handler-permissions.py --check`) | run in CI through Docker / a pip venv; not re-run here (cfn-lint install not attempted, Docker absent) |
| Whether release-1's fingerprints and cache keys still fit the schema's `^[0-9a-f]{32}$` checks (`ci_defects.fingerprint`, `ci_skip_receipts.cache_key`, `ci_audit_reruns.cache_key`) | no sender exists to exercise it (APP2-044); not traced in the engine code. Suspected gap, not proven |
| Size of a real `summary.json` for a large suite against the 6 MB Lambda limit (APP2-057) | the fixture summaries are small; no large one was produced |
| Whether a forged cache entry written into another repository's namespace is actually reused by the engine (APP2-093) | proven: the write is accepted by the service (code path). Not run end to end with the engine client |
| phoenixNAP provisioning code on `origin/claude/customer-mode-pnap` | read its file list and report headings only; never run against the real API by anyone (no API keys: NOW.md) |
| GitHub's real behaviour: branch rules on GitHub Free, `job_workflow_ref` claim | recorded as UNKNOWN/DOCUMENTED by the repository's own reports |

## 2. Database: every table, row level security, policies, grants

RAN on PostgreSQL 16.15 (scratch cluster on port 55442) after `supabase/tests/local-stub.sql` and all 16 migrations
(`0001`-`0013` once, `0014`-`0017` twice): `select relname, relrowsecurity, relforcerowsecurity from pg_class`,
`pg_policies`, `information_schema.role_table_grants`, `column_privileges`.

**RLS is enabled on all 25 tables; FORCE is on none** (the owner, i.e. the migrating/admin role, bypasses it:
APP2-021). `anon` and `authenticated` have 0 table grants. One table has RLS and no policy (`ci_trial_accounts`,
APP2-022). No Supabase Storage bucket is used (APP2-001, 002, 162).

| Table | RLS | Policies for `fenvix_api` (dashboard API; `app.user_id` + `app.workspace_id`) | Policies for `fenvix_github_app` (the App; names the org itself) | Grants |
|---|---|---|---|---|
| `workspaces` | on | SELECT own organizations (`id in api_my_workspace_ids()`); UPDATE as owner/admin (`id = api_admin_workspace()`) | SELECT `id = cp_workspace()` (columns id, region) | api: SELECT, UPDATE(name, name_confirmed, region, email_notices). **Nobody: INSERT/DELETE** (APP2-015) |
| `workspace_members` | on | SELECT own row or the request's org; UPDATE: owner any, admin only rows with role member and not self; DELETE: owner any, admin members, anyone self | none | api: SELECT, DELETE, UPDATE(role) |
| `workspace_invites` | on | SELECT as admin; INSERT/UPDATE: owner any, admin only role member | none | api: SELECT, INSERT, UPDATE(revoked_at, revoked_by) |
| `ci_plans` | on | SELECT true | SELECT true | SELECT both |
| `ci_reference_rates` | on | SELECT true | none | api: SELECT |
| `ci_subscriptions` | on | SELECT `workspace_id = api_workspace()` | ALL `workspace_id = cp_workspace()` | api: SELECT; app: SELECT, INSERT, UPDATE |
| `ci_projects` | on | SELECT member; UPDATE as owner/admin (4 columns) | ALL `= cp_workspace()` | api: SELECT, UPDATE(skip_with_proof, comment_on_pull_requests, nightly_exploration, test_command); app: S/I/U. No DELETE (APP2-016) |
| `ci_runs` | on | SELECT member | ALL `= cp_workspace()` | api: SELECT; app: S/I/U |
| `ci_test_results` | on | SELECT member | ALL `= cp_workspace()` | api: SELECT; app: S/I/U |
| `ci_skip_receipts` | on | SELECT member | ALL `= cp_workspace()` | api: SELECT; app: S/I/U |
| `ci_defects` | on | SELECT member (no UPDATE: APP2-014) | ALL `= cp_workspace()` | api: SELECT; app: S/I/U |
| `ci_audit_reruns` | on | SELECT member | ALL `= cp_workspace()` | api: SELECT; app: S/I/U |
| `ci_explorations` | on | SELECT member | ALL `= cp_workspace()` | api: SELECT; app: S/I/U/D |
| `ci_usage_events` | on | SELECT member | ALL `workspace_id is not distinct from cp_workspace()` | api: SELECT; app: S/I/U |
| `ci_trial_accounts` | on | **none** | **none** | **none** (only inside `gh_link_installation`, security definer) |
| `gh_installations` | on | SELECT member | ALL `true` | api: SELECT; app: S/I/U |
| `gh_repositories` | on | SELECT member | ALL `true` | api: SELECT; app: S/I/U |
| `gh_warmups` | on | SELECT member | ALL `true` | api: SELECT; app: S/I/U |
| `gh_jobs` | on | none | ALL `true` | app: S/I/U |
| `gh_pull_requests` | on | none | ALL `true` | app: S/I/U |
| `gh_pushes` | on | none | ALL `true` | app: S/I/U |
| `gh_run_results` | on | none | ALL `true` | app: S/I/U/D |
| `gh_run_summaries` | on | none | ALL `true` | app: S/I/U/D |
| `gh_webhook_deliveries` | on | none | ALL `true` | app: S/I/U/D |
| `gh_install_completions` | on | none (reached through `api_complete_github_link`) | ALL `true` | app: S/I/D |

Can a signed-in user of organization A touch rows of organization B? **Through `fenvix_api`: no** (RAN, T3 below:
0 rows read, `UPDATE 0`, DELETE refused). **Through the App's role: the App can**, because it names the organization
itself and nine `gh_*` tables are `using (true)`; that is by design for a service role and means RLS is no second
barrier on the writer path (APP2-020).

`security definer` functions (all with `search_path=public, pg_temp`): `is_workspace_member`, `my_workspace_ids`,
`my_admin_workspace_ids` (execute: service_role only; leftovers of the PostgREST era), `ensure_workspace`,
`handle_new_user`, `keep_one_owner`, `ci_workspace_from_parent`, `gh_workspace_from_installation`,
`gh_link_installation`, `gh_is_admin` (execute: fenvix_github_app), `api_workspace`, `api_admin_workspace`,
`api_owner_workspace`, `api_my_workspace_ids`, `api_members`, `api_me`, `api_create_organization`,
`api_accept_invitation`, `api_complete_github_link` (execute: fenvix_api). Not definer: `cp_workspace`, `api_user`,
`ci_touch_updated_at`. `handle_new_user` and `ci_touch_updated_at` are executable by PUBLIC but are trigger functions
(cannot be called directly).

Foreign keys and what is left behind: deleting a workspace cascades to members, invites, subscriptions, projects,
runs, results, receipts, defects, audit reruns, explorations, usage events, completions and warm-ups, and sets
`gh_installations.workspace_id`, `gh_repositories.workspace_id`, `ci_trial_accounts.workspace_id` to null; but nobody
can delete a workspace (APP2-015). Deleting an installation is blocked by `ci_usage_events.installation_id` (no ON
DELETE) and no role may do it (APP2-018, 019). Deleting an auth user cascades only to `workspace_members` (APP2-017).

What the promise needs and has no table: traces/fingerprint chains (001), replay bundles (002), API keys (003), audit
log (004), invoices/payment (005), exploration schedules (006), machines (007), cache entries (008). Present: runs,
tests, receipts, defects, explorations (results), usage events, plans, subscriptions (trial dates), organizations,
members, invitations, installations, repositories, jobs.

## 3. Infrastructure as code: what exists (fenvix-app `infra/github-app`, `main` c59d913)

| Resource | Where | Notes |
|---|---|---|
| API Gateway HTTP API + custom domain `github.fenvix.dev` (ACM, TLS 1.2), stage throttle 50 rps / burst 100, access logs | `lib/stack.ts:311-337` | execute-api endpoint off; `/v1/{proxy+}` -> dashboard API Lambda, `/v1/runner/{proxy+}` and default -> HTTP Lambda |
| Lambda (Node 22, x86_64): `http` 29 s/512 MB, `api` 29 s/512 MB, `worker` 120 s/512 MB (SQS batch 5, max concurrency 2), `sweep` 300 s (every minute), `warmup` 120 s (every minute, per-job), `reaper` 120 s (every 10 minutes), `demo` 180 s (demo mode only) | `lib/stack.ts:136-308` | no reserved/provisioned concurrency, no versions/aliases, scheduler retries 0 |
| SQS work queue (visibility 720 s, retention 4 days) + dead-letter queue (after 5 receives, 14 days) | `lib/stack.ts:73-79` | one alarm on the DLQ; SNS e-mail only if `alarmEmail` set |
| S3 overflow bucket (`work/`, 5-day expiry, SSE-S3, not versioned) | `lib/stack.ts:80-85` | no DynamoDB anywhere |
| EC2: VPC 10.42.0.0/24, one public subnet in `<region>a`, runner security group (egress 443/80 + cache), launch template (c6i.large, 30 GB gp3 encrypted, IMDSv2 hop 1, shutdown = terminate), Image Builder pipeline (Ubuntu 24.04 + install.sh) | `lib/network.ts`, `lib/runner-fleet.ts` | per-job machines, max 4 running; job role has no permission |
| EC2 cache machine t4g.nano, 8 GB, private IP 10.42.0.10, no public address, no outbound | `lib/cache.ts` | per-job mode only |
| S3 + CloudFront dashboard stack | `lib/dashboard.ts`, `lib/app.ts` | **behind `dashboardOnAws` (off)**: the dashboard is on Vercel |
| IAM: GitHub OIDC provider, deploy role `fenvix-github-deployer` (trust: sub by ids, repository_id, job_workflow_ref), permissions boundary, CDK deploy/publish/CloudFormation-exec roles, assets bucket | `infra/bootstrap/fenvix-bootstrap.json` (built by `build.mjs`) | created once by hand in the console; asserts account + `eu-west-1` |
| Firecracker hosts | `infra/customer-mode/spike/` | scripts for one job on one c7i; "Nothing here has run on a real host yet" |

Region: `eu-west-1` only. Switches: `dashboardOnAws` (off), `runnerMode` (`per-job` default, `demo`), `warmupEnabled`
(true), the GitHub App "configured or not" (three ids), second region settings (empty). Demo-only: the `demo`
function, `scripts/demo-up.sh`/`demo-down.sh`, reaper deregistration.

Secrets required and where each is documented (`docs/DEPLOY-AWS.md` sections A, C, D; `infra/github-app/lib/parameters.ts`;
`deploy/lib/bootstrap.mjs`):

| Name | Type | Set by |
|---|---|---|
| `/fenvix/prod/bootstrap/supabase-db-url` | SecureString | founder (Supabase admin connection, session pooler) |
| `/fenvix/prod/bootstrap/supabase-anon-key`, `supabase-ca-cert` (optional), `github-app-id`, `github-app-slug`, `github-app-client-id` | String | founder |
| `/fenvix/prod/bootstrap/cloudflare-api-token` (optional) | SecureString | founder |
| `/fenvix/prod/github-app/private-key`, `client-secret` | SecureString | founder (section C4) |
| `/fenvix/prod/github-app/database-url`, `api-database-url` | SecureString | pipeline (`deploy/lib/roles.mjs`) |
| `/fenvix/prod/github-app/webhook-secret`, `state-signing-key`, `runner-token` (`runner-token-previous` during rotation) | SecureString | pipeline (`deploy/lib/secrets.mjs`) |
| `/fenvix/prod/cache/signing-key` (SecureString), `signing-public-key` (String) | | pipeline |
| GitHub repository variables: `CLOUDFLARE_ZONE_ID`, `FENVIX_ALARM_EMAIL`, `FENVIX_RUNNER_MODE`, `FENVIX_DEMO_REPOSITORY`, `FENVIX_DASHBOARD_ON_AWS` | not secret | founder |
| Vercel: `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (public), `VITE_DATA_BACKEND=mock` for Preview | public | founder (`docs/DEPLOY-VERCEL.md`) |
| Supabase dashboard: Google and GitHub OAuth client secrets, SMTP credentials | secret | founder, by hand, documented only in `README.md:64-77` |

CORS of the API: `github-app/src/api/server.ts` allows the origin of `DASHBOARD_URL` (`https://console.fenvix.dev`)
plus `API_CORS_ORIGINS`; the workflow sets no extra origin, so a `*.vercel.app` address is refused (by design; previews
use mock data: APP2-072).

Sign-in and organizations, what exists:

| Feature | Schema | API | UI |
|---|---|---|---|
| GitHub / Google OAuth, e-mail magic link (Supabase Auth, PKCE) | Supabase (not in repo) | token verified by JWKS (`auth.ts`) | `src/session/supabase.ts`, `SignIn.tsx` |
| Sign-out | - | none needed (stateless JWT; APP2-116) | yes |
| Delete account | no | no | no (APP2-103) |
| Create organization (max 50 per user) | `api_create_organization` | `createOrganization` | yes |
| Invite by e-mail (link only, 7 days, 20/day, verified e-mail must match) | `workspace_invites` | create / list / revoke / accept | yes; **no e-mail sent** (APP2-117) |
| Roles owner / admin / member, change role, remove member, leave, last owner kept | `workspace_members`, `keep_one_owner` | yes | yes |
| Transfer ownership | via two role changes | no single operation (APP2-120) | via role select |
| Delete organization | no | no | no (APP2-015) |
| Link organization to a GitHub installation (signed state, OAuth check, single-use completion) | `gh_install_completions`, `gh_link_installation` | install-link / complete | `Connect.tsx` |
| Unlink / move an installation | no | no | no (APP2-119) |
| API keys | dropped | no | "Coming soon" (APP2-003) |

## 4. Tests run here (commands and trimmed real output)

All in scratch copies; nothing in `/home/user/fenvix-app` was changed.

```
# Row level security + migrations (ce69a6b tree; the migrations and tests are identical at c59d913)
$ TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55442/fenvix_scratch bash supabase/tests/run-local.sh
1/3 local stand-ins for Supabase
2/3 migrations: 0001 to 0013 once, then 0014 to 0017 twice each
3/3 row level security
     API RLS OK
     CI RLS OK
     CI EXPLORE RLS OK
     GH RLS OK
     WARM RLS OK
done: migrations and the dashboard API's, the CI tables' and the GitHub App's row level security pass

# Infrastructure tests (CDK synth, cdk-nag, policies), infra/github-app: npm test
ce69a6b: tests 135, pass 135, fail 0, skipped 0, EXIT 0      (infra-test.log)
c59d913: tests 141, pass 141, fail 0, skipped 0, EXIT 0      (infra-test-c59d913.log)

# Deploy tests, deploy: FENVIX_DEPLOY_TEST_DB=postgresql://postgres@127.0.0.1:55442/postgres npm test
ce69a6b (copy without .git): tests 67, pass 65, fail 1, skipped 1   (deploy-test2.log)
   the 1 failure is an artifact of my copy: pipeline-2.test.mjs:71 runs `git grep` and the copy had no .git
   ("app.fenvix.dev still in: 128 !== 1"); the 1 skip is the local-Supabase case (needs Docker)
c59d913 (git clone, with .git): tests 72, pass 71, fail 0, skipped 1, EXIT 0   (deploy-test-c59d913.log)
without a database (default localhost:54329): every database suite fails with ECONNREFUSED (deploy-test.log)

# Dependency audit (scratch copy)
$ npm audit --omit=dev      # in ., github-app, infra/github-app, deploy
found 0 vulnerabilities     (x4)
$ (cd infra/github-app && npm audit)
minimatch  7.0.0 - 11.0.0  Severity: moderate ... GHSA-g3hv-75wg-m249
  node_modules/aws-cdk-lib/node_modules/minimatch
2 moderate severity vulnerabilities
```

```
# github-app unit tests at c59d913: npm run test:unit      -> tests 139, pass 139, fail 0, EXIT 0   (gh-unit-c59d913.log)
# dashboard unit tests at c59d913 (root): npm run test:unit -> tests 70, pass 70, fail 0, EXIT 0   (root-unit-c59d913.log)
# github-app integration tests: not run (need the local Supabase in Docker)
```

What is never tested against real AWS (APP2-086, 159): every CDK resource is only synthesized; the permissions
boundary and the EC2 launch conditions as AWS evaluates them; Image Builder; the per-job boot (user data ->
`fenvix-job.target` -> runner online); Scheduler targets; ACM/Cloudflare flows (fetch stubs); SSM (in-memory fake);
GitHub (in-process fake with GitHub's OpenAPI schemas); Supabase Auth and the pooler (plain Postgres or a local image).

## 5. Evidence appendix (keyed by gap id)

### APP2-009, 010, 011, 012, 014, 015, 016, 017, 018, 020, 031 (adversarial checks on the scratch database `adv`)

Schema copied with `pg_dump -s` from the fully migrated scratch database; two users inserted into `auth.users`
(the sign-up trigger gave each an organization: A and B).

```
workspaces after signup | 2                                             -- APP2-031
--- T1 language/test_runner checks
ERROR:  new row for relation "ci_projects" violates check constraint "ci_projects_language_check"      ('java','junit')
ERROR:  new row for relation "ci_projects" violates check constraint "ci_projects_language_check"      ('kotlin','gradle')
ERROR:  new row for relation "ci_projects" violates check constraint "ci_projects_test_runner_check"   ('node','playwright')
ERROR:  new row for relation "ci_projects" violates check constraint "ci_projects_test_runner_check"   ('node','node:test')
ERROR:  new row for relation "ci_projects" violates check constraint "ci_projects_test_runner_check"   ('python','unittest')
INSERT 0 1                                                                                           ('go','go test')
--- T2 defects
ERROR:  new row for relation "ci_defects" violates check constraint "ci_defects_language_check"        (language 'go')
ERROR:  new row for relation "ci_defects" violates check constraint "ci_defects_cause_check"           (cause 'async_race')
ERROR:  new row for relation "ci_defects" violates check constraint "ci_defects_fingerprint_check"     (64-hex fingerprint)
--- T3 fenvix_api as user A with app.workspace_id = B
A reads B projects | 0
UPDATE 0                                   (update public.workspaces set name='hacked' where id = B)
ERROR:  permission denied for table workspaces          (delete)
--- T4 fenvix_api as owner A in A
ERROR:  permission denied for table workspaces          (delete own organization)        -- APP2-015
ERROR:  permission denied for table ci_projects         (delete own project)             -- APP2-016
ERROR:  permission denied for table ci_defects          (update ... set state='fixed')   -- APP2-014
--- T5 fenvix_github_app
app reads B projects | 1                   (after set_config('app.workspace_id', B))     -- APP2-020
ERROR:  permission denied for table ci_projects         (delete)
ERROR:  permission denied for table gh_installations    (delete)                         -- APP2-018
ERROR:  permission denied for table ci_runs             (delete)
--- T6 delete the auth user who is the only owner
DELETE 1
orphan org still there | t | members 0 | projects 2                                      -- APP2-017
--- T7
anon/auth table grants | 0
```

### APP2-021, 022, 029, 030, 019 (catalog dumps)

`relrowsecurity = t, relforcerowsecurity = f` for all 25 tables. `ci_trial_accounts`: no row in `pg_policies`, no
grantee. Indexes (non-primary): `ci_runs (workspace_id, started_at desc)`, `(project_id, started_at desc)`,
`unique (project_id, number)`; `gh_jobs_match (repository_id, run_id, run_attempt, runner_name)`,
`gh_jobs_repo_sha (repository_id, head_sha)`; `ci_test_results (run_id, outcome)`; `gh_webhook_deliveries`: primary key
only. Foreign keys: `ci_usage_events (installation_id) REFERENCES gh_installations(installation_id)` (no ON DELETE),
`ci_usage_events (workspace_id) ... ON DELETE CASCADE`; none for `gh_install_completions.user_id`,
`gh_installations.linked_by`.

### APP2-128, 136 (plans as migrated)

```
select id, kind, price_usd_month, units_included, max_projects from public.ci_plans order by sort;
starter|plan|129.00||
team|plan|479.00||
scale|plan|1350.00||
monorepo|plan|4200.00||
nightly-exploration|addon|||
```

### APP2-039, 040, 060 (the pinned engine commit)

```
$ git -C fenvix-engine-cli log -1 --format='%H %ci %s' a20b93d7f840b23f71c73c03efdaee3d6a233252
a20b93d7... 2026-11-18 14:31:07 +0000 R-008c: REPORT-4 (start-up Popen fix, engine suite in both package sets, ...)
$ git merge-base --is-ancestor a20b93d origin/claude/release-1 && echo ANCESTOR || echo NOT-ANCESTOR
NOT-ANCESTOR
$ git rev-list --count a20b93d..origin/claude/release-1
3034
$ git ls-tree --name-only a20b93d crates/                  => crates/detpy-core crates/detpy-py
$ git ls-tree --name-only origin/claude/release-1 crates/  => detpy-core detpy-node detpy-py fenvix-go fenvix-jvm fenvix-skip
$ git merge-base --is-ancestor 8d47dcd4 a20b93d  (proof cache: review R-019c E-1/E-7/E-8/E-9, 2026-11-19)  => not an ancestor
$ git merge-base --is-ancestor 8896c363 a20b93d  (R-020 fixes: no wrong reuse from memoised state ...)     => not an ancestor
$ sha256sum infra/github-app/lib/cache/cache_service.py ; git show origin/claude/release-1:python/detpy/cache_service.py | sha256sum
2b93cd9aac59ba160bc28ae0e9c4b725b0abd29ec6784e5ed910f479eeea33a8   (both)
```

### APP2-042, 043, 044, 045 (what the engine repository does not contain, on any of its 63 remote branches)

```
$ for b in $(git branch -r | grep -v HEAD); do git ls-tree -r --name-only $b runner/ | grep -q warmup && echo "HAS warmup: $b"; done
(no output)
$ for b in ...; do git grep -l -I "runner/results" $b -- . ; done
(no output)
$ for b in ...; do git grep -q -I "FENVIX_MODE" $b -- runner && echo $b; done
(no output)
$ git grep -n -I "runner/explorations\|runner/results\|runner/progress\|runner/summaries" origin/claude/release-1
(no output)
$ git grep -n -I "FENVIX_MODE\|FENVIX_REGION" origin/claude/release-1 -- runner python crates release
(no output)
```
On the machine, the only senders are `infra/github-app/lib/runner/files/fenvix-summary-poster` (POST
`/v1/runner/summaries`) and `fenvix-warmup-report` (POST `/v1/runner/warmups`).

### APP2-048, 049 (phoenixNAP branch)

```
$ git merge-base --is-ancestor origin/claude/customer-mode-pnap main && echo MERGED || echo NOT-MERGED   => NOT-MERGED
$ git log -1 --format=%ci origin/claude/customer-mode-pnap                                               => 2026-11-18 20:22:19 +0000
$ git rev-list --count origin/claude/customer-mode-pnap..main                                            => 51 (at ce69a6b)
$ git diff main...origin/claude/customer-mode-pnap --stat | grep migrations
 supabase/migrations/0014_pnap_customer_mode.sql    |   85 +
```

### APP2-046, 135, 014, 118, 117, 125, 146, 148, 150, 151, 155 (greps that return nothing)

```
grep -rn 'skip_with_proof\|test_command' github-app/src         => only api/data.ts:117-121 (the settings update), service.ts:862-863 reads comment_on_pull_requests only
grep -rn 'baseline_median\|baseline_runs_sampled' github-app/src => (none)
grep -rn 'fixed' github-app/src (excl. openapi.gen.ts)           => api/data.ts:299 (query filter) only
grep -rn 'email_notices\|emailNotices' github-app/src            => api/orgs.ts, api/server.ts only
grep -rnwi 'sendgrid|resend|nodemailer|smtp|postmark|mailgun|SESClient|sesv2|sendEmail' (service, infra, deploy) => (none)
grep -rnwi 'stripe|paddle|lemonsqueezy|chargebee|braintree|invoice|invoices' (service, openapi, migrations 0015-0017) => (none)
grep -rnwi 'sentry|datadog|honeycomb|opentelemetry|xray|x-ray|newrelic|pagerduty|opsgenie|statuspage|budgets?|pitr|backups?' (service, infra/lib, bootstrap, deploy, .github) => (none)
grep -nwi 'sentry|budget|backup|backups|pitr|restore|status page|on-call|runbook|uptime' docs/DEPLOY-AWS.md docs/GITHUB-APP.md README.md infra/github-app/README.md
  => docs/DEPLOY-AWS.md:479 "... turn on EBS fast snapshot restore" only
grep -rn 'hook/deliveries' github-app/src                         => (none)
grep -c 'AWS::CloudTrail|AWS::Budgets|AWS::CloudWatch::Alarm|AWS::DLM|AWS::Backup|AWS::Route53::HealthCheck|AWS::Synthetics' infra/bootstrap/fenvix-bootstrap.json => 0
```

### APP2-092, 093 (cache token scope), code quoted

`infra/github-app/lib/cache/fenvix_cache_auth.py:95` `return {"org": p["org"], "write": p["w"]}` (the payload's `job`
/ `warm` fields "are for the logs"). `cache_service.py:307-313`: `if len(parts) >= 3 and parts[1] == "ns": return
"ns:" + parts[-1], "/".join(parts[2:-1])`; `:324-325` `if route == "ns:runs" and ns and _valid_ns(ns): return
self._send(200, {"runs": self.app.store.runs(tok["org"], ns)})`; `:361-367` `add_keys(org, ns, rows)`. Token minted
in `github-app/src/service.ts:548` with `{ installationId, write: trusted, exp, jobId }`; `cacheOrgOf` =
`gh-<installation id>` (`runners/credentials.ts:77-80`).

### APP2-101 (legal links)

`src/pages/SignIn.tsx:143`: `By continuing you agree to the <a href="https://fenvix.com/terms">Terms of Service</a>
and the <a href="https://fenvix.com/privacy">Privacy Policy</a>.` `find fenvix-landing -type f \( -iname "*privacy*"
-o -iname "*terms*" -o -iname "*dpa*" -o -iname "*legal*" -o -iname "*status*" \)` => only `content/security.md`,
`pages/src/security.html` matched the wider search (`*secur*`); nothing for the others.

### APP2-105 (GitHub App permissions, `docs/GITHUB-APP.md:81-89`)

Administration **Read and write**; Checks Read and write; Contents Read and write; Metadata Read-only; Pull requests
Read and write; Workflows Read and write.

### APP2-124 and section 4: see the audit output above.

## 6. Smaller observations not worth an entry

- `README.md` (root) still says the dashboard "is used for sign-in (GitHub, Google, email link)" and lists pages
  ("API keys", "Billing (plans by run units ...)") that are placeholders or read-only views; the page inventory is
  APP1's area.
- `infra/github-app/lib/stack.ts` header comment still says "runner machines ... POST .../v1/runner/summaries" only,
  which matches reality (no results sender), while `docs/data-contract.md` describes five runner endpoints.
- The landing `/security` page marks "One job per machine" as "In progress": in per-job mode that part is in fact
  built (one EC2 machine per job); what is not built is the microVM isolation the decision asks for (APP2-097).
- `infra/github-app/cdk.json` contains the AWS account id and the repository's numeric ids; they are not secrets.

## 7. Not covered (stopped on the budget limit; for another session)

Every numbered item of the brief (1-8) was worked and has entries. What was NOT done inside each item:

1. **Supabase.** Migrations 0002-0007, 0009 and 0010 (the removed database product) were skimmed by their
   statements, not read line by line (0001, 0008, 0011-0017 were read in full). `supabase/tests/*.sql` were run
   (5/5 pass) but their assertions were not reviewed line by line for missing cases. Not checked on the hosted
   project: default privileges, PostgREST exposure, storage (none is used in code).
2. **Sign-in.** Account linking between providers, session lifetime and SMTP are Supabase dashboard settings and
   were not verifiable; the dashboard's sign-in and invite screens (`src/pages`, `src/session`) were only grepped,
   not read in full (APP1's area).
3. **Billing.** Complete as far as the code goes; the dashboard's Billing/Usage pages were not read (APP1's area).
4. **Infra.** Not read in full: `infra/bootstrap/fenvix-bootstrap.json` (1,469 generated lines; `build.mjs` head and
   the five policy files were summarised by script, statement by statement), `infra/github-app/test/*.ts` (run:
   141/141 pass; not reviewed for what they fail to assert), `infra/github-app/scripts/*` except `demo-up.sh`,
   `infra/customer-mode/spike/build-guest.sh`, `guest/*`, `read-result.py`, `guest-kernel-docker-check.sh`. The
   phoenixNAP branch `origin/claude/customer-mode-pnap` (87 files) was not read, only its file list, merge state and
   report headings. `github-app/src/warmup/warmups.ts`, `runners/demo.ts`, `onboarding/onboard.ts`,
   `results/summary.ts`, `results/render.ts` were grepped, not read in full.
5. **Deploy.** `deploy/test/*.mjs` were run (71 pass, 1 skipped) but not reviewed; `docs/REVIEW-R-024*.md` and
   `docs/REPORT-deploy-pipeline*.md` were only grepped for "unknown / not verified". Not run: actionlint, cfn-lint.
6. **Monitoring and operations.** Complete from code and docs; nothing could be checked on the live account.
7. **Security.** Not done: a line-by-line review of `github-app/src/app.ts` (HTTP routes), `service.ts` (1,058
   lines; read in parts) and `github/client.ts` for injection or authorization bugs; the engine side of traces and
   cassettes (what values they contain) was not inspected, only that the service has no upload path; `npm audit`
   was run in all four packages (results in section 4).
8. **Tests for infra/deploy.** Run: infra (141/141), deploy (71 + 1 skipped), github-app unit (139/139), dashboard
   unit (70/70), RLS (5/5). Not run: github-app integration tests and everything that needs Docker (local Supabase).

Suspected, not proven (candidates for entries): the schema's 32-hex checks against release-1's fingerprint and key
formats; a summary.json over 6 MB on a large suite; expired invitations and `gh_pushes`/`gh_pull_requests` rows of
removed repositories never cleaned (covered in general by APP2-027).
