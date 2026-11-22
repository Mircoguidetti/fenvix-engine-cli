# Serial-suite scan: do public suites run on one worker on purpose?

Scan date 2026-11-22. All repositories are public; each row of `scan.jsonl` is pinned to the
default-branch commit read that day. This report names repositories, never people.

## Answer

Of the public suites in this sample that run serially on a multi-core GitHub-hosted runner,
**<!--multi_core.stated.breakage-->43 of <!--serial_on_multi_core_runner-->256 (16.8%)** say,
in their own words, that they do so to keep their tests from breaking (shared database, port,
file or fixture; races; flakes). In the unbiased half of the sample (repositories reached only by
flag-alone searches) it is **<!--arm.flag_only.multi_core.stated.breakage-->27 of
<!--arm.flag_only.multi_core-->213 (12.7%)**. That share is small. Most serial flags carry no
reason at all: <!--multi_core.none-->189 of the 256 multi-core serial suites say nothing.

The small number is the finding. Two qualifications, both measured below:

* When a reason is written down, it is almost always breakage: <!--serial.stated.breakage-->70
  of <!--serial.stated-->83 stated reasons, against <!--serial.stated.resource-->8 resource
  (memory/CPU/startup cost) and <!--serial.stated.other-->5 other (output readability,
  crash diagnosis, a deliberate serial canary).
* Silence is not evidence of inertia. Of <!--file_kind.package.json.serial-->72 serial flags in
  `package.json`, a file that cannot hold comments, <!--file_kind.package.json.stated-->1 states
  a reason. Where a comment is possible next to the flag (test config files),
  <!--file_kind.test_config.stated-->56 of <!--file_kind.test_config.serial-->147 state one.
  Read 12.7-16.8% as a floor on deliberate serialisation, not as an estimate of it.

## The three counts (all MEASURED)

| count | value | command |
|---|---|---|
| repositories examined | <!--repositories_examined-->834 | `jq -s 'length' harness/serial_scan/scan.jsonl` |
| repositories running serially | <!--repositories_running_serially-->426 | `jq -s 'map(select(.running_serially))\|length' harness/serial_scan/scan.jsonl` |
| of those: stated / implied / none | <!--serial.stated-->83 / <!--serial.implied-->20 / <!--serial.none-->323 | `jq -s -c 'map(select(.running_serially))\|group_by(.reason_kind)\|map({(.[0].reason_kind):length})\|add' harness/serial_scan/scan.jsonl` |
| serial on a multi-core runner | <!--serial_on_multi_core_runner-->256 (stated <!--multi_core.stated-->55, implied <!--multi_core.implied-->12, none <!--multi_core.none-->189) | `jq -s -c 'map(select(.multi_core_runner))\|group_by(.reason_kind)\|map({(.[0].reason_kind):length})\|add' harness/serial_scan/scan.jsonl` |
| of those, stated reason = breakage | <!--multi_core.stated.breakage-->43 | `jq -s 'map(select(.multi_core_runner and .reason_kind=="stated" and .reason_category=="breakage"))\|length' harness/serial_scan/scan.jsonl` |

`python3 harness/serial_scan/verify_scan.py` re-derives every number in this file, including
those in the prose (each is tagged), from `scan.jsonl` and `raw/search_log.jsonl`. It exits
non-zero on any mismatch. `verify_scan.py --print` prints the full block at the end.

## Two arms: flag alone vs flag + reason word

The search used both kinds of query (section 4 of the brief). Queries that pair the flag with a
reason word (`runInBand database`, `singleFork flaky`, ...) over-sample suites that explain
themselves, so the arms are reported apart. The flag-alone arm is the one to quote.

