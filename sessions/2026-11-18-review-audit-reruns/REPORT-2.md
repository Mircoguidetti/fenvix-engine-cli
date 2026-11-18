FIX 1

# R-013 · Review round 2 (last) of P-025 audit reruns: the fix delivery

Reviewer session 2026-11-18. Delivery: `claude/audit-reruns` @ `4f944dd` (code `49f0bd5` on `5c77597`),
`sessions/2026-11-18-audit-reruns/REPORT-2.md` (PARTIAL). Round 1: `claude/review-r013`
`sessions/2026-11-18-review-audit-reruns/REPORT.md` (FIX 4). This branch: `claude/review-r013b` (from
`claude/audit-reruns`). Scope as briefed: only the four FIX items and the NOTEs the delivery addressed (1, 2, 5),
whether the fixes opened a new way for an audit to miss a wrong reuse, the app patch, and the engine suite.

New failing test: `tests/test_review_r013b.py` (one test, with a docstring). Run:
`maturin develop --release && pytest tests/test_review_r013b.py`.

## Verdict: FIX 1 (one proven error, a regression that fix 2 introduced)

| # | test | defect |
|---|---|---|
| 5 | `tests/test_review_r013b.py::test_r013_5_wrong_skip_of_an_order_dependent_test_is_marked_on_the_shared_cache` | **The new-process second run turns the wrong skip of an order-dependent test into "flaky with evidence", so the wrong entry is never marked and every other machine keeps reusing it.** The second fresh run now runs the test **alone** in a new process. Take a test whose result depends on what ran before it in the session (state left by an earlier test, which is very common: shared DB rows, registries, session fixtures with state). The cached result says skipped. The first fresh run, in the session, passes. The second, alone, fails. `audit::verdict` returns `FlakyEvidence` whenever `second != first`, **even when `second != cached` too**, so a cached result that **both** fresh runs contradict is not "wrong". The result: no `mark_untrusted`, nothing pushed to the service, the entry dropped on the auditing machine only, and the bound counts it as a check that was not wrong. Measured (shared cache, audit 100% on machine 2): `checked 2, matched 1, wrong 0, flaky_evidence 1` (`cached skipped, fresh passed, fresh2 failed (process new)`), and the service's untrusted log is empty. **On `5c77597` the same case was caught:** `WRONG SKIP test_m.py::test_b_uses_it: cached skipped, fresh passed and passed; key … marked untrusted` (the in-process second run kept the earlier test's state). On `5c77597` the test still fails, but only at its last line (machine 3 reuses), which is defect 1 of round 1. So the classification part of the test passes before the fix and fails after it: this is a **regression** of fix 2. |

The in-process run (round 1, defect 2) and the alone-in-a-new-process run (now) are each wrong for one class of
tests: state carried forward breaks the first, state needed from earlier tests breaks the second. Neither run can
reliably tell "flaky" from "wrong". The robust rule does not depend on how the second run is made.

Cheapest fix (proposal, the work session decides): in `audit::verdict`, call a mismatch **wrong whenever the second
fresh run also differs from the cached result** (`Some(s) if s != cached => Wrong`). Keep `FlakyEvidence` only when
the second run reproduces the cached result. A mark only stops reuse, so the cost of being wrong is a rerun. The
bound then counts these cases as wrong, which is conservative. Keep the new process (it fixed round-1 defect 2).
Alternative: on `FlakyEvidence`, mark the key untrusted as well (push the mark), and keep it out of `wrong`.

## The four round-1 FIX items

Before = `5c77597`, after = `49f0bd5`. The Rust core is unchanged by the fix, so one `maturin develop --release`
build serves both: the "before" runs use a `git worktree` of `5c77597` first on `PYTHONPATH`, and
`detpy.__file__` was checked. `tests/test_review_r013.py` has 0 lines of diff against `claude/review-r013`.

