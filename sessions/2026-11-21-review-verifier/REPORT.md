MERGE OK: F-01 yes, F-02 yes, F-03 yes, F-18 yes (4 non-blocking problems, each with a failing test)

# Review R-051: re-check of PR #11 (claude/verifier-cli @ 57d76c4, code 30f0260) before merge

Reviewer session 2026-11-21, branch `claude/review-verifier-r051` (cut from 57d76c4, one commit added: this report and
`tests/test_review_r051_verifier.py`). No product code changed. Every number is MEASURED (command named) unless marked.

## How it was built and run

- Wheel from 57d76c4: `maturin build --release --compatibility linux` → `fenvix-0.1.0-cp312-abi3-linux_x86_64.whl`,
  installed with pytest and pytest-xdist in a fresh CPython 3.13.18 venv; `_core` copied into `python/detpy` as the
  CI `python` job does. Node addon: `cargo build -p detpy-node --release`, copied to `node/detjs.linux-x64.node`,
  `npm ci` (Vitest 5.1.0, Node 22.23.5).
- Only CPython 3.13 and Node 22 were run here. 3.12, 3.14 and Node 24 are left to GitHub (release-1 run 44897463074).
  Full suites not run, as instructed.

## Earlier tests and the session's new tests

| suite | result |
|---|---|
| `tests/test_review_p1_findings.py` (#5, #8, #9, #10) + `tests/test_review_r050_verifier.py` (V10) | **5 passed** (35.5 s) |
| Same files, against their sources | `test_review_p1_findings.py` = the reviewer's 4 tests from `604a64f`, function bodies unchanged (diff shows only deletions of the other findings' tests and the docstring); `test_review_r050_verifier.py` identical to `a4312ed` |
| Session's new tests: `test_network_gaps.py::test_a_connection_kept_alive…`, `::test_tls_over_memory_bios…` (asyncio, anyio-shape; not skipped), `test_verifier_truth.py::test_same_inputs_are_identical`, `tests/test_fenvix_cli.py` | **31 passed** (198 s) |
| `node --test test/projects.test.js test/verifier-inputs.test.js` | **pass 13, fail 0** |

## Verdict per item

| item | verdict | evidence |
|---|---|---|
| #3 multi-project Vitest ids (`1100f69`, `d74d033`) | **FIXED** | Session test passes. My cases (`node --test` on a scratch file, 2 Vitest projects running one file, second project's value changed between runs): **unnamed** projects → ids `test/v.test.mjs@@0::value`, `@@1::value`, verify `stable` / `diverged`; **name as `{label, color}`** → `@@one::value`, `@@two::value`, `stable` / `diverged`. Rust `test_key` and the legacy policy skip an id that already has `@@`. |
| #4 kept-alive TCP in cassettes (`1d6d16b`) | **FIXED** | Three tests over one module-level `http.client` connection, test c sending 2 requests: record `3 passed`; replay all `3 passed`; c alone `1 passed`; order c,b,a `3 passed`. Then test b changed to request `/a` (test a's recording): replay all `1 failed, 2 passed`, b alone `1 failed`, so it is refused and not answered from a's recording. |
| #5 replay-clients, TLS over `wrap_bio` (`ca23d6a`) | **PARTLY** | asyncio and the anyio shape pass (session tests). **R4:** `_caller_socket` binds the `SSLObject` to the first recorded socket in the caller's frames, not to the socket the TLS runs over. A test that opens `idle` and then `sock` and runs TLS over `sock` through `wrap_bio`: plain pytest `1 passed`, record `1 passed`, but the cassette holds `send b'hello' / recv b'echo:hello'` on the **idle** connection (marked tls) and the raw ciphertext (`\x16\x03\x01…`) on the TLS socket. Replay: `AssertionError: assert b'' == b'echo:hello'`, `1 failed`. That is a false failure, not a refusal and not a false pass. Test `test_r4_…` |
| #5 (reviewer p1-verifier) repro names a polluter that is not the cause (`f1a12f5`) | **FIXED** | Reviewer's test passes. My case (an external counter file, fails 1 run in 3; another test in the suite): `status: NOT REPRODUCIBLE … failed 2/6 replays`, `cause: not established: … the tests it ran with (tests/test_a.py::test_noop) are not shown to be the cause`, exit 1. Remains (not blocking): `replay:` and `rerun:` lines are still printed for this NOT REPRODUCIBLE bundle, built on a configuration that fails 2/6. |
| #8 traces without run inputs called IDENTICAL (`f1a12f5`) | **PARTLY** | With no `inputs` key: `verdict: NOT PROVEN`, exit 1 (reviewer's test passes). **R1:** with `"inputs": {}` in both headers: `verdict: IDENTICAL: all 1 tests ran with the same inputs and observed the same events`, `run inputs: identical in every run`, exit 0. Cause: `verify.rs:285 run_inputs` returns `Some(empty map)`, so `inputs_recorded` is true. No shell in the tree writes an empty object today (`grep` over go/ jvm/ crates/ node/src), so nobody hits it now. It is a one-line guard. Test `test_r1_…` |
| #9 replay outside the project root (`f1a12f5`) | **FIXED** | Reviewer's test passes. My case: from the project's own `tests/` subdirectory → `tests/test_b.py is not under …/proj/tests: run fenvix replay from the project root … (…/proj)`, exit 2. **R3 (same class, new):** the target is now `@pytest.mark.skip` (quarantined): `NOT REPRODUCED: failed 0/2 runs, identical fingerprint: True … the defect no longer fails the same way: fixed, or it depends on …`, exit 1. The body never ran. Test `test_r3_…` |
| #10 / V10 explore with a broken file next to a good one (`f1a12f5`) | **FIXED** | R-050's V10 passes. My cases (a module with `import not_installed_pkg` next to a good one): plain explore → exit 2, `the suite does not collect cleanly (runner exit 1): only the 1 test(s) that collected were explored. The runner said: …ModuleNotFoundError…`; `--json` → exit 2, same error in the JSON; `-- tests/test_fine.py tests/test_imp.py` → exit 2. |
| `30f0260` "urandom" input renamed "entropy" | **A rename that makes the probe pass. The product behaviour was already correct before it. The session's claim about old traces is false (R2).** | See below. |

