FIX 3

# Review R-017: claude/rust-hotpaths-2 (round 2, everything that is not interface moved to Rust)

Target: `claude/rust-hotpaths-2` at 62c70c8. Its report is `sessions/2026-11-18-rust-hotpaths/REPORT-R2.md`; the code
is the same as a9981c5/e2696ec, and the later commits only add walk shards. Failing tests are in
`tests/test_review_r017.py` on `claude/review-r017`. All three findings fail on the target branch.

**The question: can the Rust port reuse a result it should not, or make `--det` less deterministic than the Python
it replaced?**

* **Wrong reuses from the port: none found.** I wrote new inputs the author's equivalence tests did not cover and
  ran them through both the reference Python capture and the Rust capture. Stores, receipts, outcomes and summaries
  came out identical in every session (details below). The decision path (`check_all`, the verification draw,
  `seed_exclusive`, `stale_skip`) matches the reference line by line. The plan is merged by ordered context
  lists, so no HashMap order reaches a key.
* **Less deterministic: yes, through one behaviour change (H1).** Commit 264b183 keeps pytest's rewritten test
  modules in the `--det` bytecode cache. That makes a `--det` run depend on which configuration an *earlier* run
  had, and with `--det-cache` it records results produced by the other configuration's code.
* There is one label error in the report (H2), and one pre-existing wrong reuse that the port carried over
  unchanged (H3).

## Findings

### H1 (port regression): the rewritten-test pyc cache ignores the configuration the rewrite depends on

`plugin.py:_cache_rewritten_tests` writes pytest's rewritten module with pytest's `_write_pyc` into the
deterministic cache, and pytest's `_read_pyc` later accepts it. pytest checks such a pyc only against the
source hash, the magic number and the `PYC_TAIL` (pytest version + cache tag). But the rewrite also depends on the
`enable_assertion_pass_hook` ini option (`AssertionRewriter.__init__`, `_pytest/assertion/rewrite.py:694`). When the
option is on, extra code is emitted that calls `pytest_assertion_pass`.

Before round 2, `--det` never wrote these pycs (`PYTHONDONTWRITEBYTECODE=1`), so every run rewrote with its own
configuration. Now:

| sequence (same project, same `DETPY_PYC_CACHE`) | `pytest_assertion_pass` calls in the last run |
|---|---|
| `--det -o enable_assertion_pass_hook=true` on an empty bytecode cache | 1 |
| `--det`, then `--det -o enable_assertion_pass_hook=true` | **0** |
| the same two runs with `DETPY_REWRITE_CACHE=0` | 1 |

What this means:

* The same command with the same sources and options behaves differently depending on history. That is exactly
  what `--det` exists to rule out.
* With `--det-cache`, turning the option on changes the configuration digest, so every test is re-run. The re-run
  executes the code rewritten for the previous configuration, and its result is recorded under the new key.
* The walks' "fresh `--det` run" verification shares the same bytecode cache, so it reproduces the stale code and
  cannot catch this.

Plain pytest has the same staleness upstream; its docs say to delete pycs after toggling the option. But under
`--det` it is new in this round.

Tests:
* `test_h1_rewritten_pyc_ignores_assertion_pass_hook_option`
* `test_h1_cache_records_result_of_other_configuration`: the hook-dependent test fails in the run that has the
  hook on.

Both pass with `DETPY_REWRITE_CACHE=0`. Possible fixes:
* Do not cache when `enable_assertion_pass_hook` is set.
* Or put the option in the pyc's name (a cache directory per configuration).
* And audit whatever else in `config` reaches `rewrite_asserts`.

### H2 (report): "Fresh CI runners never see it" is contradicted by the CI run behind the headline table

REPORT-R2 finding 2 (deterministic temporary names run out, `tempfile.TMP_MAX == 20`) says the problem is local
only. In `results/p8/pygments-0of1.json`:

* Plain pytest (`P0`) passes in all 5 rounds.
* Every `--det` engine exits 1 with `not_cached: {"outcome": 2}` from round 3 on (base, r1, r2cp) or round 2 on
  (r2), in `B`, `C` and `W` alike. Two tests fail.

One CI runner runs about 60 `--det` sessions in one temporary directory, so it does hit the limit. The pygments
rows of the headline table (cold 1.27x, floor 0.28x, `--det` 1.08x) are medians that include those runs. The ratios
barely move (2 of 5,346 tests), but the rows are labelled MEASURED without saying that the runs failed.

Test: `test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does`. Fix the wording; ideally rerun p8 with
`--clean-tmp` (the harness has it) or a fresh `TMPDIR` per run.

