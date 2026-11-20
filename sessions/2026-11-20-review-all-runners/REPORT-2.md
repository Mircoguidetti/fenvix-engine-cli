FIX 7

# Review R-032b: `claude/all-runners-2` (14 runners on the Rust engine, R-032 fixes, Node policy in Rust)

Reviewed commit: `7e36c1c7c578869ec9075f623bcd9d8fe15ca1c6` (`git rev-parse HEAD` of `claude/all-runners-2`).
Report under review: `sessions/2026-11-19-all-runners/REPORT-2.md` (PARTIAL). Labels: **MEASURED** (run here, or
re-derived from committed raw files), **DECLARED** (the branch's documents), **ESTIMATED**, **UNKNOWN**.

Environment (MEASURED): Python 3.13.18, Node 22.23.5, Bun 1.4.4, Deno 2.9.6 (`DETJS_DENO`), engine built with
`maturin build --release` + `pip install` and `npm ci && npm run build`. Runner packages installed here: nose2 0.16.0,
Django 6.1.3, hypothesis 6.170.16, zope.testrunner 8.4, ward 0.68.0b0, pytest-django 4.14.0, pytest-xdist.

Tests added by this review (they fail where a finding is open):

* `tests/review_r032b/test_review_r032b_python.py` — Python attacks (unittest, nose2, zope.testrunner, Django,
  doctest, ward, pytest plugin serial and `-n 2`).
* `node/test/review-r032b.test.js` — node --test, Mocha, bun test, deno test.
* `node/test/review-r032b-policy.test.js` — Rust Node policy vs the JavaScript it replaced, 3000 adversarial inputs.
* `sessions/2026-11-20-review-all-runners/rederive2.py` — independent re-derivation of REPORT-2's walk numbers
  (`--at <rev>` reads a commit's tree).
* Raw outputs of every run quoted below: `sessions/2026-11-20-review-all-runners/r032b-raw/`.

## Verdict

**FIX 7.** R-032 F1–F8 are fixed (the reviewer's files pass unchanged, claim 1). The port has one implementation
(claim 2). But the Rust engine still makes wrong reuses: the carried-set rule misses state an earlier test leaves
through a channel that is not a static import, so an **order-dependent** test is reused after the earlier test
changes (F1: unittest, nose2, zope.testrunner, the pytest plugin serial and under `-n 2`). There are also four
unseen inputs (F2–F5) and two Node/Bun/Deno gaps (F4, F5, F6). The walk numbers reproduce exactly at the commit
the report was written on (claim 5). The report's head number is one shard stale at the reviewed head, and the walks
ran on an older engine (F7).

## Findings

| # | claim | finding | runners hit (MEASURED) | test | where to fix |
|---|---|---|---|---|---|
| F1 | 3, 6 | **Wrong reuse: state left by an earlier test, with no static-import edge between them.** `test_a` runs `mock.patch('consts.V', open('data.txt').read()).start()` (a leaked patch by dotted name: a common order-dependent bug). `test_b` does `import consts` (no imports in `consts.py`) and asserts `consts.V == 'v1'`. When `data.txt` changes, `test_a` reruns and `test_b` is reused as **passed**. A fresh run fails it. Root cause: `record.rs` carries an earlier context only if one of its executed repository files *statically references* a node in the test's reach (`reference_closure_with`). Writes by name (`mock.patch` string, `importlib.import_module(name)`, `sys.modules[...]`) and shared global objects (`builtins`, `os.environ`) create no such edge. `test_b` reaches only `consts` (unittest is infrastructure, pytest is infrastructure), so nothing is carried. The same channel via `importlib`, `builtins` and `os.environ` (the variable is absent at session start, so its env key does not change) | unittest (W1, W2, W3, W4), nose2 (W1), zope.testrunner (W12), pytest plugin serial (`test_w1_pytest_plugin`) and pytest-xdist `-n 2 --dist=loadgroup` (W15). Held: Django (W13: `django.test` is a library node, so the contexts connect), ward (W14), same-file under xdist `loadfile` (W15) | `test_w1_*`, `test_w2_*`, `test_w3_*`, `test_w4_*`, `test_w12_*`, `test_w15_pytest_xdist[loadgroup]` | `crates/detpy-core/src/record.rs` carried-set selection (~805–935) and `reference_closure_with` (~328). Connectivity must cover writes that do not go through a static import: e.g. module-dict / `builtins` / `os.environ` writes observed at run time (dict watchers or audit), or an earlier context that ran an attribute-writing-by-name API (`mock.patch` with a string target, `setattr` on a module object, `importlib.import_module`) is carried into every later test. Note: tests reached only through runner infrastructure are the common case under unittest-family runners |
| F2 | 3 | **Wrong reuse: `os.DirEntry.stat()`** (`os.scandir`). A test asserts `e.stat().st_size == 3` for the one entry of `d/`. The file grows to 4 bytes and the test is reused. A fresh run fails it. The listing is keyed by names and kinds. `DirEntry.stat` is a C method that the `_patch_stat` wrappers do not reach. (`os.fstat` after `os.open` held, W6.) | unittest (shared capture: every Python shell, ESTIMATED) | `test_w5_scandir_entry_stat_size` | `crates/detpy-py/src/capture.rs` `os.scandir` arm (~1520): either key the entries' metadata when `DirEntry.stat()` is called (it cannot be wrapped in Python), or key the listing with sizes/mtimes |
| F3 | 3 | **Wrong reuse: calls into the C library through ctypes.** `ctypes.CDLL('libc.so.6').access(b'flag.txt', 0) != 0`; then `flag.txt` appears and the test is reused. A fresh run fails it. The `ctypes.dlopen` arm keys a library by content and lookup, but every libc function called through it (`access`, `stat`, `open`/`read`, `getenv`, `time`) is unobserved. By the R-021 F3 rule ("an API the capture does not see makes the test uncacheable") this must refuse | unittest (shared capture, ESTIMATED: every Python shell) | `test_w7_libc_access_via_ctypes` | `capture.rs` `"ctypes.dlopen"` arm (~1445): flag the context (as for a project `.so` that is then called), or refuse system C libraries loaded by user code |
| F4 | 3 | **Wrong reuse: `module.findPackageJSON` (Node ≥ 22.14) with a nested `package.json` that appears** (the R-032 F6 class through another API). The test asserts that the nearest `package.json` of `lib/x.js` is not `lib/package.json`. Then `lib/package.json` appears and the file is reused; a fresh run fails it. The C++ lookup's absent probes are not keyed | node --test, Mocha, deno test (Node compat). Bun: held (its fresh `--det` run still passes) | `review-r032b.test.js` E3 | `node/src/cache/capture.js` (and the Deno runtime): treat `findPackageJSON` like `nearestPackageJson` (key each probed `dir/package.json` as absent), or flag it `runtime-api` |
| F5 | 3 (clocks) | **Wrong reuse: Deno `Temporal.Now` is a real clock.** It is neither virtualized nor flagged. A test that passes only before a real-time deadline is reused after the deadline; a fresh `--det` run fails it (`false !== true`). Under Node, Bun and Deno, `Intl.DateTimeFormat().format()` and `performance.timeOrigin + performance.now()` are refused (sound, MEASURED) | deno test | `review-r032b.test.js` D4 | `node/src/runners/deno-runtime.js` (Level 0): virtualize `Temporal.Now.*` or flag `clock-real`. Bun: UNKNOWN (not tested; check whether `Temporal` exists there) |
| F6 | 3 (workers) | **Wrong reuse: a Bun `Worker` reads a file.** The worker posts `fs.readFileSync('data/v.txt')`; the data changes; the test file is reused; a fresh run fails it. node --test / Mocha flag `worker`. Deno refuses workers (R-032 held). `Bun.spawnSync`, `child_process` are refused (MEASURED) | bun test | `review-r032b.test.js` B2 | `node/src/runners/bun-runtime.js` / `bun-preload.js`: flag `new Worker` (`worker`) like the Node capture |
| F7 | 5 | **Report accuracy.** (a) At the reviewed head `aggregate2.py` gives **74,924** tests verified (Python **28,797**), not 74,893 / 28,766: `runner-doctest-nameparser-1of2` (+31 verified, 100 transitions, 0 mismatches) landed in 2ca15db after the report (c17f6c7). The nameparser row still says "PENDING (0 of 2 shards landed)". (b) Every walk ran the engine at `7510773`. `7510773..7e36c1c` changes `schedule.rs`, `_proof.py`, `proofcache.py` and `xdist.py` (the quarantine / stable placement merge, cd3e24e): the walks do not cover the final tree. The report does not say so. (c) The Deno walks ran Deno **2.9.8** (raw files' `runtime`); the report names 2.9.6 (local only). (d) "Node verification against a separate fresh run": the Node raw files keep only the fresh run's counts (`fresh.n`, `rc`), not its per-test outcomes. The per-test comparison therefore cannot be re-derived from committed raw files, only its counts. Python raw files likewise keep counts (`verify.checked`), not ids. (e) `node --test`… "fresh run" is `detjs <runner> --det` without cache, i.e. the engine under Level 0, not a plain runner run (the report's wording is correct; the claim "plain" is not) | — | `rederive2.py` | regenerate REPORT-2 at the final head; state the engine sha of the walks and the Deno version; commit per-test fresh outcomes (or a digest of them) if "per test against a fresh run" is to be re-derivable |

Nits (not counted):

* `node/test/legacy-proof-policy.js` says the JS is "unchanged except" for input plumbing. Its `envDep` was changed,
  though (`hasOwnProperty && typeof string` instead of `curEnv[name] ?? null`). This matches the new `proof.js`
  sanitizing, but the header does not say so.
* The policy equivalence differs from the old JavaScript in two cases. Flag details that are objects get the reason
  text `{"y":"z"}` from Rust and `[object Object]` from JS. Flag names inherited from `Object.prototype`
  (`constructor`, `toString`) are flags only in JS. Neither occurs in real captures (the flag set is fixed and its
  details are strings), and stores and decisions are equal (MEASURED below).

## Claim 1: R-032 F1–F8 (MEASURED here)

* `tests/review_r032/test_review_r032_python.py` (unchanged, identical to `claude/review-r032` ff31354): **22 passed,
  1 skipped** (de_DE locale not installed; P7 stays UNKNOWN). With nose2/Django/hypothesis installed; without them 6
  are skipped (the branch's report counts 229 passed, 3 skipped over a larger set).
* `node/test/review-r032.test.js`, `review-r032-runtimes.test.js` (unchanged), `all-runners-2-f6f7.test.js`,
  `policy-equivalence.test.js`, and the branch's `review-r032-runners-b.test.js`: all pass (88 tests together).
* `review-r032-runners-b.test.js` is **modified** on the branch: tap's N3 is restated as "cached agrees with fresh".
  The **original** file (from `claude/review-r032`) fails only tap N3, on its precondition ("the change must make a
  fresh run fail"). That is the review's own "n/a" for tap, so it is not a wrong reuse. Raw:
  `r032b-raw/node-r032-unchanged.txt`.
* `rederive.py` (unchanged) on its own branch: 153,483 / 0 mismatches, as R-032 found. It re-derives the old walks;
  REPORT-2's numbers are in claim 5.
* F8 (count tests): holds. `rederive2.py` checks every transition: Python `verify.checked == n_reused`. Node
  `compare.checked + n_missing == skip.summary.reused_tests == verify.summary.verified_tests`. 0 inconsistencies,
  0 missing.

## Claim 2: one implementation

* `_statcap.py` is gone (`git ls-files`). Path probes are `_proof.Capture._patch_stat` (Python wrappers of
  `os.stat`/`lstat`/`access`/`readlink` and the `os.path.exists` family), which hand off to
  `CaptureCore.stat_check` (Rust). Module lookups go through a `sys.meta_path` finder to `CaptureCore.lookup` (Rust).
  This is interception only: what is keyed, and how, is Rust. That is consistent with DECISIONS 2026-11-18
  (MEASURED by reading). Its coverage gap is F2.
* Node: `node/src/cache/proof.js` gathers inputs and calls `ProofCache.recordSession` / `receiptLines` /
  `uncacheableTable` (Rust `detpy_core::node_session`). No second copy of the policy is in `node/src`: `UNCACHEABLE`
  comes from Rust, and `recordAll`/`verifyOne` exist only in the test-only `legacy-proof-policy.js` (MEASURED, grep).
* The equivalence test compares real old code: `legacy-proof-policy.js` matches `claude/node-cache-proof:proof.js`
  `recordAll`/`uncacheable`/`verifyOne`/`writeReceipts` line by line, except `envDep` (nit above). Its generator is
  limited, so this review adds `review-r032b-policy.test.js`. It uses 3000 inputs with unicode and separator
  characters (`::`, `@@`, NUL) in ids, paths, projects and env names; `''` labels (start-up writer collisions);
  duplicate file and test ids; `upto` 0 / beyond the log; numeric, array and `null` details; env names `toString`,
  `__proto__`, `valueOf`; earlier-session writers with `''` and unicode labels; and hits under every key form.
  Result: **identical stores, recorded counts, reasons and order, verified lists and ran files on all 3000**
  (MEASURED). The only differences are the two nit classes above (object details, prototype flag names), which the
  final file excludes with a comment.

## Claim 3: wrong reuse on the Rust engine

MEASURED (each scenario: record, change one input, fresh run fails, cached run must not reuse). "held" = no wrong
reuse; "refused" = never reused (sound, coarse).

| attack | result |
|---|---|
| order-dependent state through leaked patch / import by name / builtins / environ | **F1** (unittest, nose2, zope, pytest serial + xdist loadgroup); held Django, ward, same file |
| `DirEntry.stat` size | **F2** |
| libc via ctypes | **F3** |
| `os.fstat` on `os.open` fd; `pathlib.Path.exists` / `is_file` / `stat().st_size`; `os.path.exists` bound as a default argument before the test; `glob` with a missing directory component; doctest module-level optional import | held (W6, W8 ×3, W9, W10, W11) |
| R-032 P1–P11 (namespace `__init__`, zipimport, project `.so`, lru_cache/module dict prefix, `.pth`, helper optional import, …) | held (claim 1) |
| Node `module.findPackageJSON` + nested package.json | **F4** (node-test, Mocha, Deno); held Bun |
| `process.loadEnvFile('.env')` changes | held: node-test, Mocha, Bun; refused Deno |
| `fs.globSync` match appears | held all four |
| `TZ` change read by ICU (`Intl…resolvedOptions().timeZone`) | held all four |
| `child_process.execFileSync` reads data; `Bun.spawnSync`; `Deno.Command` | refused (never reused) |
| `Intl.DateTimeFormat().format()` and `performance.timeOrigin + now()` past a real deadline | refused under node-test, Mocha, Bun, Deno |
| Deno `Temporal.Now` past a deadline | **F5** |
| Bun `Worker` reads a file | **F6** |
| Bun global `~/.bunfig.toml` `[define]` (HOME) | held (a fresh `--det` run still passes: not read) |
| `Bun.password.hashSync` (random salt) | held (identical under two `--det` runs: seeded) |
| Deno `deno.json` `imports` retarget; `importMap` file retarget; dynamic import of an absent module that appears; re-export chain leaf change (the load hook is off, only the resolve hook kept) | held (D1, D2, D3, D6) |
| WebCrypto keygen, nested `package.json` type (R-032 F6/F7) under every Node runner, Bun, Deno | held (claim 1) |

Not attacked here (UNKNOWN): `__mocks__` (no runner of this branch uses that convention); tsconfig `paths` under
tsx / ts-node; `deno.lock` / `bun.lock` changes; Django cached template loader (covered by the branch's tests, not
re-attacked); Karma (not built).

## Claim 4: quarantine and sticky placement under non-xdist runners

* They do not apply (MEASURED by reading and run). The quarantine file is written only by the pytest shell
  (`proofcache._after_session` overrides `_proof.ProofSession._after_session`, which is a no-op for the runner
  shells). The plan (`xdist.py` → `schedule.rs`) is built only for `-n`. The runner shells force one process
  (Django `--parallel` → 1, zope `-j` → 1, others serial), so there is nothing to place.
* Can they hide a wrong reuse? Under the runners, no: there is a single process. Under pytest-xdist, F1 occurs with
  the plan in use (W15 `loadgroup`: both files on one worker; the target is reused after the earlier test changes).
  Placement does not cause it: the hole is the same serially. I did not find a case where the quarantine itself moves
  a test into a reuse that a serial run would not make (UNKNOWN beyond the branch's own
  `test_carried_library_memo.py` quarantine tests).

## Claim 5: re-derivation of REPORT-2's numbers (MEASURED from committed raw files)

`python3 sessions/2026-11-20-review-all-runners/rederive2.py --at c17f6c7` (the commit that wrote REPORT-2):
**74,893 verified tests (Python 28,766, Node 46,127), mismatches 0, confirmed wrong 0**. This reproduces the report
exactly. At the reviewed head 7e36c1c: **74,924 (Python 28,797)**, see F7(a). Per-file numbers match the report's
table, and `aggregate2.py` agrees with `rederive2.py` at both revisions.

* Counting is per test (F8): Python `checked == n_reused` on every step. Node `checked + n_missing ==
  skip.summary.reused_tests`, with `n_missing = 0` everywhere. Engine `--det-cache-verify` `verified_tests` equals
  the compared count on every transition. 0 consistency issues (`r032b-raw/rederive2-*.txt`).
* Node's fresh run is a **separate** process tree (`walk.py::fresh_tests`, `detjs <runner> --det` without cache,
  outcomes from its trace). Since F7(d) applies, the per-test comparison itself is DECLARED by the harness and only
  its totals are re-derivable.
* Run ids: 44656473683 (all-runners-python) and 44656473680 (all-runners-node) show status **queued**, and
  44656473729 (node-c) **completed / success**. All three are at head `7510773` on `claude/all-runners-2`. The engine
  field of every Python raw file is `7510773fb8`.
* **Pending (DECLARED in REPORT-2, consistent with the raw files):** django-debug-toolbar, nose2-nose2 (1 shard
  unfinished: `finished` empty), nose2-howdoi shard 1, doctest-autopep8 shard 0, doctest-nameparser shard 0 (shard 1
  landed after the report), commander, dependency-cruiser (2 of 3 shards), yargs (1 of 2), ava-globby,
  jasmine-xregexp, uvu-browserslist, ink, hexo.
* Coverage caveat: three repositories contribute 0 verified tests (ward, thoughtspot-tml, wouter), and howdoi 0. No
  walk transition exercised F1–F6, so the walks are no evidence about them.

## Claim 6: order-dependent tests

**Yes: F1.** `test_b` passes only because `test_a` ran first in the same process (fresh `test_b` alone would fail
too). After `test_a`'s input changes, `test_b`'s cached pass is reused, although in the fresh run `test_b` fails. The
carried-set rule fixes this when the two tests are joined by static imports through a common repository module or
library (R-032 F4 tests, Django W13, same-file W15). It does not when the only join is a name-based write or a
process-global object. Within one Node test file, the prefix rule keeps every earlier test's inputs (held). Across
Node files, every runner runs one process per file under `--det-cache` (MEASURED from the session headers), so no
in-process carry exists. The exception is Bun workers (F6).

## Gates re-run here (MEASURED)

* `cargo test --release --workspace`: **138 passed, 0 failed** (matches REPORT-2).
* Python runner files (`tests/test_runners_{unittest,django,nose2,doctest,zope,ward}.py`) + `tests/review_r032`: **228 passed, 2 skipped**, 0 failed (REPORT-2: 229 passed, 3 skipped; the set and installed packages differ slightly).
* The full Python suite (1031) and the full Node suite (642) were not re-run here; the R-032 and new attack files were.
* Raw: `r032b-raw/gates.txt`.

## Rules check

No human-team time estimates. Every number is labelled. No attack was skipped for difficulty. ward was installed by
hand (its `click-completion` dependency does not build on this setuptools) so that W14 could run. Not run, for lack
of a prerequisite: the de_DE locale (P7), Karma.
