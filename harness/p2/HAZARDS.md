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
  rotation) and reads its own audit JSON files (`logs/.<hash>-audit.json`, line 221). No read of the log's content was
  found in the start-up path read (lines 500-540); the whole library was not reviewed.
- Does an outcome depend on it? Plain Vitest (`vitest run`) with `logs/` removed, with today's
  `logs/app-<date>.log` pre-filled with 1 MB of unrelated text, and as it was: 438 passed in all three, the same outcome
  for every test (0 differ). The directory was restored afterwards.

So the hazard pairs (161 `read-write` on that file in round 1) come from the logger writing the log and the rotator
checking it in each test file's process, and no test outcome depends on the log, as measured above.

## agentlang: can the project declare `logs/` as not shared? (founder decision agentlang = A)

Checked, no engine change. The engine has a declaration for directories the footprint leaves out
(`DETJS_FOOTPRINT_SKIP_DIRS`, and the shells' `parallel.skipDirs()`), shown in the header as
`meta.parallel.skip_dirs`, with refused ones in `meta.parallel.skip_dirs_ignored` and their reason. But it honours a
directory only under `node_modules/` or strictly under `os.tmpdir()` outside the project (`src/parallel.js`
`footprintSkip()`, parallel-proof-gaps (c), gate note 3; asserted by `node/test/parallel-proof-gaps.test.js` for an
in-repo `.cache` and `fixtures`). For agentlang:

    footprintSkip('/root/pm/repos/agentlang', ['logs'])
    -> { skip: [], ignored: [{ dir: '/root/pm/repos/agentlang/logs', reason: 'outside node_modules and tmpdir' }] }

So declaring `logs/` today would be visible in the header only as ignored, and its paths would still pair files as
hazards. Supporting such a declaration for a directory inside the project is a separate founder question.

## agentlang with `logs/` declared (D10 built, 861a83bc): a shared database the footprint does not see

One fixed-epoch run at 4 workers with the head (`--det-workers=4`: C3's override; `logs/` declared through the declared
change): 54.6 s, 4 lanes, 0 hazards, no one-lane re-run, outcomes 308 passed / 78 failed / 53 skipped, against 437 of
439 passed in every serial run. Cause:
- agentlang names its SQLite database `db-${Date.now()}` in the project directory
  (`src/runtime/resolvers/sqldb/database.ts` 250-251, `mkDbName()`, unless `AGENTLANG_DB_NAME` is set). In a plain run
  `Date.now()` is real and each worker has its own file; under `--det` it is virtual and starts from the same fixed epoch
  in every lane, so every lane opens the same file (`db-1735689600000`, 2025-01-01, was left in the checkout).
- better-sqlite3 opens that file from native code, not through Node's `fs`: the footprint does not record it, and no
  hazard pairs the files.
- Before the declaration the `logs/` hazards paired every file, so the one-lane re-run covered this by accident; without
  C3's override agentlang ran serially.
Not changed: reported to the coordinator as question D11; nothing is measured with the declaration until it is answered.
