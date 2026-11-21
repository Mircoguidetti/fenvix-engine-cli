# R-058 free review — verifier block

**5 wrong results. 4 non-blocking findings.**

Verdict against the bar fixed in advance (PASS = zero wrong results): **FAIL.**

One of the five is a **new shape**, not another instance of the family found so far. It is #4. If you
read one thing, read #4.

## Scope and provenance

- Head reviewed: **03f96bb** (`report: what the reviewer round and CI found, and where the rule's
  cost really is`). This is one commit **past** the 31ff5697 named in my brief; 31ff569 is its
  parent. `origin/claude/verifier-cli` was at 03f96bb when I fetched it at 22:15 UTC.
- Branch: `claude/review-verifier-r058`.
- **I never obtained my brief.** `prompts/R-058-free-reviewer.md` and `prompts/COMMON-BLOCKS.md` in
  `fenvix-brain-cli` were unreachable: `add_repo` was denied by this session's auto-mode classifier
  ([Unauthorized Access]), and a read-only `get_file_contents` is refused because the session's
  GitHub scope is `mircoguidetti/fenvix-engine-cli` alone. I worked from the context in the
  launching message. Anything the brief said that was not in that message, I did not apply.
- Same reason: this report could not be written to `sessions/2026-11-21-review-verifier-r058/REPORT.md`
  on `main` of the brain. It is at that path inside the **engine** checkout instead, for copying
  across.
- No product code was changed. Every test is a new file under `crates/detpy-core/tests/`.
- Numbers below are **MEASURED** unless marked otherwise.

## Tests

```
cargo test -p detpy-core --test r058_false_identical          # 0 passed, 1 failed
cargo test -p detpy-core --test r058_empty_fingerprint        # 0 passed, 3 failed
cargo test -p detpy-core --test r058_unknown_sensor_fails_open # 1 passed, 2 failed
cargo test -p detpy-core --test r058_stdin_and_truncation     # 2 passed, 2 failed
```

MEASURED: 8 failing tests over 5 wrong results; 3 passing tests, which are the regression tests for
attacks the engine survived and the control case for #4.

---

## #4 — NEW SHAPE — `judge` has no list of sensors it knows, and clause 3 fails open

`required_controls` (crates/detpy-core/src/provable.rs:917) ends:

```rust
} else {
    // a sensor the core does not know: clause 1 of `judge` has already refused it
    &[]
}
```

**Clause 1 has not refused it.** Clause 1 checks three things: that the sensor string is non-empty,
that `contract` equals `SENSOR_CONTRACT`, and that `surface` equals `surface_digest()`. It never
compares the *name* against anything. The only two places any sensor name is inspected in the whole
file are the `starts_with("py-")` and `starts_with("node-")` tests inside `required_controls`
itself.

So for any sensor name outside those two prefixes, clause 3 — the clause whose entire job is to
refuse a run that had a `--det` control switched off, i.e. the fix for the `judge`-ignores-controls
bug already found in this block — iterates an empty list and passes.

**Live in the product, by the path "a Node run served entirely from the cache":**

1. `node/src/session.js:327` (`provableField`): when no process declared a sensor — which is exactly
   the fully-cached run, because nothing ran — the run declares sensor **`cache-reuse/1`**.
2. `crates/detpy-node/src/lib.rs:319` (`provable_header`) stamps this core's real `SENSOR_CONTRACT`
   and real `surface_digest()` onto whatever name it is handed.
3. `cache-reuse/1` starts with neither prefix → `required_controls` → `&[]` → no controls required.

MEASURED (`r058_unknown_sensor_fails_open.rs`): `judge` returns `Provable` for `cache-reuse/1` with
`controls: []`, and likewise for `totally-made-up/9`, `x`, `py`, `node`, `deno-whatever/1`.

The third test in that file is the control: the same call with `py-monitoring/1` and `node-vitest/1`
returns `NotProven`. It passes. That contrast is what makes this a hole and not a design.

End to end, with the header a fully-cached Node run really writes
(`two_fully_cached_runs_with_every_control_off_are_not_reported_identical`):

```
verdict: IDENTICAL: all 1 tests ran with the same inputs and observed the same events
covered by Level 0: 1  not covered: 0  missing: 0  input differs: 0  not proven: 0
```

for two runs that ran nothing, recorded no fingerprint, and had every `--det` control off.

**Why this is a new shape.** The six found so far were a verdict resting on an *absence*: absent
data, or an absent caller, read as a presence. This one is a **fail-open default whose safety
argument is a comment asserting that a different clause already refused — a clause that performs no
such check.** The guard is present; the premise written underneath it is fiction. A reader auditing
clause 3 reads the comment and stops. That is a different failure mode from the others, and it sits
on the control path the previous fix was supposed to close.

