FIX 5

# Review R-020: dependency-update verdict (prototype `--det-cache-dists`)

Target: `review-input/REPORT.md` (PARTIAL, 39% vs 20%, 0 wrong over 16,464, 7 of 7 inside the affected set), against
`review-input/P-028-dependency-update-verdict.md` and `review-input/IDEA-3.md`. Engine code reviewed: `python/detpy/distid.py`
and its hooks in `python/detpy/proofcache.py` at the base of this branch (prototype 81354c25, tests 7f353b0f).

Committed on `claude/review-r020`:
- `tests/test_review_r020_dep_verdict.py`: 4 failing tests, one per wrong reuse (H1 to H4), plus 1 failing test outside the
  target (O1). Each dependency test installs small distributions into a site directory, records with `--det-cache-dists`,
  bumps one distribution, then runs with the cache and once fresh, and asserts that every reused result equals the fresh
  one. All 4 fail with the flag and pass without it (today's engine reruns everything after any bump; checked by running
  the same file with the flag removed: 4 passed).
- `sessions/2026-11-19-review-dep-verdict/rederive.py`: the verdict numbers re-derived from the committed pair rows,
  without importing `analyze.py`, plus the checks behind M1.

Run: `python -m pytest tests/test_review_r020_dep_verdict.py -p pytester` (Python ≥ 3.12; H4 needs `cc`) and
`git archive 0b87033 harness/dep_verdict | tar -x -C /tmp/cut && python3 sessions/2026-11-19-review-dep-verdict/rederive.py /tmp/cut/harness/dep_verdict`.

## Findings

| # | severity | finding | evidence |
|---|---|---|---|
| H1 | High | A distribution's metadata answer memoised by one test is used by later tests without a dependency | `test_version_answer_memoised_by_an_earlier_test` |
| H2 | High | A namespace-package submodule added by a bump of a distribution the test never loaded | `test_namespace_subpackage_added_by_a_bump` |
| H3 | High | `.pth` startup code of a distribution no test imports | `test_pth_startup_code_of_a_distribution_no_test_imports` |
| H4 | High | A native library that C code loads with `dlopen()` during a test is not seen | `test_native_library_dlopened_lazily_by_an_extension` |
| M1 | Medium | "0 wrong over 16,464" and "7 of 7 inside" rest on 3 tests in one pair; a rule with no dependency check at all scores 3 wrong in 21,313 (0.014%), under the report's bound | `rederive.py` |

### H1. Memoised metadata answer (wrong reuse)

`helper` (never changed) calls `importlib.metadata.version("lib")` the first time it is needed and keeps the answer
(`functools.lru_cache`). `test_a` makes the query, so only `test_a` depends on `d/lib`. `test_b` gets the cached answer:
no event, so it depends only on `d/helper` (loaded). After `lib` 1.0 → 2.0, `test_b` is reused as passed; a fresh run
fails it. The loaded-module rule (`Tracker.loaded`) carries a distribution's *modules* to later tests. Nothing carries a
*metadata answer* or a *data file* read by an earlier test. Today's engine is safe here only because every test depends
on every distribution (`runtime_identity`), so the per-distribution rule turns a dormant hole into a wrong reuse.
Real code does this: version and feature gates computed lazily and cached in `transformers`, `huggingface_hub`, plugin
registries, `packaging`-based compatibility shims.

Checked and **not** a finding: the same query made at *import time* of a third-party module (while a test module imports
it) is credited to the global import context, so every test depends on `d/lib` (reproduced: `test_b` reran on `data:
.../d/lib`).

### H2. Namespace submodule added by a bump (wrong reuse)

