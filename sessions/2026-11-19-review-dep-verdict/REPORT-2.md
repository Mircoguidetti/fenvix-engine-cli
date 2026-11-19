FIX 3

# Review R-020b: dependency-update verdict after the R-020 fixes (last round)

Target: `sessions/2026-11-18-dep-verdict/REPORT-2.md` on `claude/dep-verdict-abjcfw` (9019c6d). It reports PARTIAL:
39.9% vs 20.7%, 0 wrong over 16,397, the 5 R-020 tests fixed, and the cost of the O1 prefix rule on ordinary commits
UNKNOWN. First review: `claude/review-r020`, `REPORT.md` (FIX 5). Engine reviewed: `python/detpy/distid.py` and
`python/detpy/proofcache.py` at 9019c6d. The engine trees at 9e0d005, e996d86, 1b731fa and 9019c6d are identical.

Committed on `claude/review-r020b`:
- `tests/test_review_r020b_dep_verdict.py`. It has 3 failing tests, one per new wrong reuse (N1 to N3), with the
  protocol of the first review: record at P, bump, cached and fresh run at C, and every reused result must equal the
  fresh one. Each of the 3 fails with `--det-cache-dists` and passes without it: today's engine reruns everything
  after any bump (checked by running the file with the flag removed from the shared `walk` fixture: all 6 dependency tests passed). The
  file also has 3 passing tests for attempts that are not findings, and 1 failing test outside the target (O2).
- This report.

Run: `python -m pytest tests/test_review_r020b_dep_verdict.py -p pytester` (Python ≥ 3.12; N2 needs `cc`).

## Findings

| # | severity | finding | evidence |
|---|---|---|---|
| N1 | High | A file installed by two distributions is mapped to one owner; upgrading the other changes it unseen | `test_file_installed_by_two_distributions` |
| N2 | High | A native library a wheel installs outside site-packages (`<prefix>/lib`) is skipped by the maps scan | `test_native_library_installed_outside_site_packages` |
| N3 | High | An existence check (`shutil.which`, `os.path.exists`) of a file a bump adds is not an input | `test_console_script_added_by_a_bump` |
| M1 | Medium | The O1 prefix rule's cost on ordinary commits, labelled UNKNOWN, is measurable. On click it lowers the reused share from 30.6% to 20.6% over 43 commit transitions, and on pygments from 21.8% to 17.8% over 50. The verdict line should carry it. | walks below |

N1 to N3 are wrong reuses of the kind R-020 asked about. Each one is a bump that changes behaviour without changing
anything the test's key records. M1 is not a wrong number. It is a measured cost the report left UNKNOWN, given here
so the next engine decision has it; it is not counted in FIX 3.

### N1. One file, two owners (wrong reuse)

`Index.build` keeps `files[path] = owner` for every RECORD line, so when two distributions install the same path,
the last one iterated wins. A test that reads the file depends on that owner alone.

Upgrading the *other* distribution goes like this:
- pip removes the files of its old RECORD, the shared one included;
- pip writes the new wheel, so the shared file has new content;
- the mapped owner's RECORD, version and `d/` identity file stay the same.

The test reads `cipher/table.txt` with `importlib.resources`. It is reused as passed, and a fresh run fails it.

A shared *module* is caught, but by another input: its executed code is recorded. That was the first attempt; the
committed test uses a data file. Real cases: `opencv-python` / `opencv-python-headless` / `opencv-contrib-python`
(the same `cv2/` tree, data XMLs and extension), `pycrypto` / `pycryptodome` (`Crypto/`), `jwt` / `PyJWT`,
`msgpack-python` / `msgpack`. A second package that overwrites files of the first is common in CI images where one
variant is pinned and another comes in transitively.

Fix direction: a path claimed by more than one RECORD depends on every claimant, or on its own content digest.

### N2. Native library outside site-packages (wrong reuse)

Wheels can install shared libraries into `<prefix>/lib` through `<name>.data/data/lib/`. `mkl`, `intel-openmp`,
`tbb`, `impi-rt` and `oneccl` do this, and numpy and torch builds load them through an rpath. `Index.files` knows the
owner, because the RECORD path `../lib/libb.so` is resolved. But `Tracker.scan()` drops every `/proc/self/maps` entry
that is not under a site directory before it asks `dist_of`. The H4 fix (read the maps after every test) does not
help: the entry is read and then skipped.

The test builds an extension `nat`, linked with an rpath to `natlib-b`'s `libb.so` in `<prefix>/lib`. The test
depends on `d/nat` only. After `natlib-b` 1.0 → 1.1 the library's answer changes: reused as passed, fails fresh. This
happens at *import* time, so it is not the lazy-`dlopen` case of H4.

Fix direction: map every maps entry through `dist_of`. A path no RECORD lists stays outside, as today.

### N3. Existence checks (wrong reuse)

`shutil.which`, `os.path.exists`, `os.path.isfile` and `Path.is_file` call `stat()`/`access()`. CPython raises no
audit event for them, so the engine's in-process recorder sees nothing (`strace` sees `stat` for children only).

