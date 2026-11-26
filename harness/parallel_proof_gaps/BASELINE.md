# Baseline of spec parallel-proof-gaps (before any change)

Base: f3c6711d (claude/runner-proof; release-1 did not contain it at launch). Worktree `/home/user/fenvix-base`,
napi addon built from the same tree (`node scripts/build.js`), wheel `maturin build --release` of the same tree,
Node v22.23.5, Python 3.13, 4 vCPU. Run 2026-11-25 by `suite-run.sh` (one step per task; two steps ran at a time,
so timing-sensitive tests ran under load). Logs: `baseline/*.log.gz`.

| step | command | result |
|---|---|---|
| cargo | `cargo test -p detpy-core -p detpy-node` | exit 0 (202 passed, 1 ignored in the core crate) |
| node 0/4 | `node --test --test-concurrency=1 $(python3 ../release/shard.py 4 0 . 'test/*.test.js')` | exit 1: 313 pass, 3 cancelled (jest: parallel lanes: the plan is identical...; parallel fingerprints equal the serial ones; cache: recorded in parallel...) |
| node 1/4 | same, shard 1 | exit 1: 284 pass, 3 fail ((b) a test waiting on real work is not timed out by the virtual clock; --det-order: exactly the listed tests...; two --det runs give identical fingerprints; the controls are active inside bun test) |
| node 2/4 | same, shard 2 | exit 0: 186 pass |
| node 3/4 | same, shard 3 | exit 1: 316 pass, 1 fail (a file another test file wrote: not cacheable) |
| python 0/4 FULL | `python -m pytest -q -p no:randomly $(release/shard.py 4 0 tests ...) --deselect tests/test_review_r017.py::test_h2_...` | exit 1: 14 failed, 336 passed, 14 skipped (test_py_cache.py x2, test_review_r056_pycache.py x12) |
| python 1/4 FULL | same, shard 1 | exit 0: 476 passed, 19 skipped |
| python 2/4 FULL | same, shard 2 | exit 1: 1 failed, 327 passed, 27 skipped (test_r023c_fixes.py::test_e2_shutil_copy2_into_a_temporary_directory_stays_reusable) |
| python 3/4 FULL | same, shard 3 | exit 1: 1 failed, 409 passed, 20 skipped (test_packaging.py::test_gate_runs_on_pull_requests_and_trunk_only_and_cancels_only_superseded_pr_runs) |
| attacks | `python3 tests/attacks.py` | exit 1: python 12 failed, 157 passed, 2 skipped (test_review_r056_pycache.py, the same 12 as python 0/4); node 60/60 pass |

Not run: the shard-0 extra suites of release-1.yml that need their own venvs (django/nose2/ward/zope runners, numpy
+ time-machine, hypothesis + pytest-benchmark), and test_review_results.py (informational).
