FIX 6

# R-008 review: Block 4 part 2, the cache shared across machines

Reviewed: engine branch `claude/shared-cache`. Head is `da1afa9`; it only adds `docs/SHARED-CACHE.md` on top of the
reported code commit `8d606a2`. Hosted runs: 44262651294 (8f3ea09), 44263752890 (80ad62a), 44264885597 (8d606a2).
All three runs succeeded. I recomputed the numbers from 44264885597.

**Scope caveat.** In this session I could not attach `fenvix-brain-cli`: `add_repo` was denied, and the session's
GitHub scope is the engine repo only. So I did **not** read CLAUDE.md, prompts/REVIEWER.md, prompts/COMMON.md,
RULES.md, prompts/P-018-shared-cache.md or the session REPORT.md. I checked the work against the claims the branch
makes itself (`docs/SHARED-CACHE.md`, the `runtime_id` / `remote_cache` / `cache_service` docstrings) and the
contract wording in the review request ("different whenever behaviour can differ"). This report is committed on the
engine branch `claude/review-r008-tests` for the coordinator to copy into the brain.

## Verdict

The design is sound: content-addressed, append-only, per-organization isolation, and the client treats pulled
entries as candidates only. The hosted numbers recompute. But the runtime identity does **not** meet "different
whenever behaviour can differ":

* Two holes give a **wrong reuse end to end** through the service: machine 2 reuses `passed` where a real run on
  machine 2 fails.
* Five more holes make two machines equal while a test's behaviour differs.

The service also inflates request bodies before it checks the token. Docs and code overclaim in two places: the
token is "never seen by tests", and only the outcome is a claim. Six FIX items follow.

Failing tests: `tests/test_review_r008.py` on engine branch `claude/review-r008-tests` (commit `635dec5`, on top of
`da1afa9`). They are not on `claude/shared-cache`.
All 12 tests fail at `da1afa9`:

```
FAILED test_hole_unowned_package_directory_in_site_packages
FAILED test_hole_file_inside_a_distribution_not_listed_in_its_record
FAILED test_hole_legacy_egg_info_distribution_is_keyed_on_metadata_only
FAILED test_hole_module_on_an_import_path_outside_site_and_root
FAILED test_hole_ld_preload_changes_behaviour_not_identity
FAILED test_hole_locale_categories_other_than_ctype
FAILED test_hole_cpu_count_visible_to_the_process
FAILED test_hole_service_decompresses_unauthenticated_bodies
FAILED test_e2e_wrong_reuse_module_outside_site_and_root      # machine 2 reused 'passed'; real run: failed
FAILED test_e2e_wrong_reuse_ld_preload                        # machine 2 reused 'passed'; real run: failed
FAILED test_hole_token_file_is_readable_by_the_tests
FAILED test_hole_entry_with_no_recorded_inputs_is_reused
```

Each identity test first asserts that the behaviour really differs between the two "machines". For example:
`import vendored` gives 1 vs 2, `os.getuid()` gives 0 vs 4242, `locale.str(1.5)` gives `1.5` vs `1,5`. Then it
asserts the identity differs. So every failure is a real hole, not a cosmetic one.

## Engine suite (re-run)

* Built with `maturin develop --release` on Python 3.13.
* `pytest`: **135 passed, 7 skipped** (300 s).
* `cargo test --release`: **47 passed**.
* `test_runtime_id.py` + `test_shared_cache.py` alone: 23 passed, 1 skipped. The skip is the Python-patch-release
  test, which needs two 3.13.x interpreters; this machine has one.

## FIX 1: installed code that no RECORD lists is invisible

`proofcache._ignored` drops every read under a site directory, and import-system reads are never inputs. Only
project code is traced. So for anything in site-packages, the runtime identity is the only guard. But
`runtime_id._distributions` hashes only the files a `RECORD` lists, and `_site_loose` only *files directly* in the
site directory:

* a package directory with no dist-info (vendored by a build step, `pip install --target` leftovers, an image
  layer): `test_hole_unowned_package_directory_in_site_packages`;