| arm | examined | serial | stated / implied / none | multi-core | multi-core stated (breakage) |
|---|---|---|---|---|---|
| flag alone | <!--arm.flag_only.examined-->486 | <!--arm.flag_only.serial-->343 | <!--arm.flag_only.serial.stated-->53 / <!--arm.flag_only.serial.implied-->11 / <!--arm.flag_only.serial.none-->279 | <!--arm.flag_only.multi_core-->213 | <!--arm.flag_only.multi_core.stated-->39 (<!--arm.flag_only.multi_core.stated.breakage-->27) |
| flag + reason word | <!--arm.flag_word.examined-->348 | <!--arm.flag_word.serial-->83 | <!--arm.flag_word.serial.stated-->30 / <!--arm.flag_word.serial.implied-->9 / <!--arm.flag_word.serial.none-->44 | <!--arm.flag_word.multi_core-->43 | <!--arm.flag_word.multi_core.stated-->16 (<!--arm.flag_word.multi_core.stated.breakage-->16) |

A repository reached by any flag+word query counts in the second arm.

GitHub's own `total_count` for each query is in the block below as `search[...]`. Those numbers
are DECLARED by GitHub, not measured here, and **they cannot answer the question**. Legacy code
search matches the words anywhere in a file and returns an estimated count, so
`runInBand port` (375808 files) reports more than `"--runInBand" filename:package.json`
(325120). The only usable fraction is the one measured on the sample above.

## By runner (a count from one runner is a count about that runner)

| runner | examined | serial | stated | implied | none | multi-core | multi-core stated breakage |
|---|---|---|---|---|---|---|---|
| Vitest | <!--runner.vitest.examined-->164 | <!--runner.vitest.serial-->102 | <!--runner.vitest.stated-->38 | <!--runner.vitest.implied-->5 | <!--runner.vitest.none-->59 | <!--runner.vitest.multi_core-->69 | <!--runner.vitest.multi_core.stated.breakage-->27 |
| Jest | <!--runner.jest.examined-->202 | <!--runner.jest.serial-->45 | <!--runner.jest.stated-->3 | <!--runner.jest.implied-->0 | <!--runner.jest.none-->42 | <!--runner.jest.multi_core-->30 | <!--runner.jest.multi_core.stated.breakage-->1 |
| pytest | <!--runner.pytest.examined-->110 | <!--runner.pytest.serial-->66 | <!--runner.pytest.stated-->9 | <!--runner.pytest.implied-->4 | <!--runner.pytest.none-->53 | <!--runner.pytest.multi_core-->47 | <!--runner.pytest.multi_core.stated.breakage-->5 |
| Go | <!--runner.go.examined-->116 | <!--runner.go.serial-->64 | <!--runner.go.stated-->11 | <!--runner.go.implied-->4 | <!--runner.go.none-->49 | <!--runner.go.multi_core-->38 | <!--runner.go.multi_core.stated.breakage-->4 |
| Rust (cargo) | <!--runner.cargo.examined-->95 | <!--runner.cargo.serial-->47 | <!--runner.cargo.stated-->4 | <!--runner.cargo.implied-->1 | <!--runner.cargo.none-->42 | <!--runner.cargo.multi_core-->29 | <!--runner.cargo.multi_core.stated.breakage-->0 |
| Playwright | <!--runner.playwright.examined-->47 | <!--runner.playwright.serial-->37 | <!--runner.playwright.stated-->16 | <!--runner.playwright.implied-->6 | <!--runner.playwright.none-->15 | <!--runner.playwright.multi_core-->19 | <!--runner.playwright.multi_core.stated.breakage-->6 |
| AVA | <!--runner.ava.examined-->25 | <!--runner.ava.serial-->25 | <!--runner.ava.stated-->0 | <!--runner.ava.implied-->0 | <!--runner.ava.none-->25 | <!--runner.ava.multi_core-->10 | <!--runner.ava.multi_core.stated.breakage-->0 |
| tap | <!--runner.tap.examined-->25 | <!--runner.tap.serial-->23 | <!--runner.tap.stated-->0 | <!--runner.tap.implied-->0 | <!--runner.tap.none-->23 | <!--runner.tap.multi_core-->3 | <!--runner.tap.multi_core.stated.breakage-->0 |
| Mocha | <!--runner.mocha.examined-->24 | <!--runner.mocha.serial-->16 | <!--runner.mocha.stated-->1 | <!--runner.mocha.implied-->0 | <!--runner.mocha.none-->15 | <!--runner.mocha.multi_core-->11 | <!--runner.mocha.multi_core.stated.breakage-->0 |
| node:test | <!--runner.node:test.examined-->26 | <!--runner.node:test.serial-->1 | <!--runner.node:test.stated-->1 | <!--runner.node:test.implied-->0 | <!--runner.node:test.none-->0 | <!--runner.node:test.multi_core-->0 | <!--runner.node:test.multi_core.stated.breakage-->0 |

