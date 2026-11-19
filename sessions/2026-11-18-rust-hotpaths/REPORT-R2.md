PARTIAL

# rust-hotpaths, round 2: everything that is not interface moves to Rust

Branch `claude/rust-hotpaths-2`. Founder decision (DECISIONS 2026-11-18): move to Rust everything in `python/detpy`
that is not the interface Python requires; Python keeps thin shims (pytest hooks, patched entry points,
`sys.monitoring` / audit-hook registration, CLI entry). Round 1: [REPORT.md](REPORT.md). Fix rounds merged into this
branch: review R-015 F1-F4 and R-015b G1-G3 (`claude/rust-hotpaths`), review R-009b R1-R4
(`claude/cache-proof-step1` to 3b197a4), each ported into the Rust modules.

Labels: **MEASURED** (a run named here), **ESTIMATED** (derived), unmarked = description. "local" = this container
(4 CPUs, Python 3.13, the harness's own venvs); "CI" = GitHub Actions runs committed under `tracks/rust-hotpaths/`.

PARTIAL because (1) `proofcache.py` still holds about 400 lines of logic that could move but did not (listed in the
table: the runtime identity loop, the sqlite schema check, the test-report assembly of the record plan, the
reporting); (2) the final CI measurements (profile p7, walk w5, both on the final engine) were queued behind the
checkpoint runs when this was written: home-assistant's final numbers are not in this report (they commit themselves
to `tracks/rust-hotpaths/results/p7/` and `walk/w5/`).

## Result in one table

Cold run (empty cache) and fully reused run ("floor"), both / plain pytest, medians:

| project | metric | base (24b6d15) | round 1 (128dcc6) | round 2 checkpoint (c28a531: clock and call sites) | round 2 final | source |
|---|---|---|---|---|---|---|
| click | cold / plain | 1.88x | 1.33x | 1.32x | FINAL_CLICK_COLD | CI p5 (base..checkpoint), local (final row: all four engines) |
| pygments | cold / plain | 1.43x | 1.32x | 1.31x | FINAL_PYG_COLD | idem |
| home-assistant 0/16 | cold / plain | 1.57x | 1.35x | 1.28x | pending (p7) | CI p5 |
| home-assistant 5/16 | cold / plain | 1.35x | 1.31x | 1.22x | pending (p7) | CI p5 |
| home-assistant 10/16 | cold / plain | 1.52x | 1.29x | 1.24x | pending (p7) | CI p5 |
| home-assistant walk | cold / plain | 1.47x (s1f) | 1.30x (w1) | 1.26x (w3, 23 of the 80 cold measurements, partial) | pending (w5) | CI walks |
| click | floor (warm / plain) | 1.15x | 0.69x | 0.66x | **0.53x** | local floor.py (interleaved, 3 rounds) |
| pygments | floor (warm / plain) | 0.37x | 0.35x | 0.34x | FINAL_PYG_FLOOR | local floor.py |

MEASURED. CI p5 = `tracks/rust-hotpaths/results/p5/` (engines base, round 1, checkpoint; 5 rounds click/pygments, 3
home-assistant); local = `tracks/rust-hotpaths/floor/final-*.json` and `results/local-final/` (all four engines
interleaved in one job, so the four columns of a local row are comparable; local and CI rows are not).

## Module table

Python lines are `wc -l` at the start of round 2 (c28a531) and now. Gains are the measured cost of the moved path,
reference (old Python) vs new, inside a recorded test unless said otherwise.