---

## #1 — the verifier never checks a record's fingerprint against that record's own events

`fingerprint::fingerprint_of` (crates/detpy-core/src/fingerprint.rs:218) carries this doc comment:

> Recompute the fingerprint of a complete (non-truncated) event list.
> **Used by the verifier to validate traces** and by tests.

`grep -rn fingerprint_of --include=*.rs .` returns three hits: the definition and two lines of its
own unit test. **Zero callers.** The declared validation does not exist.

- `verify::verify` reaches `diff_records` only on the branch where the stored strings *differ*
  (verify.rs:912, `distinct.len() <= 1`). When the strings agree, the events are never read.
- `trace::read_trace_from` validates nothing about a record: not the fingerprint, not `n_events`
  against `events.len()`, not `counts`, not `checkpoints`. `check_compatible` compares only the
  header's self-declared `encoding` number.
- `render_text` (verify.rs:1175) then prints "observed the same events" — strictly stronger than
  what was checked, which is only "the two strings matched".

MEASURED (`r058_false_identical.rs`): two traces, one recording `random.random @ t.py:4 = 0.1` and
one `= 0.9`, with matching `fingerprint` fields, produce

```
verdict: IDENTICAL: all 1 tests ran with the same inputs and observed the same events
```

Both pass `check_compatible` and every clause of `provable::judge` with a genuine sensor, contract,
`surface_digest()`, audited runtime and all required controls on.

**Honest limit on reachability, stated because it changes the severity.** Inside Rust, no
first-party producer emits such a trace: `TestRecord` is only ever built by `Fingerprinter::finish`.
The one fallback that would have produced one — `node/src/cache/trace-reused.js:33` — is **not**
reachable, because `checkFile` (node/src/cache/proof.js:558) bails out on any missing test receipt
and returns `receipts` aligned with `tests`. So this is "the verifier trusts its input, and the doc
comment promising otherwise is unimplemented", **not** "a real run produces this". I report it as a
wrong result anyway for three reasons: the doc comment shows the check was intended and is simply
missing; nothing in the format signs or self-digests a record, while `concat_traces` copies records
verbatim out of parts it did not produce; and the verdict sentence makes a claim the code does not
check. Rank it below #4 and #2 if you are triaging.

---

## #2 — the empty fingerprint is compared as if it were a value

`""` is what a shell writes when it has **no evidence at all** about a test:

| site | when |
|---|---|
| `node/src/vitest/shell.js:31` | a test that never reached the runner hooks (a failing hook, or a filter) — routine, not defensive |
| `node/src/jest/runner.js:391` | tests circus never bracketed (a failing `beforeAll`) |
| `node/src/runners/common.js:641` | `notRun` (skipped, todo) |
| `node/src/isolate.js:160` | a test an isolate lost |
| `node/src/cache/trace-reused.js:33` | a reused test whose receipt holds none |
| `node/src/cache/remote.js:361` | a remote entry without one |

`STATE.endTest` (node/src/state.js:125) returns `null` when there is no recorder, and
`capture.js:999` turns that into `''`.

MEASURED: grepping `verify.rs`, `proof.rs`, `provable.rs` and `trace.rs` for an empty-fingerprint
guard returns **nothing**. So the verifier compares `"" == ""`, calls the test `STABLE`, counts it
under "covered by Level 0", and prints "observed the same events" for a test about which it holds
no evidence (`a_test_with_no_recorded_fingerprint_is_not_reported_identical`).

---

## #3 — `proof::prove` returns `Proven` on `"" == ""`

`prove` (proof.rs:170) asks "same key, and the stored serial fingerprint equals the parallel one".
With both empty that is `"" == ""` → `Proof::Proven`, so a parallel entry that recorded nothing is
admitted as the serial result and a later serial session reuses it.

MEASURED (`an_empty_fingerprint_does_not_prove_a_parallel_result_equal_to_the_serial_one`).

Smaller blast radius than the others: both sides must be evidence-free, and an evidence-free entry
is a test that did not run. I am not inflating it.

---

## #5 — `_io`: a test that reads standard input is `Provable`

The `_io` doc comment (provable.rs:427) states the gap itself and calls it "the one place this
table's claim is weaker than the rest": a stream that is not a file has no `open` behind it, "a test
that reads `sys.stdin` goes through the same `_io` methods, and nothing records what it read."

My brief asked me to confirm or break it. **Confirmed, and the consequence is a false green, which
the comment stops short of saying:** because `_io.read` answers `Accounting::Recorded` rather than
`Unaccounted`, a stdin read puts nothing in the record's `unaccounted` list, so clause 5 of `judge`
has nothing to refuse and the test is `Provable`. Two runs fed different standard input compare
equal on every field the verifier looks at.