Vitest contributes 27 of the 43 multi-core breakage statements. Vitest flags live in a TS config
that takes comments, so this is partly a runner effect and partly a file-format effect. Jest's
serial flags sit mostly in `package.json` scripts, which cannot hold a comment.

Playwright: <!--serial.playwright_scaffold_default-->10 serial rows are the line `npm init
playwright` writes (`workers: process.env.CI ? 1 : undefined`). Excluding them leaves
<!--serial_excluding_playwright_scaffold-->416 serial rows, with
<!--multi_core_excluding_playwright_scaffold.stated.breakage-->43 multi-core breakage statements
out of <!--multi_core_excluding_playwright_scaffold-->249.

## By the kind of file holding the flag

| file kind | serial | stated | implied | none |
|---|---|---|---|---|
| `package.json` | <!--file_kind.package.json.serial-->72 | <!--file_kind.package.json.stated-->1 | <!--file_kind.package.json.implied-->0 | <!--file_kind.package.json.none-->71 |
| GitHub workflow | <!--file_kind.workflow.serial-->112 | <!--file_kind.workflow.stated-->14 | <!--file_kind.workflow.implied-->4 | <!--file_kind.workflow.none-->94 |
| Makefile/justfile | <!--file_kind.makefile.serial-->72 | <!--file_kind.makefile.stated-->11 | <!--file_kind.makefile.implied-->3 | <!--file_kind.makefile.none-->58 |
| test config (jest/vitest/playwright config, pyproject, pytest.ini...) | <!--file_kind.test_config.serial-->147 | <!--file_kind.test_config.stated-->56 | <!--file_kind.test_config.implied-->10 | <!--file_kind.test_config.none-->81 |
| other | <!--file_kind.other.serial-->23 | <!--file_kind.other.stated-->1 | <!--file_kind.other.implied-->3 | <!--file_kind.other.none-->19 |

Where the reason was found (stated only): same file <!--serial.stated.source.same_file-->66, a
doc line naming the flag <!--serial.stated.source.doc-->5, the message of the commit that last
touched the flag line <!--serial.stated.source.commit_message-->12.

