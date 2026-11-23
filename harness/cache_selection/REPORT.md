NOT DONE

# Measurement A: test skipping today, free per-PR selection share, and free-selection false greens

Branch `claude/cache-measure-a`, cut from `claude/release-1`. Everything is in `harness/cache_selection/`.
Measured 2026-11-23, in one container (4 cores). Two repositories ran at the same time, each pinned with `taskset` to its own 2 cores.
This report is a claim until the coordinator re-checks it. What I verified and what I could not is listed at the end.

## Rule changes (spec rule 4), before any result

1. **Base of a PR.** The spec says `base = git merge-base <default> head`. I use `git merge-base <landing>^1 head`, where `<landing>` is the default-branch commit that landed the PR. Reason: for a merge-commit PR, `head` is already an ancestor of the default branch, so `merge-base <default> head` returns `head` itself, and every diff and selection would be empty. For squash and rebase PRs the two definitions agree whenever the PR was up to date. (`history.py`)
2. **Bot author.** A PR counts as `dependency` by author only if *every* commit author in `base..head` is a bot: renovate, dependabot or github-actions in the name or email local part, or a name ending in `[bot]`. A PR mixing bot and human commits is classed by its files. Reason: the spec says "the commit author", singular, and PRs have several commits.
3. **"package.json version/dependency change".** I read this as: the package.json is equal at `base` and `head` once the keys `version`, `dependencies`, `devDependencies`, `peerDependencies`, `optionalDependencies`, `overrides`, `resolutions` and `packageManager` are removed. Lockfiles: `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `npm-shrinkwrap.json`, `bun.lock`, `bun.lockb`.
4. **Fresh install at every checkout.** All `node_modules` are deleted and the install command is run again at every commit used. Reason: reusing `node_modules` across commits produced 80 false failures in one ironcurtain full run, because `git clean -x` deleted a built `dist/` that a fresh install recreates. That full run, and one codex-multi-auth state measured with the reused install, were discarded and re-measured; the DISCARDED lines are in each `data/<repo>/log.txt`.
5. **Reruns are per file.** "Run it 3 more times … one file at a time" is implemented as: run the test's file alone, plain (`vitest run <file>` / `jest --runTestsByPath <file>`), 3 times at the state and 3 times at `base`. The test's own status is read from each run's JSON. A test absent from a run, for example because the file does not exist at `base`, counts as not failing in that run. Its file is marked `absent`.
6. **PREEXISTING** = the test fails in at least 1 of the 3 base runs. SELECTION_MISS is exactly the spec's rule: base 0/3 failing and state ≥2/3 failing. FLAKY is everything else.
7. **ENV.** A failure whose first failure line matches a container cause is labelled ENV, unless it is a SELECTION_MISS; no miss is ever relabelled. The patterns are: `No native build was found`, `Could not locate the bindings file`, `EAFNOSUPPORT`, `ECONNREFUSED`, `EADDRNOTAVAIL`, `ENETUNREACH`, `EAI_AGAIN`, `ENOTFOUND`, `getaddrinfo`, `EHOSTUNREACH`, `Executable doesn't exist`, `browserType.launch`, `Cannot connect to the Docker`, `docker: not found`. The two native-module patterns cover packages whose compiled part is not built because the specs.json install command uses `--ignore-scripts` (isolated-vm in ironcurtain, better-sqlite3 in agentlang). The original label is kept as `orig_class` in results.jsonl. (`aggregate.py`)
8. **Rerun commit not installable → UNKNOWN.** If the base (or state) of a failing test cannot be installed, the 3+3 rule cannot be applied, and the failure is labelled UNKNOWN with the install error. This affects agentlang PR #630 (80 failures).
9. **At most 40 failing tests classified per state** (sorted by test id). The rest are listed in `failures_not_classified`. This happened only in agentlang PR #630, states 3 and 4 (250 failures not classified). That PR's base does not install, so every one of them would be UNKNOWN under rule change 8. The cap changed no count.
10. **Share over files with known minutes.** Spec step 5 says files absent from the full run count as UNKNOWN minutes and are reported. The share is then computed over the files with known minutes. Each row lists those files in `files_unknown_minutes`; repositories where this exceeds 10% of files are flagged below.
11. **Install command transcriptions.** specs.json gives some install commands as prose. The command run is in `repos.json` (`install`; `spec_install` is the specs.json text):
    - yalc: the `web/` install is guarded by `if [ -f web/package.json ]`, because `web/` does not exist at older commits.
    - lerna-lite: the build (`pnpm build`) runs as a separate step after the install.
    - drydock: `npm ci` in the root and in `app/` (tests run in `app/`), with `--no-audit --no-fund`, on Node 24 (`/opt/node24/bin` first on PATH).
    - All other commands are the specs.json command unchanged.