Tests gate on installed tools all the time:
- `skipif(shutil.which("ruff") is None)`;
- "black not installed";
- a CLI smoke test of the project's own console script.

The test asks `shutil.which("tool-fmt")` and skips when the answer is None. `tool` 2.0 adds that console script
(RECORD `../bin/tool-fmt`). The cache reuses "skipped", and a fresh run runs the test and fails it. A skipped result
that hides a now-runnable, failing test is the worst kind of wrong reuse for CI, because it reads as green.

The same hole applies to an existence check of a path under site-packages that a *second* distribution adds, for
example an optional plugin file. When the test already depends on the distribution that adds the file, it is covered.

Fix direction: record `stat`-family calls on paths under site directories and on `PATH` lookups. Wrapping
`os.stat`/`os.access`/`os.path.*` in-process is cheap. Outside the flag, see O2.

### M1. The O1 prefix rule on ordinary commits (measured)

Method:
- Re-ran the cache-proof walks of click and pygments over their spec windows (51 commits each, `mode: suite`, one
  pytest process per commit).
- Engine before the prefix rule: 96f4bd1, the parent of 8896c36. Engine after: 9019c6d. Between the two, the default
  cache differs only by the prefix rule; H2 to H4 act under `--det-cache-dists` only, and the Rust core is unchanged.
- Same container, 4 walks in parallel, `harness/cache_proof/walk.py` unchanged. Rows and the comparison script are in
  `sessions/2026-11-19-review-dep-verdict/o1-walks/` (`python3 cmp.py` reprints every number of this section).
- Reused share = test time of reused results / test time of all tests, per transition, over the transitions both
  walks completed.

| project | transitions | before: mean / pooled | after: mean / pooled | commits ≥ 5% reused, before → after | verified reuses (wrong), before / after |
|---|---|---|---|---|---|
| click | 43 | 30.6% / 30.3% | 20.6% / 20.9% | 15 → 12 | 28,699 (0) / 19,342 (0) |
| pygments | 50 | 21.8% / 22.0% | 17.8% / 18.1% | 11 → 10 | 58,131 (0) / 47,345 (0) |

For comparison, the committed walk `tracks/cache-proof/results/s1d` (older engine, the same 51 commits per project)
has click 33% and pygments 22% mean. click has 43 transitions, not 50: 8 of its commits ended with a status other
than ok in both walks, as in s1d (42 transitions).

Where the time goes:
- **Permanent refusals.** click has 37 tests that spawn a subprocess. Every test after one of them in the process is
  now refused ("after an earlier test or fixture of this process"): 162 of 1,994 tests per commit (median), at
  every commit. They show up as `new` misses at every later commit too, because they are never recorded.
- **One early read invalidates the session.** Examples:
  - pygments `3e77fdd3e4` changes only `tests/contrast/min_contrasts.json`: 100% reused before, 0% after.
  - click `68e7ea7228` changes `pyproject.toml`, `uv.lock` and `CHANGES.md`: 91% → 0%.
  - click `36baa15ff8`: 90% → 0%.
  - click `16fc00e2f4` (`types.py` plus a test): 80% → 1%.
- **Cache-run wall time** (median, cache run A / full run B): click 11.0 / 6.5 s → 11.8 / 6.2 s; pygments
  17.1 / 13.8 s → 22.9 / 13.9 s. The cache run was already slower than the full run on both projects before the
  rule. The rule adds 0.8 s (click) and 5.8 s (pygments, +34%) to it, because larger entries (each test carries its
  prefix) cost record time, and fewer results are reused.

So the prefix rule costs about a third of the default cache's reuse on click and a fifth on pygments, both suite-mode
projects (MEASURED, 2 projects). In the per-file harness of the dependency study, the cost is smaller, because a
process holds one file. The report's direction was right ("probably much larger"), and the number now exists.

Requested changes to the report:
- Replace "Cost on ordinary commits: UNKNOWN" with these figures.
- Put "the default cache changes; cost −10 points on click (30.6% → 20.6%) and −4 points on pygments
  (21.8% → 17.8%)" in the verdict line or right under it.

Wrong reuse from the prefix rule: none found. The rule only adds inputs, with one exception, the carried-read
exemption (9e0d005). That exemption skips the "reads a file another test wrote" refusal for a read made by an earlier
context, and only when the digest is unchanged and the test did not read the file itself. The writers of such a file
ran before the read, and their inputs are carried, so a changed writer reruns the test. The only counterexample I
could build needs a test that appends to a file left over from an earlier session. That is cross-session state, and
it is already the report's open item 1 (order dependence through reuse). Over 153,517 verified reuses in the 4 walks
there are 0 wrong (MEASURED).

## Task 1: R-020's tests and the 5 fixes

- `tests/test_review_r020_dep_verdict.py` and `sessions/2026-11-19-review-dep-verdict/rederive.py` are byte-identical
  to `claude/review-r020` (`git diff origin/claude/review-r020 HEAD` on both paths is empty).
