# Final suites on 8848e7f8 vs BASELINE.md (f3c6711d)

Run 2026-11-26 by `suite-run.sh` in the checkout at 8848e7f8 (release-1 ece09e1f merged at 72197258), two steps at a
time. The shard lists differ from the baseline's (files were added), so the failures are compared by name.

| step | result | vs baseline |
|---|---|---|
| cargo | exit 0 (202 passed, 1 ignored in the core crate) | same |
| node 0/4 | 416 pass, 2 fail: --det-order exactly the listed tests...; two --det runs give identical fingerprints (bun) | both in the baseline (node 1/4) |
| node 1/4 | 222 pass, 3 cancelled: jest parallel lanes (plan identical / fingerprints / cache) | in the baseline (node 0/4) |
| node 2/4 | 296 pass, 1 fail: a file another test file wrote: not cacheable | in the baseline (node 3/4) |
| node 3/4 | 268 pass, 1 fail: (b) a test waiting on real work is not timed out by the virtual clock | in the baseline (node 1/4) |
| python 0/4 | 4 failed, 308 passed: test_py_cache.py x2 (same two), test_r023c_fixes e2 shutil_copy2, r056 w11 | all in the baseline |
| python 1/4 | 555 passed | - |
| python 2/4 | 360 passed | - |
| python 3/4 | 1 failed: test_packaging gate_runs_on_pull_requests... | in the baseline |
| attacks | python 1 failed (r056 w11), node 60/60 | baseline: python 12 failed (r056; 11 fixed by the release-1 merge) |

No failure that is not in the baseline. The earlier run on 3457ac64 (final-3457ac64/) had 15+ new node failures: the
footprint probes were recorded (fixed in 298e80df, 8848e7f8).
