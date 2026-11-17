# Skip-with-proof study 2: where are the minutes?

**Status (2026-11-17 03:05 UTC): version 3, partial.**

* **Final:**
  * the R-002 code fixes: 3 proven errors and 6 notes, each with a test; 14 of 14 tests pass (MEASURED, `harness/skip_study2/tests/`);
  * setting 1 on the **v2 capture** (docusaurus, vue-core, terraform, prometheus, Home Assistant 12% sample);
  * the verdict on the two verification mismatches, now also re-checked on GitHub Actions: both flaky, 0 wrong;
  * setting 3 v1.
* **Pending: setting 1 on the v3 capture.** This is run `v3` (GitHub Actions run 44004047856). It has been queued behind the account's concurrency limit since 02:35 UTC, with 18 jobs of earlier runs queued ahead of it. Results are expected around 09:00-12:00 UTC (ESTIMATED: queue plus a 330-minute walk budget). The v3 column of the before/after table says "pending". When the bot has committed `results/v3/walk/`, run `python3 harness/skip_study2/aggregate.py --compare r1,r2,r3,r5,r6,r7,r8 v3` to fill it in.
* **Partial:**
  * saleor (v2 capture; shards 6-7 were restarted, so right now no commit has been reached by all 8 shards);
  * the reruns (41 attempts);
  * setting 2 agent PRs (**v2 capture**, 170 pushes; not re-walked with v3);
  * name rule v2 (10 of 14 libraries).

Every number is labelled. Raw data: `harness/skip_study2/results/<run>/`. Tables: `python3 harness/skip_study2/aggregate.py --md`.

## Headline: before / after the R-002 fixes

"v2" = the walks of version 2 (capture v2). "v3" = the same commits re-walked with the fixed capture (run v3).

* **Proof rule** = `closure`. In Go, `closure` = go test cache hit AND no runtime read changed AND (v3) no connection to a non-loopback address AND (v3) the same runtime and environment.
* The **go test cache alone is "no proof"**. It is shown separately and is never counted as proof.
* **Verified skips** = skips of that rule that were run anyway and compared with the cached outcome.

| setting | rule | v2: time skipped with proof, median / mean | v2: wrong hits (verified skips) | v3: time skipped, median / mean | v3: wrong hits (verified skips) | label |
|---|---|---:|---|---:|---|---|
| reference: first study, 14 small Python libraries | closure | 0% / 22% | 0 | - | - | MEASURED |
| 1. home-assistant (pytest, 50 commits, 12% sample) | closure | **98% / 85%** | 0 (2573) | pending (run v3) | pending | MEASURED / pending |
| 1. docusaurus (vitest, 50 commits) | closure | **98% / 81%** | 0 (829) | pending | pending | MEASURED / pending |
| 1. vue-core (vitest, 50 commits) | closure | 25% / 28% | 0 (371) | pending | pending | MEASURED / pending |
| 1. terraform (Go, 50 commits) | closure (proof; v3 adds the net guard) | **35% / 31%** | 0 (475) | pending; lower bound 22% / 20% | pending | MEASURED; bound ESTIMATED |
| 1. terraform | go test cache (**no proof**) | 72% / 61% | 0 (697) in the sample; **1 wrong found by the reviewer** (`internal/cloud`, network) | pending | pending | MEASURED |
| 1. prometheus (Go, 50 commits) | closure (proof; v3 adds the net guard) | **56% / 52%** | 0 (313) | pending; lower bound 41% / 37% | pending | MEASURED; bound ESTIMATED |
| 1. prometheus | go test cache (**no proof**) | 56% / 52% | 0 (313) | pending | pending | MEASURED |
| 1. saleor (pytest + Django, 10 commits, 15% sample) | closure | 0% / 9% | 0 (7) | not in run v3 | - | MEASURED, partial |
| 2. coding-agent PR pushes, 170 pushes pooled | closure | 52% / 51% | 0 (1408), 2 flaky | not re-walked (v2 capture); with the Go net guard at least 29% / 42% | - | MEASURED; bound ESTIMATED |
| 2. the same 170 pushes | go test cache for Go (**no proof**), closure otherwise | 76% / 53% | - | - | - | MEASURED |

**How to read the before/after:**

* **The v2 "0 wrong" was a sample result, not a proof.** The reviewer found:
  * 1 real wrong hit outside the sample: terraform `internal/cloud`, a cached PASS of a test that needs app.terraform.io (go test cache);
  * 1 wrong hit reproduced on a demo repository: a sqlite fixture opened read-write;
  * 3 docusaurus files that are latent wrong hits whenever `$HOME` differs between the recording and the reusing runner.

  The v3 capture closes all three (next section). The v3 verification count is what this delivery owes.
