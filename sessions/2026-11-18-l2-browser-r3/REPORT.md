PARTIAL

# REPORT · L2 browser round 3 (review R-011: FIX 6, experiments E1, E2, E5, E6, step 3, decision)

Session 2026-11-18, branch `claude/l2-browser-r3` of fenvix-engine-cli (= round 2 delivery `claude/l2-browser-r2` @
786181b + `review-input/` + the reviewer's six failing tests). Measurements on GitHub-hosted runners (4 vCPU) unless
marked "local" (this container, 4 vCPU). Raw data: `tracks/l2-browser-r3/results/`. Tables:
`python3 tracks/l2-browser-r3/harness/analyze.py`. Runs: PENDING.

## In one paragraph

PENDING

## 1. The six review tests (all fail on 786181b, MEASURED)

| Test | After this branch | What changed |
|---|---|---|
| R1 `node/test/review-r011.test.js` (elapsed-time budget hidden) | **passes** (local; Actions build job of run 44326292154: 18 of 18 fixture tests pass) | The test code's clock adds the real time waited since the test's first clock read, floored to 1 s (`DETJS_PW_WORKER_CLOCK_WAIT_MS`). The 1.5 s request now measures >= 1100 ms under `--det`: the test fails as it does plain |
| R2 same file (12.5 days of skew) | **passes** (same) | The test code's clock follows the app server's message clock (epoch + released messages x 100 ms), strictly increasing over the run (persisted across worker restarts). Skew in the fixture: under 1 ms. Round 2's per-test hash offset (up to 24.8 days) is gone |
| H1 `tracks/l2-browser-r2/review/test_review_r011.py` | **passes** | `aggregate.py`: a target is *control-induced* when it is in `broken_by_controls` or passes in every plain run while every default-seed `--det` replay fails; control-induced targets count toward none of "identical", "fail in some seed", "failing seed reproduces", "replay command reproduces", and are reported apart (`control_induced`) |
| H2 | **passes** | same rule: `fail in some seed` on the round-2 data is **0 of 15** (was 3; the 3 are control-induced) |
| H3 | **passes** | Cause found: actual runs `playwright test --browser=chromium` with a config without projects; the printed command kept `--project=chromium` and dropped `--browser=chromium`, so it matched no project and ran no test. Fix: the replay command carries `--browser`/`--timeout`/`--ignore-snapshots`; fixture test `node/test/l2r3.test.js` "H3" fails before (checked by restoring the old `reporter.js`) and passes after. Re-measured on actual (run 44327291710, MEASURED): seed 1 times out, the printed command `npx detjs playwright --det --det-seed=1 --det-epoch=... test e2e/accounts.mobile.test.ts:67 --project=chromium --browser=chromium` runs its test and times out too. Written into `tracks/l2-browser-r2/results/actual.json` by `tracks/l2-browser-r3/harness/remeasure_h3.py`, the round-2 value kept as `replay_cmd_outcome_r2: "missing"` |
| H4 | **passes** | `aggregate.py` counts and lists tests that fail in every configured run and pass in every `--det` run (`hidden_by_controls`): 1 on the round-2 data (documenso `should reject order change on a PENDING envelope`, FFF / PP) |

Regression suites after the fixes (local, MEASURED): `node/test/l2r2.test.js` + `playwright.test.js` 13 of 13 pass;
`l2r3.test.js` 3 of 3 pass + 1 `todo` (a defect found this round, section 6).

## 2. Corrections to the round-2 report (the claims the reviewer marked wrong)

| Round-2 claim | Corrected |
|---|---|
| "3 of 15 fail in at least one of seeds 1-8" and "Why the exploration found no reproducible failing seed" | **0 of 15**. All 3 failures are caused by the controls (plain runs of the same filter PPP): actual "keeps the search" times out in 10 of 10 default-seed replays; uptime-kuma "saves the data retention period" and "RSS feed escapes" are in uptime-kuma's broken-by-controls list. The exploration found no failing seed at all; the paragraph described our own breakage |
| Replay command "runs" for the 3 failing seeds; "1 of 3 reproduces the failing outcome" | It ran its test in **2 of 3** (actual: no outcome, cause in section 1 H3). The one that "reproduced" (uptime-kuma, F) reproduced a failure the controls cause, not a flake |
| "127 of 481 identical fingerprints" | Arithmetic right; "identical" means equal in the **2** full-suite `--det` runs (`det: 2`), not 10 of 10 |
| "Only 2 tests flaked in the baseline (both documenso update-envelope-items)" | One is `admin-find-documents ... recipient prefix matches by recipient name` (FPP), the other `update-envelope-items ... combined title and order change` (FPF) |
| "all PPP except documenso EMAIL_TRANSPORT ... passes alone" | In run 5 EMAIL_TRANSPORT ran **PFP** plain: it failed alone 1 of 3, the only target that flaked without detjs in round 2 (10 replays + 8 seeds under `--det` all pass) |
| documenso's 8 broken = 3 goto timeouts + 1 send timeout + 3 expired | 3 + 1 + 3 = 7; the 8th is `template-field-prefill v2` (toBeVisible). The 2 ablated are `persist-embed-signature` and `expired-recipient-field-signing`, not the timeouts |
| (not in any round-2 table) | documenso `update-envelope-items ... should reject order change on a PENDING envelope` fails in 3 of 3 configured parallel runs and passes with `--workers=1` and in both `--det` runs: a parallel-worker failure `--det` hides (now counted, H4) |
| Diagnosis class A on etherpad ("14 of 15 sampled: final DOM, page draw count") | The 15 samples were the first 15 diverged tests in suite order (one file). Suite-wide reasons: **net 210**, other 25, sched 17, random 8 of 260: 81% of etherpad's divergences start at a network event, unclassified |
| Class A on actual (runner acts in real time) | Supported only as "the end-of-test observation differs": the two diverging events are taken by detjs's own real-time settle loop. Tested in E2 (section 4) |
| documenso's 3 "expired" tests: ESTIMATED cause test-vs-server clock skew | Proven by R2 (12.5 days of skew on a fixture) and fixed in the engine; not yet re-measured on documenso |
| The 4 non-documenso projects were measured on the delivered engine | Run 4 (their only measurement) predates fix 697c9729; re-run in step 3 (section 5) |

## 3. E1: the target set re-established

PENDING

## 4. E2, E5, E6

PENDING

## 5. Step 3: the 4 non-documenso suites on this engine

PENDING

## 6. Found this round

- **Unread fetch body holds the network queue** (MEASURED, local fixture): a page `fetch` whose body is never read
  gets no `requestfinished`, so the queue releases nothing else until the 5 s completion timeout. Fixture: passes
  plain in 210 ms, fails under `--det` on its 2 s deadline. Test: `l2r3.test.js` "unread fetch body" (`todo`).
  Cheapest fix (ESTIMATED 2-4 hours): complete fetch/XHR items on response headers and record the body digest at a
  fixed slot of the test's event list when it arrives. Likely contributor to the remaining goto/send timeouts among
  the broken-by-controls (UNKNOWN until re-measured).

## 7. Decision

PENDING
