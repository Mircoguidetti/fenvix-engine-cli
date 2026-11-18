PARTIAL

# P-025 · Self-check in production: audit reruns of skipped tests

Session 2026-11-18. Engine: `fenvix-engine-cli` branch `claude/audit-reruns` (from `claude/shared-cache` @ `9ec28a4`).
App: `sessions/2026-11-18-audit-reruns/app.patch` on this branch (two commits for `fenvix-app` `claude/github-app`
@ `44d2a33`; how to apply: `APP-PATCH.md` next to this file). Design and limits: `docs/CACHE-AUDIT.md`.

**Why PARTIAL:** everything in the prompt is built and tested for **detpy**, the shared cache, the runner, the GitHub
App and the dashboard. **detjs is not wired**: on the base branch detjs has no reuse with proof at all (its proof cache
is being built on `claude/node-cache-proof` by another session; there is nothing to audit yet). What detjs gets from
this branch: the choice, the verdict and the bound live in the Rust core (`detpy_core::audit`), shared by every shell,
and `docs/audit/chosen.mjs` is the same choice in Node, checked equal to the core on 3,000 ids. Second gap: the audit
was **not measured on real public projects** (see "Numbers").

## What was built

1. **Engine (detpy)** `--det-cache-audit=SHARE` (`0.05` or `5%`; absent: `FENVIX_AUDIT_SHARE`, else **5%**; `0` off),
   `--det-cache-audit-seed=SEED`.
   * Of the tests whose reuse is proven, a seeded random share runs **fresh instead**. The reuse decision is still
     made and recorded: every audited test has its full receipt in `receipts.jsonl` (`"audited": true`) plus
     `"audit": {verdict, key, cached, fresh, fresh2}`.
   * The fresh result is compared with the cached one: **outcome and the set of test ids** the run produced.
   * The choice depends only on (seed, test id, share): SHA-256 rule in the Rust core (`audit::chosen`), independent of
     order and of the other tests. The **first line of the receipts** is the audit header (seed, share, candidates,
     chosen ids, run); `--det-cache-audit-seed=<that seed>` chooses the same tests again (tested).
   * The seed is drawn from the OS with `os.urandom` bound at import, before `--det-urandom` makes it deterministic
     (otherwise every run would audit the same tests).
