PARTIAL

# rust-hotpaths: capture overhead of `--det --det-cache`, hot paths to Rust

Branch `claude/rust-hotpaths` (base: `claude/cache-proof-step1` at 24b6d15; its later commits, results only, merged).
Labels: MEASURED (numbers from runs named here), ESTIMATED (derived), not marked = description. Profile of the base
engine and method: [INTERMEDIATE-1.md](INTERMEDIATE-1.md).

PARTIAL because the home-assistant target (cold run <= 1.1x plain pytest) is not reached (1.27-1.37x on the three
profiled shards, from 1.41-1.57x) and the home-assistant verification walk was still running when this was written
(status at the end).

## Exit numbers

### Overhead, base engine vs this branch, same job (MEASURED, GitHub Actions run `<<RUN>>`)

`harness/rust_hotpaths/profile.py`: each job sets a spec up at its HEAD commit exactly as the cache-proof walk does
(same 12 % home-assistant sample and shards, same pytest arguments), then runs, interleaved and unprofiled, plain
pytest, and for each engine (base 24b6d15 and this branch, swapped in the same venv, each with its own bytecode cache)
`--det`, a cold `--det-cache` (empty cache) and a warm one (same cache again). Medians of 3 (home-assistant) or 5
rounds.

<<WALLS>>

Cold run / plain pytest, the price-relevant number:

| project | base | this branch | target |
|---|---|---|---|
<<TARGET>>

### Verification walk (MEASURED, workflow `rust-hotpaths-walk`, run `w1`, engine f7501bf)

Same specs and commits as the base walks; every reused result checked by a fresh `--det` run at the same commit, a
mismatch re-run once to tell wrong from flaky (`harness/cache_proof/walk.py`, unchanged).
`harness/rust_hotpaths/compare_walks.py <base dir> tracks/rust-hotpaths/walk/w1`:

<<WALK>>

## What moved to Rust, and what else changed

In order of measured gain. "Identical" = checked as described in "Equivalence".

| # | change | where | gain (MEASURED) | identical? |
|---|---|---|---|---|
| 1 | Followed children: a trace log whose strace tracer is gone is final, so it is not waited for; the wait it would have had is charged to the 3 s budget so every other child gets the wait it had before. `_core.tracer_prefixes` scans `/proc/*/cmdline` for live `-o <prefix>` arguments. | `sysmon.rs`, `Capture.collect_children` | click: children phase 3.0 s -> 0.12 s per cold run (13 pager children killed before strace wrote a log) | yes |
| 2 | `--det` precompile compiled nothing installed: the project exclusions (`venv/`, `.venv/`, `.git/` ...) were applied to the library directories too, which live in a venv themselves, so with `PYTHONDONTWRITEBYTECODE=1` every installed module was compiled from source at every `--det` run. Libraries are now compiled without them (the project keeps them); `stamps-v2.json` so the old stamps do not hide the fix. | `reexec.py` | home-assistant `--det`: 1.22-1.39x -> 1.14-1.25x plain | **behaviour change of `--det`**, see below |
| 3 | Per-test assembly of every test's inputs (`_record_all`'s Python loop: copies of the global inputs per test, a pass over every loaded module per test) -> `detpy_core::record::record_session`, fed one plan of plain data (JSON). Global reads are shared (`Arc<str>`, same JSON) and overlaid per test instead of copied. `ProofCache.unit_ranges` replaces one `file_facts` conversion per file. | `detpy-core/src/record.rs`, `proofcache.rs`, `_record_captured`/`_plan` | pygments: 617 -> ~80 samples; HA-shaped plan 0.19 s -> 0.10 s for 624 tests | yes |
| 4 | Line recorder maps: multiplicative integer hasher instead of SipHash (the top frame of the LINE callback on home-assistant) | `sysmon.rs` | ~30-40 % less per callback (bench) | yes (same maps, other hash) |
| 5 | Socket scan at every context switch: Rust, by `fstat` of each descriptor (was `os.listdir` through detpy's sorted listdir plus a `readlink` per descriptor) | `sysmon.rs` `SocketScan` | 318 -> 108 us per scan at 204 descriptors | yes |
| 6 | File facts: the skeleton and import walks visit statement lists only (statements never occur inside expressions); the old `NodeTransformer` visited every node of the bodies it then dropped | `_codefacts.py` (Python: the parse is CPython's) | 1.9x faster on pygments + stdlib | yes |
| 7 | Runtime identity: name, version and RECORD digest of each distribution read in Rust where the plain header reading is certain to match `importlib.metadata` (falls back otherwise) | `proofcache.rs` `dist_identity` | ~690 -> 77 us per distribution (~1,400 on home-assistant, every cold run) | yes |
| 8 | Env capture: a variable the current context already read is not recorded again, so the caller frame walk is skipped (outside imports) | `proofcache.py` `_note_env` | click env bucket | yes |
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
  <<EQUIV>>
* **On real environments** (`equiv_probe.py`, run inside each project's venv): file facts old vs new on up to 3,000
  of the project's files, distribution identity on every installed distribution. <<PROBE>>
* Engine suite: `pytest tests` 154 passed, 6 skipped; `cargo test -p detpy-core` 49 passed (MEASURED, local).
* Review R-009 tests: `tests/test_review_r009.py` as on `claude/cache-proof-step1` (11 tests) passes. The original
  version on `claude/review-r009-tests` fails one test, `test_git_head_read_is_an_input`, on this branch **and on the
  base 24b6d15** alike (MEASURED): `claude/cache-proof-step1` amended that assertion for its F4 fix (a git child reads
  the real clock and is refused instead of reused).

## What is left between home-assistant and 1.1x

<<LEFT>>

## Findings for the reviewers (not changed here)

1. **Line capture can drop import-time hits.** A location's events are disabled after 16 hits in a context
   (`hot`); a later hit of the same location in the same context with the other import flag (a function first run
   normally, then run during an import, or the reverse) is then not recorded. The import-time flag makes a unit an
   input of *every* test, so the miss can hide an input of other tests. Not changed: any fix changes keys.
2. **Global capture on home-assistant varies run to run in the base engine too.** Integration platforms are set up
   concurrently (executor threads); which platform modules and units land in the global import-time contexts
   differs between two runs of the same engine (MEASURED locally on shard 0: all 441 entries differ between two base
   runs, by ~20 units and a few data paths). Reuse still holds (each run records a correct superset of its own
   reads), but the keys of a shard are not reproducible and a store written by one run can differ from the next.
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