* a module or data file added inside an installed package after installation (a plugin dropped in, a generated
  `_version.py`, an extension built in place): `test_hole_file_inside_a_distribution_not_listed_in_its_record`;
* egg-info distributions (no RECORD: `setup.py install`, Debian/Ubuntu `python3-*` in dist-packages) are keyed on
  name, version and PKG-INFO text only. A Debian patch to the same upstream version keeps the identity:
  `test_hole_legacy_egg_info_distribution_is_keyed_on_metadata_only`.

**Fix:** key the site directories by tree content (relative path and bytes of every file). Exclude only the
per-machine installer files (`RECORD`, `INSTALLER`, `REQUESTED`, `direct_url.json`, `__pycache__`, the project's own
editable dist-info), not "files RECORD does not list". RECORD can stay as the per-distribution grouping for the
diff listing. The memo makes the cost one stat per file.

## FIX 2: modules on import paths outside site, stdlib and root are not keyed (wrong reuse)

`_sys_path` keeps an unknown directory's absolute path and says so: "its modules are not keyed". The same path with
other content (a sibling library on `PYTHONPATH`, a `.pth` line to `/opt/...`, a checkout of a second repository
at the runner's fixed path) gives the same identity. The reads are import-system reads, so no test records them.
This is not in the doc's "Limits" list.

* `test_hole_module_on_an_import_path_outside_site_and_root`
* **End to end:** `test_e2e_wrong_reuse_module_outside_site_and_root`. Machine 1 pushes `test_value` passed.
  Machine 2 has `helper.VALUE = 2` at the same path, pulls, and reuses `passed`. A fresh run on machine 2 fails.

**Fix:** tree-digest every `sys.path` directory outside root, stdlib and site, the same way as stdlib. Or, if that
is too big, record import-system reads of files outside those directories as per-test data inputs.

## FIX 3: process state read by C, outside os.environ (wrong reuse)

The identity's `python` part keeps `LC_CTYPE`, encodings, `time.timezone`/`altzone`/`tzname`, `platform.system()`
and `machine()`. The per-test env inputs only see `os.environ` accesses from Python. Behaviour that glibc reads
directly is in neither:

* `LD_PRELOAD` and `/etc/ld.so.preload`: the native closure is built from DT_NEEDED only.
  `test_hole_ld_preload_changes_behaviour_not_identity`. **End to end:** `test_e2e_wrong_reuse_ld_preload`: a
  preloaded shim changes `os.getuid()` on machine 2, and machine 2 still reuses `passed`. The real run fails.
  Sanitizer runtimes, libfaketime and jemalloc are the real-world cases.
* Locale categories other than CTYPE (`LC_NUMERIC`, `LC_TIME`, `LC_COLLATE`, `LC_MONETARY`, `LANG`/`LC_ALL` as
  they reach those), `LOCPATH`, and the locale data itself (`/usr/lib/locale/locale-archive`: which locales exist).
  These are read when a test calls `setlocale(LC_ALL, "")` or `setlocale(..., "de_DE.UTF-8")`.
  `test_hole_locale_categories_other_than_ctype`.
* CPUs visible to the process (`len(os.sched_getaffinity(0))`, `os.cpu_count()`, `os.process_cpu_count()`): pool
  sizes, chunking. `test_hole_cpu_count_visible_to_the_process`.
* CPU ISA (AVX-512 and similar): native code that dispatches on CPU features (numpy, OpenBLAS, simdjson) can give
  different floating-point results. The hosted rehearsal itself mixed CPUs with equal identities:
  * click: AMD EPYC 9V74 → Intel Xeon 6975P-C;
  * marshmallow: Intel 8573C → AMD EPYC 7763.

  It was harmless there (pure-Python suites), but it is exactly the "CPU features" case.

**Fix:**

1. Add to the identity:
   * the values of `LD_PRELOAD` and `LOCPATH`, the content of `/etc/ld.so.preload`, and the bytes of every library
     those name (add them as closure roots);
   * every locale category's value after `setlocale(LC_ALL, "")` (restore the previous values afterwards), and a
     digest of the locale archive or the `LOCPATH` tree;
   * the `TZ` value and the bytes of `/etc/localtime`, since `tzname` and the offsets do not fix the rules;
   * the visible CPU count. Hosted standard runners all report 4, so this costs no reuse there.
2. For ISA, either key a coarse feature level (x86-64-v2/v3/v4 from `/proc/cpuinfo` flags) or document the limit
   explicitly. Keying it would have split the hosted rehearsal (AMD vs Intel), so this is a decision for the
   planner. Today it is neither keyed nor documented.

## FIX 4: the service reads and inflates the body before it checks the token

`Handler.do_POST` calls `_body()` before `_auth()`. `_body()` reads up to `MAX_BODY` = 512 MB, then calls
`gzip.decompress` with no output bound. It checks the size only *after* decompressing. So anyone who can reach the
port can make the server allocate gigabytes from a few MB of gzip, without a token. Moving
`ThreadingHTTPServer` behind a TLS proxy does not change that.

* `test_hole_service_decompresses_unauthenticated_bodies`: the server inflated an unauthenticated body.

**Fix:** `_auth` first, `_body` second. Decompress with `zlib.decompressobj(16 + zlib.MAX_WBITS)` and `max_length`,
refusing anything over `MAX_BODY` while it streams. Also lower `MAX_BODY`: the client never sends more than about
16 MB per batch.

## FIX 5: the token file stays readable by the tests

Since 8d606a2, the workflow writes the write token to `$RUNNER_TEMP/cache-token` and exports
`FENVIX_CACHE_TOKEN_FILE`. `hide_token()` removes the variable, but the file stays on disk at a predictable path
(`RUNNER_TEMP` itself is visible to tests), owned by the user the tests run as.

* `test_hole_token_file_is_readable_by_the_tests`: a test copies the token out.

docs/SHARED-CACHE.md ("removed from the environment before any test runs") and the module docstring ("tests never
see the token") overclaim. A token with write access, combined with FIX 6, makes any test pass on every machine of
the organization.

**Fix:**

* Read the token in `fenvix-run` before pytest starts, pass it on a pipe or inherited fd (or `unlink` the file once
  read), and say in the docs exactly what a test can still reach.
* The policy belongs in the docs: write tokens only on trusted refs (default branch, protected branches), and
  read-only tokens for PR jobs.

## FIX 6: the recorded inputs are a claim too; the client trusts the server's addresses

docs/SHARED-CACHE.md "Limits": "Every candidate is checked against code and data, but the recorded outcome itself is
a claim." In fact the *set of inputs* is a claim as well. An entry that lists no code, no data and no environment
passes every check in `Checker::check`, so it is reused for any code, at any commit.

* `test_hole_entry_with_no_recorded_inputs_is_reused`: one write token turns a failing test into a reused `passed`
  on machine 2.

Also, `RemoteCache._get` does not recompute `doc_id(doc)` for the documents the service returns. A compromised
service, or anything on the path when the URL is `http://` to a non-loopback host (allowed, and the bearer token goes
in clear), can serve any document under any address.

**Fix:**

* Correct the docs: what a write token can do is "make any test pass", not "claim an outcome".
* Recompute and compare `doc_id` for every fetched document (cheap).
* Refuse `http://` to non-loopback hosts unless explicitly allowed.
* Floor check on pull: an entry must at least list the test's own file in its code sets, or it is not a candidate.
  This does not stop a forger, but it stops empty entries.
* Signed entries remain the real answer (already listed as next).

## Checked and fine

* **Cross-organization:** every SQL statement filters on `org`. `add_keys` refuses a key to a document the org does
  not hold. Lookup and blobs are scoped. The existing tests cover this and I confirmed it by reading.
* **Another project's entry in the same namespace:** candidates must match the node id and the lookup key (config and
  runtime digests), then pass content checks of every recorded code and data input. A different project fails the
  content checks. No wrong reuse, at worst a miss.
* **Tampered stored entry:** the server recomputes SHA-256 on put. UPDATE and DELETE triggers make the store
  append-only. Not tamperable through the API.
* **Cached failure:** `reusable_outcome` (`passed`/`skipped`/`xfailed`) is enforced in `Checker::check`, so it
  applies to pulled entries too.
* **Race between push and pull:**
  * push order is file/set docs, then entry docs, then the key log, so a key never points at a missing doc;
  * pull skips any entry whose sets cannot be resolved (`_set_indices` → None);
  * concurrent pushers are idempotent (`INSERT OR IGNORE`, `UNIQUE (org, ns, key, doc)`);
  * the journal is written by tmp + replace, so a lost update only re-pushes.

  I found no wrong-result race.
* **Missing auth:** every route except `/v1/health` needs a known token, and read-only tokens cannot write. FIX 4 is
  about what happens *before* the check, not the check itself.
* **Smaller notes (no FIX):**
  * Any writer can bury good entries by pushing more than 3 newer non-proving entries under a key (lookup limit 3,
    max 16). That costs availability only.
  * `_NetworkOpen` sets `network.POLICY = None` process-wide during pull and push, so a thread a test left running
    could connect in that window.
  * A pulled candidate overwrites a stale local entry for the same test. Harmless.

## Numbers recomputed (run 44264885597, compare job log)

Artifact downloads are blocked by this session's network policy (blob storage host refused). I recomputed from the
`compare.json` rows the compare job prints in its log, and from the machine-2 verify output.

| target | one machine: reused / tests | two machines: reused / tests | ratio | checked | wrong | misses one → two |
|---|---:|---:|---:|---:|---:|---|
| pygments | 5287 / 5314 | 5288 / 5314 (5288 from service) | 1.00019 | 5288 | 0 | code 2, new 3, data 1, clock 21 (27) → code 2, new 24 (26) |
| click | 1657 / 1982 | 1657 / 1982 (1657 from service) | 1.0000 | 1657 | 0 | new 84, clock 41, code 195, data 3, env 2 (325) → new 125, code 195, data 3, env 2 (325) |
| marshmallow | 675 / 1192 | 675 / 1192 (675 from service) | 1.0000 | 675 | 0 | clock 400, new 4, code 113 (517) → new 404, code 113 (517) |

* **Every miss total sums to tests − reused.** Pull stats agree:
  * pygments: 5290 injected, 5288 proven;
  * click: 1857 injected, 1657 proven;
  * marshmallow: 788 injected, 675 proven.

  Runtime digests are equal across machines in all three. The previous RECORD-based identity differs in all three,
  which reproduces the motivating failure.
* **"100%" is honest but rounded.** pygments is 5288/5287: one test (`test_unicode_options`) missed on one machine
  because of a random temp-file path, and was reused across machines. The one-machine "clock" misses show up as
  "new" across machines, because pull asks only for the current epoch and the no-clock key. The counts are
  unchanged.
* **The "checked" re-run is independent of the cache.**
  * `fenvix-run verify` strips every `--det-cache*`, `--det-outcomes` and `--junitxml` argument and drops the client
    variables (`without_client_env`).
  * It runs the full suite on machine 2 at the same epoch. The log shows
    `pytest --det --det-urandom -p no:cacheprovider ... --det-outcomes=...verify-1.json`, with no cache argument.
  * It compares every reused outcome, re-runs mismatches once, and exits non-zero if `checked < reused`.
* **What 0 wrong does not show.** Both hosted machines are built from the same image, the same pinned uv and the same
  paths, so none of the holes above could show up. "0 wrong" supports "equal machines reuse safely". It says nothing
  about "different machines are told apart". The failing tests above cover that side.
* **Wall time (not a claim of the report, noted for the planner):** pull adds 2.4 s on pygments. Two-machine job 2
  wall time is 8.5 s against 4.4 s on one machine, for 10 s of test time saved.

## Requested for the fix round

1. FIX 1–3 with the tests in `tests/test_review_r008.py` passing. The identity tests must keep "same image, other
   paths/installers → equal" (`test_runtime_id.py`) green.
2. FIX 4–6 with the matching tests passing, or (FIX 6, floor check) a documented reason not to.
3. Re-run `fenvix-shared-cache` once, to confirm the new identity still equals across two hosted machines (the
   reuse ratio must not drop).
