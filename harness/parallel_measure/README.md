# harness/parallel_measure — the single copy

This directory is the single copy of the parallel measurement harness. The three branch copies
(`claude/parallel-measure` @ 20f7752d, `claude/parallel-measure-b` @ 12a55133, `claude/parallel-measure-c`) are
historical; do not measure from them.

- `measure.py`, `repro.py`, `classify.py`, `table.py`, `vitest_ids_reporter.mjs`: byte-identical to
  `claude/parallel-measure` @ 20f7752d (it includes the D18 temp-dir fix).
- `specs.json`: the 14 specs of the reference; `agentic-qe`, `sqlectron`, `claudekit` from -b (each carries a
  measured reason); `smart-second-brain` from -b; the 12 specs added by -c; `wind-comic` stays the reference entry.
- `results.jsonl`, `data/`, `TABLE.md`, `REPORT.md`, `RERUN.md`, `bugs/*.md`: the reference's.
- From -b: `overrides-b.json`, `results-b-preD13.jsonl`, `TABLE-b.md` (historical), `bugs/claudekit.md`,
  `bugs/sqlectron.md`, `bugs/smart-second-brain.md`.
- From -c: `results-c.jsonl`, `results-c-pre-d13.jsonl`, `TABLE-c.md` (historical), `TABLE-c.notes.md`,
  `bugs/yalc.md`, `bugs/kodus-ai.md`, and `bugs/lerna-lite-c-pre-d13.md` (-c's `bugs/lerna-lite.md`, renamed so
  `classify.py` can write a new one).
- `data/lane-a/`: Lane A measurements (agentic-qe, lerna-lite, step 3 candidates); see `REPORT-lane-a.md`.

Rule: every measurement records in `RERUN.md` the commit of this harness (on the trunk, or on
`claude/harness-trunk` until it is merged) it was taken with, next to the engine commit `measure.py` records per row.