12. **Time cap applied to codex-multi-auth** (8 h, lane started 11:39 UTC, stopped 19:39 UTC). Following the spec's drop order (states first):
    - kept: the final state of all 30 PRs, and the second state of all 26 PRs that have one;
    - kept in part: the third state of 8 of 21 PRs;
    - dropped: states 4 and 5 of every PR, and the third state of the other 13 PRs (45 states in all);
    - PR count kept at 30.

## Results per repository

| repository | PRs kept (code / dependency) | PRs with measured final-state share (code / dependency) | skips tests in CI today | median selection share, code | median selection share, dependency | SELECTION_MISS, code | SELECTION_MISS, dependency | E1 lower bound |
|---|---|---|---|---|---|---|---|---|
| codex-multi-auth | 29 / 1 | 29 / 1 | no (none found) | 68.8% (n=29) MEASURED | 0.0% (n=1) MEASURED | 0 over 58 states with excluded files MEASURED | 0 over 0 states with excluded files MEASURED | env in-test 0, env run-level 0, fs 8658, io read 0, io race 0 (of 8660 tests) MEASURED |
| ironcurtain | 13 / 17 | 13 / 17 | no (none found) | 63.4% (n=13) MEASURED | 100.0% (n=17) MEASURED | 0 over 31 states with excluded files MEASURED | 0 over 15 states with excluded files MEASURED | env in-test 0, env run-level 0, fs 6667, io read 0, io race 0 (of 6913 tests) MEASURED |
| yalc | 19 / 0 | 19 / 0 | no (none found) | 81.3% (n=19) MEASURED | UNKNOWN: no dependency PR | 0 over 25 states with excluded files MEASURED | – (no PR) | UNKNOWN: no verify output |
| nestjs-pino | 2 / 28 | 2 / 28 | no (none found) | UNKNOWN: fewer than 5 code PRs measured (n=2 of 2) | 100.0% (n=28) MEASURED | 0 over 0 states with excluded files MEASURED | 0 over 28 states with excluded files MEASURED | env in-test 1, env run-level 0, fs 2, io read 0, io race 0 (of 269 tests) MEASURED |
| agentsys | 30 / 0 | 30 / 0 | no (none found) | 99.7% (n=30) MEASURED | UNKNOWN: no dependency PR | 0 over 57 states with excluded files MEASURED | – (no PR) | env in-test 129, env run-level 1536, fs 18, io read 0, io race 1 (of 2224 tests) MEASURED |
| lerna-lite | 19 / 11 | 14 / 7 | no (none found) | 100.0% (n=14) MEASURED | 0.0% (n=7) MEASURED | 0 over 14 states with excluded files MEASURED | 0 over 2 states with excluded files MEASURED | UNKNOWN: no verify output |
| drydock | 12 / 0 | 12 / 0 | no (none found) | 0.0% (n=12) MEASURED | UNKNOWN: no dependency PR | 0 over 5 states with excluded files MEASURED | – (no PR) | UNKNOWN: no verify output |
| agentlang | 30 / 0 | 18 / 0 | no (none found) | 2.4% (n=18) MEASURED | UNKNOWN: no dependency PR | 0 over 30 states with excluded files MEASURED | – (no PR) | UNKNOWN: no verify output |
| alakajam | 28 / 2 | 0 / 0 | no (none found) | UNKNOWN: no code PR with a measured share | UNKNOWN: no dependency PR with a measured share | 0 over 0 states with excluded files MEASURED | UNKNOWN: no measured state | UNKNOWN: no verify output |

