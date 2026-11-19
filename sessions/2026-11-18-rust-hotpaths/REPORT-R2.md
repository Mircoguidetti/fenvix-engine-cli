FIRSTLINE

# rust-hotpaths, round 2: everything that is not interface moves to Rust

Branch `claude/rust-hotpaths-2`. Founder decision (DECISIONS 2026-11-18): move to Rust everything in `python/detpy`
that is not the interface Python requires; Python keeps thin shims (pytest hooks, patched entry points,
`sys.monitoring` / audit-hook registration, CLI entry). Round 1: [REPORT.md](REPORT.md). Fix rounds merged into this
branch and ported into the Rust modules: review R-015 F1-F4 and R-015b G1-G3 (`claude/rust-hotpaths`), review R-009b
R1-R4 (`claude/cache-proof-step1` to 3b197a4).

Labels: **MEASURED** (a run named here), **ESTIMATED** (derived). "local" = this container (4 CPUs, Python 3.13, the
harness's own venvs, all four engines interleaved in one job); "CI" = GitHub Actions runs committed under
`tracks/rust-hotpaths/` (one runner per project / shard, engines interleaved). Local and CI rows are not comparable
with each other; the columns of one row are. The final engine is a9981c5 (CI p8 / w6 ran e2696ec, the same code plus
the run files).

STATUSLINE

## Result

Python in `python/detpy`: **6,203 -> 4,006 lines** (round-2 start c28a531 -> final); Rust in `crates/`: 5,783 ->
19,012 lines (with tests). What stays Python is listed per module below, each with the reason.

Cold run (empty cache), fully reused run ("floor") and `--det` without cache, each / plain pytest, medians (MEASURED):

| project | metric | base (24b6d15) | round 1 (128dcc6) | round 2 checkpoint (c28a531, "clock and call sites") | round 2 final | source |
|---|---|---|---|---|---|---|
| click | cold / plain | 1.78x | 1.22x | 1.21x | **1.03x** | CI p8 (5 rounds) |
| click | floor / plain | 1.13x | 0.68x | 0.66x | **0.52x** | CI p8 |
| click | `--det` / plain | 1.01x | 0.99x | 0.95x | **0.78x** | CI p8 |
| pygments | cold / plain | P8_PYG_COLD | CI p8 |
| pygments | floor / plain | P8_PYG_WARM | CI p8 |
| home-assistant 0/16 | cold / plain | P8_HA0_COLD | CI p8 (3 rounds) |
| home-assistant 5/16 | cold / plain | P8_HA5_COLD | CI p8 |
| home-assistant 10/16 | cold / plain | P8_HA10_COLD | CI p8 |
| home-assistant 0 / 5 / 10 | floor / plain | P8_HA_WARM | CI p8 |
| click | cold / plain | 1.71x | 1.23x | 1.19x | **1.05x** | local profile (3 rounds) |
| click | floor / plain | 1.07x | 0.65x | 0.60x | **0.49x** | local profile |
| pygments | cold / plain | 1.49x | 1.35x | 1.30x | **1.33x** | local profile |
| pygments | floor / plain | 0.40x | 0.34x | 0.34x | **0.28x** | local profile |
| click | floor / plain | 1.12x | 0.69x | 0.65x | **0.52x** | local floor.py (3 rounds) |
| pygments | floor / plain | 0.41x | 0.36x | 0.35x | **0.28x** | local floor.py |

Sources: `tracks/rust-hotpaths/results/p8/` (CI), `results/local-final/profile-*.json`, `floor/final-*.json`. The
checkpoint's own CI run p5 (base, round 1, checkpoint) measured cold / plain click 1.88 / 1.33 / 1.32, pygments 1.43 /
1.32 / 1.31, home-assistant 0/16 1.57 / 1.35 / 1.28, 5/16 1.35 / 1.31 / 1.22, 10/16 1.52 / 1.29 / 1.24.

pygments' cold run did not get faster in round 2 (1.30x -> 1.33x local, within the run-to-run spread of 3 rounds):
its 5,346 tests spend the cold run's detpy time in recording (1.27 s of 17.6 s, the same in both engines: `facts`, the
CPython parse of every new file version, and `assemble`, `detpy_core::record`, already Rust since round 1) and in the
`--det` controls; the R-009b / R-015b fixes add work (one `stat` and `realpath` per file opened under the root, child
stats) that the moves pay back.

## Module table

