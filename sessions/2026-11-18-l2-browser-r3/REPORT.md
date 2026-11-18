PARTIAL

# REPORT · L2 browser round 3 (review R-011 fixes + experiments E1, E2, E5, E6)

Draft written while the Actions runs are in progress: run 44326292154 (batch 1) and 44326636551 (batch 2).
Sections marked PENDING are filled when their results land.

## 1. The six review tests

| Test | Before (786181b) | After | Change |
|---|---|---|---|
| R1 `node/test/review-r011.test.js` | fails | passes | worker clock: real waits floored to 1 s are added |
| R2 same file | fails | passes | worker clock aligned with the server's message clock |
| H1 `tracks/l2-browser-r2/review/test_review_r011.py` | fails | passes | aggregate.py: control-induced targets out of the exit number |
| H2 | fails | passes | same |
| H3 | fails | PENDING (re-measurement of actual's printed command) | replay command keeps `--browser` |
| H4 | fails | passes | aggregate.py: "hidden by the controls" counted |
