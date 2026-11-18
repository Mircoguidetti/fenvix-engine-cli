DONE (fix round for review R-008, FIX 6) — with one decision for the planner: the instruction-set level

# Shared cache across machines: fixes after review R-008

All six FIX items are fixed on `claude/shared-cache` (head `1d430a6`). The reviewer's 12 tests
(`tests/test_review_r008.py`, copied unchanged from `claude/review-r008-tests` 635dec5) fail at `da1afa9` and pass
now, including both end-to-end wrong reuses. The identity now also keys the CPU instruction-set level, as FIX 3
asked. On GitHub's mixed fleet that splits the cache by level: machines at the same level still reuse 100% of
what one machine reuses; machines at different levels (x86-64-v3 vs v4) reuse nothing. With the level left out
(`FENVIX_RUNTIME_ISA=off`), every pair reuses 100% again. Whether the level stays in by default is the planner's
call (below).

## Numbers

| item | result | label |
|---|---|---|
| reviewer tests `tests/test_review_r008.py` | 12 of 12 fail at `da1afa9` (also on this machine, none skipped); **12 of 12 pass** at `1d430a6` | MEASURED |
| engine suite | **152 passed, 6 skipped** (`pytest tests`, 438 s, 4 CPUs); before this round 136 passed, 6 skipped. `cargo test --release`: 47 passed (no Rust change) | MEASURED |
| identity "same image, other paths/installers → equal" (`tests/test_runtime_id.py`) | still green (11 tests, one added: TZ rules and the ISA switch) | MEASURED |
| hosted, ISA level keyed (default) | run [44299953107](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44299953107): 3 of 3 pairs at different levels → **0 reused**. Run [44300528610](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44300528610): pygments v4/v4 **5,288 vs 5,287 (100%)**, click v4/v4 **1,657 vs 1,657 (100%)**, marshmallow v3/v4 **0**. In every 0, the identities differ only in `cpu` | MEASURED |
| hosted, `FENVIX_RUNTIME_ISA=off` | run [44300539734](https://github.com/Mircoguidetti/fenvix-engine-cli/actions/runs/44300539734): pygments **5,288 vs 5,287**, click **1,657 vs 1,657**, marshmallow **675 vs 675** = 100% each. Two of the three pairs crossed AMD EPYC 7763 (v3) and 9V74 (v4). Identities equal | MEASURED |
| wrong | **0** in every hosted run; every reuse checked by a full fresh run (e.g. run 44300539734: 5,288 + 1,657 + 675 = 7,620 checked) | MEASURED |
| other identity parts across hosted machines | equal in all 9 new pairs: site tree, extra paths, locale, time zone, CPU count, native closure. The new parts cost no reuse on GitHub's image | MEASURED |
| previous (RECORD-based) identity | still different on every pair: the original failure is still shown and fixed | MEASURED |

Cost (MEASURED, single runs, NOISY):

* Identity computation: 0.07 s warm, 0.3-0.5 s cold here (whole site tree now hashed, memoised per file).
* Pygments pull on hosted machines: 2.4-3.0 s.

## The six items

1. **FIX 1, files no RECORD lists.** `site_tree` keys every file under every site directory by relative path and
   bytes. It covers unowned packages, files added after install and egg-info installs. It leaves out only bytecode,
   installer bookkeeping (`RECORD`, `INSTALLER`, `REQUESTED`, `direct_url.json`) and the project's own editable
   install. `site_loose` is gone, since `site_tree` contains it. Tests: `test_hole_unowned_package_directory_in_site_packages`,
   `..._file_inside_a_distribution_not_listed_in_its_record`, `..._legacy_egg_info_...`.
2. **FIX 2, modules on other import paths.** `extra_paths` keys the content of every `sys.path` entry outside the
   project, the stdlib and the site directories. Paths under the interpreter prefix get symbolic names, so a
   relocated interpreter stays equal. An entry with more than 50,000 files is keyed on a random value, so it is never
   reusable, rather than unchecked. Tests: `test_hole_module_on_an_import_path_outside_site_and_root`,
   `test_e2e_wrong_reuse_module_outside_site_and_root`.
3. **FIX 3, state read by C.** Changes to the identity:
   * `native` now also holds the `LD_PRELOAD` and `/etc/ld.so.preload` libraries, by bytes, as closure roots.
   * `locale`: every category a test gets from `setlocale(LC_ALL, "")`, plus `LANGUAGE` and the locale data
     (`LOCPATH` or `/usr/lib/locale`). The process's own locale is restored afterwards.
   * `tz`: `TZ`, the zone file it names, `/etc/localtime`, `/etc/timezone`.
   * `cpu`: affinity, `cpu_count`, `process_cpu_count`, and the **ISA level** (x86-64 v1..v4 from `/proc/cpuinfo`;
     elsewhere the feature list). `FENVIX_RUNTIME_ISA=off` leaves the level out, as a deliberate, documented choice.

   Tests: `test_hole_ld_preload_...`, `test_e2e_wrong_reuse_ld_preload`, `test_hole_locale_categories_other_than_ctype`,
   `test_hole_cpu_count_visible_to_the_process`, `test_time_zone_and_instruction_set_level_are_keyed`.
4. **FIX 4, auth before body.** The token is checked before the body is read; an unknown caller costs a header parse
   and the connection is closed. Gzip bodies are inflated with `zlib.decompressobj(...).decompress(..., max_length)`
   in bounded steps and refused past `MAX_BODY`, now 64 MB (was 512 MB). Tests:
   `test_hole_service_decompresses_unauthenticated_bodies`, and a new
   `test_service_refuses_a_gzip_bomb_from_a_known_token_while_inflating`.
5. **FIX 5, token reachable by tests.**
   * `fenvix-run` takes the token (from `FENVIX_CACHE_TOKEN`, or the hand-off file `FENVIX_CACHE_TOKEN_FILE`, which it
     deletes once read) and passes it to pytest on an inherited pipe (`FENVIX_CACHE_TOKEN_FD`).
   * Used directly, the engine moves a `FENVIX_CACHE_TOKEN` into a pipe before detpy re-executes the interpreter, so
     the token is not in the test process's `/proc/self/environ`.
   * Before any test runs, the client closes the pipe, deletes a hand-off file and removes its variables.
   * Tests: `test_hole_token_file_is_readable_by_the_tests`. The new environment test now also scans
     `/proc/self/environ` and every readable pipe; without the pipe move it fails, with it it passes.
     `test_fenvix_run_...` checks that the hand-off file is consumed.
   * **What a test can still reach, now documented:** the client's memory, since it runs in the test process, and,
     with `--det-no-reexec`, an env-given token in `/proc/self/environ`. Policy in `docs/SHARED-CACHE.md`: write
     tokens only on trusted refs; read-only tokens for jobs that run untrusted code.
6. **FIX 6, inputs are a claim; addresses not checked.**
   * Every fetched document's address is recomputed, and a mismatch is dropped and counted.
   * A candidate must list its own test file among its code or data inputs. This held for **10,963 of 10,963**
     entries in the four real stores (pygments, both click pairs, marshmallow) (MEASURED), so it costs no legitimate
     reuse.
   * Plain `http://` to a non-loopback host is refused unless `FENVIX_CACHE_ALLOW_HTTP=1`.
   * Docs now say a write token can make **any test pass**, and that the floor check does not stop a forger who
     lists the file; signed entries remain the answer.
   * Tests: `test_hole_entry_with_no_recorded_inputs_is_reused`, `test_documents_that_do_not_match_their_address_are_dropped`,
     `test_plain_http_to_a_remote_host_is_refused`. The non-loopback service test now sets the allow flag.

## Decision for the planner: the instruction-set level

* Keyed (default now): the safe reading of "different whenever behaviour can differ". glibc's libm, numpy and
  OpenBLAS pick code paths by CPU features, which can change floating-point results.
* The cost on GitHub-hosted runners, which mix EPYC 7763 (v3) with AVX-512 machines (v4): 2 of the 6 keyed pairs
  matched levels. A cache shared by such a fleet splits into two (v3, v4); each side warms on its own. MEASURED on 6
  pairs, so the share is only indicative.
* On our own fleet (`runs-on: fenvix`), we pick machines at one level: no cost.
* Option: default `off` for projects with no native extension modules outside the stdlib. It is not done: libm in
  pure Python is still a theoretical difference, and I could not prove it harmless.
* The hosted exit item (cross-machine reuse > 90% of one machine) holds for every same-level pair and for every pair
  with the level off. With the level keyed, it fails for cross-level pairs by design.

## What I decided and why

* The whole site tree instead of RECORD plus extras. Simplest complete rule, and the memo keeps it to one stat per
  file. pygments' venv: 502 files; cold 0.3-0.5 s. Very large environments (thousands of distributions) are not
  measured here (UNKNOWN).
* Not done (reviewer smaller notes, no FIX):
  * lookup burying by many non-proving entries;
  * `_NetworkOpen` process-wide (now documented);
  * pull asking only the current epoch.

## What blocks or is missing

* The ISA decision above.
* Still open from the first report: signed entries; data inputs outside the project keyed by absolute path
  (proofcache.py, step-1 territory); pull volume (pygments ~10 MB, 2-3 s); step 1 not landed, so not rebased (one
  expected conflict in `proofcache.runtime_identity`).
* Hardware other than the ISA level and the CPU count (CPU model, memory, GPUs) is not keyed (documented).

## Links

* Engine branch `claude/shared-cache`, commits:
  * `95ae49c` reviewer tests;
  * `d7b7ec9` FIX 1-3;
  * `20ec467` FIX 4;
  * `3851039` FIX 5-6;
  * `471b83f` workflow input `isa`;
  * `1d430a6` docs.
* Files: `python/detpy/runtime_id.py`, `python/detpy/cache_service.py`, `python/detpy/remote_cache.py`,
  `runner/fenvix-run`, `runner/shared-cache-compare`, `.github/workflows/fenvix-shared-cache.yml`,
  `docs/SHARED-CACHE.md`, `tests/test_review_r008.py`, `tests/test_runtime_id.py`, `tests/test_shared_cache.py`.
* Hosted runs after the fixes: 44299953107 (keyed), 44300528610 (keyed), 44300539734 (`isa=off`).

## Errors or gaps in the brain

* None found in this round.
