FIX 6

# R-003: independent review of Block 2 "reproduce and explore" (P-010)

Reviewed: fenvix-brain-cli `sessions/2026-11-17-block2/REPORT.md`, fenvix-engine-cli `origin/claude/gracious-rubin-eyswxd` at 455c57c (measurement code ef2aa7a), data in `harness/results/block2/` (Actions run 43974053422).

Setup:
- Worktree `<scratch>/rv-b2`, built like the CI tests job: uv venv on Python 3.13, `maturin develop --release`. Plugin suite: 81 passed, 4 skipped (time_machine and Django not installed at first). Not a defect.
- Evidence is in `<scratch>/review-R-003/` (not committed). `<scratch>` = `/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad`.

Labels: MEASURED means measured or recomputed by me. DECLARED means taken from the session's report.

## Checks

| # | check | result |
|---|---|---|
| 1 | Recompute tables 1-4 and the comparison from the raw per-repo JSON (`recompute.py`, `compare.py`, `sets.py`) | Tables 1, 2, 3 and 4 recompute exactly (MEASURED). **Errors:** E1 (pytest-randomly replay cost counted 4x), E2 (wrong test named), E5 ("142 min of repro" is 133). The "only randomly 15 / only detpy 4" split recomputes once "found" is read as replays 10/10. 140/138/91 and 4.7x (365→77) recompute. |
| 2 | `detpy repro` on 5 targets from 5 repositories (head wheel, local, Python 3.9, serial) | ljson, krllint, accessify, pykicad: same seed, prefix, minimal order and polluter as CI. Each replays 10/10 with one fingerprint, and `detpy replay` reports `matches_bundle: true`. The ljson fingerprint `59de1a28…` is identical to CI's (MEASURED). Minimality holds: the target alone, same seed, passes 3/3 for all four. **py-autodoc `examples/test_pytest.py::test_post`:** reported "fails alone, no setter", yet `[test_should_not_generate, test_post]` passes under `--det`. This is **E6**. |
| 3 | Fairness of the pytest-randomly comparison | Fair on seeds (1..50 both), pins (same prepared venv and `pytest_args`), serial (`-n 0` both), targets (388, identical lists), and the "fails under seed ≤ K" definition. **Unfair:** detpy counts 14 failures that detpy itself causes as "found" (**E3**), and pytest-randomly's proof cost is inflated 4x (**E1**). Timings: 18 of 28 repositories ran detpy and pytest-randomly on different CPU models, so +24% per seed run is NOISY. |
| 4 | N3, N4, N5, N6, T1, T2 fail before their fix and pass after (`before_after.sh`, parent commits) | All six VERIFIED (MEASURED). N3/N4/N5 at de5f7a6: 3 failed → 5 passed. N6 at f6364dc: 8 failed → 10 passed. T1 at 67560d0: 1 failed → 1 passed. T2 at c568c31: 1 failed → 2 passed. **Extra T1 cases** (`t1extra/test_t1_extra.py`): `time.monotonic` and `random.random` as class attributes pass, and so does `threading.Lock` on Python 3.9 (their test only exercises it below 3.13, and CI runs 3.13). `os.system` and `socket.gethostbyname` as class attributes still fail under `--det` at head (**E4**). |
| 5 | Claims in "For the coordinator" and customer-facing claims | The version caveat is false (E3). The headline "as a finder detpy equals pytest-randomly (96.9% each)" is false (E3). "Proving costs less than pytest-randomly" is reversed (E1). Details below. |

## Proven errors

