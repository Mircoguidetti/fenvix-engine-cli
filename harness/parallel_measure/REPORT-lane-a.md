NOT DONE — step 4 (second merge into claude/release-1) pending; steps 1-3 done (AC1-AC5 evidence below)

# Lane A report: one harness on the trunk, the missing raw rows, three more candidates

Branch `claude/harness-trunk`. Spec: gstack /spec revision 2 (2026-11-22). Machine: this session's cloud container,
`nproc` 4, Intel(R) Xeon(R) Processor @ 2.10GHz, 16 GB (cgroup limit), recorded per row. Engine: trunk bfaf70b4 built
from this checkout; rows taken after the step 1 merge record `engine_commit` 0071cbb9, whose engine sources
(`crates python node/src node/bin Cargo.* pyproject.toml`) equal bfaf70b4. Harness: `harness/parallel_measure/` of
this branch (measure.py, repro.py, classify.py, table.py byte-identical to `claude/parallel-measure` 20f7752d),
commits ef5b0b20 (rounds of agentic-qe 1-2) to 0071cbb9 (all later rows); only docs and specs.json changed between
them. Commands: `RERUN.md` section 4. Labels: MEASURED (command in the row's `cmd`, file named), DECLARED (source
named), ESTIMATED, UNKNOWN.

## Acceptance criteria

