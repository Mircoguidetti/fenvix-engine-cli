# fenvix-app: how to apply `app.patch`

**R-013 update (REPORT-2.md):** commit 2 now vendors the service of engine commit `49f0bd5`
(SHA-256 `1e624a663ee5afcefb66eaec45c9188041b3b45710412b80c5d629f4fed4eea4`): marks with `seq` and `?after=`,
`GET /v1/audit` counting every token's wrong skips (its `test/cache.test.ts` expectation changed accordingly:
`checked 1, wrong 1, checked_without_summary 1` after the read-only mark). Commit 1 is unchanged. This session could
not reach `fenvix-app` (the session's GitHub proxy refuses the repository; attaching it was out of scope), so commit 2
was regenerated from the patch text: the vendored file's diff from its known base (`1ad68b4`, engine `9ec28a4`)
reproduces the engine file byte for byte (checked), the other hunks keep their context. **The app suites were not
re-run on it**, and the post-image `index` hash of `test/cache.test.ts` is the old one (only `git am --3way` reads
index lines, and it reads the pre-image, which is unchanged).

`app.patch` holds two commits for `Mircoguidetti/fenvix-app`, branch `claude/github-app`, made on top of
**`44d2a331fd000f172c8f3f67d4701024f08b6efd`** (Review R-012 fixes (docs)), the branch head when this session finished.
Another session was editing that branch, so nothing was pushed there.

| # | commit (in this session's clone) | what | apply when |
|---|---|---|---|
| 1 | `53847c7` Cache audit: summary audit block, wrong-skip alert... | App parses `summary.json` → `audit`, stores the counts on `ci_runs`, one `ci_audit_alerts` row and one ERROR log line per wrong skip, check run and PR comment rows, dashboard (overview card with the per-project and all-project bound and the open alerts, run page fact), migration `0014_cache_audit.sql` with its RLS test, data contract | now |
| 2 | `2f0f02a` Shared cache service: vendor the engine's cache audit version... | `infra/github-app/lib/cache/cache_service.py` = engine `claude/audit-reruns` `49f0bd5` (R-013 fixes) byte for byte (untrusted keys, `GET /v1/audit`), PROVENANCE, its pinned SHA-256 in `test/cache.test.ts` plus checks for marks and `/v1/audit` through the signed-token wrapper, `engineCliCommit` in `cdk.json` and `DEPLOY-AWS.md` | only after the engine branch `claude/audit-reruns` is approved (it moves the runners and the cache machine to that engine commit) |

## Apply

```bash
git clone https://github.com/Mircoguidetti/fenvix-app && cd fenvix-app
git checkout claude/github-app
git log -1 --format=%H        # 44d2a331fd000f172c8f3f67d4701024f08b6efd, or later (then see "If the branch moved")
curl -sL https://raw.githubusercontent.com/Mircoguidetti/fenvix-engine-cli/claude/audit-reruns/sessions/2026-11-18-audit-reruns/app.patch -o /tmp/app.patch
#   (or: git -C <engine checkout> show origin/claude/audit-reruns:sessions/2026-11-18-audit-reruns/app.patch > /tmp/app.patch)
git am /tmp/app.patch          # both commits
# only commit 1 for now:  git am /tmp/app.patch && git reset --hard HEAD~1
```

Checked here: on `44d2a33`, `git am` applies both commits and the resulting tree is identical to the tested one.
The patch is made with one line of context (`git format-patch -U1`) so that no unrelated line of the repository is copied
into the engine repository.

## If the branch moved

`git am --3way /tmp/app.patch`. The likely conflicts are the import block at the top of `github-app/src/service.ts`
(keep both: the branch's imports plus `type AuditSummary` in the `./results/summary.ts` import) and the end of the
second test of `infra/github-app/test/cache.test.ts` (keep the branch's block, then the cache audit block). Those were
the two conflicts when this patch was moved from `98cb03e` to `44d2a33`.

## Database

Run `supabase/migrations/0014_cache_audit.sql` in the Supabase SQL editor after 0013 (safe to repeat). The patched
App needs it for every run (the insert of a run names the new `audit_*` columns), so the order is: migration first,
then the App. The dashboard loads without it (no alerts shown; runs read as audit off).

## Tests (all run in this session on the patched `44d2a33`)

```bash
# scratch Postgres 16 on port 54329 (TEST_DATABASE_URL=postgresql://postgres@localhost:54329/gh_test)
cd github-app && npm ci && npm run db:prepare && npm test         # typecheck, 62 unit, 69 integration: pass
cd ../infra/github-app && npm ci && npm test                      # typecheck, 52: pass (commit 2)
cd ../.. && npm ci && npx tsc --noEmit && npm run test:unit && npm run build   # 58 unit: pass, build ok
TEST_DATABASE_URL=postgresql://postgres@localhost:54329/rls_scratch npm run test:rls   # ... GH RLS OK, AUDIT RLS OK
```

New tests:

* `github-app/tests/unit/results.test.ts`: reads the audit of a real runner summary
  (`tests/fixtures/runner/job4-audit-wrong-skip.summary.json`, written by this branch's `fenvix-run`: 12 tests, audit
  25%, seed `fixture-seed`, 5 checked, 1 wrong planted skip); refuses audits that do not add up or claim more checks
  than tests that ran; the check run and the comment show the audit; a wrong skip alone does not fail the check.
* `github-app/tests/integration/results.test.ts` "a wrong skip found by the cache audit": the ERROR line
  (`alert: "cache_audit_wrong_skip"`, test, cached, fresh, key), the `ci_audit_alerts` row, the run's audit columns,
  `tests_skipped` = 7 (reused only, the 5 audited tests are in `tests_ran`), the usage event's minutes saved = the reused
  tests' only, no second alert for the same job.
* `supabase/tests/audit-rls.sql`: members read only their organization's alerts and write none; the App writes only for
  the organization it acts for and cannot change an alert; anon reads nothing; the audit counts must add up and
  cannot exceed the tests that ran.
* `tests/unit/ci.test.ts`: the bound (rule of three, Clopper-Pearson, same values as the engine core), per-project and
  all-project totals for this month, only open alerts on the overview, a run's audit from its row (and audit off for
  rows from before 0014).
* `infra/github-app/test/cache.test.ts` (commit 2): a pull request's read-only signed token marks a key untrusted in
  its own organization, another customer sees no mark, `GET /v1/audit` answers.

Paging on the ERROR line is not configured (as the prompt says: later).
