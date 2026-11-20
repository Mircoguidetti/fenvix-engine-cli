# BRANCH: work that exists on a branch but did not reach `claude/release-1` (engine) or `main` (fenvix-app)

Agent `BRANCH`, gap audit P-036. Stopped early on a budget instruction from the coordinator: see "Not covered".
Gaps: `/home/user/audit/findings/BRANCH.gaps.jsonl` (76 entries, BRANCH-001 to BRANCH-076).
Scratch: `/home/user/audit/work/BRANCH/` (`only/*.only` = files on each branch and absent from release-1, results
directories excluded; `unskip-*.log` = runs below; `gaps_0*.py` + `emit.py` = source of the JSONL).

Method. For every engine branch: ahead/behind against `origin/claude/release-1` (529c1609), then content, because
histories were rebased and ported (commit counts mislead): (1) files on the branch and absent from release-1;
(2) for branches with unique commits, the non-result files those commits touch and whether the blob differs;
(3) the set of `--det*` options defined on each branch against release-1's (this catches a feature whose file exists
on both sides); (4) test function names per test file. Where a feature or test was absent I ran the branch's own
test, or the flag, against the release-1 wheel in `/home/user/audit/build/dist/` (Python 3.12 venv in scratch).

## 1. Facts settled (each asked for explicitly)

| Question | Answer | Evidence |
|---|---|---|
| L1 asyncio (`--det-async`) on release-1? | **No.** Only the unused `Source::Sched` vocabulary in detpy-core | RAN: `pytest --det --det-async` => `unrecognized arguments`; no `python/detpy/aio.py`. BRANCH-001 |
| L1 threads (`--det-threads`) on release-1? | **No.** Not in Python, not in Rust | RAN: `unrecognized arguments: --det-threads`; no `threads.py`/`frames.py`. BRANCH-002..006 |
| `detpy repro`, `explore`, `replay`, bundles, families on release-1? | **Yes**, ported to Rust (`crates/detpy-core/src/repro.rs`: `reproduce`, `ddmin`, `ExploreLog`, `render_bundle`; `python/detpy/repro.py` is a thin shell; `tests/test_repro.py`, `test_repro_rust.py`). pytest only | RAN: `detpy --help` lists `verify, backends, repro, explore, replay` + 6 runner names |
| `detpy` console script? | **Yes**: `pyproject.toml` `[project.scripts] detpy = "detpy.cli:main"` | RAN: `v312/bin/detpy --help` |
| Shared cache service (claude/shared-cache) fully on release-1? | **No.** Service file and Python client file are in the tree, but the client is not wired: `--det-cache=https://...` becomes a directory name. Only a directory transport (`--det-cache-shared DIR`, Rust `shared.rs`) works. detjs has its HTTP client (`node/src/cache/remote.js`) | RAN, section 3.1. BRANCH-007..012 |
| Audit reruns (claude/audit-reruns) on release-1? | **No**, nothing of it | RAN: `--det-cache-audit` unrecognized. BRANCH-020..025 |
| runner-node on release-1? Does the runner drive Node? | **No.** `runner/fenvix-run` on release-1 is byte-identical to claude/shared-cache's (blob 6841d969, 509 lines, pytest only) | BRANCH-026..030 |
| runner prototype on release-1? | Yes (`runner/`), in the shared-cache version; only `runner/LAST-LIVE-RUN.txt` (a trigger file) is missing | blobs table, section 3.6 |
| L2 browser on release-1? | **Nothing.** The branches hold a product component (`detjs playwright`, `detjs serve`, `detjs state`, `lockstep.rs`, a Chromium patch), not only a study harness | BRANCH-031..039 |
| claude/parallel-proof-3 (5 ahead) | 2 engine commits not on release-1 (fa290d64, e3628639: `capture.rs`, `tests/test_round4_capture.py`, reference capture); 3 report/gate commits | RAN: its 3 tests fail on the release-1 wheel. BRANCH-016..019 |
| claude/go-l0 (6 ahead) | results only (6 "Go harness: ..." commits, no source file) | `git log --name-status R..go-l0` without results: empty |
| claude/all-runners-2 (90 ahead) | results + report/gate text only (`sessions/2026-11-19-all-runners/REPORT-2.md`, `make_report2.py`, `tracks/all-runners-2/gates/*`) | section 3.5 |
| claude/dep-verdict-abjcfw (2 ahead) | one report file (`sessions/2026-11-18-dep-verdict/REPORT-3.md`) | same |
| claude/node-cache-proof (148 ahead) | superseded: every `node/test` file and test name of the branch is on release-1 (0 names missing), the last fixes (R-032 F6/F7, r021b) are in `node/src/cache/capture.js`; only session reports are missing | section 3.5 |
| Is there a `main` in the engine repository? Default branch? | **No `main`.** Default = `claude/gracious-rubin-eyswxd` (Block 2 results, 2026-11-17, 3,034 commits behind release-1) | `git ls-remote --symref origin HEAD`. BRANCH-040 |
| Consequence for `schedule:` | The only scheduled workflow (`go-nightly-real-clock.yml`) is not on the default branch: it never fires on schedule | BRANCH-041, 042 |

