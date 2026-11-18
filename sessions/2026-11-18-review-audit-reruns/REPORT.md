FIX 4

# R-013 · Review of P-025 (audit reruns: the product's self-check of skipped tests)

Reviewer session 2026-11-18. Delivery: `claude/review-r013` @ `428db39` (engine code from `cf33351`, base
`claude/shared-cache` @ `9ec28a4`), `sessions/2026-11-18-audit-reruns/REPORT.md` (PARTIAL), `docs/CACHE-AUDIT.md`,
`sessions/2026-11-18-audit-reruns/app.patch` for fenvix-app `claude/github-app` @ `44d2a33`.
Contract: P-025 items 1-4, serving P-024 acceptance item 5 ("any wrong skip pages us and disables reuse for that key").

The failing tests are in `tests/test_review_r013.py` on this branch (one test per defect, each with a docstring saying
why it matters). Run: `maturin develop --release && pytest tests/test_review_r013.py`.

## Verdict: FIX 4 (proven errors)

| # | test (`tests/test_review_r013.py`) | defect | question |
|---|---|---|---|
| 1 | `test_r013_1_untrusted_mark_reaches_machines_whose_mirror_already_holds_the_wrong_entry` | A key marked untrusted on the shared cache is **still reused by every machine whose local mirror already holds the wrong entry**. Marks are pushed (`POST /v1/ns/<ns>/untrusted`) but never pulled: `pull()` skips any test the local store already proves (`pull_local_already`) and never reads the service's marks, so the local `Checker` has nothing to refuse. Measured: machine 3 pulls the wrong entry (reused, skipped); machine 2 audits it, wrong, marks it on the service; machine 3's next run **reuses it again** (`reused_ids` contains it, outcome `skipped`, the test passes). The delivery's own test hides this by using a machine with an **empty** mirror. | (2) untrusted everywhere, all machines |
| 2 | `test_r013_2_second_fresh_run_is_not_fresh_a_deterministic_test_is_called_flaky` | **A wrong skip is classified "flaky with evidence"** because the second run is not fresh: it runs in the same process right after the first (`_audit_rerun` → `runtestprotocol`), so state the first run left (module globals, `lru_cache`, a file, a registry) changes it. Measured: a test that passes in 3 of 3 separate pytest processes, cached as skipped, is audited at 100%: `checked 1, wrong 0, flaky_evidence 1`; nothing is marked, the wrong entry is kept, the **next run skips it again**, and the bound counts it as a correct skip. The delivery's own `test_mismatch_the_second_fresh_run_does_not_reproduce_is_flaky_with_evidence` is this very case (a per-process deterministic test) asserted as correct. | (1) wrong reuse misclassified as flaky |
| 3 | `test_r013_3_audit_compares_what_reuse_replays` | **The audit compares a field the reuse never shows.** Reuse replays the entry's `report` phases (`_reuse`); the audit compares the entry's `outcome` field (`audit_after_run`: `cached = (r["outcome"], [nid])`). An entry whose `report` says skipped while `outcome` says passed (corruption, or a document filed by a job with a write token) is reused as **skipped**, and the audit at **100%** calls it **matched** (2 matched, 0 wrong): never caught, never marked, and re-served by the service to every machine. | (1) comparison too weak |
| 4 | `test_r013_4_service_audit_report_counts_wrong_skips_found_by_pull_request_jobs` | **`GET /v1/audit` reports wrong = 0 for a project with a wrong skip found and marked on that same service.** It sums only runs filed with a write token, so every wrong skip found by a pull-request job (read-only token) is dropped from `wrong` while its `checked` is also dropped; the bound shown is the rule-of-three one. Measured: after the read-only job's wrong skip (marked, visible in `GET /v1/ns/proj/untrusted`), the project reads `{checked 1, matched 1, wrong 0, upper_bound_95 1.0}` and `all.wrong = 0`. The delivery's own shared-cache test asserts `"wrong": 0` right after a wrong skip. (The App's dashboard counts every job's summary, so the two reports disagree.) | (4) report per project, all projects |