Copies: <!--serial.rows_sharing_identical_flag_line_with_another_repo-->160 serial rows share a
byte-identical flag line (same file name) with at least one other repository: scaffolds, starter
kits and copied codebases (for example eight copies of one XR engine's `mocha --jobs 1`). This is
the visible trace of inertia. Those lines were copied, not decided.

## Definitions

* **examined**: the repository was found by a search query, its default-branch HEAD was pinned,
  and the hit file was re-read at that commit. A hit is a candidate only; the flag is confirmed
  by regex on the pinned file (`examine.py`, `FLAGS`).
* **running serially**: a confirmed serial flag on an active line of an executed file. Not
  serial (counted in examined): flag only in documentation/prose (`.md` and similar: agent skill
  files, READMEs), commented out, only on a debug/watch line (`test:debug --inspect-brk
  --runInBand`, the NestJS scaffold), in a template/example/fixture path, in an inactive file
  (`.bak`, `.tmp`, `.deactivated`...), or set aside by hand review (4 rows; reasons in the block).
* **Flags counted**: Jest `--runInBand`, `-i`, `--maxWorkers=1`, `maxWorkers: 1` (including
  conditionals whose branch is 1); Vitest `--no-threads`, `singleThread: true`,
  `singleFork: true`, `fileParallelism: false` / `--no-file-parallelism`, `maxWorkers|maxThreads|maxForks: 1`,
  `threads: false`; node:test `--test-concurrency=1`; pytest `-p no:xdist`, `-n 0`; Go `go test
  -p 1`, `-parallel 1`, `GOFLAGS=-p=1`; Rust `--test-threads=1`, `RUST_TEST_THREADS=1`; AVA
  `--serial`, `serial: true`, `--concurrency=1`; tap and Mocha `--jobs=1` / `-j 1`; Playwright
  `workers: 1`, `--workers=1`. Vitest `fileParallelism: false`, Rust `--test-threads=1` and
  Playwright `workers: 1` are additions to the brief's list; each means one worker.
* **reason_kind** (serial rows only):
  * `stated`: a line says why. Evidence searched: the flag line's own trailing comment, the
    contiguous comment block directly above it, the YAML step name holding it, any comment within
    5 lines that talks about serial/parallel execution, lines of README/CONTRIBUTING/TESTING/CHANGELOG
    (top two levels) that name the flag, and the message of the commit that last touched the flag
    line (git blame within the fetched depth of 150 commits). Every auto-detected candidate was
    **read and decided by hand** (`review_decisions.json`, one note per repository; 158
    decisions). A stated row carries `reason_quote` verbatim with `reason_file:reason_line`.
    `finalize.py` re-checks the quote against the evidence and fails on a mismatch.
  * `implied`: a comment next to the flag about CI, flaky tests or serial execution that does not
    say why (for example `#TODO: macOS has tests are failing in github CI`). Step names such as
    "Run tests" do not count.
  * `none`: nothing says why.
* **reason_category** (stated only, hand-assigned): `breakage` = parallel runs make tests fail,
  flake, race or hang (shared DB/file/port/fixture/singleton, rate-limited or connection-limited
  external service, timing-sensitive assertions, a runner crash); `resource` = machine capacity
  (memory/OOM, CPU, startup cost); `other` = readability of output, crash diagnosis, a deliberate
  serial canary.
* **multi_core_runner**: true only when a `.github/workflows` job with a GitHub-hosted `runs-on`
  label (`ubuntu-*`, `windows-*`, `macos-*`, or a matrix of them) runs the serial path. The flag
  must be in that workflow itself, or the workflow must run the `package.json` script holding it
  (one level of script indirection followed), the make target holding it, a default-named config
  file through a test command (for Playwright, a Playwright run), or reference the non-default
  config/script by name. The rule used is recorded per row in `multi_core_method`. Cores:
  GitHub-hosted standard runners for public repositories have 4 vCPU on Linux/Windows and 3-4 on
  macOS (DECLARED, GitHub docs "About GitHub-hosted runners"). Other CI systems, self-hosted
  labels and repositories without workflows count as false (UNKNOWN treated as false).
* **test_count_estimate**: ESTIMATED number of test *files* in the pinned tree, by file-name
  pattern (`*.test.*`, `*.spec.*`, `__tests__/`, `test_*.py`, `*_test.go`, `tests/*.rs`, ...).
  It is not a count of test cases.

## Method and deviations from the brief

1. `search.py`: 36 code-search queries (listed in the block), one page of up to 100 results each.
   3600 hits.
2. Sampling: for each query, the first 25 non-fork repositories in the order GitHub returned
   them. A repository hit by several queries is examined once. Result: 834 repositories.
   Metadata (stars, language, default branch) comes from `gh api search/repositories` (`meta.py`).
3. **Deviation (reading method).** `gh api repos/...` is refused in this session for repositories
   outside its own scope, so the files could not be read via `gh api` as the brief assumed.
   `examine.py` instead does a bare, blobless, depth-150 partial fetch
   (`git clone --bare --filter=blob:none --depth=150`). That transfers commits and trees, and
   only the blobs of the files actually read. Nothing is checked out or executed, and each fetch
   is deleted right after. Commit authors are never recorded.
4. `examine.py --reclassify` and `--recheck-multicore` re-apply refined rules offline (the rules
   were tightened after spot checks: commented `jest --init` boilerplate, `--` mistaken for a
   comment marker, inactive file names, non-default config names).
5. `finalize.py` applies the hand decisions and writes `scan.jsonl`; `verify_scan.py` checks it.

Limits that bias the numbers, and in which direction:

* Code search order is not random, and GitHub does not document it. Median stars are 158 over
  the examined rows and 221 over the serial rows (MEASURED:
  `jq -s '[.[]|.stars]|sort|.[length/2|floor]' harness/serial_scan/scan.jsonl`, add
  `select(.running_serially)` for the second). The sample is not representative of all public
  suites, and nobody can draw a random sample of public code through this API.
* Evidence is local. A reason written more than 12 lines above the flag, deeper than two levels in
  the docs, or in a commit older than the 150 fetched, is missed. This biases `stated` **down**.
  Hand review only promoted or demoted auto-detected candidates; `none` rows were spot-checked
  (25 random rows with evidence) but not all read.
* Hand classification is one reviewer's judgment. Each decision has a note, so it can be
  re-judged row by row.
* The search reaches default branches only, so suites configured on other branches are invisible.
* Suites that are serial by default and never set a flag (pytest without xdist, plain `go test`
  of a single package) are outside this scan. They are the pure inertia case, and this scan cannot
  see them.

## Candidates

`candidates.json` lists 25 repositories, newest pinned commit first. Each entry has the pinned
commit, clone/install/collect/run commands and the flag location. **They are NOT VERIFIED.**
Installing and collecting third-party suites executes the repositories' own code (npm lifecycle
scripts, `jest`/`vitest` configs, pytest test-module imports, Go test binaries). That step was
denied by this session's permission policy. The commands were therefore planned from the pinned
tree (lockfiles detected through the same blobless fetch) and never run, so install and collect
status is UNKNOWN for every candidate. Selection: serial, runner in Jest/Vitest/Mocha/pytest/Go,
>= 10 test files (ESTIMATED), not archived; ordered multi-core first, then stated > implied >
none, then stars. To produce the verified list, run
`python3 harness/serial_scan/candidates.py <workdir> 40` in a session where executing those
installs is allowed (`raw/candidate_trials.jsonl` records each attempt).