## 2. Branch -> verdict

### 2.1 Engine (61 branches besides release-1; ahead/behind counted against release-1)

| Branch | Ahead | Verdict | Gap ids |
|---|---|---|---|
| claude/l1-asyncio-study | 20 | **HAS UNMERGED WORK** (asyncio scheduler, tests, docs, workflows) | 001, 003, 005, 006 |
| claude/l1-threads-fix | 169 | **HAS UNMERGED WORK** (threads + asyncio, tests, docs, harness) | 001-006 |
| claude/review-r007b | 154 | **HAS UNMERGED WORK** (reviewer test on L1 threads) | 004 |
| claude/shared-cache | 38 | **HAS UNMERGED WORK**: files copied, engine wiring lost in the Rust port (client, token hiding, start-up rule) | 007-015 |
| claude/review-r008-tests | 27 | on release-1 but 4 tests carry a skip marker added later | 011 |
| claude/review-r008b | 33 | on release-1 but 1 test skipped | 012 |
| claude/review-r008d | 38 | on release-1 but the whole file skipped (stale marker) | 013, 014, 015 |
| claude/audit-reruns | 46 | **HAS UNMERGED WORK** (whole feature) | 020-025, 075 |
| claude/review-r013 | 44 | **HAS UNMERGED WORK** (reviewer tests of the audit) | 023 |
| claude/review-r013b | 45 | **HAS UNMERGED WORK** (reviewer tests of the audit) | 023 |
| claude/runner-node | 26 | **HAS UNMERGED WORK** (Node path of the job wrapper, bootstrap, tests, workflow) | 026-030, 076 |
| claude/runner-prototype-ee21he | 19 | superseded by shared-cache's runner files (on release-1); only a trigger file missing | - |
| claude/l2-browser-r2 | 49 | **HAS UNMERGED WORK**, ancestor of l2-browser-lockstep | 031-039 |
| claude/l2-browser-r3 | 111 | **HAS UNMERGED WORK**, ancestor of l2-browser-lockstep | 031-039 |
| claude/l2-browser-lockstep-ytoqnv | 172 | **HAS UNMERGED WORK** (still running, P-030) | 031-039 |
| claude/review-r011 | 51 | **HAS UNMERGED WORK** (reviewer tests of L2 browser r2), ancestor of lockstep | 038 |
| claude/parallel-proof-3 | 5 | **HAS UNMERGED WORK** (2 round-4 engine commits + 1 test file) | 016-019 |
| claude/parallel-proof | 0 | merged | - |
| claude/parallel-proof-design | 4 | superseded (design doc and `tracks/parallel-proof` are on release-1 in later versions) | - |
| claude/all-runners | 275 | superseded by all-runners-2 (`_statcap.py` -> Rust capture, `capture.rs:2332`; differing test names are renames) | 054 (reports) |
| claude/all-runners-2 | 90 | results + report/gate text only | 054 |
| claude/review-r032 | 276 | merged (reviewer files identical on release-1; one case of `review-r032-runners-b.test.js` rewritten for tap) | - |
| claude/review-r032b | 1 | merged (reviewer files identical); report files missing | - |
| claude/node-cache-proof | 148 | superseded (all tests and fixes on release-1); reports missing | 054 |
| claude/node-l0 | 0 | merged | - |
| claude/review-r021 | 97 | merged (reviewer files identical) but `harness/node_cache/test_review_r021_labels.py` is in no gate | 049 |
| claude/review-r021b | 117 | merged (reviewer files identical) | - |
| claude/go-l0 | 6 | results only | - |
| claude/review-r025 | 0 | merged (`go/internal/skip`, `strace` later replaced by the Rust core, a5405cf5) | - |
| claude/review-r025b | 0 | merged | - |
| claude/jvm-l0 | 0 | merged | - |
| claude/review-r022 | 0 | merged | 050 (runner not in gate) |
| claude/review-r022b | 0 | merged, but `run_review_r022b.py` is not in the gate | 050 |
| claude/dep-verdict-abjcfw | 2 | report only | 054 |
| claude/review-r020 | 2 | merged (test identical); review inputs/report missing | - |
| claude/review-r020b | 0 | merged | - |
| claude/exact-culprit | 0 | merged (as a harness, `harness/culprit/finder.py`; no product command) | 047, 048 |
| claude/exact-culprit-n98yc2 | 0 | merged | - |
| claude/review-r019 | 2 | test files on release-1, identical, but outside the gate | 047 |
| claude/review-r019b | 0 | merged; tests outside the gate | 047 |
| claude/review-r019c | 2 | test files identical on release-1 but outside the gate; sample drivers and report missing | 047 |
| claude/cache-proof-step1 | 0 | merged | - |
| claude/review-r009-tests | 2 | on release-1, edited after the review | 051 |
| claude/review-r009b | 2 | on release-1, edited after the review | 051 |
| claude/rust-hotpaths | 0 | merged | - |
| claude/rust-hotpaths-2 | 0 | merged | - |
| claude/review-r015 | 1 | merged (one assert message changed) | - |
| claude/review-r015b | 2 | merged (identical) | - |
| claude/review-r017 | 1 | merged (identical) but H2 is deselected in the gate | 046 |
| claude/review-r017b | 0 | merged | - |
| claude/review-r023 | 0 | merged | - |
| claude/review-r023b | 2 | merged (test file identical on release-1); report missing | - |
| claude/compassionate-edison-2dsntf | 2 | results only (same commit as the default branch) | 040 |
| claude/gracious-rubin-eyswxd | 2 | results only; it is the **default branch** | 040, 041 |
| claude/loving-maxwell-58mv2w | 1411 | study branch (harnesses, results, pricing); no product code missing | 052 |
| claude/sweet-mendel-rtdg7f | 1512 | study branch | 052 |
| claude/pricing-v2 | 1413 | study branch (pricing model + its test) | 052 |
| claude/market-test | 1516 | study branch | 052, 053 |
| claude/market-test-r010 | 1516 | same commit as claude/market-test | 052, 053 |
| claude/review-r010b | 1518 | study branch + reviewer tests of the market test | 053 |
| review-claude/market-test | 1514 | study branch | 052, 053 |

