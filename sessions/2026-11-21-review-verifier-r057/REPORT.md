MERGE OK: F-01 not decided, F-02 not decided, F-03 not decided (re-check incomplete, see "Not finished").
No R-055 finding was found still broken. The session was stopped before D3, the 4 CI fixes and the coordinator's 10
added points were checked.

# Review R-057: re-check of R-055 on PR #12 (claude/verifier-cli @ bf13934)

Independent reviewer session, 2026-11-21. Branch `claude/review-verifier-r057` was cut from bf13934. Its one commit
adds this report. No product code or test file was changed. This was a re-check only, not a new review.

## How it was built and run

- Wheel: `maturin build --release --compatibility linux` → `fenvix-0.1.0-cp312-abi3-linux_x86_64.whl`, installed in a
  fresh CPython 3.13.18 venv with pytest and pytest-xdist. `detpy._core` was copied into `python/detpy` (as
  `release-1.yml` does).
- Node addon: `cargo build -p detpy-node --release`, copied to `node/detjs.linux-x64.node`, then `npm ci` (Node 22).
- `tests/test_review_r055_verifier.py` and `node/test/review-r055.test.js` on bf13934 are byte-identical to those on
  `claude/review-verifier-r055` (`git diff origin/claude/review-verifier-r055 HEAD -- <both files>` was empty).

## Results

| item | verdict | evidence |
|---|---|---|
| V1-V13, V15 (Python) | FIXED | `python -m pytest -q -p no:randomly -n 4 tests/test_review_r055_verifier.py` → `1 failed, 18 passed in 47.62s`; the one failure is V14, below. |
| V14 rusage | FIXED in the product; the R-055 test fails at its precondition | The test fails at `assert vals[0] != vals[1]`: `the attack did not change what the test observed (['43252', '43252'])`. That held in 3 of 3 runs on this machine. Run directly (the same harness, `attack(c_rusage)`), `fenvix verify` exits **1**: `verdict: DIVERGENT … resource.getrusage @ tests/test_atk.py:8 returned different values: "1540f33af814e675" vs "49ac5dfb6253b5d7"` (`clock.py` now records a digest of all the memory and I/O counters). So there is no wrong IDENTICAL. The test needs a precondition that does not depend on `ru_maxrss` changing. This is the "V14-rusage" CI item the coordinator named. |
| E1 explore | FIXED | `test_r055_explore_does_not_report_clean_when_seeds_crashed` passes, in the run above. |
| V1, V2, V3 (both), V5, V6, V8, V16 (Node) | FIXED | `cd node && node --test --test-concurrency=4 test/review-r055.test.js` → `# tests 8  # pass 8  # fail 0`. |
| D1 | FIXED | Two unchanged runs of a `ThreadPoolExecutor` test: `verdict: NOT PROVEN: 1 of 1 tests used a source this release does not control …; no test is shown to differ`, `NOT-PROVEN … [thread]`, exit 1. Same for `subprocess.run(['echo','x'])`: `NOT-PROVEN … [child]`, exit 1. No longer headlined DIVERGENT. |
| D3 repro on the E1 crash | NOT CHECKED | `fenvix repro tests/test_b.py::test_b` on the E1 project was started and then interrupted. There is no result. |

Found still broken: **none**. No case gave a wrong IDENTICAL.

## Not finished

- **D3**: the run was interrupted (above).
- **The 4 CI fixes, not run**:
  - (a) the trace footer `late` only when non-empty;
  - (b) `tests/test_network_rust.py::test_sessions_match_reference`;
  - (c) `tests/test_harness_parallel_proof.py::test_synthetic_project_and_comparison`, including whether accepting
    `fs.stat` or `fs.read` weakens it;
  - (d) `tests/test_proofcache_import_lookups.py::test_stat_bound_before_the_session[serial,n2]`.
- **The coordinator's added scope, on a new head that was never received; not started**:
  - Node: udp to localhost; stat size only; a dependency reads a project file at import; a generated client in
    `node_modules/.prisma`; a dependency with the same size and mtime.
  - Python: `os.access`; stat at module scope; a late import inside a test; `-p no:warnings`; `PYTEST_ADDOPTS`.
  - CI items: `test_capture_sessions_match_reference` and V14-rusage (see V14 above for the precondition).

## MERGE OK

Not decided for F-01, F-02 or F-03. Every R-055 verify finding that was re-checked holds on bf13934, but D3, the 4 CI
fixes and the added points are open. A later session should run those before a verdict.