2. **Mismatch** → the test runs **once more**, at once, in the same process, under the same per-test Level 0 controls
   (clock restarted, seeds, network), not reported (no log report, no junit row, not in the trace), its reads
   attributed to the test (never to "between tests").
   * second run = first run (≠ cache): **wrong**. The entry is dropped, the fresh runs are not recorded, the proof key
     is marked **untrusted** (`proof-cache.json` → `untrusted`). `Checker::check` refuses any entry with that key
     (`untrusted: a cache audit found this result wrong (run ...)`), wherever it comes from, until a **fresh** record of
     the same key (`Store::record`; entries fetched from the service use `Store::record_entry`, which does not clear).
   * second run ≠ first: **flaky with evidence**; nothing recorded or marked.
   * Reported: terminal (`WRONG SKIP ... key ... marked untrusted`), `--det-outcomes` → `cache.audit`, and
     `fenvix-run`'s `summary.json` → `audit: {share, seed, candidates, checked, matched, wrong, flaky_evidence,
     upper_bound_95, wrong_tests, flaky_tests}`, plus `[fenvix] ERROR wrong skip: ...` and a step-summary section.
   * **Shared cache**: the client pushes the marks first (`POST /v1/ns/<ns>/untrusted`); the service (append-only log)
     leaves out of every lookup the entries filed under the key before the mark, returns those filed after it (a fresh
     run that recorded the key again). The service reads each key row's proof key from the stored entry document,
     never from the request. The client also drops candidates whose key its local store marks (a service that missed
     the mark cannot hand the entry back). Old stores get the new table and column on start.
   * **GitHub App alert** (patch commit 1): one ERROR log line per job with wrong skips (`alert:
     "cache_audit_wrong_skip"`, tests, cached, fresh, key) and one `ci_audit_alerts` row per wrong skip (migration 0014,
     row level security), shown on the dashboard overview with the run link. Paging: not configured (later, as asked).
3. **Audited tests ran**: `reused_with_proof`, `test_seconds_saved` and the App's `tests_skipped` / `minutes_saved`
   never include them; they are in `ran`. Tested end to end in the engine (`fenvix-run`) and in the App (run row and
   usage event).
4. **Per project and over all projects**: checked, wrong, flaky with evidence and the **one-sided 95% upper bound on
   the wrong-skip rate**: `3/checked` when wrong = 0 (rule of three), else exact Clopper-Pearson. Same rule in four
   places, tested equal: Rust core (`detpy._core.audit_upper_bound`), cache service (`GET /v1/audit`, standard library
   only), `python -m detpy.audit_report SUMMARY.json...` (groups `fenvix-run` summaries by the new `project_key`), and
   the dashboard (overview card + per-project totals, `src/data/ci.ts` `upperBound95`).

## Tests (MEASURED, this container, Python 3.13.18, Rust stable)

Engine, `tests/test_cache_audit.py` (11, all pass), each rule:

| test | rule |
|---|---|
| `test_planted_wrong_reuse_is_caught_at_full_share` | a planted wrong reuse (entry says skipped, test passes, every input checks out) is reused without the audit, and **caught at 100%**: wrong 1, matched 1, key marked untrusted, entry dropped, receipts carry seed, chosen ids and the verdict, nothing counted as reused |
| `test_untrusted_key_stops_reuse_until_a_fresh_run_records_it_again` | the same wrong entry put back is **not reused** (`untrusted: ...`); that run, fresh, records the key again; the next run reuses it |
| `test_untrusted_key_stops_reuse_through_the_shared_cache` | forged entry on the service; machine 2 with a **read-only** token audits, marks the key on the service; machine 3 (empty mirror) gets no candidate for it and runs it; machine 4 reuses machine 3's fresh entry; `GET /v1/audit` per project and overall |
| `test_client_drops_candidates_with_a_locally_untrusted_key_even_when_the_service_has_no_mark` | defence in depth in the client |
| `test_mismatch_the_second_fresh_run_does_not_reproduce_is_flaky_with_evidence` | cached skipped, fresh passed, again failed: flaky 1, wrong 0, no mark, entry kept |
| `test_seed_in_the_receipts_reproduces_the_choice` | same seed → same chosen set (= the core's rule); no seed → a new seed per run, each choice reproducible from its receipts |
| `test_default_share_is_five_percent` | no option, no variable: share 0.05 on 200 reusable tests, chosen exactly as the core's rule says |
| `test_share_option_values` | `150%`, `lots` refused with a clear message |
| `test_fenvix_run_counts_audited_tests_as_run_and_reports_the_audit` | `summary.json` `audit` block, `reused_with_proof` 0 / `ran` 2 / `test_seconds_saved` 0 with 2 audited, ERROR line, step summary; per-project and all-project aggregation (rule of three for 300/0) and the CLI |
| `test_bounds_agree_between_the_core_and_the_service` | Rust vs service, 9 cases |
| `test_the_javascript_reference_chooses_like_the_core` | Node reference = core on 3,000 (seed, id, share) |

Rust (`cargo test -p detpy-core`): 53 pass, 5 new (SHA-256 known answers, choice independent of order and ~5% of
20,000, verdicts incl. another set of test ids, bounds vs Clopper-Pearson tables (100/1 → 0.0466, 1000/5 → 0.0105),
untrusted key: blocks, survives save and merge, not cleared by a fetched entry, cleared by a fresh record of the key).

Whole engine suite (`pytest tests/`): see "Engine suite" at the end. `tests/conftest.py` sets `FENVIX_AUDIT_SHARE=0`
for the other suites (their reuse counts would otherwise be random); the audit tests set the share themselves.

App (patched `44d2a33`): github-app typecheck + 62 unit + 69 integration pass; infra/github-app 52 pass; dashboard
`tsc`, 58 unit, `vite build` pass; `npm run test:rls` incl. the new `AUDIT RLS OK`. Details: `APP-PATCH.md`.

## Numbers

* Planted wrong reuse at 100%: **caught 1 of 1** (MEASURED, generated project, tests above; also the App fixture:
  12 tests, audit 25%, seed `fixture-seed`: 5 checked, 4 matched, **1 wrong** = the planted one, written by this
  branch's `fenvix-run`).
* Wrong-skip rate on real projects: **UNKNOWN**. I prepared two consecutive releases of six small PyPI projects
  (sqlparse, toolz, more-itertools, boltons, structlog, attrs: record release N, switch the tree to N+1, audit 100%,
  then again) but running the downloaded test suites was refused by this session's permission policy, so nothing was
  run and the downloads were deleted. Next test (cheap, $0): the same on GitHub Actions or a session allowed to run
  public suites, `fenvix-run --audit 100%` on the cache-proof specs (`harness/cache_proof/specs/*.json`), then
  `python -m detpy.audit_report */summary.json`.
* Cost of the audit: the audited share of the reusable test time runs again, so time saved drops by the share
  (5% by default) (ESTIMATED, by construction); a second run happens only on a mismatch.
* How fast the bound tightens with no wrong skip: 300 audited skips → under 1%, 3,000 → under 0.1% (ESTIMATED, rule of
  three). At 5% of 1,000 reusable tests per run: 0.1% after about 60 runs.

## Decisions taken here (the coordinator may want the founder on the first)

1. **Any token may mark a key untrusted**, read-only (pull-request) tokens included: a wrong skip found in a PR job must
   stop reuse everywhere, and a mark can only stop reuse. Risk: a malicious PR of the same customer can mark that
   customer's keys and make its next runs slower (no wrong result possible; with R-012 each customer is its own cache
   organization). Marks are logged with the token label. Alternative: write tokens only, and PR-job marks stay local.
2. **The service's audit totals count only runs filed with a write token** (a read-only token cannot file a run), so a PR
   job cannot inflate "checked" and shrink the bound. The App's totals come from every job's `summary.json`.
3. Flaky with evidence: the entry is kept and nothing is marked (the prompt names no action); the run reports the first
   fresh result.
4. A wrong skip does not fail the check run: the job's real outcome (the fresh run) is what the check shows; the wrong
   skip is shown as a row and a section.
5. `--det-cache-verify` (older, unseeded, unrecorded) is left as it was; the audit takes precedence for a test chosen by
   both.
6. The report is on the engine branch as the task says; the brain's CLAUDE.md asks work sessions to push reports to the
   brain's `main`: not done (the task said otherwise). Nothing was written to the brain.

## Risks (to turn into tests, not proven errors)

* The second fresh run is in the same process right after the first: a test that pollutes its own state can turn a
  wrong skip into "flaky with evidence" (never a false "wrong": that needs two equal fresh results that both differ
  from the cache).
* pytest-xdist: each worker draws its own seed (each in its receipts); one seed per run would need the controller to
  hand it over.
* Old service key rows (filed before this version) have no proof key: only the client's local marks cover them.
* Receipts now start with a header line whose `nodeid` is null; consumers that index `row["nodeid"]` without `.get`
  must skip it (the engine's, the runner's and the client's do).

## Other findings

* `tests/test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored` fails in this container
  on the **unchanged base `9ec28a4`** too (built in a separate worktree and venv): `{'test_m.py::test_daemon_answer':
  'subprocess'}` instead of `{}`. Not caused by this branch; environment-dependent (the daemon's fork timing). For the
  R-008 owner.
* The first full run found one real clash, fixed: the variable was first named `FENVIX_CACHE_AUDIT`, and
  `test_token_is_not_visible_even_to_a_test_that_enumerates_the_environment` rightly asserts that no `FENVIX_CACHE*`
  variable reaches a test; renamed `FENVIX_AUDIT_SHARE`.
* `cargo fmt --check` is not clean on the base either (12 files); left as is.

## Files

Engine: `crates/detpy-core/src/audit.rs` (new), `crates/detpy-core/src/proof.rs` (untrusted keys),
`crates/detpy-py/src/{lib,proofcache}.rs` (bindings), `python/detpy/{proofcache,plugin,remote_cache,cache_service}.py`,
`python/detpy/audit_report.py` (new), `runner/fenvix-run`, `docs/CACHE-AUDIT.md` (new), `docs/SHARED-CACHE.md`,
`docs/audit/chosen.mjs` (new), `tests/test_cache_audit.py` (new), `tests/conftest.py`.
App (patch): `github-app/src/{service.ts,results/summary.ts,results/render.ts}`, `supabase/migrations/0014_cache_audit.sql`,
`supabase/tests/audit-rls.sql`, `src/data/{types,ci,ci-rows,supabase,mock}.ts`, `src/pages/{Overview,Run}.tsx`,
`docs/data-contract.md`, tests and fixture; commit 2: vendored `cache_service.py`, PROVENANCE, `cdk.json`, cache test,
`DEPLOY-AWS.md`.

## Engine suite

MEASURED on `cf33351` in this container: `cargo test -p detpy-core` 53 passed; `pytest tests/` **187 passed, 9 skipped,
1 failed** in 570 s. The one failure is
`test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored`, which fails the same way on
the unchanged base `9ec28a4` (see "Other findings").