## Files

* `scan.jsonl`: one row per examined repository (834).
* `REPORT.md`: this file. `verify_scan.py`: the checker.
* `candidates.json`: 25 planned, not verified, candidates.
* `review_decisions.json`: the hand decisions with notes.
* `search.py`, `meta.py`, `examine.py`, `finalize.py`, `review_queue.py`, `candidates.py`: the
  pipeline. `raw/`: search log, hits, repository metadata, per-repository examination records
  with all evidence lines, candidate plans.

## Counts block (re-derived by verify_scan.py)

<!-- counts:begin -->
```
repositories_examined = 834
repositories_examined_readable = 834
repositories_running_serially = 426
serial.stated = 83
serial.implied = 20
serial.none = 323
serial.stated.breakage = 70
serial.stated.resource = 8
serial.stated.other = 5
serial_on_multi_core_runner = 256
multi_core.stated = 55
multi_core.implied = 12
multi_core.none = 189
multi_core.stated.breakage = 43
multi_core.stated.resource = 8
multi_core.stated.other = 4
serial.playwright_scaffold_default = 10
serial_excluding_playwright_scaffold = 416
serial_excluding_playwright_scaffold.stated = 81
serial_excluding_playwright_scaffold.implied = 17
serial_excluding_playwright_scaffold.none = 318
multi_core_excluding_playwright_scaffold = 249
multi_core_excluding_playwright_scaffold.stated.breakage = 43
serial.stated.source.same_file = 66
serial.stated.source.doc = 5
serial.stated.source.commit_message = 12
serial.rows_sharing_identical_flag_line_with_another_repo = 160
file_kind.package.json.serial = 72
file_kind.package.json.stated = 1
file_kind.package.json.implied = 0
file_kind.package.json.none = 71
file_kind.workflow.serial = 112
file_kind.workflow.stated = 14
file_kind.workflow.implied = 4
file_kind.workflow.none = 94
file_kind.makefile.serial = 72
file_kind.makefile.stated = 11
file_kind.makefile.implied = 3
file_kind.makefile.none = 58
file_kind.test_config.serial = 147
file_kind.test_config.stated = 56
file_kind.test_config.implied = 10
file_kind.test_config.none = 81
file_kind.other.serial = 23
file_kind.other.stated = 1
file_kind.other.implied = 3
file_kind.other.none = 19
arm.flag_only.examined = 486
arm.flag_only.serial = 343
arm.flag_only.serial.stated = 53
arm.flag_only.serial.implied = 11
arm.flag_only.serial.none = 279
arm.flag_only.serial.stated.breakage = 41
arm.flag_only.multi_core = 213
arm.flag_only.multi_core.stated = 39
arm.flag_only.multi_core.implied = 9
arm.flag_only.multi_core.none = 165
arm.flag_only.multi_core.stated.breakage = 27
arm.flag_word.examined = 348
arm.flag_word.serial = 83
arm.flag_word.serial.stated = 30
arm.flag_word.serial.implied = 9
arm.flag_word.serial.none = 44
arm.flag_word.serial.stated.breakage = 29
arm.flag_word.multi_core = 43
arm.flag_word.multi_core.stated = 16
arm.flag_word.multi_core.implied = 3
arm.flag_word.multi_core.none = 24
arm.flag_word.multi_core.stated.breakage = 16
runner.ava.examined = 25
runner.ava.serial = 25
runner.ava.stated = 0
runner.ava.implied = 0
runner.ava.none = 25
runner.ava.multi_core = 10
runner.ava.multi_core.stated.breakage = 0
runner.cargo.examined = 95
runner.cargo.serial = 47
runner.cargo.stated = 4
runner.cargo.implied = 1
runner.cargo.none = 42
runner.cargo.multi_core = 29
runner.cargo.multi_core.stated.breakage = 0
runner.go.examined = 116
runner.go.serial = 64
runner.go.stated = 11
runner.go.implied = 4
runner.go.none = 49
runner.go.multi_core = 38
runner.go.multi_core.stated.breakage = 4
runner.jest.examined = 202
runner.jest.serial = 45
runner.jest.stated = 3
runner.jest.implied = 0
runner.jest.none = 42
runner.jest.multi_core = 30
runner.jest.multi_core.stated.breakage = 1
runner.mocha.examined = 24
runner.mocha.serial = 16
runner.mocha.stated = 1
runner.mocha.implied = 0
runner.mocha.none = 15
runner.mocha.multi_core = 11
runner.mocha.multi_core.stated.breakage = 0
runner.node:test.examined = 26
runner.node:test.serial = 1
runner.node:test.stated = 1
runner.node:test.implied = 0
runner.node:test.none = 0
runner.node:test.multi_core = 0
runner.node:test.multi_core.stated.breakage = 0
runner.playwright.examined = 47
runner.playwright.serial = 37
runner.playwright.stated = 16
runner.playwright.implied = 6
runner.playwright.none = 15
runner.playwright.multi_core = 19
runner.playwright.multi_core.stated.breakage = 6
runner.pytest.examined = 110
runner.pytest.serial = 66
runner.pytest.stated = 9
runner.pytest.implied = 4
runner.pytest.none = 53
runner.pytest.multi_core = 47
runner.pytest.multi_core.stated.breakage = 5
runner.tap.examined = 25
runner.tap.serial = 23
runner.tap.stated = 0
runner.tap.implied = 0
runner.tap.none = 23
runner.tap.multi_core = 3
runner.tap.multi_core.stated.breakage = 0
runner.vitest.examined = 164
runner.vitest.serial = 102
runner.vitest.stated = 38
runner.vitest.implied = 5
runner.vitest.none = 59
runner.vitest.multi_core = 69
runner.vitest.multi_core.stated.breakage = 27
not_serial[flag only in documentation/prose, not an executed config] = 251
not_serial[no serial flag at pinned commit in the hit file(s)] = 132
not_serial[flag is in an inactive file (backup/temp/sample/disabled name), not the active config] = 8
not_serial[flag only on a debug/watch line (e.g. test:debug --inspect-brk), not the suite run] = 8
not_serial[flag is in a template/example/fixture path, not the repository's own suite] = 5
not_serial[hand review: conftest.py:176 mentions `-p no:xdist` in a docstring; not an executed flag] = 1
not_serial[hand review: flag is in a docstring of plugin.py] = 1
not_serial[hand review: flag is inside a message string in tools/story_check.py, not an executed command] = 1
not_serial[hand review: flag is on a pytest --collect-only invocation, not a test run] = 1
search[jest|flag|"--runInBand" filename:package.json] = 325120
search[jest|flag|runInBand path:.github/workflows] = 7072
search[jest|flag|maxWorkers 1 filename:jest.config.js] = 24160
search[jest|flag|maxWorkers 1 filename:jest.config.ts] = 14112
search[jest|flag+word|runInBand flaky] = 4488
search[jest|flag+word|runInBand database] = 56064
search[jest|flag+word|runInBand "shared"] = 45760
search[jest|flag+word|runInBand port] = 375808
search[jest|flag+word|maxWorkers 1 race] = 62336
search[vitest|flag|singleFork true filename:vitest.config.ts] = 3048
search[vitest|flag|singleThread true filename:vitest.config.ts] = 1626
search[vitest|flag|fileParallelism false filename:vitest.config.ts] = 31872
search[vitest|flag|fileParallelism false filename:vitest.config.mts] = 3116
search[vitest|flag+word|singleFork database] = 3672
search[vitest|flag+word|fileParallelism false database] = 21728
search[vitest|flag+word|singleFork flaky] = 2384
search[node:test|flag|"--test-concurrency=1"] = 58368
search[pytest|flag|"-p no:xdist"] = 6800
search[pytest|flag|"-p no:xdist" path:.github/workflows] = 209
search[pytest|flag|"-n 0" pytest path:.github/workflows] = 805
search[pytest|flag+word|"no:xdist" database] = 985
search[pytest|flag+word|"no:xdist" flaky] = 513
search[go|flag|"go test" "-p 1" filename:Makefile] = 3064
search[go|flag|"go test" "-p 1" path:.github/workflows] = 3888
search[go|flag|"go test" "-parallel 1"] = 4352
search[go|flag+word|"go test" "-p 1" database] = 15056
search[go|flag+word|"go test" "-p 1" race] = 17280
search[cargo|flag|"--test-threads=1" path:.github/workflows] = 8688
search[cargo|flag|"--test-threads=1" filename:Makefile] = 1542
search[cargo|flag+word|"--test-threads=1" database] = 23488
search[cargo|flag+word|"--test-threads=1" shared] = 55872
search[ava|flag|"ava --serial" filename:package.json] = 822
search[tap|flag|"tap" "--jobs=1" filename:package.json] = 113
search[mocha|flag|"mocha" "--jobs 1"] = 139
search[playwright|flag|workers 1 filename:playwright.config.ts] = 155392
search[playwright|flag+word|workers 1 filename:playwright.config.ts database] = 13408
```
<!-- counts:end -->
