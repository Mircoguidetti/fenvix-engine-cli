# R-058 free review — verifier block (`claude/verifier-cli`)

**5 wrong results. 4 non-blocking findings.**

Verdict against the bar fixed in advance (PASS = zero wrong results): **FAIL.**

**#4 is a NEW SHAPE** — not another instance of the family found on 2026-11-21. If you read one
thing, read #4. Three of the other four are the known family and I say so for each.

Review stopped on the founder's order at 22:29 UTC, mid-review. Written up in full below.

## Scope and provenance

- **Head reviewed: `03f96bb`** (`report: what the reviewer round and CI found, and where the rule's
  cost really is`). One commit **past** the `31ff5697` named in my brief; `31ff569` is its parent.
  `origin/claude/verifier-cli` was at `03f96bb` when I fetched at 22:15 UTC. Stated here because the
  coordinator asked me to say so in the report.
- Branch `claude/review-verifier-r058`. No product code changed; every test is a new file under
  `crates/detpy-core/tests/`.
- **The brief reached me only at 22:29 UTC**, after the review was done, pasted by the coordinator
  because `fenvix-brain-cli` is unreachable from this session (`add_repo` denied by the auto-mode
  classifier; GitHub scope is `fenvix-engine-cli` alone). Findings #1–#5 were produced from the
  launching message's context, before I had read the brief. Having now read it, nothing in it changes
  a verdict below, and its "DECLARED" label — which the launching message omitted — is applied in
  the table at the end.