### H3 (pre-existing, carried into Rust): an environment variable with a non-UTF-8 name is not an input

`CaptureCore.fill_plan` (capture.rs) builds `plan.env` with
`filter_map(|n| String::from_utf8(n.clone()).ok())`. The reference `_plan` filters the same names out
(`_encodable`). A test that reads `os.environb[b"R17\xff"]` is recorded without that dependency. After the value
changes, the old result is reused and reported `passed`, although the test now fails (checked on the target
branch).

Not caused by the port. Counted because it is a wrong reuse on this branch, and the port was the chance to fix it.
Paths already handle this case: a non-UTF-8 path refuses the test with `badpath`. Doing the same for env names
(flag "badpath"/"badenv"), or keying the raw bytes, would be safe.

Test: `test_h3_env_var_with_undecodable_name_is_an_input`.

## What was checked and held

### 1. Equivalence, old Python vs Rust, on inputs the author's tests did not cover

I used a differential driver of my own, `equivalence/run.py`, with specs in `equivalence/`. It runs the same
project through `-p _capref` (the round-2 Python capture) and through the Rust capture: 4 to 5 sessions each, with
edits and environment changes in between. It compares the store byte for byte (apart from run ids and durations),
the receipts, the outcomes and the cache summary. The one way it differs from the author's harness: both paths
share one compiled clock shim. Shims compiled separately differ in digest, and the author's test does the same.
All comparisons were **identical**.

* **spec1:**
  * fixtures of every scope: class, module, package and session (from conftest and from a class)
  * non-ASCII names in both NFC and NFD forms; a non-UTF-8 byte name, given both as bytes and as a surrogate `str`;
    bytes paths and `__fspath__` returning bytes
  * `//` prefixes, `/./` and `..` through a symlinked directory; a symlinked file whose target is changed between
    sessions; listing a symlinked directory
  * environment: `getenv`, `get`, `in`, `environb`, `setdefault`, `pop`, `copy`, a value that is not valid UTF-8, a
    name that is
  * time and locale: `tzset`, `setlocale`, `zoneinfo`
  * other opens: `open(fd)`, `os.open` with `dir_fd`, `getmtime`
* **spec2b:**
  * doctests in a module and in a `.rst` file
  * a write followed by reads and listings in other tests
  * exclusive creates: `O_CREAT|O_EXCL`, `mkstemp` in the project, mode `"x"`
  * a read from a thread
  * followed children: `python -c` reading a file, and `sh -c cat`, with the file changed between sessions
  * rename then read; append mode
* **spec3:**
  * TZ / LANG changes and TZ-dependent APIs
  * `getaddrinfo("localhost")` and a numeric lookup
  * sqlite with a bound `'now'`
  * `inspect.getsource`, `importlib.resources`
  * an env read from a thread
  * a helper module's import-time file and env reads, with the file changed
* **Code edited mid-session** (a test rewrites a module that a later test imports): both paths refuse every test
  ("source changed during the session").

Level 0 (`-p _l0ref`, `DETPY_L0_REF=1`, file `equivalence/l0_edges_test.py`):
* Covered: every `random` API including subclasses, `binomialvariate`, `randbytes`, `counts=`, and
  `seed()`/`getstate()`; `mkstemp`/`mkdtemp` names; every clock read and wall-derived function; `sleep(-1)` and
  `sleep(nan)`; `clock_gettime`; `datetime.now(tz)`.
* Also: `listdir`/`scandir`/`glob`/`rglob`/`walk` and `listdir(fd)`, over names that are not valid UTF-8, NFD, a
  space and a dot.
* Values and traces are identical, with or without `--det-urandom`. The only exceptions are uncontrolled entropy
  without `--det-urandom` (expected) and the wait timeouts below.

### 2. Review tests

`tests/test_review_r009b.py`, `test_review_r015.py` and `test_review_r015b.py` on the branch are byte-identical
to the reviewers' originals (`claude/review-r009b` 83aa80e, `claude/review-r015` 5dc927c, `claude/review-r015b`
e25222e). All of them pass, as does `test_review_r009.py`.

Full suite on the target (local, Python 3.13, pytest 9.2.0, `maturin develop --release`):
* `pytest tests`: **513 passed, 8 skipped, 0 failed**
* `cargo test --workspace`: **detpy-core 60 passed**
* The `detpy-py` crate, which holds about 13k of the new Rust lines, has **0 Rust unit tests**. All of it is tested
  through Python. That is not a defect, but worth knowing.

