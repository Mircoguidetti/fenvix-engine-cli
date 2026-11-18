# Cache audit: skipped tests rerun in production

A test skipped with proof is reused only when every input it read is unchanged. The proof is only as good as the
list of inputs the engine saw; the audit checks it in every customer run, not only in our studies.

## What happens in a run

`pytest --det --det-cache=... [--det-cache-audit=SHARE] [--det-cache-audit-seed=SEED]`

1. The reuse decision is made for every test as before (receipts unchanged).
2. Of the tests that would be reused, a seeded random share (default **5%**; `--det-cache-audit`, `0.05` or `5%`;
   when the option is absent `FENVIX_AUDIT_SHARE`, else 5%; `0` turns it off) is **run fresh instead**.
3. The fresh result is compared with what reuse would have shown: the final outcome of the entry's `report` (the
   phases reuse replays, not its `outcome` field) and the test ids the recorded run produced (`report.ids`, stored
   when they are not just the test's own id).
   * equal: **matched** (the fresh run is recorded as usual);
   * different: the test is run **once more, in a new process**: the first process's command line (options, ini
     `addopts`, environment) restricted to that test, so the same configuration, plugins and Level 0 controls
     (order, seeds, hash seed, clock epoch, network), and nothing the first run left in the process. The second
     process has no proof cache; its outcomes, trace, basetemp and pytest cache go to a scratch directory; it is not
     reported;
     * the second run gives what the first gave: **wrong skip**. The entry is dropped, the fresh runs are not
       recorded, and the proof key is marked **untrusted**;
     * the second run differs from the first: **flaky with evidence**. Nothing is recorded or marked, and the entry,
       which a fresh run contradicted, is **dropped** (the next run runs the test); the run reports the first fresh
       result.
     * the second run cannot be made (no outcome, timeout): **wrong** (an unexplained mismatch is never trusted).
4. The run reports what it did: terminal summary, `--det-outcomes` → `cache.audit`, `fenvix-run`'s `summary.json` →
   `audit: {share, seed, candidates, checked, matched, wrong, flaky_evidence, upper_bound_95, wrong_tests,
   flaky_tests}` and a line `[fenvix] ERROR wrong skip: ...` per wrong skip.

Audited tests **ran**: `reused_with_proof` and `test_seconds_saved` never include them, so the dashboard and the
billing never count them as skipped.

## Reproducible

The choice depends only on the seed, the test id and the share (not on the order or on which other tests exist):
`h = SHA-256(part("fenvix-audit-1") ‖ part(seed) ‖ part(test_id))`, `part(s) = u64-LE(len(s)) ‖ s` (UTF-8),
`x = u64-BE(h[0..8]) >> 11`, audited iff `x < share × 2^53`. Implemented once in the Rust core
(`crates/detpy-core/src/audit.rs`, exposed as `detpy._core.audit_chosen`); `docs/audit/chosen.mjs` is the same rule
in Node for detjs, checked against the core on 3,000 ids by `tests/test_cache_audit.py`.

The first line of the receipts is the audit's header:
`{"nodeid": null, "reused": false, "kind": "audit", "seed", "share", "candidates", "chosen": [...], "run"}`; every
audited test then has a row with its full reuse receipt (`"audited": true`) and `"audit": {"verdict", "key",
"cached", "fresh", "fresh2"}`. `--det-cache-audit-seed=<seed from the receipts>` chooses the same tests again.
Without the option every run draws a new seed from the operating system (bound before `--det-urandom` makes
`os.urandom` deterministic).

## Untrusted keys

* **Local store** (`proof-cache.json` → `untrusted: {proof key: {nodeid, run, reason}}`): `Checker::check` refuses an
  entry whose key is untrusted (`untrusted: a cache audit found this result wrong (run ...)`), wherever the entry
  came from. A **fresh** record of the same key (a test that ran in a session) clears the mark; an entry fetched
  from the shared cache does not (`Store::record` vs `Store::record_entry`). Marks survive merges of concurrent
  sessions.