| # | review test | before | after | really fixed? |
|---|---|---|---|---|
| 1 | `test_r013_1_…warm_mirror…` | FAIL (machine 3 reuses, `miss reasons {}`) | pass | **Yes.** `pull_marks` follows the service's log by `seq` (journal-kept cursor) before every lookup, and applies a mark when the mirror holds the test **under the marked key**. That key is computed by the local core (`key_of`), not read from the document. The cursor is independent of the selected items. Applied marks are tagged so that they are never pushed back. GET `untrusted` is allowed for read-only tokens, so pull-request jobs pull marks too. The marks that are consumed without being applied (mirror does not hold that key) cannot come back through the service: lookups leave out entries filed before the mark, and the new proof-key check stops a document from dodging that filter. |
| 2 | `test_r013_2_…deterministic_test_is_called_flaky` | FAIL (`(1, 0, 1)`) | pass | **Yes, for the reported class** (state carried forward). It is a real new process, with the same Level 0 controls (epoch passed explicitly, seeds and hash seed inherited, `-p no:xdist`), no proof cache in the child, and scratch outputs. "Flaky with evidence" now drops the entry. **But it opened defect 5** (state needed from earlier tests), see above. |
| 3 | `test_r013_3_audit_compares_what_reuse_replays` | FAIL (`2 matched, 0 wrong`) | pass | **Yes.** The cached side is `_final(entry["report"])`, the phases `_reuse` replays (`_reuse` iterates only `setup`/`call`, so the new `report.ids` key does not affect replay). Shared-cache candidates whose `report` and `outcome` disagree are refused (`_consistent`). **The deviation is accepted:** a *local* inconsistent entry is still reused. The review test's own precondition asserts that reuse, so the delivery could not refuse it without editing the test. Only a hand edit or disk corruption can produce such an entry locally, and the audit now catches it. Non-blocking: a `Checker` refusal would still be cheaper than waiting for the 5% audit. |
| 4 | `test_r013_4_…pull_request_jobs` | FAIL at `p["wrong"] >= 1` (`wrong 0`) | FAIL **only at its last line** | **Yes, and the last line is unsatisfiable** (see below). `Store.audit` now counts `wrong` as distinct (run, test) pairs from the summaries' `wrong_ids` (plus unnamed ones when the list is capped) and from the untrusted log. A wrong skip known only from the log adds one check (`checked_without_summary`). `checked`/`matched` stay write-token only, and the response says so (`counted`). Every way it can be off overcounts `wrong` (a summary run id that differs from the mark's run id, capped `wrong_ids` versus the log's node ids), never undercounts it. That is conservative. |

### The delivery's claim about `test_r013_4`'s last line: correct

The last line asserts `p["upper_bound_95"] > cs.upper_bound_95(p["checked"], 0)`. MEASURED with the service's own
function:

| checked n | bound for wrong = 0, 1, …, n |
|---|---|
| 1 | 1.0, 1.0 |
| 2 | 1.0, 0.9747, 1.0 |
| 3 | 1.0, 0.8646, 0.983, 1.0 |
| 6 | 0.5, 0.5818, … |

For n ≤ 3 the rule of three gives `min(1, 3/n) = 1.0`, and no bound is above 1.0. The scenario has at most 3 audited
checks in all (machine 2: 2, machine 5: 1; output above), so no correct implementation can pass that line. Inflating
`checked` past the real checks would be the only way, and that would be wrong. The error is in the round-1 review, not
the delivery. After the fix the project reads `checked 2, wrong 1, bound 0.9747`. That is CP(2, 1),
the right value for what the service knows.

**The replacement test covers the same defect.**
`tests/test_cache_audit_r013.py::test_service_bound_reflects_a_wrong_skip_found_by_a_pull_request_job` uses the
same shape: write-token machine 1 records; a forged skipped entry; the **read-only** machine 2 audits at 100% and
finds the wrong skip; write-token machine 5 audits; then `GET /v1/audit`. It uses 6 tests, so the inequality can
hold. Before the fix it fails on the defect itself (`{'checked': 5, 'matched': 5, 'wrong': 0}`, `assert 0 == 1`).
After the fix it passes with `checked 6, matched 5, wrong 1, checked_without_summary 1`, bound
`upper_bound_95(6, 1) = 0.5818 > 0.5`, the same in `all`. It also checks that a wrong skip in both a summary and the
log is counted once. One residual difference, by design and declared: the read-only job's 5 matched checks are
unknown to the service, so it counts that job as 1 check. That is conservative.

Accept `test_r013_4` as satisfied by everything up to its last line plus the replacement test. Its last line should
read `p["wrong"] >= 1 and p["upper_bound_95"] == cs.upper_bound_95(p["checked"], p["wrong"])`.

## The NOTEs the delivery addressed