A branch `claude/gap-audit` appeared on origin during this audit (2 commits, "Gap audit P-036: platform probe",
workflows `gap-audit.yml`, `gap-audit-macos-arm.yml`). It was created by another audit session, not analysed here.

### 2.2 fenvix-app (58 branches besides main)

Current product (share history with main):

| Branch | Ahead | Verdict | Gap ids |
|---|---|---|---|
| claude/customer-mode-pnap | 7 | **HAS UNMERGED WORK** (customer mode on phoenixNAP, whole feature; brain LOG.md:145 "NOT merged") | 055-059, 062 |
| claude/review-r014 | 6 | **HAS UNMERGED WORK** (reviewer tests; contained with fixes in customer-mode-pnap) | 060 |
| claude/review-r014b | 7 | **HAS UNMERGED WORK** (reviewer test N1) | 061 |
| claude/review-r012 | 1 | tests on main (`infra/.../review-r012.test.ts` adapted to a DEMO helper); report missing | 066 |
| claude/review-r012b | 1 | **HAS UNMERGED WORK**: `infra/github-app/test/review-r012b.test.ts` absent on main, all 3 tests fail on main | 063, 064, 065 |
| claude/review-r016 | 2 | test identical on main; report missing | 066 |
| claude/review-r016b | 1 | test identical on main; report missing | 066 |
| claude/review-r018 | 2 | merged (test and report identical) | - |
| claude/review-r018b | 2 | report + screenshots only | 066 |
| claude/dashboard-vercel, dashboard-wiring, deploy-pipeline, github-app, warm-cache-install, fenvix-customer-dashboard-pl5jeo, compassionate-edison-2dsntf, fix-cfn-tag-permissions, fix-shellcheck, review-r024, review-r024b, review-r024c | 0 | merged | - |