`tests/test_review_r017.py` alone on the target: 4 failed (H1 x2, H2, H3); the H1 tests pass with `DETPY_REWRITE_CACHE=0`.

### 3. Rust-specific risks

* **HashMap order.**
  * The capture keeps insertion order where Python had dicts (`OrdMap`/`OrdSet`), and `writers` uses `BTreeSet`.
  * `fill_plan` hands `HashMap`s to `record.rs`, but `record.rs` merges contexts by iterating ordered context
    lists (`g_ctx_all`, `ctxs`) and sorts the data, units and sets it emits.
  * `FxHasher` memo tables are equality-checked, so a collision cannot change a result.
  * Nothing order-dependent reached a key or a trace in any run above.
* **Unicode and path encoding.**
  * Paths are carried as `str`-lossless WTF-8 (`w_of`, surrogatepass).
  * Non-UTF-8 paths become `badpath` on both paths, and are compared equal in spec1.
  * `normpath` and `dirname` are posixpath ports.
  * H3 is the one encoding hole, and it is inherited.
* **Panics and errors across FFI.**
  * The C audit hook returns -1 when the callable raises, so the error propagates to the audited call, as the
    Python hook's did. A pyo3 panic arrives as `PanicException`, a `BaseException` that `except Exception` in a test
    does not swallow.
  * `finish` catches `Exception` and records nothing; the earlier entries stay keyed.
  * I found no place where an `Err` silently drops an input in Rust when Python would have recorded it. The
    conversions that can fail (`utf8` in `fill_plan`) fail the whole recording, as the reference's JSON
    round trip did.
  * The one `catch_unwind` (network wrappers) raises `RuntimeError`.
* **Threads.**
  * Capture state sits behind `Mutex`es, and the GIL is held across each audit callback.
  * `helper_inactive` turns capture off around the loopback checks, as the Python did (`self.active = False`).
    Rust holds the GIL through the `/proc` reads, so no other thread can run in that window. That is narrower than
    in Python, where reading a file released the GIL.

### 4. Headline numbers

I recomputed the numbers from `tracks/rust-hotpaths/results/p8/*.json` (medians of `walls`, each divided by the
`P0` median) and from `walk/w6/*.json.gz`:

| | report | re-derived |
|---|---|---|
| click cold / floor / `--det` (r2) | 1.03 / 0.52 / 0.78 | 1.03 / 0.52 / 0.78 |
| pygments | 1.27 / 0.28 / 1.08 | 1.27 / 0.28 / 1.08 (runs with 2 failing tests included, H2) |
| home-assistant 0 / 5 / 10 cold | 1.26 / 1.22 / 1.24 | 1.26 / 1.22 / 1.24 |
| home-assistant floor | 0.33 / 0.25 / 0.28 | 0.33 / 0.25 / 0.28 |
| base columns | 1.78, 1.13, 1.01, 1.44, 0.37, ... | identical |
| local floor `W/P0` (`floor/final-*.json`) | 0.52 / 0.28 | 3.82/7.33 = 0.52, 3.72/13.52 = 0.28 |
| w6 click / pygments | 43 ok, 28,700 verified, 0 wrong / 51, 58,131, 0 | identical; w6 cold/plain 0.93 (n=5) / 1.29 (n=6) |
| w6 home-assistant | 480 of 800 shard-steps, 271,804 verified, 0 wrong | at 62c70c8: 550 shard-steps in 15 of 16 shard files (shard 1 not yet committed), 308,543 verified, 0 mismatches, cold/plain 1.24 (n=63) |

The labels hold (MEASURED = a named run, ESTIMATED = derived buckets), except H2. The `P0`/engine exit 1 on
home-assistant comes from failures the project already has in plain pytest, and the `W` runs reuse them as
uncached. home-assistant shard 5 base (`W:base` 1.43) reuses nothing, as the report says.

## Observations (not findings: present unchanged in the Python reference)

* The virtual clock's value after a timed-out `queue.Queue.get(timeout=)`, `Condition.wait`, `Lock.acquire(timeout=)`
  or `select` varies from run to run in the last digits (e.g. `…0.4999986` / `…0.4999995` / `…0.4999998`). This
  happens in the round-1 Python Level 0, in the round-2 Python clock (`DETPY_L0_REF=clock2`) and in Rust alike.
  It makes the trace of such a test differ between identical runs. Worth its own look; it is not a port regression.
* `os.stat`/`getmtime` of a data file is not an input in either path (only code files have stat keys, R-015 F1).
* The pygments temporary-name exhaustion (REPORT-R2 finding 2) reaches CI; see H2.