| NOTE | delivery test | before | after | fixed? |
|---|---|---|---|---|
| 1 (test-id comparison vacuous) | `test_audit_compares_the_test_ids_the_recorded_run_produced` | FAIL (`(1, 0)`) | pass | Yes: `report.ids` is stored when it is not just `[nodeid]` and compared. Still only meaningful once detjs is wired (NOTE 7). |
| 2 (service trusts the document's `proof_key`) | `test_shared_cache_document_with_a_proof_key_not_of_its_content_is_not_reused` | FAIL (reused, `skipped`) | pass | Yes for the dodge: after injection, a candidate whose `proof_key` differs from the key the local core computes is removed (`pull_rejected_proof_key`). The declared residual stays: a write token can re-file a wrong entry under the right key after a mark. |
| 5 (project config turns the audit off) | `test_fenvix_run_audit_is_not_turned_off_by_the_project_addopts` | FAIL (`share 0.0`) | pass | Yes for `addopts` and `PYTEST_ADDOPTS`: `fenvix-run` always passes `--det-cache-audit` and a fresh seed, and command-line options win. `FENVIX_AUDIT_SHARE=0` in the workflow still turns it off, which is a workflow-trust question (P-024). A `conftest.py` can always change options; that is not in scope. |

The other new delivery tests also fail before and pass after (all 7 of `tests/test_cache_audit_r013.py` fail on
`5c77597`, MEASURED): `…same_level0_controls`, `…report_and_outcome_disagree_is_not_reused`,
`…marks_are_followed_by_sequence_and_applied_once`.

## Did the fixes open another way to miss a wrong reuse?

* **Yes: defect 5** (above).
* Not found elsewhere. Checked:
  * Fix 1:
    * Marks are consumed even when not applied, and this is safe (see the table).
    * Pagination ends.
    * An older service with no `seq` still has its newest 1,000 marks applied.
    * The proof-key check uses the core's key.
  * Fix 3: `_final` ignores the `ids` key.
  * Fix 4: only overcounts.
  * The fix-2 child process:
    * Strips the cache, selection and output options.
    * Keeps `-k`/`-m`, plugins and `--det-urandom`.
    * Turns a missing outcome or a timeout into **wrong**.
* Non-blocking, not new: if `GET …/untrusted` fails, `pull()` records the error and goes on, so a warm mirror still
  reuses an entry marked elsewhere for that run (fail-open, the same as an offline mirror). Round 1 had no mark pull
  at all. Option: when the marks cannot be read, do not reuse entries that came from the service in that run.

## App patch: NOT RUN (blocked, same as the delivery)

* `git clone https://github.com/Mircoguidetti/fenvix-app` fails here
  (`could not read Username for 'https://github.com'`). This session's GitHub access is scoped to
  `fenvix-engine-cli`, and the brief rules out attaching other repositories. A check of the proxy's status was
  refused by this session's permission settings, so I stopped there. **No fenvix-app suite was run** by the delivery
  or by this review. Postgres 16 is installed here; only the repository is missing.
* What could be checked without the repository (MEASURED):
  * `app.patch` is well formed (`git apply --stat`: 2 commits, 25 files).
  * Engine `9ec28a4`'s `cache_service.py` is the delivery's stated base of the vendored file. Applying commit 2's hunk
    for that file to it gives a file **byte-identical** to the engine's at `49f0bd5` (`cmp`). Its SHA-256 is
    `1e624a66…eea4`, which is the value pinned in `test/cache.test.ts`, PROVENANCE and `engineCliCommit` `49f0bd5…`.
* Still to do, on a machine that can reach fenvix-app: `git am app.patch` on `claude/github-app`, then the four
  suites of round 1. The minimum is `cd infra/github-app && npm ci && npm test`, because commit 2 changes the
  `/v1/audit` expectation. Defect 5's fix is in the engine (`audit.rs` / `proofcache.py`), not in
  `cache_service.py`. The vendored file can then stay the same, but `engineCliCommit` moves.

## Engine suite (MEASURED, this container, Python 3.13.18, pytest 9.2.0, `maturin develop --release`, branch head `4f944dd` + `tests/test_review_r013b.py`)

* `cargo test -p detpy-core`: **53 passed**.
* `pytest tests/`: **197 passed, 9 skipped, 3 failed** in 572 s. That matches the delivery's 197 passed / 2 failed, plus this review's new test. The 3 failures:
  * `test_review_r013b.py::test_r013_5` (defect 5).
  * `test_review_r013.py::test_r013_4` (its last line only, which cannot pass; see above).
  * The pre-existing R-008d test below.
* The pre-existing `test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored` failure is
  R-008d's, not this delivery's.

## Delivery claims checked

* "Before" column: the 4 review tests and the 7 new tests all fail on `5c77597` (MEASURED). `test_r013_4` fails at
  `wrong 0`, as stated.
* "After" column: 3 review tests pass. `test_r013_4` fails only at its last line, with `checked 2, wrong 1,
  bound 0.9747`, as stated. The 7 new tests pass.
* The runner tests pinned to `--audit 0` / `FENVIX_AUDIT_SHARE=0` (`f699efc`): reasonable. They test reuse. The
  audit's effect on reuse counts is covered elsewhere.
