DONE

# P-025 · R-013b FIX 1: wrong skip of an order-dependent test is marked

Review: `claude/review-r013b` `sessions/2026-11-18-review-audit-reruns/REPORT-2.md` (FIX 1, defect 5).
Engine: `claude/audit-reruns`, fix commit on `4f944dd`.

## Fix (the reviewer's proposal)

In `crates/detpy-core/src/audit.rs`, `audit::verdict` now says:

```rust
match second {
    None => Verdict::NeedsSecondRun,
    Some(s) if s == cached => Verdict::FlakyEvidence,   // the second run reproduces the cache
    Some(_) => Verdict::Wrong,                           // both fresh runs contradict the cache
}
```

* Before, a mismatch was wrong only when the second fresh run equalled the first. Now it is wrong whenever the second
  fresh run also differs from the cached result, whether or not it agrees with the first.
* "Flaky with evidence" is kept only when the second run reproduces the cached result.
* The new-process second run is kept, so round-1 defect 2 stays fixed (`test_r013_2` passes).
* The Python shell, `proofcache.audit_after_run`, calls the core and needed no logic change. Only its docstrings,
  comments and the `not_cached` reason were updated, along with `audit_report.py`'s description.
* This rule is conservative: a flaky test whose two fresh runs both differ from a cached result is now counted
  wrong, and its key is marked untrusted. The cost of that is reruns of the key, never a wrong reuse.

## Tests

* `tests/test_review_r013b.py`: copied unchanged from `claude/review-r013b` (`git show … >`; 0 diff lines).
* The Rust unit test `audit::tests::verdicts` gains one case: `cached passed, fresh failed, fresh2 error → Wrong`.
* `tests/test_cache_audit.py`: the delivery's own flaky test encoded the old rule. It had a planted skip, then fresh
  runs failed and passed: both contradict the cache, so under the new rule that case is **wrong**. I split it in two:
  * `test_mismatch_the_second_fresh_run_reproduces_the_cache_is_flaky_with_evidence`: recorded passed, fresh failed,
    then fresh2 in a new process passed (the counter on disk alternates). The result is flaky with evidence: nothing
    is marked, the entry is dropped, and the run reports failed.
  * `test_mismatch_both_fresh_runs_contradict_although_they_disagree_is_wrong` (new): the same test with a planted
    skip gives skipped / failed / passed. The result is wrong: the key is marked untrusted and the entry is dropped.

## Before / after (MEASURED, this container, Python 3.13.18, `pip install -e .` = maturin release build)

"Before" is this branch with only the two match arms of `verdict` reverted to the old rule, rebuilt.

| test | before | after |
|---|---|---|
| `test_review_r013b.py::test_r013_5_wrong_skip_of_an_order_dependent_test_is_marked_on_the_shared_cache` | FAIL: `checked 2, matched 1, wrong 0, flaky_evidence 1` (`cached skipped, fresh passed, fresh2 failed (process new)`, verdict `flaky-evidence`) | **pass** (wrong 1, key in the service's untrusted log, machine 3 does not reuse) |
| `test_cache_audit.py::test_mismatch_both_fresh_runs_contradict_although_they_disagree_is_wrong` | FAIL (verdict flaky) | **pass** |
| `test_cache_audit.py::test_mismatch_the_second_fresh_run_reproduces_the_cache_is_flaky_with_evidence` | pass | pass (unchanged behaviour) |
| Rust `audit::tests::verdicts` | FAIL: `left: FlakyEvidence, right: Wrong` | **pass** |

## Full suites (after, MEASURED)

* `cargo test --workspace`: **53 passed**, 0 failed.
* `pytest tests/`: **200 passed, 8 skipped, 2 failed** in 880 s. The two failures are already known and accepted;
  neither comes from this change:
  * `test_review_r013.py::test_r013_4_…`: fails only at its last line, `assert 0.9747 > upper_bound_95(2, 0) = 1.0`.
    The round-2 review rules that line unsatisfiable for n ≤ 3. The replacement test
    `test_cache_audit_r013.py::test_service_bound_reflects_a_wrong_skip_found_by_a_pull_request_job` passes.
  * `test_review_r008d.py::test_finished_startup_process_that_left_a_daemon_is_not_ignored`: pre-existing R-008d
    failure.
* Compared with the review's run (197 passed, 9 skipped, 3 failed): r013_5 now passes and the new test passes. One
  test that was skipped there passed here. The skip count depends on the environment; nothing was skipped or
  disabled by this change.
* Every other audit test passes: `test_cache_audit.py`, `test_cache_audit_r013.py`, and `test_review_r013.py` 1–3.

## Docs

* `docs/CACHE-AUDIT.md` step 3:
  * New rule: wrong unless the second run reproduces the cached result.
  * Why the two fresh runs need not agree: order-dependent tests run alone versus state carried within one process.
  * The cost of a false "wrong" (only reruns of that key).
* `docs/CACHE-AUDIT.md` Limits: the new-process caveat is updated, plus a note that "wrong" is conservative.
* The module docstrings in `audit.rs` and `proofcache.py` were updated the same way.

## Not done / unchanged

* The fenvix-app patch was not touched. The fix is in the engine core, not in `cache_service.py`, so the vendored
  file is unchanged. Only `engineCliCommit` would move in fenvix-app. The app suites were still not run, because
  this session cannot reach fenvix-app.