| module | lines before / after | moved to Rust | stays Python, and why | gain (MEASURED unless marked) |
|---|---|---|---|---|
| `proofcache.py` | 1921 / 1350 | `capture.rs`: the audit hook and everything it calls (caller-kind / import-context / first-user-site frame walks, `_abs`, `_ignored`, reads, writes, R-015 F1 stat keys, R-009b R2 exclusive creates, R-015b G2/G3), contexts and `switch` (socket scan, segments, re-arming), env reads (`_note_env`), Level 0 events, `arm` (entry / last line from the bytecode), `scan_modules`, followed-children crediting (`collect_children`, `_credit_child`, R-015b G1), the plan's capture part; `proofcache.rs`: the reuse decisions (`check_all`, expiry), reuse entries (`reuse_info`), the receipts writer; `proof.rs`: memoised checker (sets, env, key parts, FxHash) | pytest hooks of `ProofCachePlugin` (interface); `Capture.start/stop` (`sys.monitoring` and audit-hook registration); the `sqlite3.connect` patch and its trace callback with R-009b R1's schema check (needs a sqlite connection; the regexes could move, did not); `_patch_environ` (swaps `os.environ`'s class); runtime / config identity (`importlib.metadata` discovery and pytest's config objects are Python; per-distribution identity has been Rust since round 1; the per-distribution memo loop could move, did not: ESTIMATED 0.05-0.3 s per home-assistant run from p3's identity bucket); `_prefetch_facts` (drives `_codefacts`); the record plan's test list (pytest reports); the summary and terminal report; helpers Rust calls for rare events whose rules are Python's (`_own_listener`, `_both_ends_mine`, `_numeric_host`: `ipaddress`; `_spawn_detail`) | `open` 4.0 -> 1.5-2.4 us of capture overhead per call, `os.listdir` 3.4 -> 1.5 us, `os.environ.get` 0.35 -> 0.30 us; warm check (3,000 tests) 0.060 -> 0.015 s; the checker memo on pygments' store (5,346 entries) 0.29 -> 0.16-0.24 s; the plan's capture part: no gain measured (0.017 -> 0.018 s, 3,000 one-context tests) |
| `follow.py` | 675 / 371 | `follow.rs`: strace log parsing (`parse`, line / argument / quote parsing, special paths, shebang, log listing and completeness), R-009b R2 (op `a`) and R4 (stats of files the tree wrote, of /proc/<pid>) | `Follower` (patches `_posixsubprocess.fork_exec`), `probe` and `build_shim` (strace and a C compiler, once per session, with the shim's C source), `_wait_logs` (real waiting; its tests are Rust) | parse of real logs: 156.0 -> 8.3 ms over 7 logs (19x) |
| `clock.py` | 490 / 391 | `clock.rs` (round 2 start had the counter and the six `time.*` reads): `sleep` (validation, record, advance, the real-sleep decision), `localtime/gmtime/ctime/asctime/strftime`, `clock_gettime[_ns]`, `datetime.now/utcnow`, the wait-timeout rules, the process-start stand-ins | `install/uninstall` (patching), `_TimedLock` / `_TimedLockMeta` (types: `isinstance` and method binding), one-line method shims for `Condition.wait`, `select`, `acquire` | `datetime.now()` 2.1-2.7 -> 0.88-1.1 us; `time.localtime()` 2.1-2.8 -> 0.95-1.25 us; `time.sleep(0)` 85-88 -> 75-79 us (the real `sleep(0)` and /proc reads dominate) |
| `network.py` | 545 / 284 | `network.rs`: the policy (local names, `ipaddress` parsing ported and checked on 200k strings; IPv4-mapped addresses handed to Python), connect / sendto / DNS decisions, the wrappers as method descriptors of `_socket.socket` / `SSLSocket`, recording bookkeeping, cassette lookups | the replay server thread (socketpair), `ReplayTLSSocket`, `NetworkBlockedError`, `SSLContext.wrap_socket` shim, `install/uninstall`; `urlsplit` of proxy URLs (once per session) | blocked `connect` 5.2 -> 1.7 us; loopback `connect_ex` 6.0 -> 3.2 us; `getaddrinfo` unchanged (the real lookup) |
| `seeds.py` | 178 / 117 | `seeds.rs`, `standin.rs`: every random draw wrapper, `Random.seed`, `os.urandom` / `random._urandom`, `numpy.default_rng`, the per-test counter and keys, `repr` of floats | `install`, `start_test`, `end_test` (gc scan, numpy, tempfile: Python objects) | `random.random()` 1.5-1.6 -> 0.73-0.94 us; `random.choice` 1.6-1.7 -> 0.76-0.99 us |
| `fsorder.py` | 134 / 87 | `fsorder.rs`: `listdir`, `scandir` (sorted iterator), the event, the quiet flag | the glob / pathlib wrappers stay thin Python functions (method binding, lazy generators) calling Rust | `os.listdir` (5 entries) 6.9-7.4 -> 4.3-5.6 us |
| `_sites.py` | 163 / 126 | `norm_path`, `_shorten` (with `fsorder`) | `_dirs` / `refresh` (`sysconfig`, `sys.modules`: Python's own state) | part of the `listdir` gain |
| `_state.py` | 98 / 98 | `digest_names` (now a one-line call) | `Config` / `State` dataclasses (the Python view of the configuration), `quiet` context manager | - |
| `reexec.py` + `_pycompile.py` | 320 + 0 / 212 + 95 | `precompile.rs`: the checked-hash bytecode check (R-015 F2/F3: `_pycompile`'s walk and source-hash test, CPython's keyed SipHash), `dir_stamp`; `reexec.rs`: `aslr_disabled`, `personality(2)`, `plan`, `_argv`, `can_reexec`, `pyc_cache_dir`, `bytecode_active`, the precompile's stamps and todo decision | `os.execve`; `sysconfig.get_paths()`; `_pycompile.py` is the driver run in a child interpreter: compiling is CPython's `py_compile` | unchanged project precompile 0.142 -> 0.034 s (5,364 files); up-to-date precompile 2.4 -> 2.2 ms; `plan` + `can_reexec` 10.5 -> 7.5 us |
| `repro.py` | 489 / 275 | `repro.rs`: `ddmin`, prefix / order / slug, divergence of traces, outcome classes, the explore book-keeping, bundle content and texts | the Runner (pytest subprocesses, outcome files), bundle file writes, argument parsing | none, by design: 99.9 % of `detpy repro` is pytest subprocesses (5.537 -> 5.108 s wall on the victim project, the decision logic 49.6 -> 53.6 ms for 300 calls) |
| `plugin.py` | 685 / 727 | - | pytest hooks and glue on pytest objects (config, items, reports): the interface. Pure helpers that stay: `_final_outcome`, `_exception_of`, `_parse_epoch` (`datetime.fromisoformat`'s rules). +42 lines: the rewritten-test-module cache shim (below) | - |
| `_codefacts.py` | 235 / 235 | - | the facts are digests of CPython's `ast.dump` of CPython's parse (`_codefacts.py` lines 76, 97, 101): another parser would change every key, so it cannot move without a key change | - |
| `_patch.py` | 172 / 172 | - | the patching helpers (`disguise`, non-binding wrappers, `rebind_module_references`): interface | - |
| `cli.py`, `__main__.py`, `__init__.py` | 98 / 98 | - | CLI entry | - |
| **total** | **6,203 / 4,638** | Rust: `crates/` 5,783 -> 15,888 lines (with tests) | | |

Not a move but the largest floor gain of the round: **pytest's rewritten test modules are kept in the deterministic
bytecode cache** (264b183, behaviour change, below).

## The fixed floor: what a fully reused run is made of

`harness/rust_hotpaths/floor.py` (new): plain pytest (`P0`), plain `pytest --collect-only` (`K0`: start-up and
collection, what any pytest run pays before its first test), the warm run (`W`), its pre-exec stage alone (`X`: the
first interpreter up to detpy's re-exec, the bytecode precompile) and a py-spy profile of the exec'd warm process
split into buckets. Local, interleaved, medians of 3 (MEASURED):

FLOOR_TABLE

What it is made of (final engine, py-spy samples of the exec'd warm process, MEASURED):

FLOOR_BUCKETS

* **collection is pytest's own**: on click plain `--collect-only` costs 0.49 of a plain run: the warm run now costs
  about what pytest costs to start and collect; on pygments `--collect-only` is 0.11 and the rest of the floor is
  pytest's reporting of the reused results (the `reuse` bucket is `pytest_runtest_logreport` hooks building
  `TestReport`s, `item.location`) and start-up.
* **what this round removed from it**: re-rewriting every test module's asserts at every run (click: ~12 % of the
  floor at the checkpoint), the Python check loop (`json.loads` of each receipt, `strptime` of each run id; the
  checker's per-entry re-checks of shared sets), the pre-exec precompile walk (`X` 0.29-0.43 s -> 0.17-0.21 s), the
  Python receipts writer.
* **what is left of detpy's own**: `check` (Rust: digests of the code and data files, keys), the reuse report hooks
  (pytest interface), `configure` (plugin loading, runtime identity), the pre-exec stage.

Round 1 measured the floor at 0.32-0.45 of plain pytest on its projects; the comparable numbers here are pygments
0.37 (base) -> FINAL_PYG_FLOOR and click 1.15 -> 0.53 (click's floor includes its 37 never-cacheable subprocess
tests, which run in every warm run).

## Behaviour changes (each a separate commit)

1. **Rewritten test modules cached** (264b183). Under `--det` pytest looked for its rewritten pycs in the
   deterministic cache but never wrote them (`PYTHONDONTWRITEBYTECODE=1`). pytest >= 9 keeps them as checked-hash
   pycs, so detpy writes them with pytest's own `_write_pyc`; a stale one never runs (a same-size, same-mtime edit is
   tested). A test module now runs from marshal-loaded code, also in the first run: a set constant has one layout in
   every run (it can differ from a fresh compile, as for library modules since round 1). Older pytest: unchanged.
   `DETPY_REWRITE_CACHE=0` turns it off.
2. **The R-009b and R-015b fixes** add refusals and inputs (exclusive creates, child stats of files the tree wrote,
   sqlite schemas reading the clock, child reads of files changed after the child started, symlinked modules), as on
   their branches.

All other moves keep keys, receipts, decisions and traces identical (next section).

## Equivalence

Every move keeps the old Python verbatim in `tests/rust_hotpaths_ref/` and runs whole sessions both ways:

| reference | switch | tests | compared |
|---|---|---|---|
| `_ref_proofcache.py` (round-2 capture, decisions, receipts; with R-009b R1/R2 and R-015b G1-G3 applied as on their branches) | `-p _capref`, `DETPY_CAPTURE_REF` | `test_capture_rust.py` | four sessions (new, unchanged, code + env change + stale reuse, after the writes) over a project with import-time reads, fixtures, conftest hooks, a doctest, env reads (one, all, contains, `environb`), clock, random, a followed subprocess, a name lookup, /proc reads, sqlite (file, `now`), `os.open` modes, `a+` / `x` opens, renames / copies / removes, relative paths after `chdir`, a symlinked module: **stores byte-identical** (but run ids and durations), receipts, outcomes, summaries identical; `repr(float)` and `json.dumps(str)` against Python on 9,000 values |
| `_ref_record.py` (round 1's record loop) | `-p _eqplugin` | `test_rust_hotpaths.py` | unchanged from round 1, passes through the Rust capture's views |
| `_ref_follow.py` (with R-009b R2/R4 applied) | direct | `test_follow_rust.py` (14) | every `Result` attribute on real strace logs (python, sh, ls, git, cc; shim and no shim; three cwds; truncated at 40 offsets), ~4,000 generated and ~90 hand-written lines, the R-009b cases |
| `_ref_l0_*.py` (round 1 Level 0, seeds, fsorder, network) | `-p _l0ref`, `DETPY_L0_REF=1` | `test_level0_rust.py`, `test_level0_seeds_fsorder_rust.py`, `test_network_rust.py` | `--det` traces byte-identical, cassettes identical, `--det-cache` stores and warm receipts identical; unit checks of every value string, `norm_path` on ~5,000 paths, `ipaddress` on 200k strings |
| `_ref_l0_clock_r2.py` (round-2 clock) | `DETPY_L0_REF=clock2` | `test_clock_rust.py` (14) | traces, printed values, stores, receipts; validation errors (type, message, context) |
| `_ref_reexec_r015.py` + `_pycompile.py`, `_ref_reexec_r2.py` | direct | `test_precompile_rust.py`, `test_reexec_rust.py` | stale lists in the driver's order, stamps, byte-identical bytecode trees across edits, fuzzed stamps files against `json` |
| `_ref_repro.py` | direct | `test_repro_rust.py` (18) | `ddmin` on 2,800 predicates (same minimal lists and callback sequences), simulated and real `repro` / `explore` runs: `bundle.json`, traces, texts identical |

Suite on the final HEAD: **`pytest tests` 304 passed, 8 skipped; `cargo test -p detpy-core` 60 passed** (MEASURED,
local).

## Verification walks: wrong reuses

| walk | engine | project | commits ok | reuses verified by a fresh `--det` run | wrong | cold / plain, median |
|---|---|---|---|---|---|---|
| w1 (round 1) | f7501bf | click / pygments / home-assistant | 43 / 51 / 800 shard-steps | 28,700 / 58,136 / 374,425 | **0 / 0 / 0** | 1.08x / 1.31x / 1.30x |
| w3 (checkpoint) | 48b0f08 (round-2 clock and call sites) | home-assistant (partial: WALK_W3_STEPS shard-steps when written) | WALK_W3_STEPS | WALK_W3_VERIFIED | **0** | 1.26x (n=WALK_W3_N) |
| local (final) | this branch's final engine | click / pygments | WALK_FINAL_STEPS | WALK_FINAL_VERIFIED | **WALK_FINAL_WRONG** | WALK_FINAL_COLD |
| w5 (final, CI) | this branch's final engine | home-assistant, click, pygments | queued | | | |

MEASURED (`/tmp`-independent counts from the committed walk files; `harness/rust_hotpaths/compare_walks.py`
needs all 16 home-assistant shards of a commit, which w3 does not have yet). click's 8 oldest commits fail collection
under pytest 9.2 in every walk (w1, w2, local): 43 commits are compared.

## Findings (not changed)

1. **A virtual `time.sleep` makes a test uncacheable.** The clock's real-sleep decision reads
   `/proc/self/task/*/children`, and the capture records that read as the test's ("reads /proc, /sys or /dev"). Kept
   identical in both paths (the Rust check raises the same audit events). Any test calling `time.sleep` is never
   reused today.
2. **Deterministic temporary names can run out.** `tempfile`'s name sequence is reseeded per test under `--det`; a
   test that leaves its `mkstemp` file behind (pygments' `test_unicode_options`, `test_valid_output`) finds the same
   names taken at the next run. With this container's Python (`tempfile.TMP_MAX == 20`), the 21st local run failed
   with "No usable temporary file name found" (MEASURED; fresh CI runners never see it). Not engine-specific.
3. **asyncio and `Queue.get(timeout=...)` advance the virtual clock by real-time-dependent amounts** (the clock
   worker's finding): fingerprints and later printed monotonic values can vary run to run under load, in every
   engine.
4. **In record mode the network policy remembers the last name looked up for an address** (the network worker's
   finding): a later `localhost` lookup renames 127.0.0.1 proxy recordings, which then fail to replay.

## Commits

Merges: R-015 (612e9b8), R-009b (ce7c594), R-015b (54d114b). Moves, in order: precompile check (0b3effe), rewritten
test modules (264b183, behaviour change), capture (a317fdc), decisions and receipts (ce7fb8a), follow parsing
(0cdb8e9), seeds (6edeb43), fsorder / norm_path (a782646), children crediting (05a28d8), plan (4acbadf), cleanup
(96e34a4), checker memo (dbd18e0), repro (b8e2d21), reexec (b88b5b5), clock (1185e26, bffd2a8, 049a607, 512c73e),
network (c64dbfe, a466b76, ae43f5c). Harness: `floor.py` (152f784), `profile.py` cache fix. Runs: p5 / w3
(checkpoint, CI), p7 / w5 (final, CI, queued), local final runs in `tracks/rust-hotpaths/floor/` and
`tracks/rust-hotpaths/results/local-final/`.
