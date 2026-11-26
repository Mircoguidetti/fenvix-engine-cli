# Final suites on 3457ac64: red evidence for the quiet-probe fix

Logs of the final suites run on 3457ac64. node-s0 and node-s1 stopped after they finished; py-s0 finished; py-s2
was stopped at start for the fix. Compared with BASELINE.md, node shards 2 and 3 show failures that pass on f3c6711d (base) and on
ece09e1f (release-1). Examples:

- network-p041 G-1421 / G-1427 / G-1429: `fs.stat @ t/a.test.mjs:2 returned different values: "out|missing" vs "out|dir"`
- P1 C vitest / jest: `diverged: event #4 ... os.tmpdir`
- cache, F4 fs.cpSync, fs.promises.cp, R-009: `run 2 must reuse ...`

Cause: the footprint recorder's own probes ran through the patched fs / os, and Level 0 and the cache capture recorded
them. The probes are lstat in the mkdir and rename wrappers, realpath.native for real-path keys, and os.tmpdir in the
skip-dir check.

Bisect (P1 C jest: process.pid read by tests, with the commit's parallel.js and parallel-rerun.js in a scratch tree
at 72197258):

| parallel.js of | P1 C jest |
|---|---|
| 96c0bbbe | pass |
| cf4eb913 | pass |
| cd58a876 (recursive mkdir root: lstat probes) | fail |
| c69f9d4b, c657dd55, f80ce6cf, 72197258, 3457ac64 | fail |
| 3457ac64 + quiet() probes | pass (6/6 of the file) |

Fix: the probes run inside quiet() (STATE.quiet plus cache capture busy, like src/runners/common.js quiet). What the
footprint records is unchanged.