Column notes:
- *Share*: the median of (minutes of test files not selected / minutes of all test files), over the PR's final state; n = PRs with a measured share.
- *Code median*: reported only when n ≥ 5 (spec).
- *SELECTION_MISS*: counted over all measured states (up to 5 per code PR).
- *E1*: from `e1.json`, computed by `python3 harness/cache_selection/e1.py` from `harness/parallel_measure/data/verify-<repo>-round2-w4.json.gz`.

### Detail per repository

- **codex-multi-auth**: states measured 64 of 64 run / 109 planned (UNKNOWN states: 0). Excluded test files run: 19624 (code 19624). Failing tests classified: SELECTION_MISS 0, PREEXISTING 53, FLAKY 3, ENV 84, UNKNOWN 0; not classified (cap) 0. Median share over all PRs: 68.6%. Final states with share UNKNOWN: 0. 
- **ironcurtain**: states measured 51 of 51 run / 51 planned (UNKNOWN states: 0). Excluded test files run: 14000 (dependency 5799, code 8201). Failing tests classified: SELECTION_MISS 0, PREEXISTING 90, FLAKY 1, ENV 132, UNKNOWN 0; not classified (cap) 0. Median share over all PRs: 100.0%. Final states with share UNKNOWN: 0. 
- **yalc**: states measured 39 of 40 run / 40 planned (UNKNOWN states: 1; 1x UNKNOWN: INSTALL_FAILED: * 1 dependencies were added: playwright@^1.49.0). Excluded test files run: 2567 (code 2567). Failing tests classified: SELECTION_MISS 0, PREEXISTING 163, FLAKY 0, ENV 0, UNKNOWN 0; not classified (cap) 0. Median share over all PRs: 81.3%. Final states with share UNKNOWN: 0. Final states where more than 10% of test files have UNKNOWN minutes: PRs [2, 3, 4, 5, 8, 17, 18, 19, 21]; code median over the remaining code PRs: 88.1%. 
- **nestjs-pino**: states measured 30 of 30 run / 30 planned (UNKNOWN states: 0). Excluded test files run: 679 (dependency 679). Failing tests classified: SELECTION_MISS 0, PREEXISTING 0, FLAKY 0, ENV 0, UNKNOWN 0; not classified (cap) 0. Median share over all PRs: 100.0%. Final states with share UNKNOWN: 0. 
- **agentsys**: states measured 57 of 57 run / 57 planned (UNKNOWN states: 0). Excluded test files run: 4536 (code 4536). Failing tests classified: SELECTION_MISS 0, PREEXISTING 57, FLAKY 0, ENV 0, UNKNOWN 0; not classified (cap) 0. Median share over all PRs: 99.7%. Final states with share UNKNOWN: 0. 
- **lerna-lite**: states measured 21 of 21 run / 42 planned (UNKNOWN states: 0). Excluded test files run: 177 (code 153, dependency 24). Failing tests classified: SELECTION_MISS 0, PREEXISTING 0, FLAKY 1, ENV 0, UNKNOWN 0; not classified (cap) 0. Median share over all PRs: 100.0%. Final states with share UNKNOWN: 0. 
- **drydock**: states measured 60 of 60 run / 60 planned (UNKNOWN states: 0). Excluded test files run: 2257 (code 2257). Failing tests classified: SELECTION_MISS 0, PREEXISTING 0, FLAKY 0, ENV 0, UNKNOWN 0; not classified (cap) 0. Median share over all PRs: 0.0%. Final states with share UNKNOWN: 0. 
- **agentlang**: states measured 39 of 55 run / 55 planned (UNKNOWN states: 16; 16x UNKNOWN: INSTALL_FAILED: Note that in CI environments this setting is true by default. If ). Excluded test files run: 120 (code 120). Failing tests classified: SELECTION_MISS 0, PREEXISTING 0, FLAKY 0, ENV 10, UNKNOWN 70; not classified (cap) 250. Median share over all PRs: 2.4%. Final states with share UNKNOWN: 12. Final states where more than 10% of test files have UNKNOWN minutes: PRs [625, 626]; code median over the remaining code PRs: 3.5%. 
- **alakajam**: states measured 8 of 63 run / 63 planned (UNKNOWN states: 55; 7x UNKNOWN: INSTALL_FAILED: npm error A complete log of this run can be found in: /root/.npm/; 48x UNKNOWN: list-only command failed (exit 1 / 1)). Excluded test files run: 0 (none). Failing tests classified: SELECTION_MISS 0, PREEXISTING 0, FLAKY 0, ENV 0, UNKNOWN 0; not classified (cap) 0. Median share over all PRs: UNKNOWN. Final states with share UNKNOWN: 30. 