Cheapest fixes (proposals, the work session decides):
1. In `pull()`, fetch the namespace's marks (`GET /v1/ns/<ns>/untrusted`, or return them with the lookup) and
   `mark_untrusted` them in the local store before `_decide`; keep a mark newer than the local entry's record time.
   This also closes the self-declared `proof_key` gap (NOTE 2), since the local `Checker` computes the key itself.
2. Run the second fresh run in a **new process** (the same command restricted to that node id, under the same Level 0
   controls), as a real next run would; keep the in-process run only as an extra signal. Until then, at least drop the
   entry on "flaky with evidence" (a fresh run contradicted it) instead of keeping it reusable.
3. Compare the final outcome of the `report` that reuse replays (`_final(entry["report"])`), and refuse to reuse an
   entry whose `report` and `outcome` disagree (Checker: a new miss kind).
4. Count `wrong` (and `wrong_ids`) from every token's summary, or from the untrusted log per namespace; keep the
   write-token filter only for `checked` and `matched`, and say so in the output.

## The five questions

**(1) Can an audit miss a wrong reuse it should catch?** Yes, three ways: defects 2 and 3, and NOTE 1 (the test-id
comparison is vacuous). What holds (MEASURED):
* Choice: `audit_chosen` equals an independent `hashlib` implementation of the documented rule on 80,000
  (seed, id) pairs (0 mismatches); observed share 4.86% at 5% (z = -1.9). Order-independent (Rust test).
* Chosen tests are never skipped: planted wrong reuses (every entry says skipped, every test passes), fixed seeds,
  `caught == chosen` and `reused ∩ chosen = ∅` asserted per run:
  * share 100%, 50 planted: 50 chosen, **50 caught** (100%).
  * share 5%, 400 planted × 10 seeds: 232 chosen, **232 caught** (100% of the chosen); 3,768 wrong reuses not chosen
    were reused, as a 5% share means. Per run the chance to catch one given wrong key is the share (5%): a key reused in
    every run is caught after about 20 runs on average (ESTIMATED, geometric).
  Script: kept out of the repo (scratch); the committed tests cover the single-plant case.
* Flaky misclassified as matched: only when the flaky test happens to give the cached result, which is not a wrong
  reuse. Fine.

**(2) Is the key untrusted everywhere until a fresh run records it again?** Local store: yes (mark survives save and
concurrent merge; `record_entry` of a fetched entry does not clear it; tested in Rust and Python). Shared cache, machines
with an empty mirror: yes. **Machines with a warm mirror: no (defect 1).** Hostile jobs:
* Forge a mark: any read-only (pull-request) token can mark any proof key in any namespace of its organization
  (decision 1 of the report). It cannot cause a wrong result, only reruns; see NOTE 4 for volume.
* Erase a mark: no API deletes it (append-only triggers). A write-token job can make it moot (NOTE 2).

**(3) Audited tests never billed or shown as skipped?** Holds (MEASURED): engine `reused_with_proof` 0 / `ran` 2 /
`test_seconds_saved` 0 with 2 audited; App `tests_skipped` = 7 of 12 with 5 audited, usage minutes from reused tests
only (integration test `a wrong skip found by the cache audit`, run here). The second, in-process run sends no log
report (`log=False`), so it adds no junit row or outcome.

**(4) Is the 95% bound right?** Holds (MEASURED). Rust core, the service (Python) and the dashboard (TypeScript)
agree to ≤ 1.2e-16 with an exact 60-digit Clopper-Pearson bisection on 13 cases (n/k = 2/1 → 0.974679, 100/1 →
0.046560, 1000/5 → 0.010484, 5000/3 → 0.001550, 20/19 → 0.997439, …); wrong = 0 gives 3/n clamped to 1
(300 → 0.01; the exact value 1 − 0.05^(1/n) is 0.009936, so the rule of three is the slightly conservative one the
contract asks for). The formula is right; **what goes into it is not** in the service report (defect 4) and is too
optimistic wherever defect 2 turns wrong skips into "flaky" (flaky counts as checked and not wrong).

**(5) App patch and suites.** `git am` of `app.patch` on fenvix-app `claude/github-app` @ `44d2a33`: both commits
apply cleanly; the vendored `infra/github-app/lib/cache/cache_service.py` is byte-identical to the engine's. Results
(MEASURED, this container, Postgres 16 scratch, Node 22):