- Numbers are **MEASURED** unless marked otherwise.
- **`5864750d` landed after I began** (the Python sensor's stack-depth attribution). None of my five
  touch that code path, but I did not re-run against it: the stop order forbids new work. Treat every
  result below as measured at `03f96bb`.
- Separate from my five: CI found a wrong result at `31ff5697` —
  `test_a_channel_derived_from_the_engines_own_table_is_not_proven`, `posix.DirEntry` reported
  IDENTICAL. Not mine, not re-derived here, already with Block 1.

## Tests

```
cargo test -p detpy-core --test r058_false_identical           # 0 passed, 1 failed
cargo test -p detpy-core --test r058_empty_fingerprint         # 0 passed, 3 failed
cargo test -p detpy-core --test r058_unknown_sensor_fails_open # 1 passed, 2 failed
cargo test -p detpy-core --test r058_stdin_and_truncation      # 2 passed, 2 failed
```

MEASURED: 8 failing tests over 5 wrong results; 3 passing tests, being the regression tests for
attacks the engine survived plus the control case for #4. Four files, five wrong results — the
counts differ because `r058_empty_fingerprint.rs` carries two distinct wrong results (#2 and #3)
and `r058_stdin_and_truncation.rs` carries one wrong result (#5) plus two survivals.

---

## #4 — NEW SHAPE — `judge` has no list of sensors it knows, and clause 3 fails open

**Cause.** `crates/detpy-core/src/provable.rs:917`, `required_controls`, final branch:

```rust
} else {
    // a sensor the core does not know: clause 1 of `judge` has already refused it
    &[]
}
```

Clause 1 of `judge` (`provable.rs:987`) has **not** refused it. Clause 1 checks three things: the
sensor string is non-empty; `contract == SENSOR_CONTRACT`; `surface == surface_digest()`. It never
compares the *name*. The only two places any sensor name is inspected in the file are the
`starts_with("py-")` / `starts_with("node-")` tests inside `required_controls` itself
(`provable.rs:918`, `:923`).

So for any sensor name outside those two prefixes, clause 3 — the clause whose sole job is to refuse
a run that had a `--det` control switched off, i.e. the fix for the `judge`-ignores-controls bug
already found in this block — iterates an empty list and passes.

**Reachable by a first-party producer: YES, on a default path.**
1. `node/src/session.js:327` (`provableField`): when no process declared a sensor — which is exactly
   the fully-cached run, because nothing ran — the run declares sensor **`cache-reuse/1`**
   (`session.js:341`).
2. `crates/detpy-node/src/lib.rs:319` (`provable_header`) stamps this core's real `SENSOR_CONTRACT`
   and real `surface_digest()` onto whatever name it is handed.
3. `cache-reuse/1` matches neither prefix → `required_controls` → `&[]` → no controls required.

**Verbatim verifier output** (`two_fully_cached_runs_with_every_control_off_are_not_reported_identical`),
header as `provableField` writes it, `controls: []`:

```
detpy verify: 2 runs, 1 tests
  run 0: /tmp/.tmpQJYGm7/all_cached_a.jsonl
  run 1: /tmp/.tmpQJYGm7/all_cached_b.jsonl
verdict: IDENTICAL: all 1 tests ran with the same inputs and observed the same events
run inputs: identical in every run
order: identical in every run
covered by Level 0: 1  not covered: 0  missing: 0  input differs: 0  not proven: 0  outcome-unstable: 0
STABLE   t.test.ts > draws
```

Two runs that ran nothing, recorded no fingerprint, and had every `--det` control off.

At the predicate directly (`r058_unknown_sensor_fails_open.rs`): `judge` returns `Provable` for
`cache-reuse/1` with `controls: []`, and for `totally-made-up/9`, `x`, `py`, `node`,
`deno-whatever/1`. **The control case passes**: the same call with `py-monitoring/1` and
`node-vitest/1` returns `NotProven`. That contrast is what makes this a hole and not a design.

**Family: NEW.** My reasoning, in full, because the coordinator asked for it specifically.

The six found on 2026-11-21 were all *a verdict resting on an absence*: a mark suppressed because a
feature was on; a count that read zero because evidence was truncated; a sensor armed on one import
form and not the other; a per-test set never cleared; `judge` not consulting controls; a declaration
citing a function with no callers. In each, something that should have been present was absent, and
the absence was read as a presence.

This one is different in mechanism. The guard **is** present and **does** run. What is absent is the
check that its permissive fallback cites as its justification. `required_controls`' `else` branch is
safe *if and only if* clause 1 rejects unknown sensors; the comment asserts that it does; it does
not. So the failure is **a fail-open default whose safety argument is a comment about a check that
does not exist.** A reader auditing clause 3 reads the comment and stops — the comment is load-bearing
and false.

It also differs in consequence: the other instances dropped or suppressed a *finding*. This one
removes an entire *clause* for a whole class of runs, and the class is not exotic — it is every
fully-cached Node run. Note the relation to the coordinator's hypothesis about `31ff5697` (a
presentation concern deciding a verdict): this is not that. Nothing here is about who made the call
or where the frame is; it is about a name never being checked against anything.

It is adjacent to, but not the same as, the known `judge`-ignores-controls item. That one was
"clause 3 does not exist". This one is "clause 3 exists and has a hole precisely where the sensor is
unrecognised" — a gap in the fix for a previously-found bug.

**Note on the brief's own wording.** COMMON-BLOCKS.md states: "an unknown sensor means NOT PROVEN for
every test" and "`required_controls(sensor)` refuses before any name is looked up". Both are DECLARED,
and both are false at `03f96bb`: an unknown sensor is `Provable`, and `required_controls` refuses
nothing for one. The rule the block is written against and the code diverge here.

---

## #1 — the verifier never checks a record's fingerprint against that record's own events

**Cause.** `crates/detpy-core/src/fingerprint.rs:218`:

> ```
> /// Recompute the fingerprint of a complete (non-truncated) event list.
> /// Used by the verifier to validate traces and by tests.
> pub fn fingerprint_of(events: &[Event]) -> String
> ```

`grep -rn fingerprint_of --include=*.rs .` returns three hits: the definition and two lines of its
own unit test (`fingerprint.rs:290`, `:296`). **Zero callers.** The declared validation does not exist.

- `verify::verify` reaches `diff_records` only on the branch where the stored strings *differ*
  (`verify.rs:912`, `distinct.len() <= 1`). When they agree the events are never read.
- `trace::read_trace_from` (`trace.rs:301`) validates nothing about a record: not the fingerprint,
  not `n_events` against `events.len()`, not `counts`, not `checkpoints`. `check_compatible`
  (`verify.rs:1112`) compares only the header's self-declared `encoding` number.
- `render_text` (`verify.rs:1175`) then prints "observed the same events" — strictly stronger than
  what was checked, which is "the two strings matched".

**Verbatim verifier output** (`r058_false_identical.rs`), run A recording
`random.random @ t.py:4 = 0.1`, run B recording `= 0.9`:

```
detpy verify: 2 runs, 1 tests
  run 0: /tmp/.tmp1hOne2/run_a.jsonl
  run 1: /tmp/.tmp1hOne2/run_b.jsonl
verdict: IDENTICAL: all 1 tests ran with the same inputs and observed the same events
run inputs: identical in every run
order: identical in every run
covered by Level 0: 1  not covered: 0  missing: 0  input differs: 0  not proven: 0  outcome-unstable: 0
STABLE   t.py::test_draw
```

Both traces pass `check_compatible` and every clause of `judge` with a genuine sensor, contract,
`surface_digest()`, audited runtime and all nine required controls on.

**Family: the known family**, and specifically the same sub-shape as `admit_record` — a declaration
citing a function with zero callers, sitting on the answer that must never be wrong.

**Reachable by a first-party producer: NO, inside Rust — this is my own narrowing of my strongest
finding, and it lowers the severity.** `TestRecord` is only ever built by `Fingerprinter::finish`
(`grep -rn "TestRecord {"` → the definition, `finish`, and test helpers only). The one fallback that
would have produced such a trace, `node/src/cache/trace-reused.js:33`
(`fingerprint: rc.fingerprint || ''` beside `outcome: rc.outcome || 'passed'`), is **not reachable**:
`checkFile` (`node/src/cache/proof.js:558`) returns on the first missing test receipt and otherwise
returns `receipts` aligned with `tests` (`receipts` is seeded with the file entry and pushed once per
test, so `receipts.length == tests.length + 1` and the `slice(1)` indexing in trace-reused.js lines
up). So this is **"the verifier trusts its input, and the doc comment promising otherwise is
unimplemented"**, not "a real run produces this".

Reported as a wrong result regardless, for three reasons: the doc comment shows the check was
intended and is simply missing; nothing in the format signs or self-digests a record, while
`concat_traces` (`trace.rs:~340`) copies records verbatim out of parts it did not produce and the
Node shells write one part per test file, so the verifier's inputs are already not all first-party;
and the verdict sentence makes a claim the code does not check. **Rank it last of the five.**

---

## #2 — the empty fingerprint is compared as if it were a value

**Cause.** `""` is what a shell writes when it has **no evidence at all** about a test:

| site | when |
|---|---|
| `node/src/vitest/shell.js:31` | a test that never reached the runner hooks (a failing hook, or a filter) — routine, not defensive |
| `node/src/jest/runner.js:391` | tests circus never bracketed (a failing `beforeAll`) |
| `node/src/runners/common.js:641` | `notRun` (skipped, todo) |
| `node/src/isolate.js:160` | a test an isolate lost |
| `node/src/cache/trace-reused.js:33` | a reused test whose receipt holds none |
| `node/src/cache/remote.js:361` | a remote entry without one |

`STATE.endTest` (`node/src/state.js:125`, `:149`) returns `null` when there is no recorder, and
`node/src/cache/capture.js:999` (`fingerprint: fingerprint || ''`) turns that into `''`.

MEASURED: grepping `verify.rs`, `proof.rs`, `provable.rs`, `trace.rs` for `fingerprint.is_empty()`,
`fingerprint == ""` or `!r.fingerprint` returns **nothing**. No empty-fingerprint guard exists.

**Verbatim verifier output** (`a_test_with_no_recorded_fingerprint_is_not_reported_identical`), two
`--det-cache` runs each missing this test's receipt:

```
detpy verify: 2 runs, 1 tests
  run 0: /tmp/.tmpVtWvc2/cached_a.jsonl
  run 1: /tmp/.tmpVtWvc2/cached_b.jsonl
verdict: IDENTICAL: all 1 tests ran with the same inputs and observed the same events
run inputs: identical in every run
order: identical in every run
covered by Level 0: 1  not covered: 0  missing: 0  input differs: 0  not proven: 0  outcome-unstable: 0
STABLE   t.test.ts > draws
```

**Family: the known family** — an absence (no evidence) read as a presence (a value that matched).

**Reachable by a first-party producer: YES** for the `''` itself — `vitest/shell.js:31` and
`jest/runner.js:391` are ordinary paths, not defensive ones. The specific trace line my test writes
comes from `trace-reused.js`, whose missing-receipt branch is blocked by `checkFile` (see #1); the
reachable route to the same state is a cached entry whose stored fingerprint is already `''`.

---

## #3 — `proof::prove` returns `Proven` on `"" == ""`

**Cause.** `crates/detpy-core/src/proof.rs:170` `prove`, with `Entry::serial_fingerprint`
(`proof.rs:147`): a serial entry with `placement == ""` and `serial_noise == false` returns
`Some(self.fingerprint)`. With both sides empty that is `"" == ""` → `Proof::Proven`, so a parallel
entry that recorded nothing is admitted as the serial result (`PLACEMENT_PROVEN`) and a later serial
session reuses it — "reused with proof" for a result that was never shown reusable.

MEASURED (`an_empty_fingerprint_does_not_prove_a_parallel_result_equal_to_the_serial_one`): returns
`Proven`.

**Family: the known family** — same absence as #2, in the cache's proof rather than the verifier.

**Reachable: partially.** Both sides must be evidence-free, and an evidence-free entry is a test that
did not run, so the blast radius is small. The asymmetric cases are safe: a real fingerprint against
`""` returns `Diverged` either way. Not inflating it.

---

## #5 — `_io`: a test that reads standard input is `Provable`

**Cause.** `crates/detpy-core/src/provable.rs:427` states the gap itself and calls it "the one place
this table's claim is weaker than the rest": a stream that is not a file has no `open` behind it, "a
test that reads `sys.stdin` goes through the same `_io` methods, and nothing records what it read."

My brief asked me to confirm or break it. **Confirmed, and the consequence is a false green** — which
the comment stops short of stating. Because `io_account` (`provable.rs:438`) answers
`Accounting::Recorded` for `read`/`readline`/`readinto`/… rather than `Unaccounted`, a stdin read puts
nothing in the record's `unaccounted` list, so clause 5 of `judge` has nothing to refuse and the test
is `Provable`. Two runs fed different standard input then compare equal on every field the verifier
looks at.

MEASURED (`r058_stdin_and_truncation.rs`): `account("_io", "BufferedReader.read")` is `Recorded`;
`judge` on the resulting attestation is `Provable`.

**Family: the known family** — a verdict resting on the absence of a complaint, where the absence is
caused by the table answering `Recorded` on the strength of an `fs.read` event that does not exist
for this stream.

**Reachable by a first-party producer: UNKNOWN end to end.** MEASURED at the accounting table and at
`judge`. I did **not** run it through the pytest plugin: the extension is not built in this container
and `maturin` is not installed. The end-to-end step rests on the doc comment's own DECLARED statement
that nothing records what stdin returned. Counted as a wrong result because the engine answers
IDENTICAL rather than NOT PROVEN; flagged as pre-disclosed in the code so nobody reads it as padding.
Whether a documented gap counts against this block is the founder's call, not mine.

---

## Attacks the engine SURVIVED — do not re-run these

| attack | result |
|---|---|
| `--det-max-events` truncation hiding a mark, an unaccounted entry or a count | **Survived.** `Fingerprinter::push` (`fingerprint.rs:166`) updates `counts`, `uncontrolled` and `unaccounted` *before* the `events.len() < max_events` check, so all three survive even at `max_events = 0`. Regression test passes. This is the earlier "a count that read zero because the evidence had been truncated" bug; it is genuinely fixed. |
| truncation collapsing two executions onto one fingerprint | **Survived.** The chain covers every event, stored or not. Regression test passes. |
| `--det-disable` against the Python shell | **Survived.** `controls_of` (`python/detpy/_level0.py:248`) is honest — `frozenset(CONTROLS) - off` — and raises `UsageError` on an unknown control. Every entry of `required_controls("py-…")` is in `CONTROLS`, so disabling any of them is caught by clause 3. The hole is #4, reached by an unknown *sensor*, not by a disabled control. |
| a known sensor declaring no controls | **Survived.** `py-monitoring/1` and `node-vitest/1` with `controls: []` both return `NotProven`. This is the control case for #4 and it passes. |
| trace format / version / encoding skew between shell and core | **Survived as far as the declared fields go.** `read_trace_from` refuses an unknown `format` and a `version` above `TRACE_VERSION`; `check_compatible` refuses mismatched `encoding`. Not a defect I can demonstrate: a shell declaring `encoding: 2` while encoding differently is a release-process failure, not a code path. It does interact with #1 — the chain is never checked against the encoding number that is declared. |
| a reused test whose receipt is missing, defaulting to `passed` | **Not reachable today**; `checkFile` returns first. The default is still there — non-blocking #2. |

## What I had not got to — UNKNOWN, stopped before reaching them

The coordinator's stop order listed five. Three of them I did reach, and I correct the list rather
than leave them looking open:

- `--det-max-events` truncation — **reached: survived** (above).
- `--det-disable` combinations against the Python shell — **reached at the level of `controls_of` and
  clause 3: survived** (above). Not exercised through a live pytest run: that part is UNKNOWN.
- `sys.stdin` / the `_io` claim — **reached: confirmed, wrong result #5** (above), unit-level
  MEASURED, end-to-end UNKNOWN.

Genuinely not attempted:

- **A C extension built at test time.** Needs a real build; `maturin` absent, and I did not install a
  toolchain into a review container.
- **A shell talking to a core of a different version.** Only the declared-fields half is testable
  without building two cores (see the survived table).
- The Python plugin end to end, for anything.
- The `posix.DirEntry` case CI found at `31ff5697` — deliberately not re-derived, already with Block 1.
- Re-running any of the five against `5864750d` and later heads.

## Non-blocking findings

1. **`admit_record` still has zero callers at `03f96bb`.** Only its definition (`cache.rs:125`), the
   comment citing it (`node/src/session.js:340`) and two rows in `docs/REPORT-verifier-rule.md`. Row
   301 of that doc presents it as closed ("Made true: a gap now goes through `STATE.onLevel0Gap`, and
   a process without a sensor stores nothing"). The gap may well be closed by that other route, but
   the citation in `session.js` is still a premise nothing implements — and it sits directly above the
   `cache-reuse/1` declaration in #4. Same mechanism as #4: a comment carrying a safety argument the
   code does not make.
2. **`node/src/cache/trace-reused.js:33` defaults a missing receipt to `outcome: rc.outcome || 'passed'`.**
   Unreachable today. The default for "no evidence" is a *green*, next to `''` for the fingerprint. If
   `checkFile`'s alignment ever loosens, this fabricates a pass.
3. **`trace::read_trace_from` validates no internal consistency**: `n_events` vs `events.len()`,
   `counts` vs the events, `checkpoints` vs the chain. Contributes to #1; worth its own note because a
   cheap load-time check would have caught #1's construction.
4. **`required_controls("py-…")` omits `order` and `bytecode`** from `CONTROLS`' eleven. I judge this
   defensible — test order is compared separately via `order_digest` / `order_divergence`, and set
   iteration order is already pinned by the required `hashseed` — but the asymmetry will trip a
   reader and the reason is not written where `required_controls` is.

## Suggested triage order

**#4, #2, #5, #3, #1.** #4 is the only one that is both live in the product on a default path and a
shape nobody has seen yet. #1 is last because, with the Rust producers honest, it needs an input the
engine did not write — though the fix is one call to the function whose doc comment already promises
it.

## Label key

MEASURED — I ran it and read the output. ESTIMATED — derived, not run. DECLARED — the repository or a
brief asserts it and I did not verify it. UNKNOWN — not established. Every claim above carries one;
the three DECLARED ones are: the `_io` comment's statement that nothing records stdin; COMMON-BLOCKS'
statements about unknown sensors (contradicted by #4); and `docs/REPORT-verifier-rule.md:301`'s
account of the `admit_record` fix.
