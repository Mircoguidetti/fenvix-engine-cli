PARTIAL

# rust-hotpaths: capture overhead of `--det --det-cache`, hot paths to Rust

Branch `claude/rust-hotpaths` (base: `claude/cache-proof-step1` at 24b6d15; its later commits, results only, merged).
Labels: MEASURED (numbers from runs named here), ESTIMATED (derived), not marked = description. Profile of the base
engine and method: [INTERMEDIATE-1.md](INTERMEDIATE-1.md).

PARTIAL because the home-assistant target (cold run <= 1.1x plain pytest) is not reached: **1.27-1.41x** on the
profiled shards and **1.29x** in the walk, from 1.41-1.57x and 1.47x. Every reuse checked so far is right (0 wrong);
the home-assistant verification walk was still running when this was written (status under "Verification walk").

## Exit numbers

### Overhead, base engine vs this branch, same job (MEASURED, GitHub Actions runs `p3` and `p2`)

`harness/rust_hotpaths/profile.py`: each job sets a spec up at its HEAD commit exactly as the cache-proof walk does
(same 12 % home-assistant sample and shards, same pytest arguments), then runs, interleaved and unprofiled, plain
pytest, and for each engine (base 24b6d15 and this branch, swapped in the same venv, each with its own bytecode cache)
`--det`, a cold `--det-cache` (empty cache) and a warm one (same cache again). Medians of 3 (home-assistant) or 5
rounds.

Run `p3` (this branch at 3131a06, all engine commits; home-assistant shard 5 had not finished) and run `p2`
(this branch at 58dddd1: changes 1-6 and 10 of the table below; it has the three shards):

| project | tests | plain pytest | --det base / new | cold base / new | warm base / new | --det / plain base / new | cold / --det base / new |
|---|---|---|---|---|---|---|---|
| click (p3) | 2653 | 7.4s | 8.0s / 7.8s | 13.8s / **9.7s** | 8.5s / 5.1s | 1.08x / 1.05x | 1.72x / 1.24x |
| pygments (p3) | 5346 | 14.5s | 16.3s / 16.1s | 21.0s / **18.9s** | 5.4s / 4.7s | 1.12x / 1.11x | 1.29x / 1.17x |
| home-assistant 0/16 (p3) | 444 | 38.5s | 54.0s / 48.2s | 57.9s / **49.5s** | 19.9s / 14.5s | 1.40x / 1.25x | 1.07x / 1.03x |
| home-assistant 10/16 (p3) | 624 | 25.5s | 37.1s / 31.8s | 36.8s / **36.0s** | 14.2s / 11.5s | 1.46x / 1.25x | 0.99x / 1.13x |
| home-assistant 0/16 (p2) | 444 | 28.0s | 38.9s / 35.1s | 43.9s / **38.4s** | 15.7s / 11.9s | 1.39x / 1.25x | 1.13x / 1.10x |
| home-assistant 5/16 (p2) | 1428 | 57.9s | 70.5s / 66.0s | 81.5s / **73.3s** | 79.6s / 72.0s | 1.22x / 1.14x | 1.16x / 1.11x |
| home-assistant 10/16 (p2) | 624 | 24.9s | 33.2s / 30.7s | 37.6s / **32.7s** | 14.4s / 11.1s | 1.33x / 1.23x | 1.13x / 1.06x |