Old product (no common history with main; README "FENVIX dashboard (olvix-app)", pages Databases / CreateDatabase /
DatabaseDetail, `control-plane/`): 37 branches, nothing for the current product (BRANCH-067):
account-linking, console-ui, control-plane, cp-engine-round2, data-browser, db-users, deploy-automation, e2e-engine,
e2e-final, engine-adapter, fix-deploy-no-cdk-roles, fix-deploy-policy-retag, fix-deploy-policy-volume,
fix-domain-fenvix-dev, fix-oidc-provider-arn, infra-align, infra-align-certbot, infra-align-lego, infra-aws,
infra-grants, navbar-fix, network-tab, orgs-invites, product-plan-template-fleet-agents, public-api,
public-api-usage, release-candidate, scale-out-design, ui-api-keys, ui-mood, ui-polish, ui-status,
claude/admiring-bell-nnpewa, claude/beautiful-carson-bin9vp, claude/dashboard-api-http-px0vt6,
claude/fenvix-dashboard-overhaul-a24sq7, claude/fenvix-ui-redesign-7gdamk.

## 3. Evidence appendix (commands and trimmed real output)

### 3.1 Shared cache service client not wired (BRANCH-007, 008, 009, 010, 011, 012)

```
$ python -m detpy.cache_service serve --data svc-data --port 18787 --quiet &
$ FENVIX_CACHE_TOKEN=$TOK pytest -q --det --det-cache=http://127.0.0.1:18787/demo/p1 -p no:cacheprovider
reused 0 result(s) with proof, ran 1, recorded 1 ...
receipts: /home/user/audit/work/BRANCH/proj1/http:/127.0.0.1:18787/demo/p1/receipts.jsonl
$ find . -maxdepth 4          ->  ./http:/127.0.0.1:18787/demo/p1   (a local directory)
$ find svc-data               ->  tokens.json, cache.sqlite3* only (no document, no key log)
$ grep -rn remote_cache python/detpy/*.py        (release-1)  -> only its own docstring
origin/claude/shared-cache:python/detpy/plugin.py:252  ns.det_cache = remote_cache.localize(ns.det_cache)
origin/claude/shared-cache:python/detpy/plugin.py:285  remote_cache.hide_token()
origin/claude/shared-cache:python/detpy/plugin.py:361  remote_cache.attach(config)
```

Skip markers removed in a scratch copy of release-1's `tests/` (layout as the gate: `python/detpy` + the wheel's
extension), release-1 wheel, Python 3.12 (`unskip-shared.log`):

```
FAILED tests/test_shared_cache.py::test_second_machine_reuses_with_proof_what_the_first_recorded
FAILED tests/test_shared_cache.py::test_another_runtime_never_reuses
FAILED tests/test_shared_cache.py::test_other_organization_gets_nothing
FAILED tests/test_shared_cache.py::test_service_down_falls_back_to_the_local_mirror
FAILED tests/test_shared_cache.py::test_entries_pushed_while_the_service_was_down_are_pushed_later
FAILED tests/test_shared_cache.py::test_token_is_not_visible_even_to_a_test_that_enumerates_the_environment
FAILED tests/test_shared_cache.py::test_fenvix_run_on_two_machines_sharing_the_service
FAILED tests/test_shared_cache.py::test_service_on_a_non_loopback_address_is_reachable_under_the_closed_network
FAILED tests/test_shared_cache.py::test_candidates_are_checked_when_the_project_looks_as_the_tests_saw_it
FAILED tests/test_shared_cache.py::test_plain_http_to_a_remote_host_is_refused
FAILED tests/test_review_r008.py::test_e2e_wrong_reuse_module_outside_site_and_root
FAILED tests/test_review_r008.py::test_e2e_wrong_reuse_ld_preload
FAILED tests/test_review_r008.py::test_hole_token_file_is_readable_by_the_tests
FAILED tests/test_review_r008.py::test_hole_entry_with_no_recorded_inputs_is_reused
FAILED tests/test_review_r008b.py::test_e2e_wrong_reuse_symlinked_package_on_an_import_path
15 failed, 21 passed in 132.69s
E   AssertionError: assert 'fxc_wrong' is None                      (token still in os.environ)
E   AssertionError: a test read the service's write token
E   AssertionError: machine 1 pushed nothing: {}
```

The 15 failures are exactly the 15 tests that carry `@_CLIENT_NOT_PORTED` on release-1; the 21 others pass.

### 3.2 Start-up process rule tests (BRANCH-013, 014, 015)

Markers removed from `test_review_r008d.py`, `test_startup_spawn.py`, `test_startup_digest.py` (`unskip-startup.log`):