## The three kill-line facts (numbers, not a decision)

(a) **2 of 7** repositories with a measured code median have a median selection share for code PRs below 30% (agentlang 2.4%, drydock 0.0%). Measured: agentlang 2.4%, agentsys 99.7%, codex-multi-auth 68.8%, drydock 0.0%, ironcurtain 63.4%, lerna-lite 100.0%, yalc 81.3%. UNKNOWN for nestjs-pino, alakajam (see table). MEASURED.

(b) **0 of 9** repositories already skip tests in CI with one of the listed tools (`statusquo.json`). MEASURED (read of CI files).

(c) **0** SELECTION_MISS over all code PRs. Checked: 220 code-PR states where the free selection excluded at least one test file, 37458 excluded test files run in total. MEASURED. (Dependency PRs: 0.)

Caveat for (c): "measured on the last 5 commits of merged PRs; breakages fixed before a commit was made, and PRs never merged, are not seen, so the count is a lower bound".

## E1 lower bound (spec step 9)

Counts are over all tests in each verify output. MEASURED by `python3 harness/cache_selection/e1.py > harness/cache_selection/e1.json` (exit 0) from the four `harness/parallel_measure/data/verify-*-round2-w4.json.gz` files.

| repository | tests in output | (a) env read inside a test | env run-level ("outside any test the run read …"), one read charged to every test | (b) fs, all paths | (c) io naming a read | io race ("concurrent I/O") |
|---|---|---|---|---|---|---|
| codex-multi-auth | 8660 | 0 | 0 | 8658 | 0 | 0 |
| ironcurtain | 6913 | 0 | 0 | 6667 | 0 | 0 |
| nestjs-pino | 269 | 1 | 0 | 2 | 0 | 0 |
| agentsys | 2224 | 129 | 1536 | 18 | 0 | 1 |
| yalc, lerna-lite, drydock, agentlang, alakajam | UNKNOWN: no per-test verify output exists for these repositories (spec, "Current state") | | | | | |

- In codex-multi-auth and ironcurtain, every `fs` description is a run input read before the test started ("before the test started: run input …").
- nestjs-pino has 8 further `io` reasons that name neither a read nor a race ("waited for I/O readiness"); they are not counted.
- `other`, `child`, `entropy`, `beyond-trace` and `missing` are not counted (counts per repository are in `e1.json`).

Caveat: "causes are named only for tests that differ or are not proven; these are also tests our own default-deny cache refuses".

## Status quo (spec step 3)

`statusquo.json`. This was read at each repository's default head with `statusquo_scan.sh <clone> <default ref>`, and then each workflow's test step was read by hand. No repository runs any of the listed skipping tools in CI. No `nx.json`, `turbo.json` or `.circleci` exists in any of the 9.

