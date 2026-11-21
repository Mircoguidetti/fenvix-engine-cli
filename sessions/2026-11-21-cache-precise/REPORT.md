PHASE 1 DONE (phase 2 waits for the go)

# P-061 cache precise tracking: phase 1 (session 2026-11-21)

Branch `claude/py-cache-precise`, from `claude/py-cache` @ 0fbf228. Phase 1 changes no cache code
(`proofcache.py`, `_proof.py`, `proofcache.rs` untouched, and no other engine file either).

## Delivered

| item | path |
|---|---|
| design | `docs/CACHE-PRECISE.md` |
| attack tests | `tests/test_cache_precise.py` |
| measurement harness | `harness/cache_precise/measure.py`, `aggregate.py`, `specs/{attrs,itsdangerous,moto}.json`, `.github/workflows/cache-precise.yml` (manual dispatch) |
| premise probe | `harness/cache_precise/modprobe.py` |

**Design** (`docs/CACHE-PRECISE.md`):

- what each test records as modified (`M`), from cell diffs at context switches, per cell family, with the attack for
  each family;
- what it records as read (`R`): the static closure for memory, and the capture's dynamic reads for files and
  environment;
- how needs are derived in each situation, with conditional reuse and late demotion;
- what stays unknown, so every earlier test reruns.

**Attack tests** (`tests/test_cache_precise.py`):

- 48 channels × 3 triggers (fail, new, edit) × serial / `-n 2 --dist loadgroup` = 288 scenarios. Each asserts its
  precondition, then that every cached outcome equals uncached `--det`.
- 8 phase-2 reuse targets (`test_reuse_*`), `xfail(strict=True)` until phase 2. Phase 2 removes the marks.

**Measurement harness:**

- `harness/cache_precise/measure.py` runs scenarios unchanged / add-test / edit-test / failing-test, serial and `-n 4`;
- it reports reused, ran and wall times, and wrong results, with a second uncached run to separate wrong from flaky;
- one GitHub job per (project, mode).

**Premise probe:** a pure-Python prototype of the walk. It counts the tests that leave in-memory state behind.

## Results (MEASURED, this container, 4 CPUs, gVisor)

### Attack tests, on 0fbf228 (the current, coarse rule)

| Python | passed | failed | xfailed (phase-2 targets) |
|---|---|---|---|
| 3.13.18 | 282 | 6 (every `putenv` scenario) | 8 |
| 3.12.3 | 282 | 6 (the same `putenv` scenarios) | 8 |

The 6 failures are **not wrong reuses**: the cache ran every test (`ran 3`). They are a wrong outcome of tests the
cache runs, present in a cold cached run.

- **What happens.** An earlier test calls `os.putenv`, and a child started later by another test does not see the
  variable under `--det-cache`. It does see it under plain pytest and under uncached `--det`.
- **Cause.** `python/detpy/follow.py:337`: to add the clock shim to `LD_PRELOAD`, an inherited environment is rebuilt
  from `os.environb._data`, which does not hold `putenv` variables.

Details and fix direction are in `docs/CACHE-PRECISE.md` section 8. **Decision for the coordinator:** who fixes
`follow.py`, which is cache code but not one of the three files under repair. The test stays failing until then.

The reasons the 8 targets fail today were checked with `--runxfail`. Each fails on the reuse count, as intended:

- a failing test at the end: `reused 0, ran 31` serial, and `reused 15, ran 16` under `-n 2`, where 1 run is wanted;
- a comment in the first file: `reused 0, ran 30`, where at most 10 runs are wanted.

### Harness baseline, itsdangerous 2.2.0, 0fbf228 engine, Python 3.13

| mode | scenario | passing | reused | wrong |
|---|---|---|---|---|
| serial | unchanged | 297 | 297 | 0 |
| serial | add-test | 298 | 0 | 0 |
| serial | edit-test (the exam's edit) | 297 | 0 | 0 |
| serial | failing-test | 297 | 289 | 0 |
| -n 4 | unchanged | 297 | 297 | 0 |
| -n 4 | add-test | 298 | 0 | 0 |
| -n 4 | edit-test | 297 | 0 | 0 |
| -n 4 | failing-test | 297 | 231 | 0 |

These reproduce the exam's 0-of-298 on edit-test. On itsdangerous the synthetic failing test lands early in the
collection order, so few tests are before it: that is why failing-test reuses 289 there, while attrs' real failures
(positions 1,073-1,074) cost much more.

attrs and moto were not run with the harness here: attrs' cached serial runs take ~10 min each, and moto needs its
service extras. Both are for the GitHub workflow.

### Premise probe (prototype walk, plain pytest, 3.13)

| suite | tests | modify state (after noise and memos) | notes |
|---|---|---|---|
| itsdangerous | 297 | 2 | the premise holds |
| attrs | 1,330 | 772 | 722 bump `attr._make._CountingAttr.cls_counter`; 212 fill an `inspect` lru cache |

Consequence, now in the design:

- `M`-precision alone gives attrs' failing tests only ESTIMATED ~55 % reuse.
- Phase 2 adds a **failing-test rule**. A failing test with an unchanged key, code prefix and needs keeps, by
  determinism, the outcome it had. It runs alone in an isolated child for its output, and is compared with the stored
  failure; on a difference it is replayed with its full prefix. ESTIMATED ≥ 99 % reused on attrs no-edit.
- The relative-order counter stays a phase-2 open item for new or edited attrs tests. The exam measures those on
  itsdangerous.

## Not done

- No GitHub measurement yet: the workflow `cache-precise.yml` is pushed with `[skip ci]` and not dispatched. The
  coordinator can dispatch it, or I do in phase 2.
- 3.14 run of the attack tests: not run (time).
- The cost of the Rust walk is UNKNOWN until phase 2. The prototype's Python cost, 0.18-0.33 s per test, is not
  representative.
- Running `tests/test_cache_precise.py` takes 8.5 min on 4 CPUs. In CI it lands in one shard. If that is too long,
  phase 2 can trim the `n2` × `edit` cells.

## Decisions for the coordinator

1. The `follow.py` putenv fix: who does it, and when.
2. The noise-cell declaration (`warnings._showwarnmsg_impl`, hypothesis's gc counters) and the declared memo list
   (`docs/CACHE-PRECISE.md` section 4).
3. The failing-test rule: a failure is reported after an isolated-child run that matches the stored failure. Is this
   acceptable as "the outcome uncached `--det` gives"?