MEASURED (`r058_stdin_and_truncation.rs`): `account("_io", "BufferedReader.read")` is `Recorded`;
`judge` on the resulting attestation is `Provable`.

**ESTIMATED / UNKNOWN:** this is measured at the level of the accounting table and `judge`. I did
**not** run it end to end through the pytest plugin — the extension is not built in this container
and `maturin` is not installed — so the end-to-end behaviour is **UNKNOWN**. It rests on the doc
comment's own statement that nothing records what stdin returned. Counted as a wrong result because
the engine answers IDENTICAL rather than NOT PROVEN; flagged clearly as pre-disclosed in the code so
nobody reads it as padding. Whether a documented gap counts against this block is the founder's call,
not mine.

---

## Attacks the engine SURVIVED — do not re-run these

| attack | result |
|---|---|
| `--det-max-events` truncation hiding a mark or an unaccounted entry | **Survived.** `Fingerprinter::push` updates `counts`, `uncontrolled` and `unaccounted` *before* the `events.len() < max_events` check, so the sets survive even at `max_events = 0`. Regression test passes. This is the earlier "a count that read zero because the evidence had been truncated" bug; it is fixed. |
| truncation collapsing two executions onto one fingerprint | **Survived.** The chain covers every event, stored or not. Regression test passes. |
| `--det-disable` against the Python shell | **Survived.** `controls_of` (python/detpy/_level0.py:248) is honest: `frozenset(CONTROLS) - off`, and it raises on an unknown control. Every entry of `required_controls("py-…")` is in `CONTROLS`, so disabling any of them is caught by clause 3. (The hole is #4, which is reached by an unknown *sensor*, not by a disabled control.) |
| a known sensor with no controls declared | **Survived.** `py-monitoring/1` and `node-vitest/1` with `controls: []` both return `NotProven`. This is the control case for #4 and it passes. |
| trace format / encoding skew between shell and core | **Survived as far as the declared fields go.** `read_trace_from` refuses an unknown `format` and a `version` above `TRACE_VERSION`; `check_compatible` refuses mismatched `encoding`. Not a defect I can demonstrate: a shell that declares `encoding: 2` while actually encoding differently is a release-process failure, not a code path. Note it interacts with #1 — the chain is never checked against the encoding number that is declared. |
| a reused test whose receipt is missing, defaulting to `passed` | **Not reachable today.** `checkFile` bails out first. See non-blocking #2 — the default is still there. |

## Not attempted, so UNKNOWN

- A C extension built at test time (needs a real build; `maturin` absent).
- The Python plugin end to end, including `sys.stdin` (same reason).
- `--det-disable` combinations through a live pytest run.

## Non-blocking findings

1. **`admit_record` still has zero callers at this head.** Only its definition (cache.rs:125), the
   comment citing it (`node/src/session.js:340`) and two rows in `docs/REPORT-verifier-rule.md`. Row
   301 of that doc presents it as closed ("Made true: a gap now goes through `STATE.onLevel0Gap`").
   The gap may well be closed by that other route, but the citation in session.js is still a premise
   nothing implements — and it is the premise sitting directly above the `cache-reuse/1` declaration
   in #4. Same mechanism as #4: a comment carrying a safety argument that the code does not make.
2. **`node/src/cache/trace-reused.js:33` defaults a missing receipt to `outcome: rc.outcome || 'passed'`.**
   Unreachable today (see above), but the default for "no evidence" is a *pass*, beside a default of
   `''` for the fingerprint. If `checkFile`'s alignment ever loosens, this fabricates a green.
3. **`trace::read_trace_from` validates no internal consistency**: `n_events` vs `events.len()`,
   `counts` vs the events, `checkpoints` vs the chain. Contributes to #1; worth its own note because
   a cheap `debug_assert`-style check at load would have caught #1's construction.
4. **`required_controls("py-…")` omits `order` and `bytecode`** from the nine it lists. I judge this
   defensible — test order is compared separately via `order_digest` / `order_divergence`, and set
   iteration order is already pinned by the required `hashseed` — but it is an asymmetry between
   `CONTROLS` (11) and the required set (9) that a reader will trip over, and the reason is not
   written down where `required_controls` is.

## Suggested triage order

#4, then #2, then #5, then #3, then #1. #4 is the only one that is both live in the product on a
default path and a shape nobody has seen yet. #1 is last because, with the Rust producers honest, it
needs an input the engine did not write — but the fix is one call to the function whose doc comment
already promises it.