```
FAILED tests/test_review_r008d.py::test_startup_git_describe_is_an_input
       {'test_m.py::test_version_is_a_1x': 'subprocess'}   (run 1 not cacheable: conservative, no wrong reuse)
FAILED tests/test_startup_spawn.py::test_startup_process_a_test_talks_to_keeps_that_test_uncached   (reason text)
FAILED tests/test_startup_spawn.py::test_spawn_inside_a_test_still_keeps_that_test_uncached
FAILED tests/test_startup_spawn.py::test_environment_handed_to_a_startup_process_is_not_an_input_of_the_tests
FAILED tests/test_startup_digest.py::test_daemon_with_a_passed_descriptor_keeps_every_test_uncached
FAILED tests/test_startup_digest.py::test_process_left_running_by_a_finished_startup_process_keeps_every_test_uncached
FAILED tests/test_startup_digest.py::test_output_read_outside_subprocess_run_keeps_the_old_flag
7 failed, 14 passed, 2 skipped in 56.36s
```

Two of these looked like possible wrong reuses (release-1 caches where the shared-cache rule refused). I checked both
by hand and found **no wrong reuse**: release-1 follows the start-up process and keys what it read.

```
daemon started at configure with pass_fds, answer changed 1.0 -> 2.0:
  run 1: recorded 1          run 2: "not reused: data 1", 1 failed          (fresh run: 1 failed)
Popen + readline at configure, tool output changed (directly, and through an inner program found by PATH):
  run 1: recorded 1   unchanged rerun: reused 1   changed: "not reused: data 1", 1 failed
```

So the "not yet ported" reason is stale for 14 of 21 tests; the entries are about passing guards being switched off
and about the six tests whose expectations no longer describe release-1 (nobody decided which behaviour is right).

### 3.3 L1 and audit flags (BRANCH-001, 002, 020)

```
$ pytest -q --det --det-async            -> error: unrecognized arguments: --det-async
$ pytest -q --det --det-threads          -> error: unrecognized arguments: --det-threads
$ pytest -q --det --det-cache=.c --det-cache-audit=0.5 -> error: unrecognized arguments: --det-cache-audit=0.5
```

Options defined on a branch and on no file of release-1 (`git grep -h -o '"--det[a-z0-9-]*"' <branch> -- python/detpy
crates/detpy-py/src`, then `comm` against release-1; same for `node/src node/bin`):

```
audit-reruns, review-r013, review-r013b : --det-cache-audit --det-cache-audit-seed
l1-asyncio-study                        : --det-async --det-async-grace --det-async-seed --det-async-settle --det-async-wait
l1-threads-fix, review-r007b            : the five above + --det-threads --det-threads-deadlock --det-threads-grace
                                          --det-threads-preempt --det-threads-real-urandom --det-threads-seed --det-threads-stuck
l2-browser-r2, review-r011              : --det-browser-seeds --det-net --det-net-window --det-server --det-state --det-vtime
l2-browser-r3, l2-browser-lockstep      : the six above + --det-freeze --det-latency
```

No other branch defines an option release-1 lacks: this list is the complete set of branch-only engine switches.

### 3.4 parallel-proof-3 round 4 (BRANCH-016..019)

`origin/claude/parallel-proof-3:tests/test_round4_capture.py` on the release-1 wheel:

```
FAILED test_a_raising_os_path_patch_does_not_reach_the_test_through_detpy   {'passed': 0} != {'passed': 1}
FAILED test_a_spawn_hook_of_the_project_does_not_make_infrastructure_spawns_its_own
       {'test_a.py::test_a': 'subprocess', 'test_spawn.py::test_spawn': 'subprocess', 'test_b.py::test_b': 'subprocess'}
FAILED test_a_boot_id_read_at_import_is_a_content_input_not_a_refusal       assert [] == ['test_a.py::test_a']
3 failed in 22.66s
```