**E1. pytest-randomly's proof cost is counted once per target, but it was paid once per seed.**
- The harness reruns the suite 10 times per distinct first-failing seed. `block2_report.py` then sums the same `seconds` list for every target that shares that seed (298 targets share another target's reruns).
- MEASURED: the reruns cost **107.2 min**, not 424. Find + prove for pytest-randomly at K=50 is **293.5 min**, not 610. This matches the jobs' own `seconds` field: 293.6 min in total.
- So detpy's 348 min of repro is about **3.2x** pytest-randomly's proof cost, and detpy's find + prove (579 min) is about **2x** pytest-randomly's.
- The report's "Proving a failure… 424 min", "Find + prove… 610 min" and the comparison row "replay cost… 424 min total" are all wrong.
- Command: `python3 -I <scratch>/review-R-003/e1_randomly_replay_cost.py <rv-b2>/harness/results/block2`

**E2. The report names the wrong test for "No bundle (1)".**
- The report says `panamah test_expiration_by_max_size`.
- The not-found bundle is `test_expiration_by_max_length`. detpy never failed `max_size` in its 50 seeds.
- Command: `python3 -I <scratch>/review-R-003/e2_e3_e5_data.py <rv-b2>/harness/results/block2`

**E3. 14 flask-multi-redis targets are detpy's own failures, but they are counted as found and reproduced.**
- What the data shows: under detpy, all 14 fail in 50 of 50 seeds and are listed in `always_failing`. The exception is `TypeError: _thread.allocate_lock() takes no arguments (1 given)` at `detpy/clock.py:468`. Under pytest-randomly the same tests fail in only 14 of 50 seeds.
- Yet they are counted as found at K=1, "reproduced, 10/10 identical", fails-alone.
- Cause: the pre-T1 Lock stand-in binds as a method. I reproduced it with `t1extra/test_t1_extra.py`:
  - Python 3.9 venv with the ef2aa7a code: the identical TypeError.
  - Head: passes.
- By Block 1's own rule (docstring of `explore_seeds` in the harness), a test that fails under every `--det` configuration is broken by Level 0. It is not a reproduction.
- Corrected detpy, MEASURED:

| K | fails | 10/10, one fingerprint | 10/10, any fingerprint |
|---:|---:|---:|---:|
| 1 | 119 | 109 | 119 |
| 5 | 301 | 290 | 300 |
| 10 | 347 | 335 | 346 |
| 20 | 353 | 341 | 352 |
| 50 | 364 (93.8%) | 351 (90.5%) | 362 (93.3%) |

- Against pytest-randomly at K=50: 382 fail, and 376 (96.9%) fail 10/10 on rerun.
- What this makes false:
  - "As a finder, detpy equals pytest-randomly (96.9% each)": detpy is 93.3%, pytest-randomly 96.9%.
  - "At K=1 detpy finds more (133 vs 113)": the real gap is 119 vs 113.
  - The version caveat "none of N6/T1/T2 should change a number": T1 changes these 14.
  - The explanation "need a real Redis, which `--det` blocks": the 14 targets fail on detpy's Lock bug in setup.
- Commands:
  - `python3 -I <scratch>/review-R-003/e2_e3_e5_data.py <rv-b2>/harness/results/block2`
  - `PYTHONPATH=<ef2aa7a worktree>/python <scratch>/review-R-003/venv39/bin/python -m pytest --det -q <scratch>/review-R-003/t1extra/test_t1_extra.py`

**E4. The T1 fix is incomplete.**
- The commit says "stand-ins for builtins no longer bind as methods". At head, on both Python 3.13 and 3.9, two builtins stored as class attributes still fail under `--det` only:
  - `os.system`: `system() takes at most 1 argument (2 given)`. It is wrapped by `_mark_external`, a plain function. The same applies to `os.fork` and `os.posix_spawn*`.
  - `socket.gethostbyname`: `_gethostbyname() takes 1 positional argument but 2 were given`.
- Both pass without `--det`.
- Command: `cd <scratch>/review-R-003/t1extra && <rv-b2>/.venv/bin/python -m pytest --det -q -p no:randomly test_t1_extra.py` gives 2 failed, 2 passed. The same command without `--det` gives 4 passed.

**E5. "eppy (67 targets, 142 min of repro)" is wrong.**
- MEASURED: eppy repro is **133.2 min**. 142.5 is repro plus explore (9.2).
- The K=50 maximum of 149.3 min per repository is anyio (80.2 + 69.0), not eppy.
- Command: `e2_e3_e5_data.py` as above.

**E6. A standalone `detpy repro` never looks for a state setter when the target already fails in the fixed order.**
- `standalone` means the copy-paste command a developer runs. The code is in `repro.py`: `for pconf in passing or ([FIXED] if config != FIXED else [])` loops over nothing when the target fails in the fixed order.
- Example: py-autodoc `examples/test_pytest.py::test_post` is reported "fails when run alone (no polluter)". Yet setter + target passes under `--det`.
- CI named the setter only because `explore` passes `known_fail` (seed 1), which leaves FIXED available as a passing configuration. The 82 "setter named" in CI therefore do not show what the developer command does.
- Command: `<scratch>/review-R-003/e6_setter_skipped.sh` (needs the prepared checkout in `<scratch>/review-R-003/work`).

## Notes

- **Different definitions of "only found by" (not an error).** By "fails under a seed ≤ 50", only pytest-randomly fails 8 targets (anyio 3, crom 1, panamah 3, todo-sync 1) and only detpy fails 4. The report's 15/4 uses "replays 10/10" instead. Both are defensible; the report should state which one it uses.
- **Always-failing targets.** domain2idna (3) and eppy (1) fail in 50 of 50 seeds under **both** tools. That is fair between the tools, but they are not "found flaky" in either one.
- **What does hold (MEASURED):**
  - minimal order median 2, max 4;
  - polluter or setter named for 264 + 82 targets;
  - 365 → 77 families;
  - repro's minimisation is correct on the 4 order bugs I checked;
  - bundles replay across machines with an identical fingerprint (ljson matches CI).
- **Customer-facing wording to drop or fix:**
  - "detpy is cheaper than pytest-randomly to prove a failure": false (E1).
  - "finds as many": false; detpy finds about 3.6 points fewer at K=50 (E3).
  - "turns each flaky test into a 2-test reproducer with its cause named": supported only as a median, and only on the CI path. A developer running `detpy repro` on a brittle test that fails in the default order gets no cause (E6).
- **Timings.** In 18 of 28 repositories, detpy and pytest-randomly ran on different CPU models. Every cost ratio is NOISY. Collected test counts were identical per repository for the two tools (MEASURED).
