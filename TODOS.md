# TODOS

## P2

- **Python sensor cost and native extension audits (investigation items #2 and #3).** To be done after the Node
  product decision of 22 December 2026.
  - Context: `git show origin/claude/engine-investigation:docs/INVESTIGATION-2026-11-22.md`
  - Effort: L

## P1 — residual findings of the gstack /review of "Engine P0: no false green" (not fixed before the merge, founder decision D6)

None of these turns a red run green: the exit code never goes below pass 1's (default-deny). Each is a gap in
counts, messages or coverage.

- `meta.status` can read `failed=0` on a red run (a file that failed to load, a runner error, pass 1 red cleared in
  the trace): by B7 it counts records only; the exit code is the verdict (documented in docs/CLI.md). Decide
  whether `meta.status` should carry the exit code too.
- B5 synthetic `skipped` records go through `beginTest`/`endTest`, so per-test hooks of detjs (events, budgets) run
  for tests that never started.
- A runner's own exit code 2 maps to detjs exit 2 ("detjs error"); runner codes >= 3 collapse to 1.
- `project|file` and `file@@project` parsing is ambiguous for paths containing `|` or `@@`.
- When the wrapper cannot read pass 1's trace back, no status line is printed (a message says so).
- A nested detjs inherits `DETJS_HAZARD_RERUN` / `DETJS_HAZARD_PASS` from the wrapper's environment.
- `stampStatus` reads the whole merged trace into memory to rewrite one header line.
- Vitest positional file filters given with the hazard re-run may make pass 2 run extra files (their records are no
  longer spliced in, but they cost time).
- `footer.missing` (tests a part declared but never recorded) is not counted in `meta.status`.
- B5 is a no-op under `jest-jasmine2` (only the circus runner reports collected tests).
- A `--det-isolate` collection failure is now red: a new false-red channel if collection is flaky.
- No tests for the B5 `--det-collect` / `--det-order` guards, nor for the pass-2 splice filter.
- A test skipped in pass 2 counts as cleared in the merged trace (the exit code is unaffected).
- Effort: M overall; context: REPORT.md of branch `claude/p0-no-false-green`.