| repository | CI test command (file:line) | skips tests in CI | notes |
|---|---|---|---|
| codex-multi-auth | .github/workflows/ci.yml:55 npm run coverage -> package.json:106 npm run build && vitest run --coverage --maxWorkers=1 (full suite on every PR; also ci.yml:45 one-file lockfile guard) | no: none found | no paths filter on pull_request (ci.yml:3-7) |
| ironcurtain | .github/workflows/ci.yml:81 npm test -> package.json:67 bash scripts/test.sh (scripts/test.sh:46 npx vitest run, full root suite, then web-ui) | no: none found | ci.yml:11-17 paths filter skips the whole CI for PRs touching only **/*.md, docs/**, LICENSE: not test selection, not in the spec's list |
| yalc | .github/workflows/ci.yml:22 pnpm test -> package.json:60 vitest run (also test.yml:22) | no: none found |  |
| nestjs-pino | .github/workflows/build-lint-test.yml:50 npm t -> package.json:22 vitest run (matrix over @nestjs versions, build-lint-test.yml:36-37) | no: none found |  |
| agentsys | .github/workflows/ci.yml:36 npm test -> package.json:13 jest | no: none found |  |
| lerna-lite | .github/workflows/main.yml:117 pnpm test -> package.json:60 vitest --coverage --config ./vitest/vitest.config.ts (unit); main.yml:196 pnpm test:e2e -> package.json:63 node scripts/run-e2e-with-verdaccio.mjs (e2e, the suite measured here via specs.json --config ./e2e/vitest.config.ts) | no: none found | main.yml:99-107 actions/cache of node_modules/.vitest and packages/*/lib: vitest's results cache orders files, it does not skip any; main.yml:113-114 skips unit tests only on 'chore(release)' commits |
| drydock | .github/workflows/ci-verify.yml:659 job test-app (app/package.json:17 vitest run --coverage --maxWorkers=1 --fileParallelism=false), :745 test-ui, :589 test-repo; no paths condition on these jobs | no: none found | ci-verify.yml:244 dorny/paths-filter (.github/filters/runtime.yml) gates heavy e2e/web jobs (ci-verify.yml:999, :1320, :1919) on changed paths: job-level path gating, not in the spec's list and not applied to the unit suites measured here |
| agentlang | .github/workflows/ci.yml:62 NODE_ENV=test npm test -> package.json:50 vitest run | no: none found |  |
| alakajam | .github/workflows/ci.yml:25 npm run test:unit:ci -> package.json:26 vitest run; ci.yml:37 npm run test:e2e (playwright) | no: none found |  |

## Repositories, PRs and states skipped, and why

(pending)

## Method (commands as run; observed exit codes and counts are in the data files)

- **History** (`history.py <key> <clone>`):
  - `git ls-remote origin 'refs/pull/*/head'`, then `git fetch origin +refs/pull/N/head:refs/remotes/pr/N` for the 150 highest PR numbers.
  - Merged detection: merge (head is an ancestor of the default branch), squash (`(#N)` in a first-parent subject), rebase (`git patch-id --stable` of the PR head equals that of one of the 3000 newest first-parent commits).
  - Output: `data/<key>/prs.json`, which records the method for each PR.
- **Full runs** (`cs.py`, spec step 5):
  - vitest: `npx --no-install vitest run <specs args> --no-file-parallelism --maxWorkers=1 --reporter=json --outputFile=<f>`.
  - jest: `npx --no-install jest --runInBand --json --outputFile=<f>`.
  - Run at the base of PRs 1, 6, 11, … in landing order. Each `data/<key>/full-NN.json` holds the commit, command, exit code, wall time, outcome counts and per-file `endTime - startTime`; the raw JSON report is `full-NN.json.raw.gz`.
- **Selection, list only** (spec step 6). Runner versions and `--help` lines are in `runner_versions.json`, recorded at each default head by `runner_versions.py`.
  - vitest: `npx --no-install vitest list <specs args> --changed <base> --filesOnly --json=<f>` at the checked-out state. The `--help` lines are "--changed [since]  Print only tests that are affected by the changed files" and "--filesOnly  Print only test files with out the test cases".
  - All files: `vitest list <specs args> --filesOnly --json=<f>`.
  - jest: `npx --no-install jest --listTests --findRelatedTests <changed files that exist at the state>`; all files: `jest --listTests`.
  - Every row's `selection_cmd` and `list_all_cmd` in results.jsonl end with the observed exit code.
- **Excluded run** (spec step 8):
  - vitest: `vitest run <specs args> --reporter=json --outputFile=<f> <excluded files>`, with the repository's own parallel settings.
  - jest: `jest --json --outputFile=<f> --runTestsByPath <excluded files>`.
  - Every state row has `excluded_run_cmd`, `excluded_run_exit` and `failures`. For each failure, results.jsonl stores the 3 state and 3 base rerun commands with the observed exit and test status (`state_cmds`, `base_cmds`).
- **Aggregation**: `python3 harness/cache_selection/aggregate.py` writes `results.jsonl`, `summary.json` and `tables.md`.

## What I verified and what I could not

(pending)