* **Shared cache**: the client pushes the marks first (`POST /v1/ns/<ns>/untrusted`), before any entry. **Any token
  of the organization may mark a key**, read-only ones included: a mark only stops reuse, and a pull-request job is
  where an audit may find a wrong skip. The service keeps an append-only log of marks; a lookup leaves out every
  entry filed under the key **before** the mark (the key log's sequence number at the time of the mark); an entry
  filed after it (a fresh run that recorded the key again) is returned. The proof key of a key row is read by the
  service from the stored entry document, never taken from the request. The client also drops any candidate whose
  proof key its local store holds as untrusted (a service that missed the mark cannot hand the entry back).
* **Every machine's mirror**: before its lookup, each client reads the marks it has not seen yet
  (`GET /v1/ns/<ns>/untrusted?after=SEQ`, the last sequence number kept in the mirror's journal) and marks them in
  its local store when it holds an entry under that key, so a machine whose mirror already holds the wrong entry
  stops reusing it (its own core computes the key). A mark is applied once: after this machine's own fresh run
  records the key again, it does not come back, and a pulled mark is never pushed back.
* **Candidates from the service** are refused when the document's `proof_key` is not the key the client's core
  computes for its content (a document could otherwise dodge every mark by leaving it out), or when its `report`
  and `outcome` disagree (the engine records both from one run). A local entry whose two fields disagree is still
  reused as its `report` says (that is what the audit now compares).

## Reports per project and over all projects

* `python -m detpy.audit_report SUMMARY.json ...` (fenvix-run summaries, grouped by `project_key`) or
  `--service URL` (`GET /v1/audit`, per namespace): checked, wrong, flaky with evidence and the **one-sided 95%
  upper bound on the wrong-skip rate**: `3 / checked` when no wrong skip was found (rule of three), else the exact
  Clopper-Pearson bound (`detpy._core.audit_upper_bound`; the service and the dashboard use the same rule). In the
  service, `checked`, `matched` and `flaky_evidence` come from the run summaries, which only write tokens can file
  (pull-request jobs cannot inflate them); `wrong` counts **every token's** wrong skips: the distinct (run, test)
  pairs of the summaries and of the untrusted log. A wrong skip known only from the log is added to `checked` as one
  check (`checked_without_summary`), so the bound is conservative, never optimistic. With 3 checks or fewer every
  bound is 1.0.
* The GitHub App and the dashboard (fenvix-app, `sessions/2026-11-18-audit-reruns/app.patch` on this branch) store
  each run's counts on `ci_runs`, raise an alert per wrong skip (ERROR log line `alert: "cache_audit_wrong_skip"` and
  a `ci_audit_alerts` row the overview shows) and show the per-project and all-project bound.

## How many checks a bound needs (ESTIMATED, from the rule of three)

With no wrong skip found, the bound is `3 / checked`: 300 audited skips bound the wrong-skip rate under 1%, 3,000
under 0.1%, 30,000 under 0.01%. At 5% of the reusable tests, a project that reuses 1,000 tests per run audits about
50 per run: 0.1% after about 60 runs.

## Limits

* The second fresh run is a new pytest process: it costs a start-up (re-exec, collection of the test's file) per
  mismatch, never per audited test. State outside the process that the first run changed (a file outside the
  inputs the engine tracks, a database) can still make it differ: then the verdict is "flaky with evidence" and the
  entry is dropped all the same.
* A mark lifted by a fresh record on one machine is lifted for the service (NOTE 3 of review R-013); a write token
  can still file a wrong entry under the right key after a mark (NOTE 2, residual).
* pytest-xdist: each worker draws its own seed (written in its receipts).
* detjs: the rule and the reference implementation are here; wiring into detjs waits for its proof-cache reuse
  (branch `claude/node-cache-proof`, in progress).