| suite | result |
|---|---|
| `github-app`: `npm run db:prepare && npm test` | typecheck ok, **62/62** unit, **69/69** integration |
| `infra/github-app`: `npm test` | **52/52** |
| root: `tsc --noEmit`, `npm run test:unit`, `npm run build` | ok, **58/58**, build ok |
| `npm run test:rls` | RLS, FUNCTIONS, ORGS, CI, CI EXPLORE, GH, **AUDIT RLS OK**, seed idempotent |

Matches the delivery's numbers. The vendored service carries defect 4 (same file).

## Engine suite (MEASURED, this container, Python 3.13.18, `maturin develop --release`)

* `cargo test -p detpy-core`: **53 passed**, as reported.
* `pytest tests/`: run in progress at this commit; result in the next commit.
* The pre-existing failure `test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored`
  reproduces here too (`'subprocess'` instead of `{}`), as the delivery reports; not this delivery's.
* `tests/test_cache_audit.py`: 11/11 pass (they do not exercise defects 1-4; two of them assert the wrong behaviour,
  see defects 2 and 4).

## NOTES (not provable as a failing test here, or by design; they never block)

1. **The "set of test ids" comparison is vacuous in detpy.** The cached side is always `[nodeid]` (the entry stores no
   ids), so only a run that reports under another node id can differ. Harmless for pytest items; for detjs file-level
   results the entry must store the ids the recorded run produced, or the comparison cannot catch a changed test set.
   Cheapest test: when detjs is wired, plant a file entry with one test id fewer than the file now runs.
2. **The service trusts the `proof_key` written inside the entry document.** A write-token job can file the same
   wrong result with `proof_key` missing or different (or just another `run` value after a mark): the key row is never
   excluded by any mark, and the client's defence (`docs[d]["proof_key"] in untrusted`) reads the same claim. Today a
   write token can already file any wrong entry, so this adds no new power, but the mark is then not "until a fresh
   run records it again". Fix 1 above closes it on machines that know the mark (the core computes the key). Cheapest
   test: re-file the forged document without `proof_key` after the mark, run a fresh machine, assert not reused.
3. **A mark is lifted by any fresh record of the key, on any machine.** When the hole is an input the engine does not
   see and that differs by machine, the machine where the cached result is right records the key again (an audit that
   matched, or a miss), and the service serves it again to the machine where it is wrong. Wrong skips then recur at the
   audit's rate. Option: lift a mark only with a fresh run on the runtime that found it wrong, or keep a counter and
   stop reuse for a key marked twice. Cheapest test: two machines with an untracked differing input, alternate runs.
4. **Marks have no volume limit.** 10,000 per request, unlimited requests, any read-only token: a hostile pull request
   can grow the `untrusted` table without bound and slow every lookup (`NOT EXISTS` per key row). Cheapest test:
   1,000,000 marks, then time a 5,000-key lookup.
5. **The customer's configuration can turn the self-check off.** `fenvix-run` passes `--det-cache-audit` only when
   `--audit` is given, so `addopts = --det-cache-audit=0` (or `--det-cache-audit-seed=fixed`) in the repository, or
   `FENVIX_AUDIT_SHARE=0` in the workflow, disables or freezes the audit, and a pull request can do it for its own
   runs. Option: the runner always passes the share and a fresh seed explicitly (command-line options come after
   `addopts`, so they win). Cheapest test: a project with that `addopts`, assert `summary.audit.share == 0.05`.
6. **The App's audit totals come from the job's own `summary.json`**, which the job writes (any pull request), so a
   job can claim many matched audits (bounded only by `checked ≤ ran`) or hide a wrong skip; the service's write-token
   filter (decision 2) does not apply to the dashboard's bound. Belongs to the summary-integrity question of P-024.
7. **Delivery gaps already declared PARTIAL:** detjs not wired; wrong-skip rate on real projects UNKNOWN (no public
   suite was run). Both still needed for P-024 item 4 ("report N and the bound").
8. Location: this report is on the engine branch as the launch message asks; `REVIEWER.md` names the brain and a
   `review-<branch>` branch. Nothing was written to the brain.
