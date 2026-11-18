FIX 2

# R-008b review, second and last round: Block 4 part 2, the cache shared across machines

Reviewed: engine branch `claude/shared-cache` at `1d430a6`, as delivered in `delivery-REPORT-2.md`. The code
commits are `d7b7ec9` (FIX 1-3), `20ec467` (FIX 4), `3851039` (FIX 5-6) and `471b83f` (workflow input). `1d430a6`
changes only docs.

I checked only the six FIX items of round 1 (`R-008-REPORT.md`), and looked only for holes that the fix code itself
opened.

New failing tests: `tests/test_review_r008b.py` on this branch (`claude/review-r008b`, based on `1d430a6`).

## Verdict

* **All six round-1 items are fixed.** Each of my 12 tests fails at `da1afa9` and passes at `1d430a6`. I re-ran
  them here: none skipped, and every failure at `da1afa9` is the hole it asserts.
* **The hosted numbers recompute** from the compare job logs of all three runs.
* **The ISA-level decision is sound as a default.** I measured why below, and there is a cheaper option that keeps
  the safety.

The two tree walkers that FIX 1 and FIX 2 added (`_site_tree`, `_extra_paths`) do not see all the code the import
system loads. That gives two new FIX items (5 failing tests):

* One of them is a **regression from `da1afa9`**: a sourceless module directly in site-packages was keyed before
  the fix and is not keyed now.
* The other gives a **wrong reuse end to end** through the service.

Both fixes are one line each. With them, all 5 new tests pass, and the 12 round-1 tests and `test_runtime_id.py`
stay green (MEASURED, see "New FIX items").

## The six round-1 items

| item | fixed? | my tests at `da1afa9` → `1d430a6` | comment |
|---|---|---|---|
| FIX 1: installed code no RECORD lists | yes, for the cases tested | 3 fail → 3 pass | `site_tree` keys every file under every site dir. But the new walker skips sourceless `.pyc` and symlinked directories (new FIX A and B) |
| FIX 2: modules on other import paths | yes, for the cases tested | 2 fail → 2 pass, including the end-to-end wrong reuse | `extra_paths` has the same walker gaps (new FIX A and B). I also checked pytest's `pythonpath` ini option outside the root: keyed, with no wrong reuse (probe passed, not committed) |
| FIX 3: state read by C | yes | 4 fail → 4 pass, including the end-to-end `LD_PRELOAD` wrong reuse | preload libraries are closure roots by bytes; every locale category plus the locale data; TZ rules; visible CPUs; ISA level |
| FIX 4: body before auth, unbounded gzip | yes | 1 fail → 1 pass | `_auth` comes before `_body`, the connection is closed on refusal, and inflation is bounded in steps by `max_length`. MAX_BODY is now 64 MB |
| FIX 5: token reachable by tests | yes, as documented | 1 fail → 1 pass | pipe or hand-off file deleted once read, and the env var is moved to a pipe before re-exec. The docs now say what a test can still reach and set the read-only-token policy. NOTE 1 below |
| FIX 6: inputs are a claim; addresses not checked | yes | 1 fail → 1 pass | `doc_id` is recomputed on every fetched document; floor check on the test's own file; plain `http://` refused off loopback; docs corrected ("make any test pass") |

**Engine suite (MEASURED, this container, 4 CPUs, Python 3.13.18):**

* `pytest tests`: **151 passed, 7 skipped** (365 s). The delivery reports 152 passed, 6 skipped.
* The extra skip is environmental: numpy is not installed here, and this machine has no second 3.13 interpreter.
  None of the 12 round-1 tests skip.
* One caveat: for about 11 s during that suite, I patched `runtime_id.py` with `followlinks=True` to try the fix
  for FIX B, then restored it. The patch does not change behaviour for any existing test fixture, which uses no
  symlinked directories. The targeted runs afterwards (12 round-1 tests, `test_runtime_id.py`,
  `test_shared_cache.py`) were on the unpatched code.

## Hosted numbers (recomputed from the compare job logs)

Hosted runs used code `3851039` (run 44299953107) and `471b83f` (the other two). `1d430a6` changes only
`docs/SHARED-CACHE.md`, so the runs measure the delivered code. All numbers below are MEASURED.

Columns:

* **2 machines** and **1 machine** are reused tests out of the total.
* **misses 1 → 2** are the miss counts by reason, one machine first.

