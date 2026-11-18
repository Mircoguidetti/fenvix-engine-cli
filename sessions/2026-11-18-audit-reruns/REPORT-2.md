PARTIAL

# P-025 · R-013 FIX 4: cache audit fixes

**Why PARTIAL:** the four defects are fixed, and 3 of the 4 review tests pass. `test_r013_4` still fails, only at its
last line, and **no implementation can pass that line**. It asserts `upper_bound_95 > upper_bound_95(checked, 0)`.
With `checked <= 3`, every bound is 1.0 for any number of wrong skips (rule of three: `min(1, 3/n) = 1`; nothing is
above 1.0). The scenario has at most 3 audited checks in total (machine 2: 2, machine 5: 1). Every line before it now
passes (project `wrong 1`, `all.wrong 1`). The same check with enough checks passes in
`tests/test_cache_audit_r013.py::test_service_bound_reflects_a_wrong_skip_found_by_a_pull_request_job` (6 checks: bound
0.5818 > rule of three 0.5). As instructed, `tests/test_review_r013.py` is copied unchanged (0 diff lines against
`claude/review-r013`). Second gap: **the fenvix-app suites were not re-run**, because this session cannot reach
`fenvix-app` (see "App patch").

Engine: `claude/audit-reruns`, code commit `49f0bd5` (on `5c77597`). Review: `claude/review-r013`
`sessions/2026-11-18-review-audit-reruns/REPORT.md`.

## Before / after (MEASURED, this container, Python 3.13, Rust stable, `maturin develop --release`)

"Before" is the delivered Python (`5c77597`; the Rust core is unchanged by this fix). "After" is `49f0bd5`.