- With the engine at 96f4bd1 (Python files swapped in; the Rust core is identical), all 5 fail: H1, H2, H3, H4 and
  O1. At 9019c6d all 5 pass, along with the 7 tests of `test_dep_verdict_r020_fixes.py` and the 3 prototype tests.
- Each fix does what the report says:
  - H1/O1: prefix rule, `proofcache._record_all`.
  - H2: `l/` listings from `find_spec` with a path and from `os.listdir`/`scandir` under site.
  - H3: `@pth` in `global_keys`.
  - H4: maps read after every test.
- The rewritten proof-cache tests keep their original checks and add the later test's rerun. None was weakened, but
  three now assert *less* reuse by design (`test_import_time_read_...`, `test_data_file_change_...`,
  `test_function_change_...`). That is M1.
- Bypasses of the fixes found: N2 is a bypass of the maps scan (H4's mechanism). N3 is the existence-check
  sibling of H2's listing fix.

## Task 4: re-derivation from the committed rows

`rederive.py` (the first review's, unchanged) on `results/dv6` + `dv7` as `dv3` and `local5` as `local`. The layout
is the one `report2/mkbase.sh` builds.

| number | report | re-derived |
|---|---|---|
| D / T mean over 130 pairs | 39.9% / 20.7% | 39.9% / 20.7% |
| D / T mean of repository means | 26.7% / 15.6% | 26.7% / 15.6% |
| D / T pooled | 14.1% / 10.1% | 14.1% / 10.1% |
| env changed: n, D, T | 73, 34.2%, 0% | 73, 34.2%, 0.0% |
| env unchanged: n, D = T | 57, 47.1% | 57, 47.1% / 47.1% |
| cacheable ≥ 50%: n, D, T | 77, 62.9%, 32.0% | 77, 62.9%, 32.0% |
| per-repository D / T means | table | identical, all 10 rows |
| verified D (wrong, flaky); T | 16,397 (0, 0); 5,940 | 16,397 (0, 0); 5,940 (0) |
| informative cases | 2 | 2 (moto `6e705a82e3`, `test_opsworks/test_layers.py`, 2 tests) |
| null rule | 20,862 reuses, 2 wrong (0.010%) | 20,862, 2 (0.010%) |
| broken at C | 5 | 5 |

"Same 130 pairs, same sampled test files": checked against the first report's rows at `0b87033`. The pair set is
identical (130 of 130), the unit sets are identical for every pair, and so is the number of fresh tests per pair.

Labels: correct. PARTIAL follows from 39.9% under the prompt's thresholds. The report states that the other two means
sit near or under the NO line. The 0-wrong row says "2 informative cases", and the historical-breakage row is
UNKNOWN. Low, not counted:
- The `local5` rows (moto, community.general: 41 of the 130 pairs) carry an empty `engine` field. "Engine 9e0d005" is
  checkable from the rows only for the Actions runs (e996d86 and 1b731fa, both identical to 9e0d005 in `python/` and
  `crates/`).
- The cost figures (identity keys, record time) were not re-derived here; `cost.py` points into the session
  container.
- "Suite: 164 passed, 6 skipped": in this container 163 passed and 7 skipped. That is the same 170 tests; the skips
  depend on the environment (strace, ip, numpy).

## Task 5: suites

- `python -m pytest tests` at 9019c6d: 163 passed, 7 skipped.
- With this branch's file added: 4 failed (N1, N2, N3, O2) and 3 passed.
- `cargo test`: 47 passed, 0 failed.

## Outside the target

O2 (High, engine, pre-existing): `test_repository_file_existence_check` fails **without** `--det-cache-dists`. A test
that asserts `not os.path.exists("local.cfg")` is reused after `local.cfg` appears, and a fresh run fails it. The
engine records "paths it found missing" only through a failed `open`. `stat`-family checks (`os.path.exists/isfile/
isdir`, `Path.exists`, `shutil.which`, `glob` on a literal path) leave no input. This is N3 in the default cache, and
it is not in `docs/LIMITS.md`. It is not counted in the verdict.

## Not findings (checked; tests pass)

- Same version reinstalled from a different wheel: the identity includes the RECORD digest
  (`test_same_version_reinstalled_from_a_different_wheel`).
- A package data file read with `importlib.resources` (`test_package_data_file_changed_by_a_bump`).
- A plugin found by entry-point group, loaded and memoised by a registry in an earlier test
  (`test_entry_point_plugin_changed_by_a_bump`). The prefix rule carries `e/<group>` and the plugin's loaded
  distribution.
- Distributions without RECORD (egg-info, distro packages): their files map to no owner, so each file read or loaded
  is keyed by its own content digest (read in `Tracker.path`/`scan`). This is safe, but costs reuse.
- `importlib.metadata` functions captured before `install()` (`from importlib.metadata import version` in a module
  imported early): they bypass the wrapper, but their METADATA reads are `open` events under site, so the test still
  depends on `d/<name>`.
- A shared module (rather than a data file) in N1: caught by its executed code.

Not attempted: editable installs of a sibling project outside the repository. Under pytester, their sources would
sit in pytest's temp directory, which the engine classifies separately, so a test would not be conclusive.