### 30f0260: real fix or probe-only rename?

The probe (`claude/exam`, `exam/probes.py:174`, `F-02.probe.numpy-repro`) passes when
`rc == 0 and "test_a" in out and "urandom" not in out`, where `out` is the whole `fenvix repro --json` output. Its spec
(gaps G-0177/G-0178) is: 10/10 with one fingerprint, the polluter named, and the first divergent event **is not a numpy
os.urandom import event**. In CI run 44891607359 the probe failed only on the provenance line `"urandom": "controlled"`.
That line is the name of a run input. It does not name a divergent event.

Before 30f0260 the behaviour was already right: the commit changes only the key of that dict (`_level0.py:489`,
`session.js:284`) plus the verifier's alias, and no logic. On 57d76c4 (MEASURED, the probe's own project with numpy 2.x, 3.13):
`REPRODUCED: failed 10/10 replays with one fingerprint`, `cause: test order: it fails when run after
tests/test_np_od.py::test_a`, and the first divergence is `order.predecessor <none> vs tests/test_np_od.py::test_a`, not an
entropy event. So the probe's substring check was too broad: a probe false negative. The rename itself is harmless and
matches the option `--det-entropy`. It is not a fix of a product defect, and it hides none.

**R2, the claim that is false:** "verify reads `urandom` in older traces as the same input". The alias exists only in
the `Reason` mapping. The run-input comparison compares keys as they are. The same `--det` trace written once with
`entropy` and once with the key renamed to `urandom` (as an older engine wrote it):
`verdict: DIVERGENT`, `entropy: "controlled" vs <not recorded>`, `urandom: <not recorded> vs "controlled"`, exit 1, and
the hint `the test reads OS entropy … observed but not controlled by --det; add --det-urandom`, which is wrong on both
sides (both runs were controlled). This is the safe direction (never "same"), but the commit message and the report state
a mapping that does not hold. Test `test_r2_…`

## Failing tests added (all FAIL on 57d76c4, CPython 3.13.18)

`python -m pytest -q -p no:randomly tests/test_review_r051_verifier.py` → `4 failed in 11.80s`:

- `test_r1_traces_with_an_empty_inputs_object_are_not_called_identical` (F-03, #8): exit 0, IDENTICAL
- `test_r2_an_old_urandom_trace_and_a_new_entropy_trace_of_one_run_are_identical` (F-03, 30f0260): exit 1, DIVERGENT
- `test_r3_replay_of_a_target_that_is_now_skipped_does_not_suggest_a_fix` (F-02, #9 class): exit 1, "fixed, or …"
- `test_r4_tls_over_memory_bios_is_bound_to_the_socket_it_runs_over` (F-01, #5): replay `assert b'' == b'echo:hello'`
  (it skips without a non-loopback interface or `openssl`, as the session's TLS test does)

## MERGE OK

- **F-01: yes.** #4 is fixed. #5 is fixed for the asyncio, httpx and aiohttp shapes the exam measures. R4 is a false
  failure under replay, for TLS over memory BIOs written by hand with a second socket in scope. It is not a false pass.
  Fix it next round: bind by the socket the caller pumps, or refuse when more than one candidate socket is found.
- **F-02: yes.** #5 (cause) and #9 are fixed. 30f0260 is cosmetic and correct in its output. R3 (a skipped target is
  "fixed, or …") is the #9 class in a new shape. It is hedged and exits 1, so it does not block, but it should exit 2
  like `not-collected`. The `replay:` and `rerun:` lines printed for a NOT REPRODUCIBLE bundle are a leftover of #5.
- **F-03: yes.** #3 is fixed. #8 is fixed for every trace the tree's shells write. R1 (`"inputs": {}` gives IDENTICAL,
  exit 0) is the worst class of result, but no producer writes it today. Recommended before go-live: treat an empty map
  as not recorded (one line in `run_inputs`). R2 is safe-direction noise and a false claim in the report.
- **F-18: yes.** V10 is fixed in every variant tried. #12 was confirmed earlier (R-050).

## New problems (do not block)

1. R1 to R4 above.
2. Unnamed Vitest projects get index names (`@@0`, `@@1`): reordering the `projects` array changes every test id, so
   traces taken before and after the reorder compare as missing tests. This is ESTIMATED from the ids. I did not run it.
3. The verify hint for entropy still names `--det-urandom` (now an alias). The option is `--det-entropy`.

## Process note

The prompt places this report on `claude/review-verifier-r051` of fenvix-engine-cli. `CLAUDE.md` of fenvix-brain-cli
says a session's report goes to `sessions/` on brain `main`. I followed the prompt. The coordinator may want to align
the two.