Commits: fa290d64 (capture falls back to the real `os.path` functions when a patched one raises; "pydantic-ai: 81
tests failed under --det-cache only", DECLARED by the commit), e3628639 (spawn hook, kernel identity files).
`grep -n -E 'REAL_OS|fn os_call|MACHINE_FILES' crates/detpy-py/src/*.rs` on release-1: no match.

### 3.5 Superseded branches (not gaps)

- node-cache-proof: per file of `node/test` on the branch, test names missing on release-1 = 0 (cache 29/29,
  controls 30/30, r021-fixes 14/14, review-r021 20/20, unchanged 20/20, ...).
- all-runners: `python/detpy/_statcap.py` only there; release-1 `crates/detpy-py/src/capture.rs:2332` "claude/all-runners
  (`_statcap.py`'s probe set) into the Rust capture". Test names that differ are renames ("stat() mtime ...: not
  cacheable" -> "keyed by its value, a touch reruns").
- all-runners-2: files touched by its 90 unique commits and differing from release-1, results excluded:
  `sessions/2026-11-19-all-runners/REPORT-2.md`, `make_report2.py`, `tracks/all-runners-2/gates/{cargo-test,
  node-suite-summary,pytest-full,r032b-python}.txt`, `gates/summary.json`. No source.
- go-l0: 6 commits, all "Go harness: <repo>:<shard> (skip-r9) from run 44673909307"; no non-result file.
- review-r025: `go/internal/skip`, `go/internal/strace` deleted by a5405cf5 "Go skip: key and decision move to the
  Rust core"; `TestInterleavingIsMeasuredNotControlled` replaced by `TestInterleavingSchedControl`.

### 3.6 Blobs of the runner and shared-cache files

```
runner/fenvix-run            rel=6841d969 shared-cache=6841d969 audit-reruns=2bb9ed09 runner-node=9b5c04ae prototype=a3781112
runner/bootstrap.sh          rel=eb5065d6 shared-cache=eb5065d6 audit-reruns=eb5065d6 runner-node=5d6561b7
python/detpy/remote_cache.py rel=641c6d74 shared-cache=641c6d74 audit-reruns=765a1380
python/detpy/cache_service.py rel=1ad68b46 shared-cache=1ad68b46 audit-reruns=c037572a
docs/RUNNER-PROTOTYPE.md     rel=483df975 shared-cache=483df975 runner-node=b75d3276
tests/test_shared_cache.py   rel=f41831f5 shared-cache=d4a304ba   (release-1 = shared-cache's + skip markers)
```

### 3.7 Reviewer tests against release-1 and its gate

The gate (`.github/workflows/release-1.yml`): `pytest tests` (one test deselected), `node --test test/*.test.js`,
`go test ./...`, `jvm/test/run_controls.py`, `run_skipkeys.py`, `run_review_r022.py`.

| Review | Reviewer test file(s) | On release-1 | In the gate |
|---|---|---|---|
| R-001 / R-003 | tests/test_review_b1_*, b4_*, lock_type, plugin_options, t1_extra; test_review_results.py | identical | yes (results file: informational step) |
| R-007b | tests/test_review_r007b.py | **absent** | no (004) |
| R-008 | tests/test_review_r008.py | present, **4 tests skipped** | counted as skipped (011) |
| R-008b | tests/test_review_r008b.py | present, **1 test skipped** | counted as skipped (012) |
| R-008d | tests/test_review_r008d.py | present, **whole file skipped** | counted as skipped (013) |
| R-009 / R-009b | tests/test_review_r009.py, r009b.py | present, **edited** | yes (051) |
| R-010 | harness/market_test/tests/test_r010_*.py | **absent** | no (053) |
| R-011 | node/test/review-r011.test.js, tracks/l2-browser-r2/review/test_review_r011.py | **absent** | no (038) |
| R-013 / R-013b | tests/test_review_r013.py, r013b.py | **absent** | no (023) |
| R-015 / R-015b | tests/test_review_r015.py, r015b.py | present (one assert message changed) | yes |
| R-017 / R-017b | tests/test_review_r017.py, r017b.py | identical | yes, **H2 deselected** (046) |
| R-019 / b / c | harness/culprit/review_r019*/test_*.py | identical | **no** (047); ports in tests/test_absent_inputs_r019c.py, test_culprit_keys.py run |
| R-020 / R-020b | tests/test_review_r020_dep_verdict.py, r020b | identical | yes |
| R-021 / R-021b | node/test/review-r021.test.js, r021b; harness/node_cache/test_review_r021_labels.py | identical | node files yes; labels file **no** (049) |
| R-022 / R-022b | jvm/test/run_review_r022.py, run_review_r022b.py + fixtures | identical | r022 yes; **r022b no** (050) |
| R-023 / R-023b | tests/test_review_r023.py, r023b.py | identical | yes |
| R-025 / R-025b | go/cmd/fenvix-go/review_r025*_test.go | r025 edited in the author's fix round, then identical to review-r025b | yes |
| R-032 / R-032b | tests/review_r032*/, node/test/review-r032*.test.js | identical (one tap case rewritten) | yes |

### 3.8 fenvix-app: R-012b on main (BRANCH-063..065)

`origin/claude/review-r012b:infra/github-app/test/review-r012b.test.ts` copied into a scratch worktree of
`origin/main` (worktree removed afterwards), `node --experimental-strip-types --test test/review-r012b.test.ts`:

```
not ok 1 - N1 the host reads a guest's result disk without following a symlink the jail's uid could plant
   error: root opens the jail-owned path with a shell redirect, following symlinks:
          result="$(runuser -u fenvix-parse -- python3 -I "$here/read-result.py" <"$jail/result.img")"
not ok 2 - N3 a jailed Firecracker (its own uid) cannot reach the parent's metadata service
not ok 1 - N2 the boundary is no wider than the execution policy for EC2 ...
   error: the boundary allows ec2:RunInstances of any instance type (RunnerMachines)
# pass 0   # fail 3
```

N1 and N3 are in `infra/customer-mode/spike/` (the customer-mode spike); N2 is `infra/github-app/permissions-boundary.json`,
part of the deployed stack.

### 3.9 Engine pin and runner contract (BRANCH-068..076)

```
fenvix-app main  infra/github-app/cdk.json:59   "engineCliCommit": "a20b93d7f840b23f71c73c03efdaee3d6a233252"
$ git merge-base --is-ancestor a20b93d7 origin/claude/release-1   -> not an ancestor
$ git branch -r --contains a20b93d7  -> all-runners, audit-reruns, node-cache-proof, review-r008d, review-r013(b),
                                        review-r021(b), review-r032, shared-cache          (release-1 is not in the list)
$ for b in <62 engine branches>: git ls-tree -r --name-only $b runner/ | grep warmup      -> nothing
$ git grep -n -E 'runner/(progress|results|explorations|summaries|warmups)' origin/main -- infra/github-app/lib infra/customer-mode scripts deploy
   -> only fenvix-summary-poster (/v1/runner/summaries), fenvix-warmup-* (/v1/runner/warmups), spike README/run-job.sh
$ git grep -l 'v1/runner/' origin/claude/release-1 (engine)        -> nothing
$ git grep -n install-image origin/main (fenvix-app)                -> 0 lines
fenvix-app main  src/data/ci.ts:382   pullCommand = (d) => `fenvix defects pull ${d.id}`      (no such command in the engine)
```

## 4. Not covered (for the session that finishes this)

Every engine branch and every fenvix-app branch has a verdict above, but these checks were **not done** or only done
at file-name level:

Engine
- `claude/l1-asyncio-study`, `claude/l1-threads-fix`, `claude/review-r007b`: not built or run; the entries rest on
  the file tree, the option tables and the release-1 run. Whether the branch code still works on today's Python is
  unknown.
- `claude/l2-browser-r2`, `claude/l2-browser-r3`, `claude/l2-browser-lockstep-ytoqnv`, `claude/review-r011`: only
  the tree, `detjs.js` usage, `docs/L2-BROWSER.md` head and test counts were read; nothing was run; the difference
  between r2, r3 and lockstep was not itemised (only that r2 and r3 are ancestors of lockstep).
- `claude/audit-reruns`, `claude/review-r013`, `claude/review-r013b`: feature and files identified; the branch
  itself was not built; the R-013b reviewer tests were not run anywhere.
- `claude/runner-node`: `fenvix-run` Node path read at header level only; `tests/test_runner_node.py` not run.
- Study branches `claude/loving-maxwell-58mv2w`, `claude/sweet-mendel-rtdg7f`, `claude/pricing-v2`,
  `claude/market-test` (= `claude/market-test-r010`), `claude/review-r010b`, `review-claude/market-test`: classified
  by top-level directories and by the absence of paths under `python/detpy`, `crates`, `node/src` among the
  branch-only files. Modified versions of files that exist on both sides were checked only through the option
  tables (3.3), not file by file. `tracks/l1-threads`, `tracks/l2-browser`, `tracks/cache-proof` on these branches
  were assumed to be earlier states of the L1, L2 and cache work, not verified.
- Branches with ahead=0 (`cache-proof-step1`, `exact-culprit`, `exact-culprit-n98yc2`, `jvm-l0`, `node-l0`,
  `parallel-proof`, `rust-hotpaths`, `rust-hotpaths-2`, `review-r017b`, `review-r019b`, `review-r020b`,
  `review-r022`, `review-r022b`, `review-r023`, `review-r025`, `review-r025b`): taken as merged from ancestry; I did
  not check whether a file they carried was later deleted or weakened on release-1, except `go/internal/skip`.
- `claude/parallel-proof-design`, `claude/review-r015`, `r015b`, `r017`, `r019`, `r019c`, `r020`, `r023b`, `r032b`:
  reviewer test files compared by blob; the review reports (FIX lists) were not read against release-1 finding by
  finding.
- `claude/gap-audit`: created during this audit, not analysed.
- Workflows: only presence, triggers and `schedule:` were compared. Whether `workflow_dispatch` of a file that is
  absent from the default branch can be started from the GitHub UI was not verified (it normally cannot).

fenvix-app
- `claude/customer-mode-pnap`, `claude/review-r014`, `claude/review-r014b`: file lists only; the branch was not
  built, its tests were not run, and the R-014/R-014b tests were not tried against main (the feature is absent there).
- `claude/review-r012` (`infra/github-app/test/review-r012.test.ts` differs from main by a `DEMO` helper),
  `claude/review-r016` (`github-app/tests/helpers/fake-github.ts` has 15 more lines on main), `claude/review-r016b`,
  `claude/review-r018`: tests are on main; I did not run them on main.
- The 12 current-product branches with ahead=0: taken as merged from ancestry.
- The 37 old-product branches: classified by README title, `control-plane/` and page names only.

## 5. Could not check

- **Reviewer tests outside the gate** (`harness/culprit/review_r019/`, `review_r019b/`, `review_r019c/`,
  `round2/`, `round4/`): I started them against the release-1 wheel (46 tests) and had to stop the run before it
  printed a result (budget stop; `hc.log` is empty). Whether they pass on release-1 is **UNKNOWN**. Command:
  `cd <copy of harness/culprit parent> && python -m pytest -q -p no:cacheprovider harness/culprit/review_r019c
  harness/culprit/review_r019 harness/culprit/review_r019b harness/culprit/round2 harness/culprit/round4`
  (detpy wheel installed, git present; over 15 minutes on a loaded 4-core machine).
- `harness/node_cache/test_review_r021_labels.py`, `jvm/test/run_review_r022b.py` and the other JVM runners outside
  the gate: not run.
- R-017 H2 (BRANCH-046): the test checks a report text. The behaviour behind it (under `--det`, repeated runs on a
  machine that is not fresh exhaust seeded temporary names and fail tests that plain pytest passes) was not
  reproduced on release-1.
- Whether the six start-up tests that fail when unskipped (3.2) describe wanted behaviour: needs a decision, not a
  measurement. I verified by hand only that two of them are not wrong reuses.
- BRANCH-022 (fenvix-run audit block: blobs and grep only, the branch's wrapper was not run), BRANCH-025 (audit never wired for detjs: from a commit message, marked DOC),
  BRANCH-062 (no real phoenixNAP host ever ran a job: brain LOG only, marked DOC).
- That the live AWS stack was built from fenvix-app main with `engineCliCommit` a20b93d7 (BRANCH-068): read from
  `cdk.json` on main; the deployed parameter value was not observable from here.

## 6. For the lead

1. **The Rust port dropped wired behaviour without dropping the files.** `remote_cache.py`, `cache_service.py`,
   `runner/fenvix-run --cache URL` and their tests are all on release-1, which makes the shared cache look present;
   the tests are switched off with a marker that says "not yet ported". The gate is green because 15 + 24 tests are
   skipped. Count skipped tests as a gate signal (the all-runners-2 gate commit b76b2f59 reports "1098 passed, 52 skipped" for the Python suite).
2. **The token leak (BRANCH-009) is real today** for anyone who sets `FENVIX_CACHE_TOKEN` and runs release-1: the
   client that removed it from the process is not called.
3. **Block 3 "closed" does not mean shipped.** DECISIONS records L1 threads closed on 2026-11-18; nothing of L1 is on
   release-1, and brain `ARCHITECTURE.md` still sends readers to a docs file that exists only on a study branch.
4. **Three closed pieces of the paid service have no counterpart on the other side**: audit reruns (engine branch
   never merged; app has the page), warm cache at install (app closed with reviewer PASS; the engine executor
   `runner/warmup.sh` was never written), defects/explorations/progress upload (app endpoints exist; no sender).
5. **The app would run a different engine than the one audited**: `engineCliCommit` a20b93d7 is the Python-lineage
   shared-cache commit, not release-1, and the image installs through `runner/bootstrap.sh` (Python only), not
   `release/install-image.sh`.
6. Reviewer tests were rewritten by author sessions in two places after the last review of them (R-009/R-009b by
   parallel-proof round 3; R-032 tap case by all-runners-2). Both look defensible; neither was re-reviewed.
7. Contradiction: `release-1.yml` header claims the python job runs "reviewer files R-019c ... culprit keys"; it
   runs `tests/` only, where ports of those cases live, not the reviewers' files.
8. Migration number 0014 is claimed by three different files across main, `claude/customer-mode-pnap` and the
   engine's `app.patch`.
