FIX 8

# Review R-032: `claude/all-runners` (14 runners, det + skip with proof)

Reviewed commit: `b8c633390ec8d470efe547a658a2a82207918c55` (branch `claude/all-runners`, `git rev-parse HEAD`).
Compared with `claude/parallel-proof-3` at `74721a4`. Labels: **MEASURED** (run here or re-derived from committed
raw files), **DECLARED** (the branch's documents), **ESTIMATED**, **UNKNOWN**.

Tests added (they fail where a finding is open; they are the "fails before the fix" tests):

* `tests/review_r032/test_review_r032_python.py`: Python attacks under `unittest`, nose2, Django, doctest and the
  pytest plugin.
* `node/test/review-r032.test.js`: `node --test` and Mocha attacks.
* `node/test/review-r032-runners-b.test.js`: tap, AVA, Jasmine and uvu.
* `node/test/review-r032-runtimes.test.js`: `bun test` (Bun 1.4.4) and `deno test` (Deno 2.9.6; run with
  `DETJS_DENO=<path>`).
* `sessions/2026-11-20-review-all-runners/rederive.py`: re-derives claim 2 from the committed raw walk files.

Environment (MEASURED): Python 3.13.18, Node 22.23.5, engine built with `maturin develop --release` and
`npm run build`; local Linux container.

## Verdict

**FIX 8.** Seven attacks cause wrong reuses, or reuse of a test that drew real entropy (F1–F7), and the headline
reuse count is overstated (F8). Every Python wrong reuse (F1–F4) also occurs under the shipped pytest plugin of this
branch, and every one of them is already fixed in Rust on `claude/parallel-proof-3` (MEASURED: the same tests pass
there). F5 is handled on `parallel-proof-3` too. The Node hole F6 is in this branch's JavaScript capture only.

## Findings

| # | claim | finding | runners hit (MEASURED) | test | where to fix | on parallel-proof-3 |
|---|---|---|---|---|---|---|
| F1 | 1, 4 | **Wrong reuse: a namespace package gains `__init__.py`.** `import ns.m, ns`; then `ns/__init__.py` (`FLAG = 1`) appears. The test is reused as passed; a fresh run fails. importlib probes `__init__.*` through `posix.stat` bound at bootstrap, which the `_statcap.py` patches do not see; a successful import notes no miss | unittest, pytest plugin (nose2 discovery happened to rerun) | `test_p2_namespace_package_gains_init`, `test_x_pytest_plugin[namespace_init]` | `crates/detpy-py/src/capture.rs` import probes; `python/detpy/_statcap.py::_find_and_load` notes misses only | fixed (`proof::import_probe`, capture.rs ~2143): test passes |
| F2 | 1, 4 | **Wrong reuse: zipimport.** A module is imported from `lib.zip` on `sys.path` and the member changes inside the archive. Reused | unittest, pytest plugin | `test_p3_zipimport_member_changes`, `test_x_pytest_plugin[zipimport]` | capture.rs `scan_modules`/`want`: a `__file__` inside an archive is dropped, and the archive read under `<frozen zipimport>` is not kept | fixed (capture.rs ~1273): passes |
| F3 | 1, 4 | **Wrong reuse: `ctypes.CDLL` of a project `.so`.** The library is rebuilt with a different return value. Reused. There is no `ctypes.dlopen` audit-event case | unittest, pytest plugin | `test_p4_ctypes_dlopen`, `test_x_pytest_plugin[ctypes_dlopen]` | capture.rs audit hook | fixed (`"ctypes.dlopen"` arm, capture.rs ~1305): passes |
| F4 | 1, 4 (prefix state) | **Wrong reuse: memoised answers.** `functools.lru_cache` over a file read, or a lazily filled module dict: class A reads the file and class B gets the cached answer, so B records no input. After the file changes, A reruns and B is reused as passed although a fresh run fails it | unittest, nose2, pytest plugin | `test_p5_*`, `test_p6_*`, `test_x_nose2[lru_prefix]`, `test_x_pytest_plugin[lru_prefix,module_dict_prefix]` | capture / record step: inputs of earlier contexts in the same process must be carried to later ones | fixed ("carried-set rule", `ee1d06c`/`e1f4527`, record.rs): passes |
| F5 | 1, 4 | **Wrong reuse: a `.pth` file appears in site-packages** and satisfies a failed optional import made at module level | unittest | `test_p11_pth_file_appears` | runtime identity (`runtime_id.py` / `identity.rs`): the site directories' `.pth` set | handled: the runtime digest changes and the test reruns (MEASURED by hand, pytest) |
| F6 | 1, 4 | **Wrong reuse: a nested `package.json` appears** (`lib/package.json` with `"type": "module"`), changing the module format of the unchanged `lib/x.js`; a fresh run fails. `nearestPackageJson` keys the `package.json` it finds and not the absent ones it walked past, and Node reads them in C++ | node --test, Mocha, AVA, Jasmine, uvu (tap: fresh run still passes, n/a) | `review-r032.test.js` N3, `review-r032-runners-b.test.js` N3 | `node/src/cache/capture.js::nearestPackageJson` / `module()`: key every probed `dir/package.json` as absent (JavaScript, not Rust) | no Node code on that branch |
| F7 | 4 (entropy) | **OS entropy not seen: `crypto.subtle.generateKey`** (WebCrypto key material comes from C++/Rust randomness). The file is reused, and two `--det` runs give different keys (node-test: 117 vs 3), so it is also a Level 0 determinism gap. `getRandomValues`, `randomUUID` (seeded), `randomBytes`, `randomInt` and `randomFillSync` are handled | node --test, Mocha, bun test, deno test | N8b, B9, D7 | `node/src/seeds.js` and the Bun/Deno runtimes: flag `subtle.generateKey`/`generateKeyPair*`/`createECDH().generateKeys` as entropy, or seed them | — |
| F8 | 2 | **"153,483 verified reuses" counts each reused Node file once more as a file entry.** `ProofSession.verifyOne` is called for every test id and again for the file id (`proof.js` ~509), so 10,790 of the 153,483 are file entries over the same tests. Tests verified: **142,693** (Python 31,228 + Node 111,465). 2 of the 30 repositories have 0 verified reuses (ward, thoughtspot_tml), and 3 have fewer than 20 (autopep8 17, howdoi 16, nameparser 6) | — | `rederive.py` | report wording; count test-level verified reuses only | — |

### Held (no wrong reuse; MEASURED)

* Python: optional import in a helper made satisfiable by a new file in a namespace directory (reruns); `HOME`
  through `expanduser`; nose2 `nose2.cfg` appearing; Django `DJANGO_SETTINGS_MODULE` switch; Hypothesis profile
  chosen by an env var; doctest existence probe. Failures outside a test body (`tearDownModule`,
  `addModuleCleanup`, `atexit` + `os._exit`) are never reused. Locale through C `getenv`: UNKNOWN (no `de_DE`
  locale here, skipped).
* Node (node-test, Mocha): workspace `exports` retarget, nested `imports` retarget, optional module in an existing
  `node_modules` (refused as `resolve`), `require.resolve` probe, `os.homedir()` with `HOME` changed, `.mocharc.json`
  appearing, `.mocharc.js` outranking `.mocharc.json`. tap/AVA/Jasmine/uvu: nested `main` retarget. Late failures
  (`process.exitCode`, late throw, late rejection, `process.exit` on `beforeExit`) are never reused.
* Bun: `bunfig.toml` appearing, text import, `fetch(file://)`, `Bun.mmap`, `Bun.file().slice()/bytes()`,
  `Bun.resolveSync` probe (sound); `Bun.which`, `bun:ffi` dlopen (refused, never reused).
* Deno: `Deno.readLinkSync` (sound); `deno.json` appearing in the project or in a parent directory, `Deno.dlopen`,
  a Worker reading a file, `statSync().nlink` (refused, never reused).
* Hypothesis: the example database is replaced by a `None` property on the settings class, storage and local
  constants are off (`seeds.py::_hypothesis`); I found no way to reach `.hypothesis/`.

## Claim 2: re-derivation of "0 wrong in 153,483 verified reuses" (MEASURED from committed raw files)

`python3 sessions/2026-11-20-review-all-runners/rederive.py` sums 33 raw files: `tracks/all-runners-python/results/ar-py-3`
(11) and `ar-py-4` (thoughtspot_tml), `harness/node_cache/results/{ar-node-1,ar-node-2,nb1,node-c-r1}` (21). Total
verified **153,483**, mismatches **0**: the number reproduces exactly. Run ids 44568533635 and 44596076577 exist, both
concluded `success`, on `claude/all-runners`; the engine sha in the Python raw files (`60c130e`) is the run's head.

* **Python**: "verified" is an independent fresh run `B` (`pytest`/runner `--det` without the cache) of the same
  commit; `checked == n_reused` on every step (no sampled steps in these files). A mismatch would get a second fresh
  run `B2` (recheck). Caveat: `compare()` skips reused ids missing from the fresh outcomes without counting them
  (`harness/cache_proof/walk.py` ~330). None occurred here.
* **Node**: "verified" is the engine's own `--det-cache-verify` run: same cache state and decisions, every file
  executed fresh in the same per-file process model. Mismatches would get 3 rechecks with an empty cache. It is a fresh
  run of the same commit, but by the engine under review, not a separate plain run as in Python.
* Mismatches 0, so no recheck ran. Since no transition exercised F1–F7, the walks are no evidence about those
  classes.

## Claim 3: shared design

* **Python**: store, keys, decide, verify draw and receipts are in Rust (`CacheSession`), as claimed. This branch's
  absent-input fixes are interception in Python (`python/detpy/_statcap.py`: `os.stat`/`lstat`/`readlink`/`access`
  and `os.path.exists`-family patches, `_find_and_load`/`find_spec` miss notes) feeding Rust (`_core.cap_note_stat` →
  `CaptureCore.probe`, `detpy_core::proof::probe_now`). `parallel-proof-3` does the import-side probes in Rust
  (`proof::import_probe`).
* **Node**: only the store and check (`native.ProofCache`) and the digests are Rust. The session policy is
  JavaScript in `node/src/cache/proof.js`: the not-cacheable table (`UNCACHEABLE`, ~37), the outcome rule
  (`uncacheable`), verify comparison (`verifyOne`), receipts (`writeReceipts`), env-dependency selection (~430) and
  entry composition (~500). This duplicates Rust `detpy-py::session` logic, contrary to DECISIONS 2026-11-18. Bun and
  Deno add their own JS capture (`bun-runtime.js` 529 lines, `deno-runtime.js` 313), which is expected where the
  runtime APIs differ.
* ward: `ward_runner.py` contains a copy of ward 0.68's run loop (DECLARED in the report).
* **Histories**: `claude/all-runners` and `claude/parallel-proof-3` have **no merge base** (`git merge-base`
  returns nothing). `parallel-proof-3` lacks `runners/`, `_statcap.py` and `remote_cache.py`, and has `distid.py`,
  `xdist.py` and `sqlvirt.py` that this branch lacks.

## Claim 5: the open items

* ward at 0 reuse: described honestly (0 verified, 0 wrong). But "every runner meets the bar … 0 wrong reuses" is
  vacuous for ward, and nearly so for doctest (23 verified on 2 repositories) and howdoi (16). Hypothesis has no walk.
* hexo 58 vs 4 under `--det`: labelled "probable cause, not confirmed": honest. yargs listing order: honest.
  Karma: honest.
* "Failed tests are never reused, so this costs reuse, not soundness": held for every case I tried (Python failures
  outside the test body; node-test and Mocha late failures; existing suites cover Deno sanitizer failures). It is
  about false failures only. A false *pass* under `--det` (virtual clock or sorted listing hiding a real failure) is
  outside the claim and UNKNOWN.

## Claim 6: integration note

Where this branch's absent-input fixes live (DECLARED by the report, located MEASURED):

| fix | file / function | language |
|---|---|---|
| path probes (stat, exists family, access, readlink, realpath via them) | `python/detpy/_statcap.py` (`_stat`, `_kind`, `install`) → `CaptureCore.probe` (`crates/detpy-py/src/capture.rs`), `detpy_core::proof::probe_now` | Python interception, Rust keying |
| optional module appearing (Python) | `_statcap.py::_find_and_load`, `_find_spec`, `_note_miss` | Python |
| Django cached template loader | `python/detpy/_django.py` | Python |
| `rmtree` dir-fd writes, in-tree `egg-info` | capture.rs `under_dir_fd`; `python/detpy/runtime_id.py` | Rust / Python |
| Node: prior state of O_EXCL create, mkdir, unlink, rm, rmdir; optional module in an absent directory; `process.binding` and un-virtualized clocks | `node/src/cache/capture.js` | JavaScript |

To have one implementation: take `parallel-proof-3`'s Rust capture (it fixes F1–F5) as the base, port the
`_statcap.py` probe set into it (or check it is already covered there), keep the runner drivers (`runners/`), and
move Node's session policy into the shared Rust session. Because the histories are unrelated, this is a port, not a
merge.

## Rules check

No human-team time estimates. Each number above carries a label. No attack was skipped for difficulty. Two were not
run for lack of a prerequisite: the `de_DE` locale (P7, UNKNOWN), and Karma, which was not built.