| test | before | after |
|---|---|---|
| `test_review_r013.py::test_r013_1_untrusted_mark_reaches_machines_whose_mirror_already_holds_the_wrong_entry` | FAIL: machine 3 (warm mirror) reuses the marked wrong entry | **pass**: the mark is pulled, the test runs, outcome passed |
| `test_review_r013.py::test_r013_2_second_fresh_run_is_not_fresh_a_deterministic_test_is_called_flaky` | FAIL: `checked 1, wrong 0, flaky 1` | **pass**: `checked 1, wrong 1, flaky 0`, next run not reused |
| `test_review_r013.py::test_r013_3_audit_compares_what_reuse_replays` | FAIL: audit says matched | **pass**: `wrong 1` |
| `test_review_r013.py::test_r013_4_service_audit_report_counts_wrong_skips_found_by_pull_request_jobs` | FAIL at `p["wrong"] >= 1` (`wrong 0`) | FAIL **only at its last line**: `wrong 1`, bound `0.9747` (= CP(2, 1)) vs `upper_bound_95(2, 0) = 1.0` (unsatisfiable, see above) |
| `test_cache_audit_r013.py::test_service_bound_reflects_a_wrong_skip_found_by_a_pull_request_job` (defect 4, 6 checks) | FAIL: `wrong 0` | **pass**: checked 6, matched 5, wrong 1, bound 0.5818 |
| `test_cache_audit_r013.py::test_second_fresh_run_runs_under_the_same_level0_controls` | FAIL: no `fresh2.process` (the old in-process run had the controls too) | **pass**: second run in a new process passes under `--det-epoch=2001-...` → wrong |
| `test_cache_audit_r013.py::test_audit_compares_the_test_ids_the_recorded_run_produced` (NOTE 1) | FAIL: `wrong 0` (cached ids were always `[nodeid]`) | **pass** |
| `test_cache_audit_r013.py::test_shared_cache_document_with_a_proof_key_not_of_its_content_is_not_reused` (NOTE 2) | FAIL: forged document reused, outcome skipped | **pass**: refused (`pull_rejected_proof_key 1`), machine 1's entry reused |
| `test_cache_audit_r013.py::test_shared_cache_document_whose_report_and_outcome_disagree_is_not_reused` (defect 3) | FAIL: reused, outcome skipped | **pass**: refused (`pull_rejected_inconsistent 1`) |
| `test_cache_audit_r013.py::test_marks_are_followed_by_sequence_and_applied_once` (defect 1) | FAIL: wrong entry reused after the mark | **pass**: applied once; after the fresh record, reused again; not pushed back |
| `test_cache_audit_r013.py::test_fenvix_run_audit_is_not_turned_off_by_the_project_addopts` (NOTE 5) | FAIL: `share 0.0` | **pass**: share 0.05, fresh seed |
| `test_cache_audit.py` (11) | 11 pass, two of them asserting the defects (the reviewer's point) | 11 pass; those two corrected (see below) |
| `cargo test -p detpy-core` | 53 passed | 53 passed |
| `pytest tests/` (whole engine suite) | 187 passed, 9 skipped, **5 failed** (the reviewer's run with the review file: the 4 review tests + the pre-existing R-008d one) | 197 passed, 9 skipped, **2 failed** in 550 s: `test_r013_4` (last line only) and the pre-existing `test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored` (`'subprocess'` instead of `{}`, as before). The 7 new tests are included |
| fenvix-app suites (`app.patch`) | pass (reviewer: 62+69, 52, 58, RLS) | **not run** (repository not reachable from this session) |

Changed delivered tests (each asserted a defect):
* `test_mismatch_the_second_fresh_run_does_not_reproduce_is_flaky_with_evidence`: it used a test that is the same in
  every process (defect 2). Now a test whose result changes from one process to the next (a counter on disk, in
  `.detpy/`, which the cache does not track) is flaky with evidence. It asserts the entry is **dropped**.
* `test_untrusted_key_stops_reuse_through_the_shared_cache`: `GET /v1/audit` after the read-only job's wrong skip is
  now `checked 3, matched 2, wrong 1, checked_without_summary 1` (it asserted `wrong 0`).
* The mocked client in `test_client_drops_candidates_...` answers the new marks request.

Two runner tests were flaky because of the delivered default. MEASURED:
`test_shared_cache.py::test_fenvix_run_on_two_machines_sharing_the_service` failed once here with
`reused_with_proof 4 != 5`. Their minimal environment has no
`FENVIX_AUDIT_SHARE`, so the default 5% audit with a random seed runs one of the 5 reusable tests fresh in about
23% of runs (1 − 0.95⁵). `test_runner_wrapper.py` has the same exposure at 5%. Both now pin the audit off
(`--audit 0`, `FENVIX_AUDIT_SHARE=0`): they test reuse, not the audit.

## What changed

1. **Untrusted marks reach every machine's mirror** (`remote_cache.py` `pull_marks`). Before its lookup, the client
   reads the service's marks it has not seen yet: `GET /v1/ns/<ns>/untrusted?after=SEQ`. The service now returns
   `seq`, and follows the log oldest first with `after`. The last `seq` is kept in the mirror's journal. A mark is
   applied (`mark_untrusted` in the local store) when the mirror holds an entry for that test **under that key**.
   The key is computed by this machine's core, not read from the document. So `Checker::check` refuses it before
   `_decide`.
   * Each mark is applied once and never pushed back. After this machine's own fresh run records the key again, the
     mark does not come back.
   * A mark is not applied to tests the mirror does not hold. Reason: an entry fetched later is filed after the mark
     (the service leaves the older ones out), and marking it would block the legitimate fresh entry of another
     machine. The delivered shared-cache test's machine 4 showed this.
   * Also: a candidate whose `proof_key` is not the key the client computes for its content is refused (NOTE 2: a
     document could leave the key out and dodge every mark).
2. **The second fresh run is truly fresh** (`plugin.py` `_audit_rerun`). It runs in a new pytest process: the first
   process's command line (`invocation_params`, plus ini `addopts` and the environment, which reach it by
   themselves), restricted to the test by its absolute path and id.
   * It gets the same Level 0 controls: seed, controls, hash seed (inherited `PYTHONHASHSEED`), network, and the
     clock epoch, passed explicitly as `--det-epoch`.
   * It drops the selection by path and these options: `--det-cache*`, `--det-order`, `--det-compare`,
     `--det-outcomes`, `--det-trace`, `--basetemp`, `--junitxml`, `--lf`/`--ff`/`--nf`/`--sw`, and xdist `-n`.
   * It has no proof cache (`DETPY_AUDIT_CHILD`, removed from the environment before the tests run). Its outcomes,
     trace, basetemp and pytest cache go to a scratch directory, deleted afterwards.
   * If there is no outcome or a timeout (300 s + 20× the first run), the verdict is **wrong**: an unexplained
     mismatch is never trusted.
   * **Flaky with evidence now drops the entry**, because a fresh run contradicted it.
   * Cost: one pytest start-up per mismatch, never per audited test.
3. **The audit compares what reuse replays** (`proofcache.py` `audit_after_run`).
   * The cached side is `_final(entry["report"])`, the phases `_reuse` replays. When the `outcome` field disagrees,
     it is shown as `cached.outcome_field`.
   * The cached test ids are the ids the recorded run produced. They are stored as `report.ids` when they are not
     just the test's own id (NOTE 1: the comparison is no longer vacuous).
   * An entry whose `report` and `outcome` disagree is **refused when it comes from the shared cache**
     (`pull_rejected_inconsistent`). **Deviation from the brief ("must not be reused"):** a *local* entry that
     disagrees is still reused as its report says. `test_r013_3`, which must pass unchanged, asserts exactly that
     reuse (`nid in reused_ids`, outcome skipped) before it checks the audit. The engine writes both fields from the
     same run, so locally only hand edits or disk corruption can make them differ. The audit now catches it.
4. **`GET /v1/audit` counts every token's wrong skips** (`cache_service.py` `Store.audit`).
   * `wrong` is the number of distinct (run, test) pairs from the run summaries' `wrong_ids` and the untrusted log.
     A read-only job cannot file a summary, but it does mark its wrong skips.
   * `checked`, `matched` and `flaky_evidence` stay write-token only.
   * A wrong skip known only from the log adds one check (`checked_without_summary`). The bound never has fewer
     checks than wrong skips, and the unknown matched checks of those jobs only make it higher (conservative).
   * The response says how it counts (`counted`), and `python -m detpy.audit_report --service` prints it.
5. **NOTE 5:** `fenvix-run` always passes `--det-cache-audit=<--audit, else FENVIX_AUDIT_SHARE, else 5%>` and a fresh
   `--det-cache-audit-seed`. A repository's `addopts` can no longer turn the audit off or freeze its choice.

Docs: `docs/CACHE-AUDIT.md` (comparison, second run, flaky drops the entry, mirrors, refused candidates, service
counts, limits), `docs/SHARED-CACHE.md` (untrusted keys).

## App patch

`app.patch` commit 1 is unchanged. In commit 2, `infra/github-app/lib/cache/cache_service.py` now vendors engine
`49f0bd5`, SHA-256 `1e624a663ee5afcefb66eaec45c9188041b3b45710412b80c5d629f4fed4eea4`.
* PROVENANCE, the pin in `test/cache.test.ts`, `engineCliCommit` and DEPLOY-AWS are updated.
* The `/v1/audit` expectation in `test/cache.test.ts` changed: after the read-only mark it is `checked 1, wrong 1,
  checked_without_summary 1`. The vendored service gives exactly that (checked here).

**Blocked:** the session's GitHub proxy refuses `github.com/Mircoguidetti/fenvix-app` ("GitHub access to this
repository is not enabled for this session"). The brief rules out attaching other repositories. So commit 2 was
regenerated from the patch text. The vendored file's diff from its known base (`1ad68b4` = engine `9ec28a4`)
reproduces the engine file byte for byte (applied in a scratch repository, `cmp` equal), and the other hunks keep
their context. **None of the app suites were re-run.** To check it: on `claude/github-app`, `git am app.patch`, then
`cd infra/github-app && npm ci && npm test` (commit 2 touches only that package, its docs and `cdk.json`).
`APP-PATCH.md` says the same at the top.

## Still open (review NOTES not addressed here)

* NOTE 2, residual: a write token can still file a wrong entry under the right key after a mark. As before, a write
  token can already file any entry.
* NOTE 3: a fresh record on any machine lifts the mark on the service.
* NOTE 4: no volume limit on marks.
* NOTE 6: the App's totals come from job-written summaries.
* NOTE 7: detjs is not wired, and there is no measurement on real projects. Both are unchanged from REPORT.md.
* The pre-existing `test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored` failure
  belongs to R-008d, not this delivery.