* **Lower bounds for Go** (ESTIMATED from v2 data):
  * The bound treats every package that made *any* `connect()`, loopback included, as never skippable. The v2 data cannot tell loopback from external connections; v3 records the address.
  * terraform: 14 of 125 packages connect, which forces 540 closure skips to rerun. prometheus: 30 of 90 packages connect, 1 310 skips (MEASURED, the same counts as the reviewer).
  * v3 will land between the bound and the v2 value.
  * On github-mcp-server (agent PRs) the bound is very loose: 47% -> 18% median. Most of its connections are probably `httptest` servers on loopback (ESTIMATED).
* **Python and Node** (ESTIMATED, until v3 lands):
  * The v3 key adds environment variables read, runtime identity, read-write fixtures and cached failures.
  * In a single runner image the variables and the runtime do not change between commits, so the share should move little.
  * Cached failures: their effect on the v2 data is MEASURED (aggregator toggle `S2_V2_NO_FAILURE_RULE`):
    * setting 1: no change in any median or mean;
    * Home Assistant Copilot PRs: 100% / 95% -> 97% / 93%;
    * the setting 2 pooled 52% / 51%: unchanged.

## R-002 fixes (each with its test)

Code: `strace_deps.py`, `pyhooks/sitecustomize.py`, `nodehooks/envrec.cjs`, `walk.py` and `aggregate.py`, in commits 39d89da, 43359a2, dfbf300 and 9c73d3a. Tests: `tests/test_r002_capture.py` (the reviewer's 2 tests, unchanged) and `tests/test_r002_fixes.py`. Run them with `python3 -m pytest -q harness/skip_study2/tests/`: **14 passed** (MEASURED, 2026-11-17 02:50 UTC, this container).

| # | review item | fix | test(s) | status |
|---|---|---|---|---|
| E1 | read-write opens dropped from the dependencies (sqlite fixture) | An open of an existing file with `O_RDWR` / `O_APPEND` is a read. The dependency is the file's **committed** content, even if the test rewrites it. `O_TRUNC`, `O_CREAT\|O_EXCL` and files that did not exist are outputs, not dependencies. | `test_r002_capture::test_sqlite_fixture_change_is_a_dependency` (reviewer); `test_parse_rdwr_is_read_but_trunc_and_new_are_not`; `test_rdwr_dependency_is_the_committed_content` | fixed, pass |
| E2 | environment variables not captured | Python hook: `os.environ` / `os.getenv` / `os.environb` reads, recorded by name. Enumerating the whole environment records `*`; a stdlib proxy lookup records `~proxy`. Node hook: `process.env` reads. Go: variables in go's test log, plus a fixed set per language (PATH, TZ, LANG, LANGUAGE, LC_\*, and PYTHON\* / NODE\_\* / UV\_\*). The key holds the value hash of each. | `test_r002_capture::test_environment_variable_is_a_dependency` (reviewer); `test_unread_environment_variable_does_not_invalidate`; `test_whole_environment_enumeration_is_a_dependency`; `test_docusaurus_home_case_reruns_when_home_changes` (the real docusaurus `$HOME` case) | fixed, pass |
| E3 | Go: no network guard | A Go package whose last run connected to a non-loopback address is never a `closure` skip (reason `network`). This is the same rule as pytest / vitest. The go test cache alone keeps no guard and is labelled "no proof". | `test_local_address_classification`; `test_go_package_with_external_connect_is_never_skipped` | fixed, pass |
| N1 | Go "go-cache" labelled as proof | The aggregator prints "go test cache (no proof)", and the headline uses Go `closure`. | aggregator tables (label) | fixed |
| N2 | the interpreter, stdlib and shared libraries were not in the key | The key now holds a **runtime identity**: interpreter path, version and binary; the stdlib tree; libpython; the Node binary; the Go version and GOROOT; tzdata; the shared libraries the interpreter / Node link; libssl and libcrypto. | `test_interpreter_change_invalidates`; `test_runtime_identity_covers_node_binary_and_tzdata` | fixed, pass |
| N3 | verification covered only `closure` skips | Every extra skip of `func+guard`, `func` and `~cfg` beyond `closure` is now run and compared in full (`xverify`). Walks without it, which means every v2 walk, print **n/a** for those rows. | `test_extra_skips_of_func_rules_are_verified` | fixed, pass |
| N4 | cached failures reused without verification | A unit whose last outcome was a failure always reruns. v2 data is approximated: every unit that ever failed reruns at every transition. | `test_cached_failure_is_never_reused` | fixed, pass |
| N5 | the aggregator override was too permissive | The verdicts accepted as "flaky" are an explicit allow-list (`aggregate.FLAKY_VERDICTS`). Anything else stays a wrong hit. | `test_recheck_verdicts_allow_list` | fixed, pass |
| N6 | `kind_of` labelled node_modules as `env` | Paths are now classed `installed` (venv, node_modules) or `system`. The v2 docusaurus "read:env 1" is a node_modules file changed after a `package.json` bump, **not** an environment variable. | none (label only) | fixed in v3 walks |
| N7 | the GitHub Actions re-check was still queued | It ran (run 43990865851): `results/s1/recheck/home-assistant-{0,1}.json`. See the next section. | - | done |
| N8 | Home Assistant 12% sample on agent PRs leaves out the PR's own integration tests | **Not fixed**: agent PRs were not re-walked. The HA Copilot 97% median is an upper bound. | - | open |
| N9 | `.git/` reads excluded; wall-clock not a dependency | Documented in the method (below). Wall-clock is covered only under `detpy --det` (virtual clock), not by this capture. | - | documented |

## The two verification mismatches: verdict (updated with the GitHub Actions re-check)

In both cases a skipped unit's cached outcome was a **failure**, recorded at the PR's base commit, and the fresh run at a later push passed.

There are two re-checks:
* **Local** (4 vCPU, Python 3.14.6): `results/s1/recheck/*-local.json`.
* **GitHub Actions** (`recheck.py`, run 43990865851): 3 plain runs, 1 traced run alone and 4 traced runs at once, at each commit.

| unit (PR) | local: plain failed at base / PR commit | local: traced failed | GitHub Actions: plain failed at base / PR commit | GitHub Actions: traced alone / traced 4 at once failed, at base; at PR commit | verdict |
|---|---|---|---|---|---|
| `tests/components/switchbot/test_init.py` (171334) | 2 / 20; 2 / 30 | not needed | 0 / 3; 0 / 3 | 0 / 1, 2 / 4; 0 / 1, 0 / 4 | **flaky** (teardown race; `not-reproducible (load-sensitive)`) (MEASURED) |
| `tests/components/knx/test_number.py` (163164) | 0 / 20; 0 / 20 | base 6 / 8, PR 6 / 8 | 0 / 3; **2 / 3** | 1 / 1, 0 / 4; 1 / 1, 3 / 4 | **flaky** (`flaky (plain runs disagree)`) (MEASURED) |

* **knx is not only capture-induced.** On a GitHub runner it also fails in plain runs: 2 of 3 at the PR commit (MEASURED). Locally it never failed plainly in 40 runs. It is a timing race, which strace makes more likely.
* **Result:**
  * no dependency was missed;
  * both verdicts are on the allow-list;
  * the v2 verification count stays **0 wrong, 2 flaky**.
* **Product rules that follow** (both are in the v3 walker):
  1. a cached failure is never reused;
  2. a failure observed under dependency capture is confirmed by a plain rerun before it is recorded.

## 0. Question and answer

The first study (`docs/CACHE-SKIP-STUDY.md`) asked how much test time per commit can be skipped **with proof**. On 14 small Python libraries over 50 commits the answer was a median 0% / mean 22%. This study asks where the skippable minutes are.

**Answer: in large repositories made of many loosely coupled parts, and in the pushes of coding agents.**
* Home Assistant and Docusaurus: 98% median each (MEASURED, v2 capture; v3 pending).
* Tightly coupled code skips little, even when it is large (MEASURED):
  * vue-core: 25%;
  * saleor: 0% (Django loads every app in every test process).
* **Go**, with proof (`closure`): terraform 35%, prometheus 56% median (MEASURED, v2).
  * The v3 network guard will lower both, to no less than 22% and 41% (ESTIMATED).
  * The go test cache alone skips more (terraform 72%), but it is **not a proof**: the reviewer found a wrong hit in it.
* Coding-agent PRs: a median 52% / mean 51% of test time per push (MEASURED, 170 pushes, v2 capture, partial).

## 1. Method (corrected in version 3)

**Harness:**
* `walk.py`: Python, TypeScript and Go walks;
* `strace_deps.py`, `pyhooks/` and `nodehooks/`: dependency capture;
* `flaky.py`: reruns;
* `recheck.py`: mismatch re-check;
* `finer/`: setting 3;
* `agent_walk.py`: setting 2;
* `aggregate.py`: tables.

Everything runs on GitHub Actions `ubuntu-latest` (4 vCPU), workflow `.github/workflows/skip-study2.yml`.

**Basics:**
* **Unit** = one test file run in its own process (pytest, vitest), or one Go package.
* **Commits** = consecutive first-parent commits of the default branch; 50 transitions per repository unless stated. At every commit the walker:
  * checks out;
  * reinstalls when a dependency spec changed;
  * builds;
  * decides per unit;
  * really runs every unit it cannot skip.

**What IS a dependency of a unit under `closure` (capture v3).** A unit reuses its last result only if none of these changed:
* every file under the capture roots that it opened for reading. The roots are the repository, the virtualenv or node_modules, and spec roots. Since v3 this includes files opened **read-write** (`O_RDWR`, `O_APPEND`), keyed by their committed content;
* every path it found missing (has it been created since?), every path it `stat`ed, and every directory it listed after the test file was opened;
* every module name it looked up (Python import hooks), and new pytest plugin entry points;
* **(v3)** every environment variable it read, by value hash:
  * Python: `os.environ` / `getenv` reads; enumerating the whole environment counts as reading all of it;
  * Node: `process.env` reads;
  * Go: variables in go's test log;
  * plus a fixed set per language: PATH, TZ, LANG, LANGUAGE, LC_\*, and PYTHON\* / NODE\_\* / UV\_\*;
* **(v3)** the runtime identity: the interpreter or Node binary and version, the stdlib tree, libpython, the Go toolchain, tzdata, the linked shared libraries, libssl and libcrypto;
* a unit that connected to a **non-loopback address** is never skipped. This held in v2 for pytest and vitest; **v3 extends it to Go**;
* a unit whose last outcome was a **failure** is never reused (v3).

**What is NOT a dependency (known limits, stated for the product):**
* **Wall-clock time.** A test that starts failing on a date (a certificate expiry, a year boundary) is reused as a pass. This capture does not cover it. Only `detpy --det` (virtual clock) does.
* Reads under `.git/`, `.pytest_cache`, `.mypy_cache`, `.hypothesis` and the Vite cache (`SKIP_PARTS`).
* Files outside the capture roots and outside the runtime identity, for example `/etc/hosts`, CA bundles other than libssl/libcrypto, and locale files.
* Environment variables read from C code (`getenv` inside an extension module) and not through `os.environ`.
* Services reached on loopback (a database in a container), except where a spec lists `db_inputs`.
* Randomness and thread timing. Flakiness is handled by verification and reruns, not by the key.

**Rules:**
* **`strict`** = `closure` plus the first study's config rule: any lockfile, config or CI file change reruns everything.
* **Python only:**
  * `func+guard`: a proof at the Python level;
  * `~cfg`: near-proof;
  * `func`: **coverage-only, NOT a proof**.
  * The extra skips of these three rules are verified in full from v3 on. In every v2 walk they show **n/a**.
* **Go:**
  * `go test cache (no proof)` = the go command's own test cache persisted across commits, i.e. a remote cache restored into a cold CI.
  * Go `closure` (proof) = a go test cache hit AND no runtime read changed (strace) AND the same runtime and environment AND no external connection.
  * A go-cache hit whose runtime reads changed is a *potential* wrong hit and is always verified.

**Verification:**
* At every commit a random sample of the `closure` skips runs anyway. The sample is Bernoulli 8-15% per spec, the same for every unit. On Go it also includes every potential wrong hit.
* A **wrong hit** is a fresh outcome that:
  * differs from the cached one;
  * reproduces on 2 more fresh runs;
  * and whose cached outcome reproduces at its own commit.

  Otherwise it counts as **flaky**: an allow-listed re-check verdict, or a fresh outcome that does not reproduce.

**Shares and time to green:**
* **Shares** per commit:
  * skipped unit time / total unit time. Unit time = the test durations, or the unit wall time minus the fixed process start-up, whichever is larger;
  * skipped tests / total tests;
  * then median and mean over commits.
* **Time to green** (ESTIMATED from MEASURED unit costs): a longest-first schedule on the project's CI worker count. "After" includes the MEASURED capture overhead on every unit that runs; the value without it is in brackets.
* **Samples:**
  * Home Assistant: 12% of the test files (776 units, 11 889 tests);
  * saleor: 15% of the test files;
  * both use fixed-seed per-file samples, run as 4 / 8 parallel shards.

## 2. Setting 1: large repositories (v2 capture; v3 pending)

Skip shares are MEASURED on the stated sample. Time to green is ESTIMATED. The saleor rows come from report version 2: at the moment no commit has been reached by all 8 shards, because shards 6-7 were restarted.

| project | lang | transitions | units (sample) | rule | time skipped median / mean | tests skipped median / mean | time to green before -> after (after without capture overhead), median / mean | invalidate all (why) | verified skips (wrong, flaky) |
|---|---|---:|---|---|---:|---:|---|---|---|
| docusaurus | vitest | 50 | 202 (100%) | closure | 98% / 81% | 100% / 81% | 30s -> 3s (2s) / 30s -> 10s (6s) | 7/50 (read:config 6, read:env 1) | 829 (0, 0) |
| docusaurus | vitest | 50 | 202 (100%) | strict | 97% / 60% | 98% / 61% | 30s -> 4s (2s) / 30s -> 19s (13s) | 7/50 (read:config 6, read:env 1) | 829 (0, 0) |
| home-assistant | pytest | 50 | 776 (12%) | closure | 98% / 85% | 98% / 85% | 417s -> 35s (16s) / 417s -> 142s (67s) | 0/50 (-) | 2573 (0, 0) |
| home-assistant | pytest | 50 | 776 (12%) | func+guard | 98% / 85% | 98% / 85% | 417s -> 35s (16s) / 417s -> 142s (66s) | 0/50 (-) | n/a |
| home-assistant | pytest | 50 | 776 (12%) | func | 98% / 89% | 98% / 90% | 417s -> 35s (16s) / 417s -> 107s (50s) | 0/50 (-) | n/a |
| home-assistant | pytest | 50 | 776 (12%) | strict | 97% / 67% | 97% / 67% | 417s -> 35s (16s) / 417s -> 299s (140s) | 0/50 (-) | 2573 (0, 0) |
| prometheus | go | 50 | 90 (100%) | go test cache (no proof) | 56% / 52% | 84% / 73% | 135s -> 118s (118s) / 135s -> 118s (118s) | 0/50 (-) | 313 (0, 0) |
| prometheus | go | 50 | 90 (100%) | closure | 56% / 52% | 84% / 73% | 135s -> 118s (118s) / 135s -> 118s (118s) | 0/50 (-) | 313 (0, 0) |
| prometheus | go | 50 | 90 (100%) | strict | 52% / 48% | 82% / 67% | 135s -> 118s (118s) / 135s -> 119s (119s) | 0/50 (-) | 313 (0, 0) |
| terraform | go | 50 | 125 (100%) | go test cache (no proof) | 72% / 61% | 80% / 73% | 95s -> 48s (48s) / 95s -> 68s (68s) | 0/50 (-) | 697 (0, 0) |
| terraform | go | 50 | 125 (100%) | closure | 35% / 31% | 79% / 72% | 95s -> 95s (95s) / 95s -> 95s (95s) | 0/50 (-) | 475 (0, 0) |
| terraform | go | 50 | 125 (100%) | strict | 66% / 57% | 78% / 69% | 95s -> 48s (48s) / 95s -> 70s (70s) | 0/50 (-) | 697 (0, 0) |
| vue-core | vitest | 50 | 185 (100%) | closure | 25% / 28% | 46% / 39% | 31s -> 37s (24s) / 32s -> 35s (23s) | 15/50 (read:config 10, read:source 5) | 371 (0, 0) |
| vue-core | vitest | 50 | 185 (100%) | strict | 25% / 26% | 46% / 37% | 31s -> 37s (24s) / 32s -> 36s (23s) | 15/50 (read:config 10, read:source 5) | 371 (0, 0) |
| saleor | pytest | 10 | 112 (15%) | closure | 0% / 9% | 0% / 8% | 289s -> 819s (289s) / 289s -> 746s (263s) | 9/10 (listing:data 4, py-source:source 4, read:config 1) | 7 (0, 0) (v2 report, 01:55 UTC) |
| saleor | pytest | 10 | 112 (15%) | func+guard | 0% / 16% | 0% / 16% | 289s -> 819s (289s) / 289s -> 687s (243s) | 9/10 (listing:data 4, py-source:source 4, read:config 1) | n/a |
| saleor | pytest | 10 | 112 (15%) | func | 32% / 38% | 37% / 40% | 289s -> 559s (197s) / 289s -> 506s (179s) | 9/10 (listing:data 4, py-source:source 4, read:config 1) | n/a |
| saleor | pytest | 10 | 112 (15%) | strict | 0% / 9% | 0% / 8% | 289s -> 819s (289s) / 289s -> 746s (263s) | 9/10 (listing:data 4, py-source:source 4, read:config 1) | 7 (0, 0) (v2 report, 01:55 UTC) |

**Observations** (MEASURED, v2 capture):

* **Home Assistant** (50 commits):
  * 35 of 50 commits let at least 90% of test time be skipped, and no commit forced everything. The repository holds about a thousand integrations, each tested by loading the core plus one integration, and most commits touch one integration.
  * The coverage-only rule adds 4 points of mean (`func` 89% vs `closure` 85%), but its extra skips were not verified (n/a).
  * The config rule costs 18 points of mean.
* **Docusaurus:**
  * 39 of 50 commits skip at least 90%.
  * 7 of 50 invalidate everything. In 6 of them a configuration file every test reads changed. In 1 a **node_modules file** changed after a `package.json` bump. Version 2 labelled that commit "env"; it was not an environment variable.
* **vue-core:**
  * A compact core is read by nearly every test file, and 15 of 50 commits invalidate everything.
  * Time to green does not improve: the capture overhead (x1.55) eats the saving.
* **Go:**
  * With proof (`closure`), terraform skips 35% / 31% and prometheus 56% / 52%.
  * The go test cache alone (no proof) skips terraform 72% / 61%. On terraform, 222 of its verified hits were *potential* wrong hits: a file the test read changed, and the go key did not include it. All 222 reproduced the cached outcome.
  * The go cache was wrong at least once outside the verification sample: terraform `internal/cloud` (reviewer, MEASURED). Hence "no proof".
  * Terraform's time to green is set by one long package that most commits invalidate.
* **saleor** (10 commits, partial): 9 of 10 commits invalidate everything, because Django loads the whole project in every test process. Even coverage-only `func` skips only 32% / 38%.

## 3. Setting 2: commits inside pull requests opened by coding agents (v2 capture; not re-walked)

Each push of an agent PR is a transition from the previous push. At the PR's base commit every unit runs first. Home Assistant is walked on its 12% sample, Go packages in full (MEASURED, snapshot 03:00 UTC):

| repository : agent | PRs | pushes | rule | time skipped per push median / mean | verified (wrong, flaky) |
|---|---:|---:|---|---:|---|
| github-mcp-server:copilot | 15 | 101 | go test cache (no proof) | 68% / 52% | 287 (0, 0) |
| github-mcp-server:copilot | 15 | 101 | closure | 47% / 49% | 283 (0, 0) |
| github-mcp-server:copilot | 15 | 101 | strict | 14% / 43% | 287 (0, 0) |
| home-assistant:codex | 8 | 20 | closure | 98% / 55% | 476 (0, 0) |
| home-assistant:codex | 8 | 20 | func+guard | 98% / 55% | n/a |
| home-assistant:codex | 8 | 20 | func | 98% / 55% | n/a |
| home-assistant:codex | 8 | 20 | strict | 49% / 50% | 476 (0, 0) |
| home-assistant:copilot | 3 | 12 | closure | 97% / 93% | 407 (0, 2) |
| home-assistant:copilot | 3 | 12 | func+guard | 97% / 93% | n/a |
| home-assistant:copilot | 3 | 12 | func | 98% / 98% | n/a |
| home-assistant:copilot | 3 | 12 | strict | 97% / 93% | 407 (0, 2) |
| typescript-go:copilot | 5 | 37 | go test cache (no proof) | 28% / 42% | 242 (0, 0) |
| typescript-go:copilot | 5 | 37 | closure | 28% / 42% | 242 (0, 0) |
| typescript-go:copilot | 5 | 37 | strict | 28% / 42% | 242 (0, 0) |

* **Pooled over the 170 pushes** (MEASURED):
  * `closure`: median 52% / mean 51%;
  * with the go test cache (no proof) for the Go repositories: 76% / 53%;
  * with a net guard on every connecting Go package: at least 29% / 42% (ESTIMATED lower bound).

  The distribution has two humps: a push either touches something every test reads or almost nothing.
* **Home Assistant:**
  * The Copilot PRs are small single-integration fixes: 97% median.
  * The Codex PRs (8 PRs): 98% median, but a 55% mean.
  * Both are upper bounds. The 12% sample mostly leaves out the PR's own integration tests (R-002 note N8, open).
* The 2 flaky verifications are the two mismatches above.
* Still running or not yet counted:
  * Codex on openai-agents-python (0 pushes walked so far);
  * Claude Code on Home Assistant;
  * more Copilot on typescript-go.

## 4. Setting 3: finer proof rule (module-level names actually read) (unchanged from version 2; not affected by R-002)

Rule `line+names` (`finer/names.py`): a module-level change no longer reruns every test that loaded the
module; the change is reduced to the names whose value changed, propagated through module-level code, and
a test reruns only if code it executed refers to one of those names (side-effecting module-level changes
stay "hard" and rerun every loader). Same 50 commits per library as the first study, same capture.

Time skipped per commit, median / mean in percent (MEASURED; 13 of 14 libraries, more-itertools still
running; "config (strict)" = commits touching a strict-config file):

| library | transitions | config (strict) | strict/closure | relaxed/closure | strict/file+guard | strict/line+guard | strict/line+names | strict/line (coverage-only) | relaxed/line+guard | relaxed/line+names | relaxed/line (coverage-only) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| arrow | 50 | 19 | 0/10 | 0/36 | 0/11 | 0/12 | 0/12 | 49/52 | 0/42 | 0/42 | 100/82 |
| attrs | 50 | 25 | 0/25 | 95/68 | 0/26 | 0/28 | 0/28 | 0/41 | 95/72 | 95/72 | 95/85 |
| boltons | 50 | 4 | 0/6 | 0/11 | 74/43 | 74/43 | 78/50 | 80/71 | 78/47 | 79/54 | 80/76 |
| click | 50 | 11 | 0/10 | 0/19 | 0/15 | 0/17 | 0/17 | 64/47 | 0/26 | 0/26 | 66/59 |
| flask | 46 | 13 | 0/27 | 0/44 | 0/31 | 0/31 | 0/33 | 96/64 | 89/52 | 95/54 | 97/88 |
| isort | 50 | 8 | 0/8 | 0/19 | 11/17 | 19/26 | 19/26 | 32/31 | 37/38 | 37/38 | 46/42 |
| jinja | 50 | 34 | 0/22 | 98/67 | 0/22 | 0/22 | 0/22 | 0/30 | 98/69 | 98/69 | 98/82 |
| marshmallow | 50 | 28 | 0/28 | 100/80 | 0/29 | 0/34 | 0/32 | 0/39 | 100/86 | 100/84 | 100/93 |
| pygments | 50 | 0 | 0/12 | 0/12 | 0/21 | 0/23 | 0/21 | 86/88 **1 wrong** | 0/23 | 0/21 | 86/88 **1 wrong** |
| sqlparse | 50 | 7 | 0/22 | 0/26 | 0/27 | 0/32 | 49/47 | 87/57 | 0/36 | 74/51 | 88/63 |
| structlog | 50 | 20 | 0/24 | 58/50 | 0/26 | 0/26 | 0/26 | 47/34 | 58/52 | 58/52 | 58/60 |
| toolz | 44 | 21 | 0/4 | 3/7 | 0/5 | 0/5 | 0/5 | 3/10 | 4/8 | 4/8 | 4/14 |
| werkzeug | 50 | 11 | 0/1 | 0/3 | 0/1 | 0/1 | 0/1 | 30/22 | 0/4 | 0/4 | 31/28 |
| **median of medians / mean of means** | | | 0/15 | 0/34 | 0/21 | 0/23 | **0/25** | 47/45 | 37/43 | 58/44 | 86/66 |

* **Gap recovered** (MEASURED, strict config rule, mean of means): proof `file+guard` 21%, coverage-only
  `line` 45%, a 24-point gap; `line+names` reaches 25%: it recovers **4 of 24 points (about 17%)**, 2 of
  them over `line+guard` (23%). Under the relaxed config rule: `line+guard` 43%, `line+names` 44%,
  coverage-only 66%: 1 of 23 points. Medians stay 0% under the strict rule.
* **pygments 7c196150 caught** (MEASURED): coverage-only `line` and `file` skip 2853 tests on that commit
  and get one wrong (`tests/examplefiles/fstar/example.fst`, whose expected output depends on a changed
  module-level table read through `tests/conftest.py`); `line+names` reruns them (0 skipped, 0 wrong). No
  variant with a guard or with the name rule had a wrong outcome on any library.
* **Where the gap is**: mostly not Python-level imprecision. It is (a) config commits (compare the
  strict and relaxed columns on attrs, jinja, marshmallow, structlog), and (b) small libraries where most
  commits edit the module every test reads, so the changed names are really read. A v2 of the name rule
  (signature changes act only on callers, dunders only on users of the class, guarded imports as
  bindings) is running (run r7). On the 6 libraries finished so far (arrow, attrs, boltons, click, flask,
  jinja) v2 gives the same `strict/line+names` medians/means as v1 except attrs (28% -> 24% mean: v2 is more
  conservative there) (MEASURED); the table above stays v1 until v2 finishes on all 14.
* toolz: 94% of its test time (MEASURED) is in tests absent from the first study's determinism table
  (`harness/results/mixed/toolz.csv`), which every variant must rerun; by count `line` skips a median 64%.
  This rerun therefore under-states toolz for every rule alike (first study: `line` 59% / 48%); the
  comparison between rules on the same library is unaffected.

## 5. Setting 4: time to green and reruns

**Time to green per commit** (ESTIMATED: longest-first schedule of MEASURED unit costs on the project's CI
workers; "after" with the MEASURED capture overhead on every unit that runs, in brackets without it):

| project | rule | before | after, median | after, mean |
|---|---|---:|---:|---:|
| home-assistant (12% sample on 12% of the workers) | closure | 417 s | 35 s (16 s) | 142 s (67 s) |
| docusaurus | closure | 30 s | 3 s (2 s) | 10 s (6 s) |
| vue-core | closure | 31 s | 37 s (24 s) | 35 s (23 s) |
| terraform | closure (proof) | 95 s | 95 s | 95 s |
| terraform | go test cache (no proof) | 95 s | 48 s | 68 s |
| prometheus | closure (proof) | 135 s | 118 s | 118 s |
| prometheus | go test cache (no proof) | 135 s | 118 s | 118 s |
| saleor (15% sample) | closure | 289 s | 819 s (289 s) | 746 s (263 s) |

Where most units are skipped (Home Assistant, docusaurus) time to green falls 10x at the median. Where
one long unit is usually invalidated (prometheus, terraform's longest package) or nothing is skippable
(saleor), it barely moves, and the capture overhead (x1.55 vitest, x2.8 saleor, MEASURED) makes it worse
unless capture runs only on a sample of runs.


**Reruns.** The project's own CI test step is rerun at one fixed commit on fresh GitHub runners. An attempt "fails from flakiness" when it fails a test that does not fail in every attempt of that group (MEASURED):

| suite (commit) | CI groups rerun (of) | tests per group run | attempts (min per group) | attempts failed by flakiness | tests failing in every attempt | flaky full-run rate | mean job min | flaky tests |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| docusaurus (4c4ec4aa) | 1 (1) | 3254 | 10 (10) | 0 | 0 | 0% | 1.5 | - |
| terraform (b3fb138b) | 1 (1) | 12462 | 5 (5) | 0 | 14 | 0% | 5.6 | - |
| vue-core (cbd95955) | 1 (1) | 4152 | 10 (10) | 0 | 0 | 0% | 0.7 | - |
| home-assistant (cdf3f923) | 3 (10) | 11026 | 16 (5) | 0 | 0 | 0% | 8.8 | - |

* **0 flaky failures in 41 valid attempts so far** (MEASURED):
  * vue-core: 10 full runs;
  * docusaurus: 10 full runs;
  * terraform: 5 full runs;
  * Home Assistant: 16 runs of 3 of its 10 CI groups.
* **terraform fails the same 14 tests in every run** (MEASURED). These are environment defects (for example, a lockfile test run as root), not flakiness.
* Still to run: terraform repetitions 5-9 (queued), and more Home Assistant group runs. The prometheus and saleor reruns were cancelled.

## 6. Caveats

* **Sampling.** Home Assistant and saleor use a 12% / 15% fixed sample of test files, so the shares are per sample. On agent PRs the HA sample leaves out the PR's own integration tests (open note N8).
* **Time to green** is a schedule simulation from one measured run per unit, not a measured CI wall time.
* **Statistical power.** 0 wrong in 5 976 verified `closure` skips puts the per-skip error rate below about 0.05% (95% upper bound, ESTIMATED as 3 / n). That bound holds for these repositories, in one runner environment, under the v2 capture. Those 5 976 are: setting 1 = 2573 + 829 + 371 + 475 + 313 + 7, plus setting 2 = 1408 (MEASURED).
* **What the bound does not cover.** The holes the reviewer proved only fire when one of these changes:
  * a read-write fixture;
  * an environment variable;
  * the runtime;
  * an external service.

  The v3 key closes these holes, but v3 has **not yet been measured** (run v3 pending).
* **Wall-clock is not a dependency** of this capture (only `detpy --det` covers it). A shared cache that runs for a long time will reuse passes of date-dependent tests.
* **Agent PRs** are on the v2 capture. 101 of the 170 pushes come from github-mcp-server, so the pooled numbers lean on it.