Python lines are `wc -l` at the start of round 2 (c28a531) and now. Gains are the measured cost of the moved path,
old Python (kept as the reference) vs new, unless said otherwise.

| module | lines before / after | moved to Rust | stays Python, and why | gain (MEASURED unless marked) |
|---|---|---|---|---|
| `proofcache.py` | 1921 / 728 | `capture.rs`: the audit hook and everything it calls (caller-kind / import-context / first-user-site frame walks, paths, reads, writes, R-015 F1 stat keys, R-009b R2 exclusive creates, R-015b G2 / G3), contexts and `switch`, env reads, Level 0 events, `arm`, `scan_modules`, followed-children crediting (R-015b G1); `proofcache.rs`: decisions (`check_all`, expiry), reuse entries, receipts writer; `proof.rs`: memoised checker; `session.rs` (`CacheSession`): the decisions' bookkeeping and the verification draw, per-test reports, durations / fixtures / fingerprints, `_final`, the verified-result comparison, the R-009b R2 seeding and `stale_skip`, the record plan (built as a `record::Plan`, no JSON round trip), `_where` / `_ctx_label`, `summary_data`, the outcomes file's cache part, the terminal summary lines; `identity.rs`: runtime identity (per-distribution memo, stat keys, `direct_url.json`, memo file, digest), `tz_locale_identity`, `cache_epoch`, env0 (`_safe`); `sqlcap.rs`: the sqlite trace (a Rust callable as trace callback; the four regexes as matchers checked against `re` on every code point), ATTACH parsing, the schema memo, `_sqlite_file`; `sockcap.rs`: `_own_listener`, `_both_ends_mine`, socket inodes, `_loopback_hex`, `_numeric_host`, `_addr`, `_spawn_detail` | pytest hooks of `ProofCachePlugin` (pytest objects in, `TestReport`s out for a reused result); `Capture.start/stop` (`sys.monitoring` / audit-hook registration); the `sqlite3.connect` patch and the one read-only schema query through the real `connect` on a memo miss (needs the `sqlite3` module and `urllib.parse.quote`); `_patch_environ` (swaps `os.environ`'s class); `config_identity` (pytest's config objects; `repr` of option values); distribution discovery (`importlib.metadata.distributions()`, the finders are Python's) and the importlib reading of a distribution that is not a plain dist-info directory; `_module_of` (`sys.modules`); the facts driver (CPython's parser, see `_codefacts`); `_run_time` (`time.strptime`'s rules, which changed between Python versions: a Rust parser disagreed with 3.13's on run ids during the move, so Rust calls it once per distinct run id) | capture per call: `open` 4.0 -> 1.5-2.4 us, `os.listdir` 3.4 -> 1.5 us, `os.environ.get` 0.35 -> 0.30 us; warm check (3,000 tests) 0.060 -> 0.015 s; checker memo on pygments' store 0.29 -> 0.16-0.24 s; sqlite trace per statement 0.92 -> 0.27 us (`:memory:`), 5.7-6.1 -> 2.4-2.8 us (file + ATTACHed db); runtime identity with 1,008 distributions, warm memo 43.1 -> 29.3 ms, no memo 65.7 -> 41.3 ms; `tz_locale_identity` 47-54 -> 11-13 us; record plan: click cold run `plan` 0.086 -> 0.062 s, pygments `facts` + `plan` 0.534 -> 0.554 s (the whole-content files' facts now count under `facts`: no gain) |
| `follow.py` | 675 / 371 | `follow.rs`: strace log parsing, R-009b R2 (op `a`) and R4 (child stats) | `Follower` (patches `_posixsubprocess.fork_exec`), `probe` / `build_shim` (strace and a C compiler, once per session), `_wait_logs` | parse of real logs 156.0 -> 8.3 ms over 7 logs; cold run `children` phase (crediting, incl. this parse) click 0.126 -> 0.034 s |
| `clock.py` | 490 / 391 | `clock.rs`: `sleep`, the wall-derived functions, `clock_gettime[_ns]`, `datetime.now/utcnow`, the wait-timeout rules, the process-start stand-ins | `install/uninstall` (patching), `_TimedLock` / `_TimedLockMeta` (types: `isinstance`, method binding), one-line shims for `Condition.wait`, `select`, `acquire` | `datetime.now()` 2.1-2.7 -> 0.88-1.1 us; `time.localtime()` 2.1-2.8 -> 0.95-1.25 us |
| `network.py` | 545 / 284 | `network.rs`: policy (`ipaddress` parsing ported, checked on 200k strings), connect / sendto / DNS decisions, the wrappers as method descriptors, recording bookkeeping, cassette lookups | replay server thread, `ReplayTLSSocket`, `NetworkBlockedError`, `SSLContext.wrap_socket` shim, `install/uninstall` | blocked `connect` 5.2 -> 1.7 us; loopback `connect_ex` 6.0 -> 3.2 us |
| `seeds.py` | 178 / 117 | `seeds.rs`, `standin.rs`: every random draw wrapper, `Random.seed`, `os.urandom`, `numpy.default_rng`, per-test counter and keys | `install`, `start_test`, `end_test` (gc scan, numpy, tempfile: Python objects) | `random.random()` 1.5-1.6 -> 0.73-0.94 us |
| `fsorder.py` | 134 / 87 | `fsorder.rs`: `listdir`, `scandir`, the event | glob / pathlib wrappers (method binding, lazy generators) calling Rust | `os.listdir` (5 entries) 6.9-7.4 -> 4.3-5.6 us |
| `_sites.py` | 163 / 126 | `norm_path`, `_shorten` | `_dirs` / `refresh` (`sysconfig`, `sys.modules`) | part of the `listdir` gain |
| `_state.py` | 98 / 98 | `digest_names` (a one-line call) | `Config` / `State` dataclasses, `quiet` context manager | - |
| `reexec.py` + `_pycompile.py` | 320 + 0 / 212 + 95 | `precompile.rs`: the checked-hash bytecode check (R-015 F2/F3, CPython's keyed SipHash), `dir_stamp`; `reexec.rs`: ASLR / `personality(2)`, `plan`, `_argv`, `can_reexec`, cache dir, the precompile's stamps and decision | `os.execve`; `sysconfig.get_paths()`; `_pycompile.py` is the driver of the child interpreter that compiles (CPython's `py_compile`) | unchanged project precompile 0.142 -> 0.034 s (5,364 files); pre-exec stage of a warm run (`X`) click 0.32 -> 0.21 s, pygments 0.43 -> 0.22 s |
| `repro.py` | 489 / 275 | `repro.rs`: `ddmin`, prefix / order / slug, trace divergence, outcome classes, explore book-keeping, bundle content | the Runner (pytest subprocesses), bundle writes, argument parsing | none by design: 99.9 % of `detpy repro` is pytest subprocesses |
| `plugin.py` | 685 / 717 | `_final_outcome` -> `_core.det_outcome` | pytest hooks and glue on pytest objects (options, items, reports, the pytest-django grouping hook), `_exception_of` (reads `report.longrepr`), the epoch (`git log` subprocess, `datetime.fromisoformat`'s version-dependent rules), `--det-order` file reading. +42 lines: the rewritten-test-module cache shim (below) | - |
| `_codefacts.py` | 235 / 235 | - | the facts are digests of CPython's `ast.dump` of CPython's parse (`_codefacts.py` lines 76, 97, 101): another parser changes every key | - |
| `_patch.py` | 172 / 172 | - | patching helpers (`disguise`, non-binding wrappers, `rebind_module_references`): interface | - |
| `cli.py`, `__main__.py`, `__init__.py` | 98 / 98 | - | CLI entry | - |
| **total** | **6,203 / 4,006** | Rust: 5,783 -> 19,012 lines | | |

Not a move, but the largest single floor gain of the round: **pytest's rewritten test modules are kept in the
deterministic bytecode cache** (264b183, behaviour change, below): click's `collection` bucket of the warm run 2.17 ->
1.38 s (py-spy, local).

## The fixed floor: what a fully reused run is made of

`harness/rust_hotpaths/floor.py` (new): plain pytest (`P0`), plain `pytest --collect-only` (`K0`: start-up and
collection, what any pytest run pays before its first test), the warm run (`W`), its pre-exec stage alone (`X`: the
first interpreter up to detpy's re-exec, the bytecode precompile) and a py-spy profile (250 Hz) of the exec'd warm
process split into buckets. Local, interleaved, medians of 3 (MEASURED; `floor/final-click.json`,
`floor/final-pygments.json`):

| | click base | click r1 | click checkpoint | click final | pygments base | pygments r1 | pygments checkpoint | pygments final |
|---|---|---|---|---|---|---|---|---|
| plain pytest `P0` | 7.33 s | | | | 13.52 s | | | |
| plain `--collect-only` `K0` | 3.57 s (0.49) | | | | 1.52 s (0.11) | | | |
| warm run `W` | 8.21 s | 5.02 s | 4.77 s | **3.82 s** | 5.51 s | 4.89 s | 4.79 s | **3.72 s** |
| floor `W / P0` | 1.12 | 0.69 | 0.65 | **0.52** | 0.41 | 0.36 | 0.35 | **0.28** |
| pre-exec `X` | 0.32 s | 0.27 s | 0.19 s | 0.21 s | 0.43 s | 0.46 s | 0.23 s | 0.22 s |
| cache check (Rust timer) | 0.126 s | 0.134 s | 0.127 s | 0.076 s | 0.444 s | 0.479 s | 0.442 s | 0.134 s |
| record of a warm run | 3.16 s | 0.077 s | 0.067 s | 0.066 s | 0.252 s | 0.036 s | 0.047 s | 0.058 s |

py-spy of the exec'd warm process, seconds (samples / 250; buckets by the innermost matching frame; MEASURED):

| bucket | click base | click checkpoint | click final | pygments base | pygments checkpoint | pygments final |
|---|---|---|---|---|---|---|
| collection (pytest's, incl. the assertion rewrite) | 2.47 | 2.17 | **1.38** | 1.93 | 1.64 | 1.62 |
| reuse (pytest reporting of reused results: `TestReport`s, hooks, `item.location`) | 0.45 | 0.38 | 0.42 | 1.05 | 1.14 | **0.89** |
| check (detpy: digests, keys, decisions) | 0.16 | 0.13 | **0.09** | 0.49 | 0.52 | **0.25** |
| configure (plugin loading, runtime / config identity) | 0.27 | 0.30 | 0.23 | 0.50 | 0.35 | 0.30 |
| finish (detpy: record, receipts, outcomes file) | 0.62 | 0.32 | **0.19** | 0.40 | 0.13 | 0.15 |
| imports | 0.41 | 0.20 | 0.22 | 0.32 | 0.17 | 0.19 |
| tests (the 37 never-cacheable subprocess tests on click) | 0.26 | 0.16 | 0.26 | 0.20 | 0.20 | 0.24 |
| other | 0.62 | 0.60 | 0.56 | 0.36 | 0.31 | 0.34 |
| total | 5.29 | 4.29 | **3.40** | 5.28 | 4.50 | **4.00** |

* **Most of the floor is pytest's own work.** click's warm run (3.82 s) now costs 1.07x plain pytest's
  `--collect-only` (3.57 s). What is left above that is its 37 never-cacheable subprocess tests and detpy's pre-exec
  stage. pygments' collect-only is cheap (1.52 s), and its floor is collection plus pytest's reporting of 5,346 reused
  results (`reuse`, 0.89 s; `pytest_runtest_logreport` hooks and `TestReport`s are pytest's interface).
* **What this round removed from it.** The assert rewrite of every test module at every run (click `collection` -0.79
  s). The Python check loop and the checker's per-entry re-checks of shared sets (pygments `check` 0.52 -> 0.25 s). The
  pre-exec precompile walk (`X` 0.43 -> 0.22 s on pygments). The Python receipts and outcomes writers, and the plan's
  JSON round trip (`finish`). The per-statement and per-call Python of the capture.
* **What is left of detpy's own** (final engine, ESTIMATED from the buckets): click about 0.21 (pre-exec) + 0.09
  (check) + 0.19 (finish) + part of 0.23 (configure) = about 0.6 s of 3.82 s; pygments 0.22 + 0.25 + 0.15 + part of
  0.30 = about 0.8 s of 3.72 s. The rest is pytest start-up, collection and reporting, which any pytest run pays.

Round 1 measured the floor at 0.32-0.45 of plain pytest on its projects. Comparable numbers here are pygments 0.41
(base) -> 0.28 (final), and home-assistant P8_HA_FLOOR_SHORT. click's floor (1.12 -> 0.52) includes its 37 subprocess
tests, which run in every warm run.

## Behaviour changes (each a separate commit)

1. **Rewritten test modules cached** (264b183). Under `--det` pytest looked for its rewritten pycs in the
   deterministic cache but never wrote them (`PYTHONDONTWRITEBYTECODE=1`). pytest >= 9 keeps them as checked-hash pycs,
   so detpy writes them with pytest's own `_write_pyc`. A stale one never runs; a same-size, same-mtime edit is
   tested. A test module now runs from marshal-loaded code, also in the first run: a set constant has one layout in
   every run. It can differ from a fresh compile, as for library modules since round 1. Older pytest: unchanged.
   `DETPY_REWRITE_CACHE=0` turns it off. It also speeds up `--det` without the cache (click `--det` / plain 0.95 ->
   0.78, CI p8).
2. **The R-009b and R-015b fixes** add refusals and inputs, as on their branches. In the profiles' cross-engine
   comparison of stores (MEASURED, `equivalence` in `profile-*.json`), the final engine's stores differ from base's
   only where those fixes apply:
   * click: 66 tests that use `mkstemp` gain a `"missing"` input for the temporary name (R-009b R2, exclusive create).
     One test reads the deterministic cache's pycs in a subprocess; those are now checked-hash pycs (R-015 F2).
   * pygments: 5 `mkstemp` tests (R-009b R2).
   * The checkpoint's and round 1's stores are identical to base's.
3. **A hand-corrupted `distributions.json` memo entry** (a shape detpy never writes) is recomputed instead of used
   (`identity.rs`). The original indexed such entries blindly.

All other moves keep keys, receipts, decisions, summaries and traces identical (next section).

## Equivalence

Every move keeps the old Python verbatim in `tests/rust_hotpaths_ref/` and runs it against the new path:

| reference | switch | tests | compared |
|---|---|---|---|
| `_ref_proofcache.py` (the round-2 Python module: capture, plugin, sqlite, socket helpers; with R-009b R1/R2 and R-015b G1-G3 applied as on their branches) | `-p _capref`, `DETPY_CAPTURE_REF` | `test_capture_rust.py` | **six sessions** over a project with import-time reads, fixtures, conftest hooks, a doctest, env reads, clock, random, a followed subprocess, name lookups, /proc reads, sqlite (`now`, a schema default and a trigger reading the clock in an ATTACHed file, a definition on the test's own connection, `file:` URIs with %-escapes and `mode=memory`), own-listener and connected-pair sockets, spawn details, `os.open` modes, renames, relative paths, a symlinked module, a stale reuse. Sessions: new, unchanged, code + env change, after the writes, `--det-cache-verify=1`, `-v`. Compared: **stores byte-identical** (but run ids and durations), receipts, outcomes, the outcomes file's cache section (values, key order, phase order), the terminal summary text (but timings, run ids, digests) |
| `_ref_record.py` (round 1's record loop) | `-p _eqplugin` | `test_rust_hotpaths.py`, `test_review_r015.py` | the round-1 loop runs on `CacheSession.state()` beside the Rust record: same reasons, places, stale reuses, counts |
| `_ref_identity.py` | direct | `test_identity_rust.py` (197) | runtime digests and dicts on this environment and on ~35 fake dist-info trees (METADATA / PKG-INFO / RECORD variants, `direct_url.json` variants, custom finders, undecodable names), memo files byte-identical over 7 changes and 12 seeded memos, `cache_epoch` on 24 x 6 cases with byte-identical `epoch.json`, `tz_locale_identity` on 40 TZ combinations, `_safe` on 3,000 strings |
| `_ref_proofcache.py` helpers | direct | `test_sqlcap_rust.py` (9) | 60k generated SQL statements against the four `re` patterns, `\w` / `\s` on every code point, `_sqlite_file` on ~5k inputs, `_loopback_hex` on 40k strings, the socket checks on real IPv4 / IPv6 sockets |
| `_ref_proofcache.py`, `_ref_plugin_helpers.py` | direct | `test_session_rust.py` | `_final` on 343 report combinations, `_ctx_label`, `det_outcome` on 512 |
| `_ref_follow.py` (with R-009b R2/R4) | direct | `test_follow_rust.py` | every `Result` attribute on real strace logs, ~4,000 generated lines |
| `_ref_l0_*.py` (round-1 Level 0, seeds, fsorder, network), `_ref_l0_clock_r2.py` | `-p _l0ref`, `DETPY_L0_REF` | `test_level0*_rust.py`, `test_network_rust.py`, `test_clock_rust.py` | `--det` traces byte-identical, cassettes, stores, receipts; `norm_path` on ~5,000 paths, `ipaddress` on 200k strings, clock validation errors |
| `_ref_reexec_*.py`, `_pycompile.py`, `_ref_repro.py` | direct | `test_precompile_rust.py`, `test_reexec_rust.py`, `test_repro_rust.py` | stale lists, stamps, byte-identical bytecode trees; `ddmin` on 2,800 predicates, `repro` / `explore` bundles |

Suite on the final engine (MEASURED, local): **`pytest tests` 513 passed, 8 skipped, 0 failed**;
**`cargo test -p detpy-core` 60 passed**. Notes:

* Under load, `test_capture_rust.py` failed once in 8 runs, while other builds ran beside it, and did not reproduce
  in 7 runs since.
* `test_clock_rust`'s speed comparison failed once under load.
* The clock's real-wait tests need a temporary directory without other runs' leftovers (deterministic `mkdtemp`
  names; finding 2).

## Verification walks: wrong reuses

Each reuse is checked by a fresh `--det` run of the same commit:

| walk | engine | project | commits ok | reuses verified | wrong | cold / plain pytest, median |
|---|---|---|---|---|---|---|
| w1 (round 1) | f7501bf | click / pygments / home-assistant | 43 / 51 / 800 shard-steps | 28,700 / 58,136 / 374,425 | **0 / 0 / 0** (1 flaky) | 1.08x / 1.31x / 1.30x |
| w3 (checkpoint) | 48b0f08 | click / pygments / home-assistant | 43 / 51 / 760 shard-steps (13 of 16 shards finished) | 28,690 / 58,136 / 419,955 | **0 / 0 / 0** (1 flaky: `insteon/test_api_device.py::test_no_insteon_device` failed fresh, passed on the confirming rerun, as cached) | 1.07x / 1.27x / 1.25x |
| local (final) | a9981c5 | click / pygments | 43 / 51 | 28,754 / 58,131 | **0 / 0** | 0.96x / 1.32x (n = 5 / 6) |
| w6 (final, CI) | e2696ec | home-assistant, click, pygments | W6_STATUS | | | |

MEASURED: `results/local-final/walk-*.json.gz`, `walk/w3/`, `walk/w6/`. click's 8 oldest commits fail under pytest 9.2
in every walk (w1, w2, local), so 43 commits are compared.

## Findings (not changed)

1. **A virtual `time.sleep` makes a test uncacheable.** The clock's real-sleep decision reads
   `/proc/self/task/*/children`, and the capture records that read as the test's ("reads /proc, /sys or /dev"). Kept
   identical in both paths. Any test calling `time.sleep` is never reused today.
2. **Deterministic temporary names run out.** `tempfile`'s name sequence is reseeded per test under `--det`. A test
   that leaves its `mkstemp` file behind (pygments' `test_unicode_options`, `test_valid_output`) finds the same names
   taken at the next run. With this container's Python (`tempfile.TMP_MAX == 20`), about the 20th run in one temporary
   directory fails with "No usable temporary file name found" (MEASURED: the first local pygments floor,
   `floor/final-pygments-tmpleak.json`; the harnesses now take `--clean-tmp`). Fresh CI runners never see it. Not
   engine-specific.
3. **asyncio and `Queue.get(timeout=...)` advance the virtual clock by real-time-dependent amounts** (the clock
   worker's finding). Fingerprints and later printed monotonic values can vary run to run under load, in every engine.
4. **In record mode the network policy remembers the last name looked up for an address** (the network worker's
   finding). A later `localhost` lookup renames 127.0.0.1 proxy recordings, which then fail to replay.

## Commits

Merges: R-015 (612e9b8), R-009b (ce7c594), R-015b (54d114b).

Moves, in order:
* precompile check (0b3effe)
* rewritten test modules (264b183, behaviour change)
* capture (a317fdc)
* decisions and receipts (ce7fb8a)
* follow parsing (0cdb8e9)
* seeds (6edeb43)
* fsorder / norm_path (a782646)
* children crediting (05a28d8)
* plan (4acbadf)
* checker memo (dbd18e0)
* repro (b8e2d21)
* reexec (b88b5b5)
* clock (1185e26, bffd2a8, 049a607, 512c73e)
* network (c64dbfe, a466b76, ae43f5c)
* cache session, record plan and reporting (ff4338d)
* `det_outcome` (2478f66)
* sqlite trace and rare-event helpers (aa31920, f86ebd7, f7bc7c8)
* runtime identity (ae7bccd, ac2ebcd, 4340ddb)

Harness: `floor.py`, `profile.py` cache and `--clean-tmp` fixes, `bench_sqltrace.py`.

Runs: p5 / w3 (checkpoint, CI); p8 / w6 (final, CI), replacing p6 / w4 and p7 / w5, which were cancelled while
queued because their engines predate later moves; local final runs in `floor/` and `results/local-final/`.
