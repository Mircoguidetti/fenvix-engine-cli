PENDING

# P0 big trace: no false green on big traces

Branch `claude/p0-big-trace` from `origin/claude/release-1` f67be4a3. Machine: this container, nproc 4, 15 GB RAM,
Node v22.23.5, rustc stable. Spec: the session prompt (D1 A of the eng review, 2026-11-23).

## Changes to tests, validators, CI, thresholds (rule 3)

- No existing test was removed, skipped or weakened; no existing test file was edited.
- `release/python-tests.txt`: one line added, `shared tests/test_runner_node_p0.py` (the new runner test file must be
  classified, `release/shard.py` refuses unclassified files; `shared` because it exercises runner/fenvix-run's Node
  path, like `tests/test_runner_node.py` next to it).
- `src/parallel-rerun.js accountRerun` (pure function under test) also reads `r.never_started`; records with `events`
  (what `test/parallel-rerun-account.test.js` passes) are read as before. That test file is unchanged and passes.
- New tests: `node/test/trace-lines.test.js` (9), `node/test/big-trace.test.js` (13), `tests/test_runner_node_p0.py`
  (2), `crates/detpy-core/tests/golden_verify.rs` (1, over 61 golden cases), `record_source` unit tests (3), and the
  `#[ignore]` generator `golden_corpus_generate`. Each states `protects=...; fails_when=...; no_claim=...`.

## Commits

1. 91ad4e4 `verify: golden corpus of today's verifier` -- generator + 61 cases of fixtures, verify logic unchanged
   (generated on f67be4a3's verifier; the generator asserts in-memory and file reports agree).
2. 5a1e3b1 `verify: bounded memory (RecordSource, MemTrace, FileTrace, judge_slim)`.
3. d2adbf8 `detjs: stream every trace reader, fail closed when the status is unknown` (+ the item 5 fix).
4. bcfe275 runner tests (criterion 5), `harness/p0_remeasure/` copied from `origin/claude/p0-remeasure` 6b18711c.
5. this report.

## Criteria

RESULTS
