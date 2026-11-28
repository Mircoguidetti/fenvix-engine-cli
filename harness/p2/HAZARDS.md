# P2: what is behind two hazard findings (founder decisions R1 alakajam = A, R2 agentlang = A, 2026-11-28)

A bounded investigation, no engine change. The decision comes back to the founder.

## alakajam: why all 27 files end up in one lane

The hazards of the head's w4/w2 rounds on boot b0517ae9 (`data/fix-2/alakajam/P*w*.jsonl`, `meta.parallel.hazards`):

| round | hazards | by kind and path | together-edges in the plan |
|---|---|---|---|
| r1 w4 | 46 | read-write `data/tmp/unit-test.sqlite` 25; recursive-write `data` 11; read-write `data/tmp` 9; list-write `data/tmp` 1 | 0 |
| r1 w2 | 33 | read-write `data/tmp/unit-test.sqlite` 14; recursive-write `data` 10; read-write `static/uploads` 7; list-write `data/tmp` 2 | 0 |
| r2 w4 / w2 | 5 / 6 | recursive-write `data` | 21 / 20 |
| r3 | 0 | (all pairs already together) | 26 |

The paths and the code behind them:
- `data/tmp/unit-test.sqlite`: the test database. `server/testing/testing-db-config.ts` points every spec at this one
  SQLite file; `server/testing/testing-db.ts` `startTestDB()` (each database spec's setup) empties it
  (`db.emptyDatabase()`), migrates it and seeds it; `closeTestDB()` empties it again. The repository's own config says
  so: `vitest.config.ts` `fileParallelism: false`, "Specs share a single sqlite database".
- `data` (recursive-write) and `data/tmp`: `startTestDB()`'s `mkdirpSync(path.dirname(DB_SQLITE_FILENAME))`, and
  `server/core/fs-utils.spec.ts`, which writes and removes a directory with a `unit-test.sqlite` in it (`fs.rmSync`
  recursive, line 15).
- `static/uploads`: not traced to a line; probably the upload paths (`server/migrations/0030_uploads_in_data.ts`, the
  upload middleware's temp files).

Does an outcome depend on the order between the files? Plain Vitest, one file at a time (`vitest run
--no-file-parallelism`), in four file orders (the default and `--sequence.shuffle.files` with seeds 11, 22, 33): 217
passed, 4 skipped in every order, and the same outcome for every one of the 221 tests (0 differ). So not on the order:
each database spec rebuilds the database before it runs.

Does an outcome depend on files running at the same time? Yes. Plain Vitest with files in parallel (the protocol's
`plain_par` rows, `data/baseline` and `data/fix-2`, 12 runs): 117-143 tests skipped in every run and up to 26 failed,
against 217 passed in every plain serial run. The database is a real conflict for concurrency, not for order.

## agentlang: who reads `logs/app-<date>.log`

- Written by the application's logger, `src/runtime/logger.ts`: winston with `winston-daily-rotate-file`,
  `filename: 'logs/app-%DATE%.log'`, `maxSize: '20m'` (and `logs/errors-%DATE%.log`).
- Read: no test file and no application code reads it (no match for `logs/app` or the log's name in `src/` and `test/`
  outside `logger.ts`). The "read" side of the hazard is the rotation library, `file-stream-rotator` 0.6.1
  (`FileStreamRotator.js` 510-516): at start-up it checks `existsSync(logfile)` and `statSync(logfile).size` (for the 20 MB
  rotation) and reads its own audit JSON files (`logs/.<hash>-audit.json`, line 221); it never reads the log's content.
- Does an outcome depend on it? Plain Vitest (`vitest run`) with `logs/` removed, with today's
  `logs/app-<date>.log` pre-filled with 1 MB of unrelated text, and as it was: 438 passed in all three, the same outcome
  for every test (0 differ). The directory was restored afterwards.

So every test file of agentlang writes the log and the rotator stats it, and nothing that decides an outcome reads it.