`ns` is a namespace shared by `ns-core` and `ns-tools`, like `google.*`, `azure.*`, `opentelemetry.*`,
`sphinxcontrib.*` and `jaraco.*`. pydantic-ai's environment has both `google-*` and `opentelemetry-*` distributions. The
test imports `ns.core` and probes an optional `ns.extra` (`try: import ... except ImportError`). Why the test does not
depend on `ns-tools`:
- `_NameFinder` records top-level names only. `m/ns` lists who provides `ns`, and that list is unchanged.
- The import system's listing of `site-packages/ns/` is not an input.
- `ns-tools` is never loaded.

`ns-tools` 2.0 adds `ns/extra`: a fresh run takes the other branch, and the cache reuses the old outcome. The same
applies to `importlib.util.find_spec("ns.extra")`. It also applies to a regular package whose subpackage directory is
filled by a second distribution: plugin directories, and `*.libs`-style shared trees.

### H3. `.pth` startup code (wrong reuse)

`site.py` executes the `import` lines of every `.pth` file before pytest starts. A `.pth` that configures the process
inline loads no module and makes no read during the session, so no test depends on its distribution. Examples of inline
configuration: warnings filters, `sys.setrecursionlimit`, `os.umask`, an audit or `builtins` hook, coverage or tracing
bootstraps. The test bumps `tuner` 1.0 (`setrecursionlimit(5000)`) to 1.1 (`3000`): reused as passed, fails fresh.
`setuptools`' `distutils-precedence.pth` is covered only because it imports `_distutils_hack`, which is a module of
setuptools. Fix direction: every test depends on the `.pth` files of site directories (their content, or the
distributions that own them).

### H4. Lazy `dlopen()` from C (wrong reuse)