| run (ISA) | target | CPUs (level) | 2 machines | 1 machine | ratio | checked / wrong | misses 1 → 2 | identity |
|---|---|---|---:|---:|---:|---|---|---|
| 44299953107 (level) | pygments | 7763 (v3) / 9V45 (v4) | 0 / 5314 | 5287 | 0 | 0 / 0 | 27 → new 5314 | differs in `cpu` only |
| | click | 7763 (v3) / 9V45 (v4) | 0 / 1982 | 1657 | 0 | 0 / 0 | 325 → new 1982 | `cpu` only |
| | marshmallow | 9V45 (v4) / 7763 (v3) | 0 / 1192 | 675 | 0 | 0 / 0 | 517 → new 1192 | `cpu` only |
| 44300528610 (level) | pygments | 9V45 / 9V45 (v4/v4) | 5288 / 5314 | 5287 | 1.0002 | 5288 / 0 | 27 → 26 (code 2, new 24) | equal |
| | click | 8573C / 8573C (v4/v4) | 1657 / 1982 | 1657 | 1.0000 | 1657 / 0 | 325 → 325 | equal |
| | marshmallow | 7763 / 9V45 (v3/v4) | 0 / 1192 | 675 | 0 | 0 / 0 | 517 → new 1192 | `cpu` only |
| 44300539734 (off) | pygments | 7763 / 9V74 (v3/v4) | 5288 / 5314 | 5287 | 1.0002 | 5288 / 0 | 27 → 26 | equal |
| | click | 7763 / 7763 | 1657 / 1982 | 1657 | 1.0000 | 1657 / 0 | 325 → 325 | equal |
| | marshmallow | 7763 / 9V74 (v3/v4) | 675 / 1192 | 675 | 1.0000 | 675 / 0 | 517 → 517 | equal |

**Consistency checks:**

* Every miss total equals tests − reused.
* Pull stats agree with the reuse counts: 5290 → 5288 proven, 1857 → 1657, 788 → 675.
* In the `off` run, checked = reused = 5288 + 1657 + 675 = **7620**, with 0 wrong.
* "2 of 6 keyed pairs matched levels" is right.
* "In every 0, the identities differ only in `cpu`" is right, for all 4 zero pairs.
* "Two of the three `off` pairs crossed v3/v4" is right.
* No `pull_bad_address` and no `pull_rejected_no_own_file` counter appears in any pull. Both are written only when
  non-zero, so the new FIX 6 checks rejected nothing legitimate.

**One remark:** the one-machine baseline runs on a third machine, sometimes at another level than the pair (e.g.
pygments in 44300528610: baseline 7763, pair 9V45). The ratio compares counts, not identities, so this does not
bias it.

## The ISA-level decision: sound, and it can be made cheaper

I ran $0 tests on this container (Intel Xeon with AVX-512, AVX512-FP16 and AMX; glibc 2.39; CPython 3.13.18).
Lower levels were emulated by masking features. All results are MEASURED. Each probe hashes the outputs
of the functions below over fixed random inputs, under the masks named, and takes minutes to rerun.

1. **glibc libm, reached from pure Python** (`math.*` and `float.__pow__`, 18 functions × 300,000 inputs). I masked
   AVX-512 with `GLIBC_TUNABLES=glibc.cpu.hwcaps=-AVX512F,...`; `ld.so --help` confirms that v4 is then no longer
   supported.
   * **v4 vs v3: bit-identical** in all 18 functions.
   * **v3 vs v2** (also masking `AVX2,FMA,...`): **12 of 18 differ**, among them exp, pow, sin, cos, tan, tanh,
     expm1, log1p, erf and atan2. For example, exp differs in 117 of 200,000 inputs and sin(1000x) in 128.
   * Masking `FMA` alone gives the same differences. FMA is the switch.
2. **numpy 2.5.5:**
   * float64, v4 vs v3 dispatch (`NPY_DISABLE_CPU_FEATURES="X86_V4 AVX512_ICL AVX512_SPR"`): `np.exp` differs in
     **46,298 of 1,000,000** values and `np.log` in 157. sin, cos and tanh are identical.
   * float32, v3 vs v2: exp 393,436, sin 157,178, log 52,944 and tanh 329,274 differ.
   * Within v4 (SPR vs ICL vs SKX dispatch): 0 differences in 7 float16 operations over 10^6 inputs. On this sample
     the coarse level is enough.

**Conclusion.** Keying the level is necessary:

* numpy users get different float64 results between v3 and v4.
* Even pure-Python suites get different libm results between v2 and v3.

So "keyed by default" is the sound reading of the contract, and `off` "at the user's risk" is correctly documented.
The hosted v3/v4 split costs pure-Python suites reuse with no safety gain: libm is bit-identical between v3 and v4,
and the `off` run checked 7620 cross-level reuses with 0 wrong.

**Proposal for the planner (not a FIX):**

* Always key the FMA boundary (v1/v2 vs v3/v4), which is the libm switch.
* Key the full level only when the runtime holds native extension modules outside the stdlib, excluding fenvix's
  own `_core`.
* Cheapest test that decides it: rerun `fenvix-shared-cache` with that rule. Expected: 100% on every v3/v4 pair for
  pygments, click and marshmallow, if their venvs hold no third-party `.so`. Plus one numpy suite on a v3/v4 pair,
  which must miss.

## New FIX items (holes opened by the fix code)

### FIX A: the new walkers drop sourceless bytecode (includes a regression)

