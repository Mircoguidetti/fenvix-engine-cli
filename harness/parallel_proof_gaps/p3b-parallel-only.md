# P3b parallel-only cases (claude/p3b-engine-only @ 7f94795, harness/p3b/PARALLEL-ONLY.md)

Five cases failed in one `--det --det-workers=4` run and passed in both plain and both w1 `--det` runs of P3b.

| # | repository | test | status | finding |
|---|---|---|---|---|
| 1 | alakajam | `server/user/user.service.spec.ts::User service::delete user::should refuse to delete users with entries` | explained, engine bug fixed (cb42cccf) | see below |
| 2 | drydock | `api/api.test.ts::API Router::should mount all sub-routers` | explained: not parallel-only; cause of the timeout open | see below |
| 3 | drydock | `api/index.test.ts::API Index::real Express: /api/v1/* traffic is never reached by the removed-alias tombstone mounted at /api` | same as 2 | |
| 4 | drydock | `api/index.test.ts::API Index::real Express: sendUiDisabledResponse lets unmatched API, health, and metrics paths fall through ...` | same as 2 | |
| 5 | drydock | `api/index.test.ts::API Index::real Express: whitelisted wud-card endpoints still serve via the compat router ...` | same as 2 | |

## 1 alakajam: explained, an engine bug, fixed

P3b par2: the `--det-outcomes` file said failed (a 5000 ms timeout), the trace's record said passed. The file
user.service.spec.ts has real read-write hazards on `data/tmp/unit-test.sqlite` and `static/uploads` with five other
files, so the hazard files were run again in one lane, where the test passed; the merged trace holds the re-run's
record. The hazard re-run wrapper strips `--det-outcomes` from pass 2 and nothing rewrote the user's outcomes file
after the merge, so the file kept pass 1's outcome. Fixed in cb42cccf (src/parallel-rerun.js `mergeOutcomes`): pass 2
writes its own outcomes file, and a complete re-run's outcomes, fingerprints and exceptions of the hazard files go
into the user's file, with `hazard_rerun {files, reported}`. Failing-first: node/test/parallel-proof-gaps.test.js
"--det-outcomes reports what the trace reports" (red on 4ed415d8 for vitest and jest:
m/alakajam-a-red-on-4ed415d8.log). The exit code is unchanged (a re-run never lowers pass 1's code). So the case is a
lane-caused failure that the engine caught and re-ran correctly; only the outcomes file reported it wrong.

Found with it (alakajam's re-run was `complete: false` in every Step M run): `server/core/rate-limiter.spec.ts` is a
whole-file `describe.skip`; its tests never start in either pass, and a never-started re-run record never accounted
for a test, so the re-run was incomplete and the first run's records were reported for all re-run files. Fixed in
cb42cccf (`accountRerun`), failing-first test in node/test/parallel-rerun-account.test.js and
node/test/parallel-proof-gaps.test.js. Cold rounds since: `complete: true` (m/cold.md).

## 2-5 drydock: not parallel-only; the timeouts are open

All four fail with `Test timed out in 5000ms` and have 0 hazards. In this session's own drydock runs (36 traces: S1/S2
serial and P1/P2 w2/w4 at every Step M point, engines f3c6711d to cb42cccf) each of the four flips between passed and
failed, in serial runs as well as parallel ones and on the before engine f3c6711d as well (e.g. `api/api.test.ts::...
should mount all sub-routers` fails in S1 at before, cb, cb3, a, a2 and passes in S1 at cb2; the three `real Express`
cases fail in S1 at a2 and pass in S1 at cb2 / cb3, and two of them fail in S1 at before as well). So they are not parallel-only and not a lane hazard: P3b's two
w1 runs passing was chance. Why these tests take more than 5 s under `--det` (real Express servers and dynamic imports
under the controls; BASELINE.md lists a related known failure, "a test waiting on real work is not timed out by the
virtual clock") is open; owner: the serial-ladder / P3 work, not this branch.