`Tracker.scan()` re-reads `/proc/self/maps` only when `sys.modules` grew or `ctypes.dlopen` fired. An extension (`nat`)
that `dlopen()`s a library of another distribution (`natlib-b`) on first call raises neither. Real examples: torch's
lazily loaded CUDA and cuDNN libraries, onnxruntime execution providers, GDAL and PROJ drivers, OpenSSL providers. The
test then has no `d/natlib-b`. The test reproduces it with two warm-up tests before the one that calls `nat`. As the
first test of a session it is caught by luck: pytest's own lazy imports grow `sys.modules` after it, which forces a
re-scan. The bump changes the library's return value: reused as passed, fails fresh. Both the IDEA-3 risk list
("native libraries loaded by other native libraries must be followed") and this report's finding 1 assume the maps scan
sees every load. The scan only sees the loads that Python makes visible. Fix direction: read `/proc/self/maps` after every
test (the report's own cost data: the check is cheap, the index costs 0.077 s once), or compare its size/inode set.

### M1. The soundness evidence has 3 informative cases

`rederive.py` counts the tests that had a recorded result at P and whose fresh outcome at C differs from P. Only those
can expose a wrong reuse. Over the 130 pairs there are **3**: the moto `6e705a82e3` boto3 tests, which import boto3
directly. Every other one of the 16,464 verified reuses would have verified as "not wrong" under any rule. A rule that
reuses every recorded result with no dependency check would have made 21,313 reuses with 3 wrong (0.014%). That is
below the report's 95% bound of 0.018% for the prototype.

So the rule-of-three bound is mislabelled as a property of the per-distribution rule. Measured precisely, it is a
property of how rarely bumps change outcomes in this sample. The same goes for "7 of 7 inside the affected set":
- "Inside" is computed as "not reused by D1" (`analyze.py`, `inside = n not in dre`). Given 0 wrong, that is true by
  construction.
- 4 of the 7 were never cached.
- 2 of the 7 (transformers `test_cli_download*`) are network failures the report itself cannot tie to the bump.
- The historical breakages the bar asks for are not tested. Names from the projects' CI are UNKNOWN, and the one named
  breakage (airflow `6b1436e3c4`, anthropic 1.x) had every test refused.

H1 to H4 show that tests outside the affected set can break.

Requested changes to the report:
- Label the 0-wrong row "MEASURED, 3 informative cases". Drop the rule-of-three bound or state it next to the null rule's
  0.014%.
- Mark the "100% of historically broken tests" criterion as UNKNOWN (not met, not failed).
- Rewrite finding 1 ("sound in this sample") accordingly.

## Re-derivation of the verdict table (task 1)

All numbers in the report's table and "Other cuts" re-derive exactly from the rows at the cutoff commit `0b87033`. I
re-derived them with my own code (`rederive.py`), and `analyze.py` gives the same output:

| number | report | re-derived |
|---|---|---|
| D / T mean over 130 pairs | 39.1% / 20.1% | 39.1% / 20.1% |
| D / T mean of repository means | 26.2% / 15.2% | 26.2% / 15.2% |
| D / T pooled test time | 14.2% / 10.0% | 14.2% / 10.0% |
| env changed: n, D, T | 73, 33.8%, 0% | 73, 33.8%, 0.0% |
| env unchanged: n, D = T | 57, 45.8% | 57, 45.8% / 45.8% |
| cacheable ≥ 50%: n, D, T | 76, 62.2%, 31.8% | 76, 62.2%, 31.8% |
| cacheable, all | 57.7% | 57.7% |
| per-repository rows (pairs, env changed, D, T, D env-only, cacheable) | table | identical, all 10 rows |
| verified D (wrong, flaky); T | 16,464 (0, 0); 6,048 | 16,464 (0, 0); 6,048 (0) |
| rule-of-three bound | 0.018% | 0.0182% |
| broken / inside | 7 / 7 | 7 / 7 (3 `d/boto3`, 4 `new`) |

T is forced to 0 on 61 pairs. All 61 are pairs where the environment changed, none where it did not. On the 12
env-changed pairs where T did run, it reused 0%. So "T = 0 by construction" holds in the data.

Errors (low, not counted):
- "Pairs not measured: 168 of 298 listed": `commits.json` lists **288** (9 × 30, community.general 20, pydantic-ai 28).
  Not measured is **158**, and "the rest" is 85, not 95.
- At the branch head (142 pairs, including the jobs that committed after the cutoff), D is 39.3% and T 18.4% over pairs.
  D is 26.0% as a mean of repository means. The verdict does not move, as the report predicted.

Labels and the PARTIAL reasoning: the per-pair mean, 39.1%, sits between the bar's 25% and 50%, so PARTIAL follows from
the prompt's thresholds. The 5 repositories near 0% in both modes are airflow, litellm, mlflow, prefect (cacheable time
0%) and transformers (2%). They are refused for non-dependency reasons, as stated: the D1 miss reasons are "new" there.
Two points the first line should carry:
- The pooled share, 14.2%, and the mean of repository means, 26.2%, are both near or under the NO threshold of 25%.
- The per-pair mean gives most weight to the repositories whose old commits still install: esphome 23 pairs, moto 21,
  community.general 20.

With H1 to H4, the 39% is not yet a share "reused with proof": it is a share reused by a rule with 4 known holes.

## Outside the target

O1 (High, engine, pre-existing): `test_repository_file_memoised_by_an_earlier_test` fails **without**
`--det-cache-dists`. A repository function that caches a data file's content across tests (`lru_cache`) gives later tests
the old content with no data dependency: they are reused after the file changes, and a fresh run fails them. This is the
general form of H1, and it is in the engine's cache with proof today. It is listed here so it reaches the engine's next
review. It is not counted in the verdict above.

## Not findings (checked)

- Entry-point plugin discovery: `entry_points(group=...)` records the group's lines, and `ep.load()` loads the plugin
  module (loaded rule). `entry_points()` without a group and `distributions()` give `e/@all` or `@all`.
- `importlib.metadata` queries at import time of a third-party module: credited globally (see H1).
- Vendored copies (`pip/_vendor`, `setuptools/_vendor`): their files are in the vendoring distribution's RECORD.
- Transitive native loads at import time: seen by the `/proc/self/maps` scan that follows the import.
- Existing prototype tests: `tests/test_dep_verdict_distid.py` 3 passed.