**AC1 — DONE.** `claude/release-1` 0071cbb9 = `git merge --no-ff` of `claude/harness-trunk` 172f2721 (pushed
2026-11-23). `harness/parallel_measure/` exists on the trunk; `git diff origin/claude/parallel-measure --
harness/parallel_measure/{measure.py,repro.py,classify.py,table.py}` is empty (checked before the merge and again
now); `python3 -m py_compile harness/parallel_measure/*.py` passes. specs.json built as in step 1 (27 specs; see
"Spec conflicts"). Merge gate, founder's rule as amended on 2026-11-23 (coordinator message, confirmed by the founder
in this session):
- gstack /review (gstack 8143a91, installed with the coordinator's commands) run on the branch: 7 specialists
  (testing, maintainability, security, performance, simplification, state-machines, red-team) + 4 adversarial passes.
  Fixed: every finding in the files this branch wrote (RERUN.md, README.md, TABLE.md). Skipped by the founder
  (decision D1): 10 defects in the byte-identical copied scripts (kept for AC1; list under "Left open"). The skill
  stopped at its 3-cycle cap without converging; a 4th verification pass found nothing that blocks (Low documentation
  items open, below).
- CI (release-1.yml LIGHT): branch run 45132460278 (82e4da68) failing jobs = attacks, python 3.13 shard 3/4, node 24
  shard 1/4; trunk run 45041985747 (bfaf70b4) failing jobs = the same three. No new red. MEASURED (GitHub Actions).

**AC2 — DONE.** `data/lane-a/results.jsonl` holds, for agentic-qe and lerna-lite, 3 rounds of `plain`, `plain_par`
(2, 4), `serial` and `par` (2, 4), plus `verify` rows; `repro.jsonl` and `<repo>/classification.json` beside it.
`python3 table.py data/lane-a/results.jsonl specs.json` reproduces the `## Lane A rows` of TABLE.md (the section is
that output). Commands: RERUN.md section 4.

| repo | plain serial s | own parallel s (w2 / w4) | ratio (best) | `--det` serial s | `--det` parallel s (w2 / w4) | label |
|---|---|---|---|---|---|---|
| agentic-qe | 1387.25 | 702.88 / 390.79 | 3.55x | 4145.98 | 2593.66 / 2758.73 | MEASURED, median of 3 |
| lerna-lite | 617.64 | 311.36 / 283.35 | 2.18x | 610.73 | 611.47 / 615.71 | MEASURED, median of 3 |

lerna-lite: 2.18x MEASURED here; the earlier 601.06 s -> 282.62 s (2.13x) DECLARED in chat by session C also has
pushed D13 rows in `results-c.jsonl` (`claude/parallel-measure-c`), which the spec's "current state" did not list.
Classification (MEASURED, classify.py via classify_memo.py): agentic-qe THEIRS 83, UNDECIDED 195, OURS 30210, ENV 0;
lerna-lite OURS 107, THEIRS 0 (as -c's `bugs/lerna-lite-c-pre-d13.md`).

**AC3 — DONE.** agentic-qe, "exit 0 with failed tests": **reproduced**. All 6 `par` rows in
`data/lane-a/results.jsonl` exit 0 with failed tests in their own trace: round 1 w2 273, w4 276; round 2 w2 269, w4
275; round 3 w2 271, w4 274 (MEASURED, `outcome_counts.failed`). Reproducing command (round 1, w2), in
`/tmp/pm/repos/agentic-qe` at 9a42d9eb: `node <checkout>/node/bin/detjs.js vitest run --bail=0 --det --det-workers=2
--det-trace=<out>/P1w2.jsonl`; its output ends "318 test(s) failed under --det (seed 0, fixed order)" and the
process exits 0 (runs.log). The serial engine runs do the same: exit 0 with 170 / 168 / 169 failed. The DECLARED
"168 failed" (chat) matches a serial count, not a parallel one.

**AC4 — DONE (one with a caveat).** Admitted, each with plain parallel >= 2x plain serial (median of 3, from
`data/lane-a/results.jsonl`, full run), engine rows complete (3 rounds of `serial` and `par` w2/w4), classify.py and
`bugs/<repo>.md`:

| repo | plain serial s | own parallel s (w2 / w4) | ratio | `--det` serial s | `--det` parallel s (w2 / w4) | THEIRS / OURS / UNDECIDED / ENV |
|---|---|---|---|---|---|---|
| smart-second-brain | 153.50 | 84.91 / 56.04 | 2.74x | 168.57 | 100.70 / 64.55 | 0 / 2312 / 7 / 0 |
| agentlang | 76.99 | 39.07 / 28.24 | 2.73x | 86.04 | 86.99 / 87.72 | 38 / 399 / 2 / 0 |
| alakajam | 29.75 | 12.74 / 9.62 | 3.09x | 67.20 | 49.75 / 54.19 | 138 / 77 / 2 / 0 |

All MEASURED (rows' `cmd`). Caveat, alakajam: in its own parallel mode 8 of 27 test files fail (sqlite contention)
and 130-143 of 221 tests do not run, while plain serial passes 217 / skips 4; its own-parallel time covers less work,
so 3.09x overstates the gain. It passes the spec's rule as written; whether it counts is the coordinator's call.
agentlang: plain serial passes 439 of 439; its own parallel mode fails 21-51 tests per run (all run). smart-second-
brain: 1 test fails in every run, ENV (`shippedPromptHistory.test.ts` needs git release tags; the checkout is a
depth-1 fetch). agentic-qe also passes the rule (3.55x, full data, AC2) but is counted apart from the three.

Every repository tried (in the order of the pool: specs.json, then candidates.json):

| repo | result | evidence |
|---|---|---|
| react-confirm-alert | not admitted: UNKNOWN (ENV) | Vitest browser mode needs Playwright chromium_headless_shell-1248, absent here; 0 tests in every run |
| claudekit | rejected, 1.05x | plain 6.57 s, own parallel 6.27 s (w2) |
| sqlectron | rejected, 1.90x | plain 5.41 s, own parallel 2.85 s (w4) |
| smart-second-brain | **admitted**, 2.69x screen / 2.74x full | above |
| beevibe | rejected, 0.98x | plain 26.87 s, own parallel 27.40 s (w4); 7 of 885 tests fail every run (live API keys absent: ENV). Screened last, after the first pass had skipped it for its PostgreSQL setup, to keep the order |
| agentlang | **admitted**, 2.49x screen / 2.73x full | first attempt withdrawn (below) |
| alakajam | **admitted**, 3.35x screen / 3.09x full | first attempt withdrawn (below); caveat above |
| neat, instar, drydock, nhsuk-frontend | not tried | 3 admitted before them |
| kodus-ai | excluded | D13 rows in results-c.jsonl: 1.81x (< 2x) |
| open-knowledge, nuxt/scripts, drumhaus, prisma-examples, Python repos | excluded | TABLE-c.md "Excluded" |
| the 6 of the decision | excluded | spec |

Withdrawn first attempts: with the -c spec install (`--ignore-scripts`), agentlang's better-sqlite3 and alakajam's
sqlite3 native bindings were not built: 195 of 439 agentlang tests failed and 15 of 27 alakajam files did not load.
Their rows are kept in `data/lane-a/interrupted/*-native-binding-missing.jsonl`; specs.json now carries the measured
install (`... && pnpm rebuild better-sqlite3`, `... && npm rebuild sqlite3`). Screening rows of every candidate:
`data/lane-a/screen/results.jsonl`, log `data/lane-a/screen/step3.log`.

**AC5 — DONE.** Every number above and in the new TABLE.md rows is labelled; the TABLE rows are MEASURED table.py
output of `data/lane-a/results.jsonl`, whose rows carry their command.

## Spec conflicts resolved in step 1

- specs.json: reference 14 + smart-second-brain (-b) + 12 (-c); agentic-qe, sqlectron, claudekit from -b; wind-comic
  from the reference, as the spec says.
- `claude/parallel-measure-c` was at 1b1f6f0a, not cc765e2c: one later commit (kodus-ai row, bugs/kodus-ai.md,
  idea_verdict_c.py, mktable_c.sh, TABLE-c regenerated). Taken: results-c.jsonl, TABLE-c.md, TABLE-c.notes.md and
  bugs/kodus-ai.md at 1b1f6f0a (needed for the "< 2x" exclusion); the two scripts stay on -c (README.md).
- bugs/lerna-lite.md of -c renamed `bugs/lerna-lite-c-pre-d13.md` as the appendix says; its content is -c's bfaf70b4
  classification (README.md says so).
- TABLE-b.md / TABLE-c.md: the prescribed first line was added; README.md records their actual provenance (B's page
  is hand-written and predates B's measurements; C's was assembled by mktable_c.sh).
- REPORT.md untouched. RERUN.md section 1 corrected (it checked a measurement branch out over the single copy) and
  now discloses that the 50 nestjs-pino / agentsys rows of results.jsonl predate D18 (no per-repository TMPDIR).

## Deviations and incidents

- `--timeout 14400` instead of the default 3600: the first agentic-qe `--det` serial run hit 3600 s (exit 124);
  complete runs take 4056-4491 s. Interrupted rows: `data/lane-a/interrupted/agentic-qe-round1-timeout3600-restart.jsonl`.
- Two container restarts (likely session inactivity, coordinator): round 1 and round 3 of agentic-qe restarted from
  their start; completed rounds were never lost.
- `classify_memo.py`: classify.py's `reported()` re-reads every trace per THEIRS test (> 50 min on agentic-qe's 1.2 GB
  traces); the wrapper caches `measure.trace_tests` (pure) and calls classify.main() unchanged: same output, 91 s.
- agentic-qe `fenvix verify` was OOM-killed (exit -9, ~13.7 GB RSS on 1.2 GB traces) in 4 of 6 runs and in the serial
  noise check: those verdicts are UNKNOWN (an engine memory limit, reported for the engine sessions). The 2 completed
  ones (round 2/3, w2) say 0 of 30488 identical (all `fs` divergences).
- agentic-qe `classification.json` is 2.3 GB: the committed file keeps the summary and the THEIRS/UNDECIDED tests.
- `verify_serial_noise2w1.json` of agentic-qe was deleted by a driver line of mine (its row stays; that run had been
  OOM-killed, no verdict lost).
- My own load during measurement: a gzip of the 2.3 GB file ran during the first minute of lerna-lite round-1
  `plain` (616.70 s vs 618.31 / 617.64 s in rounds 2-3: no visible effect; `busy_before_pct` 25.1 recorded).
- agentic-qe writes outside TMPDIR (`hardcoded_tmp`: /tmp/agentic-qe-test, ...), and 80-84 tests fail in every plain
  run (the sampled message: "Transformer initialization previously failed: fetch failed", no model download here): ENV-type, not hidden; classify found ENV 0 because the
  message does not match its ENV_PATTERNS.

## Left open

- The 10 defects in the copied scripts (gstack /review, skipped for AC1 by the founder, D1): stale output files reused
  across runs; plain_par / jest / pytest runs not validity-checked in table.py; a timeout leaves the worker tree;
  a truncated trace line aborts a round; classify rule 4 substring match / unparsed verify; ENV pattern `::1` too
  broad; the Vitest reporter maps unfinished tests to skipped; engine_commit ignores built binaries; `--name` into
  rmtree; table.py hardcodes workers 2,4. Also: classify `reported()` cost (worked around), table.py's
  classification path (`<base>/<repo>/classification.json`). Proposed: a harness v2.
- Review items open (Low, documentation): RERUN sections 3-4 do not guard unset FENVIX / PM_WORK; the section 4 guard
  only prints STOP; after the merge, rows record the trunk SHA, not bfaf70b4.
- Specs that reset only a subdirectory (beevibe, open-knowledge, kodus-ai) and beevibe's database are not reset between
  runs (INVESTIGATE).
- alakajam's admission caveat (AC4).