Home-assistant walls move by 10-30 % between runs of the same job on different runners (plain pytest of shard 0:
28.0 s in p2, 38.5 s in p3; in p3 shard 10 the base's cold run was faster than its own `--det` run): read the
home-assistant rows as ranges. The walk's cold/plain ratio below, 16 shards over many commits, is the steadier number.

Cold run / plain pytest, the price-relevant number:

| project | base | this branch | target |
|---|---|---|---|
| click | 1.86x (p3) | **1.30x** (p3) | 1.1x |
| pygments | 1.44x (p3) | **1.30x** (p3) | 1.1x |
| home-assistant 0/16 | 1.50x (p3), 1.57x (p2) | **1.28x** (p3), 1.37x (p2) | 1.1x |
| home-assistant 5/16 | 1.41x (p2) | **1.27x** (p2) | 1.1x |
| home-assistant 10/16 | 1.44x (p3), 1.51x (p2) | **1.41x** (p3), 1.31x (p2) | 1.1x |
| home-assistant, walk (16 shards, every 10th commit, median) | 1.47x (s1f) | **1.29x** (w1) | 1.1x |
| click, walk | 1.72x (w0) | **1.08x** (w1) | 1.1x |
| pygments, walk | 1.37x (w0, 9 commits so far) | **1.23x** (w1, same 9 commits) | 1.1x |

Home-assistant: **1.27-1.41x, target 1.1x not reached.** Click reaches it in the walk (1.08x) but not at its HEAD
commit (1.30x: more tests, more followed children); pygments 1.23-1.30x.

### Verification walk (MEASURED, workflow `rust-hotpaths-walk`, run `w1`, engine f7501bf)

Same specs and commits as the base walks; every reused result checked by a fresh `--det` run at the same commit, a
mismatch re-run once to tell wrong from flaky (`harness/cache_proof/walk.py`, unchanged).
`harness/rust_hotpaths/compare_walks.py <base dir> tracks/rust-hotpaths/walk/w1`:

| project | commits compared | reused results base / new | reused test time base / new | commits with a different reuse count | verified reuses (wrong, flaky) | cache run A, median base / new | cold / plain pytest, median base / new |
|---|---|---|---|---|---|---|---|
| click (w0 = base engine 24b6d15, same commits) | 43 | 28,700 / 28,700 | 31.5% / 31.5% | **0** | 28,700 (**0**, 0) | 12.8s / 7.6s | 1.72x / 1.08x |
| pygments (w0, first 9 transitions; rest running) | 9 | 15,760 / 15,760 | 33.0% / 32.9% | **0** | 58,136 over 51 commits (**0**, 0) | 21.6s / 19.6s | 1.37x / 1.23x |
| home-assistant (s1f = base walk, same commits) | 19 with all 16 shards | 140,768 / 140,760 | 61.6% / 62.3% | 5 (1-2 results of ~9,600 each) | 342,785 (**0**, 1) | 500.2s / 388.1s | 1.47x / 1.29x |

* **0 wrong reuses** in every walk so far (MEASURED). The one home-assistant mismatch is flaky
  (`tests/components/mqtt/test_sensor.py::test_cleanup_triggers_and_restoring_state[hass_config0]`: cached passed,
  fresh failed, fresh again passed).
* Reuse share: identical at every commit on click (w0 vs w1) and on pygments so far; on home-assistant within 1-2
  results per commit, the size of the base's own run-to-run variation (finding 2).
* Walk status when written: click and pygments w1 complete (51 commits); home-assistant w1: 11 shards at 50
  commits, shards 0, 11, 12 at 40, 7 at 30, 4 at 20 (still running; results commit themselves to
  `tracks/rust-hotpaths/walk/w1/`); w0 pygments at 10 of 51. The w1 engine (f7501bf) lacks changes 8, 9 and the
  shared-string part of 3, all output-identical (click: identical stores and receipts against the base).
* The s1d click walk (older engine) reused 336 more: 24 `less` children that the base's R-009 F4 fix refuses
  ("reads the real clock"), not this branch (w0, with the base engine, reuses exactly what w1 does).

## What moved to Rust, and what else changed

In order of measured gain. "Identical" = checked as described in "Equivalence".

| # | change | where | gain (MEASURED) | identical? |
|---|---|---|---|---|
| 1 | Followed children: a trace log whose strace tracer is gone is final, so it is not waited for; the wait it would have had is charged to the 3 s budget so every other child gets the wait it had before. `_core.tracer_prefixes` scans `/proc/*/cmdline` for live `-o <prefix>` arguments. | `sysmon.rs`, `Capture.collect_children` | click: children phase 3.0 s -> 0.12 s per cold *and* warm run (13 pager children killed before strace wrote a log) | yes |
| 2 | `--det` precompile compiled nothing installed: the project exclusions (`venv/`, `.venv/`, `.git/` ...) were applied to the library directories too, which live in a venv themselves, so with `PYTHONDONTWRITEBYTECODE=1` every installed module was compiled from source at every `--det` run. Libraries are now compiled without them (the project keeps them); `stamps-v2.json` so the old stamps do not hide the fix. | `reexec.py` | home-assistant `--det`: 1.22-1.39x -> 1.14-1.25x plain | **behaviour change of `--det`**, see below |
| 3 | Per-test assembly of every test's inputs (`_record_all`'s Python loop: copies of the global inputs per test, a pass over every loaded module per test) -> `detpy_core::record::record_session`, fed one plan of plain data (JSON). Global reads are shared (`Arc<str>`, same JSON) and overlaid per test instead of copied. `ProofCache.unit_ranges` replaces one `file_facts` conversion per file. | `detpy-core/src/record.rs`, `proofcache.rs`, `_record_captured`/`_plan` | record.loop samples, pygments: 617 (p1, base) -> 201 (p3); HA-shaped plan 0.19 s -> 0.10 s for 624 tests | yes |
| 4 | Line recorder maps: multiplicative integer hasher instead of SipHash (the top frame of the LINE callback on home-assistant) | `sysmon.rs` | ~30-40 % less per callback (bench) | yes (same maps, other hash) |
| 5 | Socket scan at every context switch: Rust, by `fstat` of each descriptor (was `os.listdir` through detpy's sorted listdir plus a `readlink` per descriptor) | `sysmon.rs` `SocketScan` | 318 -> 108 us per scan at 204 descriptors | yes |
| 6 | File facts: the skeleton and import walks visit statement lists only (statements never occur inside expressions); the old `NodeTransformer` visited every node of the bodies it then dropped | `_codefacts.py` (Python: the parse is CPython's) | 1.9x faster on pygments + stdlib | yes |
| 7 | Runtime identity: name, version and RECORD digest of each distribution read in Rust where the plain header reading is certain to match `importlib.metadata` (falls back otherwise) | `proofcache.rs` `dist_identity` | ~690 -> 77 us per distribution (~1,400 on home-assistant, every cold run) | yes |
| 8 | Env capture: a variable the current context already read is not recorded again, so the caller frame walk is skipped (outside imports) | `proofcache.py` `_note_env` | click env samples 87 (p2) -> 44 (p3) | yes |
| 9 | Store save skipped when nothing was touched and no written path is new (it rewrote the same bytes) | `proofcache.rs` `save` | home-assistant warm run: 1.2 s | yes (file untouched) |
| 10 | Trace writer serializes each test record by reference (was a deep copy of every test's events) | `trace.rs` | `--det`, every test | yes (byte-identical) |

Measured and dropped: a Rust `repr` of the random state for `seeds.end_test` (no gain: CPython's repr is already C);
raw `METH_FASTCALL` monitoring callbacks (not available under the abi3/py39 limited API the wheel is built for).

Sizes: `python/detpy` 6,124 lines (from ~6,200), `crates/` 4,705 (from ~3,800). The new Rust: `record.rs` (per-test
assembly), `SocketScan`, `tracer_prefixes`, `dist_identity`, `unit_ranges`, `record_session`.

### The one behaviour change: precompile of installed modules (#2)

Before, under `--det` every installed module was compiled from source at every run (deterministic: same fixed hash
seed); now it is loaded from the deterministic bytecode cache, compiled under the same seed, which is what
`reexec.py` documents. A test whose outcome depends on the iteration order of a set *constant* in an installed module
could in principle behave differently between the two (the module docstring explains why a `.pyc` and a fresh compile
can lay a frozenset out differently); both are deterministic, and the verification walk compares the cache with
fresh `--det` runs of the same engine. It is a separate commit (58dddd1, reexec.py hunk) and can be reverted alone:
the capture work does not depend on it. The other nine changes keep keys, receipts and decisions identical.

## Equivalence (old path vs new path)

* **Old Python paths kept verbatim** in `tests/rust_hotpaths_ref/` (`_record_all` body, `_scan_sockets`,
  `_codefacts`), and `tests/test_rust_hotpaths.py`:
  * `test_record_session_matches_reference`: a project with module/session fixtures, conftest hooks, import-time
    reads, a doctest, a non-Python file, env reads (one variable, whole environment), clock, random, a followed
    subprocess, a host lookup, a /proc read, a failure, skip, xfail, a test module imported by another, a test
    writing what another reads; four sessions (new, unchanged, code + env change + a write into a reused test's
    input = stale reuse, after the writes). Every session records twice through a pytest plugin
    (`_eqplugin.py`): the old loop into a copy of the cache directory, the new path into the real one; the
    decisions, reasons, "where" reports, stale reuses and the canonical stores must be identical.
  * socket scan against the old scan in lockstep (TCP/UDP/IPv6/Unix sockets opened and closed), and the `fstat`
    inode against the `/proc` link;
  * file facts against the old module on 1,500 files (stdlib, site-packages, this repository) plus edge cases
    (nested functions, `try*`, `match`, decorators with lambdas, type parameters, syntax errors);
  * distribution identity against `importlib.metadata` on every installed distribution and crafted metadata
    (duplicates, folding, BOM, CRLF, tabs, missing name/version, PKG-INFO fallback, undecodable RECORD);
  * `tracer_prefixes`, `unit_ranges`, a store left untouched by an unchanged session.
* Rust unit tests: the per-test data overlay against a plain ordered map (randomized), the borrowed trace line
  byte-identical to the old one.
* **Across engines on real projects** (`profile.py` compare, `harness/rust_hotpaths/canon.py`): the cold store of the
  base and of this branch resolved to (path, content digest) per input, plus warm-run receipts. Tests whose entry or
  decision differs between two rounds of the *same* engine are run-to-run noise and counted apart.
  Run p3 (MEASURED): click 2,616 entries, **0 differences**, 0 warm decision differences (noise: 0); pygments 5,346
  entries, **0** outside noise (noise: 8, `test_random_input[...]`, randomized inputs); home-assistant shards 0 and
  10: **0** outside noise, but the noise covers 444 of 444 and 594 of 624 entries (finding 2), so on home-assistant
  this comparison says little beyond "no systematic difference"; the per-module equivalence tests and the walk carry
  it there. Fingerprint-only differences (threads) are listed apart.
* **On real environments** (`equiv_probe.py`, run inside each project's venv): file facts old vs new on up to 3,000
  of the project's files, distribution identity on every installed distribution. p3 (MEASURED): home-assistant 3,000 of its files and **1,727 of 1,727 distributions identical** (all on the Rust
  path), facts 9.1 s -> 5.8 s; click 91 files, 10 distributions; pygments 405 files, 19 distributions: identical.
* Engine suite: `pytest tests` 154 passed, 6 skipped; `cargo test -p detpy-core` 49 passed (MEASURED, local).
* Review R-009 tests: `tests/test_review_r009.py` as on `claude/cache-proof-step1` (11 tests) passes. The original
  version on `claude/review-r009-tests` fails one test, `test_git_head_read_is_an_input`, on this branch **and on the
  base 24b6d15** alike (MEASURED): `claude/cache-proof-step1` amended that assertion for its F4 fix (a git child reads
  the real clock and is refused instead of reused).

## What is left between home-assistant and 1.1x

Home-assistant cold run now: `--det` 1.14-1.25x plain, capture on top 1.03-1.13x (MEASURED p2/p3). Both must
shrink to reach 1.1x:

* **`--det` itself (the larger part).** After the precompile fix what remains is spread over the Python wrappers
  of the virtual clock and the Level 0 event path, which asyncio calls on every loop iteration (`monotonic`,
  `VirtualClock.read` under an RLock, `_rel`, `_state.record` -> `_sites.resolve` frame walk -> Rust recorder):
  det.plugin + det.clock 17-22 % of the `--det` difference in p3, the rest not attributable to a frame. Next step:
  the clock functions as Rust builtins holding the clock state, and call-site resolution in Rust (the frame walk with
  the same classification cache). ESTIMATED -0.05 to -0.10x on home-assistant.
* **Line capture** (largest capture bucket on home-assistant: 10-19 % in the callbacks, plus most of the
  unattributed 36-69 %, the interpreter running instrumented code). The callbacks are as cheap as the current
  strategy allows (hasher; raw C callbacks are blocked by the limited API). A cheaper strategy (function-level
  events, units from `PY_START`/`PY_RESUME` instead of every line) changes keys in exactly the cases of finding 1,
  so it belongs with that fix, reviewed as a behaviour change. ESTIMATED -0.05x.
* Facts on cold runs (10 % of capture): CPython's `ast.parse` dominates now; a content-addressed facts memo shared
  across cache directories would remove it from cold runs (a design decision: "cold" would no longer mean "nothing
  known").

## Findings for the reviewers (not changed here)

1. **Line capture can drop import-time hits.** A location's events are disabled after 16 hits in a context
   (`hot`); a later hit of the same location in the same context with the other import flag (a function first run
   normally, then run during an import, or the reverse) is then not recorded. The import-time flag makes a unit an
   input of *every* test, so the miss can hide an input of other tests. Not changed: any fix changes keys.
2. **Global capture on home-assistant varies run to run in the base engine too.** Integration platforms are set up
   concurrently (executor threads); which platform modules and units land in the global import-time contexts
   differs between two runs of the same engine (MEASURED locally on shard 0: all 441 entries differ between two base
   runs, by ~20 units and a few data paths). Every run's entries hold what that run observed and the walks found no wrong reuse, but the keys of a shard are not reproducible and a store written by one run can differ from the next.
3. **A venv inside the repository root is captured as repository code**: every installed module the tests load
   (detpy included) becomes a whole-file input (616 files on a home-assistant sample), so reinstalling detpy
   invalidates everything. The walks keep the venv outside the source tree, real projects often do not (`.venv/`).
4. **home-assistant shard 5: nothing is ever cached** (all 1,428 tests "subprocess", base and this branch alike,
   MEASURED p1/p2); every test's reason is "subprocess", so a process started outside the tests reaches every
   context. Cause not investigated here.

## Files

* `crates/detpy-core/src/record.rs` (new), `crates/detpy-py/src/{proofcache,sysmon,lib}.rs`,
  `crates/detpy-core/src/{proof,trace}.rs`; `python/detpy/{proofcache,_codefacts,reexec}.py`.
* `tests/test_rust_hotpaths.py`, `tests/rust_hotpaths_ref/`, `tests/test_precompile_stamp.py`.
* `harness/rust_hotpaths/` (`profile.py`, `analyze.py`, `canon.py`, `compare_walks.py`, `equiv_probe.py`,
  `execcap/`), `.github/workflows/rust-hotpaths{,-walk}.yml`; runs `p1` `p2` `p3` in
  `tracks/rust-hotpaths/results/`, walks `w0` `w1` in `tracks/rust-hotpaths/walk/`.