Both `_site_tree` and `_extra_paths` skip every file ending in `.pyc` or `.pyo`. Outside `__pycache__`, a
`name.pyc` with no `name.py` beside it *is* the module: the sourceless loader imports it. Vendor SDKs shipped as
bytecode and compiled deploy trees are real cases.

| test | `da1afa9` | `1d430a6` | why it matters |
|---|---|---|---|
| `test_hole_sourceless_module_in_site_packages` | **passes** | **fails** | regression: `site_loose` keyed top-level site files, `.pyc` included; `site_tree` drops them |
| `test_hole_sourceless_module_on_an_import_path` | fails | fails | FIX 2's walker claims "the content of every import-path entry" but drops the module |

**Fix (one line per walker):** skip a `.pyc`/`.pyo` only when its `.py` sibling exists (`f[:-1] in fn`).
`__pycache__` is already pruned.

### FIX B: the new walkers do not follow symlinked directories (wrong reuse)

`os.walk` without `followlinks=True` lists a symlinked directory but does not descend into it. The import system
follows the link. So a package that is a symlinked directory (`helper -> releases/helper-1/helper`, as in a deploy
tree, a monorepo or a vendored checkout) is imported but not keyed. Symlinked *files* are fine, because they are
hashed through `os.stat`.

| test | `da1afa9` | `1d430a6` | why it matters |
|---|---|---|---|
| `test_hole_symlinked_package_directory_on_an_import_path` | fails | fails | FIX 2 is incomplete: `import helper` gives 1 vs 2, same identity |
| `test_hole_symlinked_package_directory_in_site_packages` | fails | fails | FIX 1 is incomplete: same as round 1's unowned-package test, but through a symlink |
| `test_e2e_wrong_reuse_symlinked_package_on_an_import_path` | fails | fails | **wrong reuse**: machine 2 reuses `passed`, while a fresh run on machine 2 fails |

**Fix:** `os.walk(..., followlinks=True)` in `_site_tree` and `_extra_paths`. Guard against link cycles with a set
of visited `realpath`s; the 50,000-file cap of `extra_paths` already bounds the walk.

**Fix checked (MEASURED):** I applied both fixes locally (4 changed lines; not committed, file restored). Result:
`test_review_r008b.py` + `test_review_r008.py` + `test_runtime_id.py` = **27 passed, 1 skipped**. The skip is the
two-interpreter test. So "same image → equal" stays green.

## NOTES (risks, not blocking)

1. **The token in the parent's environment.** If `fenvix-run` itself is started with `FENVIX_CACHE_TOKEN` in its
   environment, a test can read the token from `/proc/<ppid>/environ`.
   * `take_token` pops it from a copy, and the parent's exec-time environment block stays readable by the same uid.
     Yama `ptrace_scope` does not cover `environ`.
   * MEASURED with a two-line parent/child probe.
   * The docs already concede that a test can reach the token in process memory, which is stronger, so nothing new
     is exposed. But "no token is left in the environment" should say "of the test process".
   * The workflow uses the hand-off file, so it is not affected.
   * Cheapest test: start `fenvix-run` with the env var and have a test grep `/proc/os.getppid()/environ`.
2. **The engine deletes the user's token file.** Used directly with `FENVIX_CACHE_TOKEN_FILE`, the engine
   *deletes* that file. The service prints a token once.
   * A developer who points the variable at their only copy (`~/.config/...`) loses it.
   * A second pytest run in the same job then silently runs on the local mirror only.
   * The docstring warns about this, but the user docs say only "deleted once read".
   * Proposal: delete only files under `$RUNNER_TEMP`/`$TMPDIR`, or only when a `FENVIX_CACHE_TOKEN_FILE_DELETE=1`
     flag is set.
3. **A project installed non-editably is invisible (pre-existing, not opened by the fixes).** "The project's own
   install" is detected by `direct_url.json` pointing under the root, editable or not.
   * A non-editable install of the project (`pip install .`, tox's default sdist install, nox `session.install(".")`)
     is therefore left out of `site_tree`.
   * Its files in site-packages are also not per-test inputs (`_ignored`).
   * The docs and docstring say "editable".
   * Cheapest test: install the project non-editably, change a source file and reinstall (the test file stays the
     same), then assert a miss.
4. **The stdlib walker has the same walker gap (pre-existing, unchanged).** `_tree_digest` for the stdlib also walks
   without `followlinks`. That is low risk (stdlib trees rarely hold symlinked package directories), but the same
   one-line fix applies.

## Links

* Round 1: `review-input/R-008-REPORT.md`; tests `tests/test_review_r008.py` (identical to `635dec5`).
* New tests: `tests/test_review_r008b.py` (5 tests; all fail at `1d430a6`; at `da1afa9` 4 fail and the
  site-packages sourceless test passes).
* Hosted runs: 44299953107, 44300528610, 44300539734 (compare job logs).
