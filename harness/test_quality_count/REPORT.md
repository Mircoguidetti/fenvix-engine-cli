NOT DONE

# Test-quality count: repositories running mutation testing in CI, and time pain

Printed by `report.py` from the committed raw rows; `verify.py` re-derives every row from the raw responses and re-prints this file. Rules: `PREREG.md`.

## Changes after PREREG

Changes after the PREREG commit (4098894), each on its own line with its justification. All of them were made before any
search request, probe or candidate read (no data existed); none changes the decision line.

1. Pre-data clarification (§2.4): `composer exec <bin>` is resolved as running `<bin>` (composer's way to run a
   vendor binary; the PREREG composer resolver only named scripts). Justification: an Infection run behind
   `composer exec infection` would otherwise be missed.
2. Pre-data clarification (§2.4): a step `uses: ./<dir>` (local composite action) has its `runs.steps[].run` resolved as
   part of that step (one level used). Justification: a mutation run inside a repository's own composite action is a
   mutation run in CI; without this it could only reach `tool-present-unlinked`.
3. Pre-data clarification (§2.4): Rake tasks are also looked up in `rakelib/*.rake` and `lib/tasks/*.rake` when not in
   the Rakefile; a plain `cd <dir>` between commands of one step or script changes the directory of the next command.
4. Pre-data clarification (§2.6, gate note 2): tool terms that belong to a mutation job (its name, its steps, the
   scripts its steps reach, and the job's own text in the workflow file) are not `tool-present-unlinked` items; the
   file-level term check runs on the workflow without its mutation jobs. Justification: otherwise every
   `configured-not-running` repository would turn `uncertain` because of its own mutation command.
5. Pre-data clarification (§1): excluded maintainer repositories (owner list) are still read through §2-§3, without
   history, so REPORT can list those that run mutation testing in CI (spec §7 "information"); they are never counted
   as read. Forks, archived and stale repositories are not read further.
6. Pre-data clarification (§2.8): run listing reads the first page (100 runs) and inspects at most 50; "more runs exist"
   is `total_count` > runs inspected. A runs request that fails after one retry makes the job `uncertain` (error).
7. Pre-data clarification (§0, AC1): discovery, probes and the issues search refuse to start unless
   `results/search_budget_free.json` (time and text of the coordinator's message) is committed.
8. Pre-data fix after /review (§2.4): leading package-manager options that take a value (`npm --prefix web run x`,
   `yarn --cwd web x`, `pnpm -C web run x`, `npm run --prefix=web x`) change the directory instead of hiding the
   script; `--filter`/`-w`/`--workspace`/`-r` with a script not in the root package.json is an unresolved item named
   after the script. Maven `-e` no longer swallows the next argument. Files the trimmed tree does not keep (e.g. an
   extensionless `bash ci/mutate`) are fetched directly (404 = absent). Justification: each hid a real mutation run
   as `no-mutation` in a reviewer's reproduction.
9. Rule change before any data (§2.8, §3): a leg `cancelled` or `timed_out` at its timeout (wall time >= timeout - 1
   min) with the mutation step found and not skipped is running evidence as well as a lower-bound value (PREREG §2.8
   named only `success`/`failure`). Justification: a mutation job always killed at its timeout ran the mutation job
   and is the strongest time-pain case; the old wording made it `configured-not-running`.
10. Rule change before any data (§2.3 Maven): a `pitest-maven` execution in a profile with `<activation>` (active by
    default or by a property) that the command does not name with `-P` is an unresolved item `pitest in maven profile
    <id>` (counted: it contains a tool term); Gradle `dependsOn(`/`finalizedBy(` followed by `pitest` on the next line
    also counts as wiring. Unresolved names for pluginManagement now read `pitest in pluginManagement` (the old name
    `pitest-maven ...` was not word-bounded and did not count). Justification: these hid a possible PIT run as
    `no-mutation`.
11. Rule change before any data (§4.5): pain is `unknown` (reason `another mutation job uncertain`) when a running
    repository also has a mutation job or caller route that is `uncertain`, `unsupported` or errored. Justification:
    that job's duration (possibly >= 30 min) is unknown, so pain `no` could hide time pain.
12. Pre-data fix (§2.6): `workflow_call` chains are followed recursively (up to 4 levels) to a caller that is not
    only `workflow_call`; runs are listed on that root file and the job name is `<root job> / ... / <job>`; a deeper
    chain or a caller whose `on:` does not parse makes the job `unsupported`. Jobs pages beyond 5 (500 jobs) and
    commit listings beyond 1,000 commits per path are recorded (`uncertain` / `history-error`) instead of read as
    complete.
13. Rule change before any data (§2.3 Infection): `php -d <ini>` / `php -n` options are stripped before matching
    (`php -d memory_limit=-1 vendor/bin/infection` is the documented way to run Infection). Justification: the PREREG
    regex `^(php )?...` would miss the common form.
14. Pre-data fix (operations): a chunk with `issues_route: workflow` refuses to start without
    `results/search_budget_free.json`; the workflow processes every request file without a chunk record (a queued run
    cancelled by GitHub loses nothing) and commits only the files a chunk writes (`rows.jsonl`, `chunks.jsonl`,
    `raw/`, `probe_workflow.json`, `issues_wf.jsonl`, `issues_raw_wf/`, `debug/`), never the session's files.
15. §0.2c probe fix (2026-11-26, after "search budget free", before discovery): the session-route issues query
    `repo:stryker-mutator/stryker-js stryker (slow OR timeout OR minutes OR hours OR expensive) created:>=2024-01-01`
    answered HTTP 422 "Query must include 'is:issue' or 'is:pull-request'" (results/probe_session_first.json). Each
    §4.3 query now runs twice, with `is:issue` and with `is:pull-request` (first 30 results each); both count in the
    300-request cap. Justification: required by GitHub; keeping both kinds keeps issues and pull requests in scope.
16. Logging only (2026-11-26 21:10Z, during discovery, at the coordinator's request): each rate-limited answer's
    stderr line also gives the limit headers (`x-ratelimit-resource`, `-limit`, `-remaining`, `-reset`, `retry-after`)
    and `limit=primary|secondary|unknown`. Justification: 65 code-search 429s in 90 min; find who shares the budget.
    No rule, regex, query, rate or budget changes; earlier 429 lines lack these fields.
17. Pacing change (2026-11-26 22:46Z, during discovery, at the coordinator's request): code search is spaced at least
    7.0 s between requests (was 60/9 + 0.1 = 6.77 s; still one request at a time, still within <= 9/min), and after a
    code-search 429 marked `limit=secondary` the next request waits max(retry_seconds, 60 s). Justification: 132
    secondary 429s in 3 slices with the primary budget untouched (CHANGES.md 16); this is GitHub's secondary limit on
    our own pace. No rule, regex, query or budget changes.
18. Pacing change (2026-11-27 00:25Z, during discovery, coordinator's rule "still above 10 per slice, double the
    spacing"): code search spaced at least 14.0 s (was 7.0 s). Secondary 429s per 30-min slice at 7 s: 27 and 25
    (slice 1 of that task, partly at 6.77 s: 46). No rule, regex, query or budget changes.
19. Retry change (2026-11-27 02:05Z, during discovery, at the coordinator's request): a rate-limited answer (429, or
    403 rate limit) is retried until it returns and no longer uses up one of the 6 attempts, so no page is skipped for
    a 429; 6 attempts remain for transport errors and 5xx. Any page that still fails stays recorded (`page_errors`,
    leaf `incomplete`) and counted in REPORT. Check at the change: 311 leaves, 0 error leaves, 0 page errors.

## Decision

**KEEP READING: read 227, running 20, pain yes 11, U_R×N 24458.1, U_P×N 22598.4.**

covered: GitHub Actions, tools stryker (JS/.NET/Scala), mutmut, cosmic-ray, PIT (Maven, Gradle), cargo-mutants, Infection, mutant, go-mutesting, gremlins, Mull, Muter, mutatest; not covered: other CI systems, private repositories, tools not listed.

read 227, running 20, not-running 147, uncertain 60; pain yes 11, unknown 2, no 7; N 58715; U_R 0.41656 (U_R×N 24458.1), U_P 0.38488 (U_P×N 22598.4); whole frame read: no; truncated leaves: 2; incomplete leaves: 0; hand check: not passed.

## Discovery

leaves 341, candidates 57499, unread hits on truncated leaves 1216, N 58715.
DROP reachable via U_P at r >= 11275 (assumes no uncertain or unknown rows).

Observed uncertain share 0.264; DROP still reachable within the frame: no.

| query | leaves | total_count | repos | only this query | unread hits | contribution to N | truncated |
|---|---|---|---|---|---|---|---|
| `A stryker` | 9 | 3525 | 2997 | 56 | 0 | 56 | 0 |
| `A mutmut` | 7 | 1224 | 1101 | 23 | 0 | 23 | 0 |
| `A cosmic-ray` | 1 | 101 | 78 | 4 | 0 | 4 | 0 |
| `A pitest` | 10 | 3774 | 3121 | 1782 | 0 | 1782 | 0 |
| `A mutationCoverage` | 1 | 587 | 516 | 0 | 0 | 0 | 0 |
| `A cargo-mutants` | 7 | 1806 | 1324 | 6 | 0 | 6 | 0 |
| `A "cargo mutants"` | 6 | 1238 | 888 | 0 | 0 | 0 | 0 |
| `A infection` | 9 | 2076 | 1846 | 184 | 0 | 184 | 0 |
| `A mutant` | 15 | 8202 | 6427 | 1175 | 0 | 1175 | 0 |
| `A go-mutesting` | 1 | 39 | 34 | 2 | 0 | 2 | 0 |
| `A gremlins` | 1 | 503 | 415 | 54 | 0 | 54 | 0 |
| `A mull-runner` | 1 | 64 | 28 | 3 | 0 | 3 | 0 |
| `A muter` | 1 | 170 | 141 | 98 | 0 | 98 | 0 |
| `A mutatest` | 1 | 10 | 9 | 4 | 0 | 4 | 0 |
| `A mutation` | 76 | 49855 | 31278 | 21736 | 0 | 21736 | 0 |
| `B stryker filename:package.json` | 21 | 10339 | 6350 | 1426 | 0 | 1426 | 0 |
| `B stryker filename:stryker.conf` | 19 | 7460 | 4978 | 135 | 0 | 135 | 0 |
| `B stryker filename:stryker.config` | 14 | 4928 | 3502 | 3 | 0 | 3 | 0 |
| `B stryker filename:stryker-config.json` | 11 | 1519 | 828 | 414 | 0 | 414 | 0 |
| `B infection filename:composer.json` | 16 | 6374 | 5047 | 2283 | 0 | 2283 | 0 |
| `B infection filename:infection.json` | 21 | 5707 | 3943 | 538 | 608 | 1146 | 1 |
| `B infection filename:infection.json5` | 10 | 1293 | 1242 | 19 | 0 | 19 | 0 |
| `B infection filename:infection.json.dist` | 20 | 2608 | 1925 | 35 | 608 | 643 | 1 |
| `B mutants filename:mutants.toml path:.cargo` | 6 | 1035 | 1021 | 296 | 0 | 296 | 0 |
| `B mutmut filename:setup.cfg` | 1 | 561 | 445 | 268 | 0 | 268 | 0 |
| `B mutmut filename:pyproject.toml` | 9 | 2819 | 2455 | 1323 | 0 | 1323 | 0 |
| `B cosmic-ray filename:cosmic-ray.toml` | 1 | 134 | 115 | 55 | 0 | 55 | 0 |
| `B pitest filename:pom.xml` | 22 | 12877 | 7400 | 6400 | 0 | 6400 | 0 |
| `B pitest filename:build.gradle` | 14 | 5706 | 3435 | 2090 | 0 | 2090 | 0 |
| `B pitest filename:build.gradle.kts` | 8 | 1734 | 1165 | 29 | 0 | 29 | 0 |
| `B mutant filename:.mutant.yml` | 1 | 80 | 37 | 16 | 0 | 16 | 0 |
| `B mutant filename:mutant.yml path:config` | 1 | 12 | 12 | 7 | 0 | 7 | 0 |

Truncated leaves: `B infection filename:infection.json` size:371..371 total 1608 read 1000; `B infection filename:infection.json.dist` size:371..371 total 1608 read 1000

## Funnel

- candidates 57499 -> rows 300 -> excluded 73 (maintainer 2, stale 72) -> read 227
- has-mutation-job 28, unresolved 6, tool-present-unlinked 51, no-mutation 142, error 0
- running 20, configured-not-running 5, uncertain with a mutation job 3 (runs cap 2, unsupported 0)
- duration read 20, duration pain 10
- pain yes 11, unknown 2, no 7

Pain unknown reasons (a repository can have several): history-error 2

## Per tool (running repositories)

| tool | running | every-change | scheduled | manual | other | median duration min (quartiles) | machine min per run (median) | wrapped |
|---|---|---|---|---|---|---|---|---|
| stryker | 6 | 2 | 4 | 0 | 0 | 55.6 (Q1 1.9, Q3 117.1) | 55.6 | 0 |
| mutmut | 2 | 0 | 2 | 0 | 0 | 209.0 (Q1 140.0, Q3 278.0) | 209.0 | 0 |
| pitest | 1 | 1 | 0 | 0 | 0 | 1.7 (one value) | 1.7 | 0 |
| cargo-mutants | 8 | 3 | 4 | 1 | 0 | 69.9 (Q1 22.5, Q3 203.2) | 162.3 | 0 |
| infection | 3 | 2 | 1 | 0 | 0 | 0.6 (Q1 0.5, Q3 9.1) | 0.6 | 0 |
| gremlins | 1 | 0 | 1 | 0 | 0 | 342.4 (one value) | 342.4 | 0 |

## Pain list

| repository | tool | frequency | minutes | kind | date | quote / evidence |
|---|---|---|---|---|---|---|
| https://github.com/anesis-dev/anesis-cli | cargo-mutants | scheduled | 295.2 | duration | - | median of 8 runs, `.github/workflows/ci.yml` job `mutants` |
| https://github.com/boredompeaks/perfume-store-backend | mutmut | scheduled | 71.0 | duration | - | median of 3 runs, `.github/workflows/mutation-weekly.yml` job `mutate` |
| https://github.com/breimanntools/aaanalysis | mutmut | scheduled | 347.0 | duration | - | median of 10 runs, `.github/workflows/mutation_nightly.yml` job `nightly` |
| https://github.com/erenmeren/alice | gremlins | scheduled | 342.4 | duration | - | median of 10 runs, `.github/workflows/nightly.yml` job `fuzz` |
| https://github.com/ext-sakamoro/ALICE-Zip | cargo-mutants | every-change | 38.3 | duration | - | median of 10 runs, `.github/workflows/quality-deep.yml` job `mutants` |
| https://github.com/JoaoPucci/ani-gui | cargo-mutants, stryker | scheduled | 360.3 | duration | - | median of 10 runs, `.github/workflows/mutation.yml` job `cargo-mutants` |
| https://github.com/lucasreali/hive | cargo-mutants | every-change | 101.6 | duration | - | median of 10 runs, `.github/workflows/mutants-full.yml` job `windows` |
| https://github.com/NotPellew/Thalvi | cargo-mutants | every-change | 24.0 | issue | 2026-11-20 | "On 2026-11-20, the developer chose to **replace** the advisory workspace-wide sweep with the failing high-risk `examine_globs` subset (faster runs, clear signal)." https://github.com/NotPellew/Thalvi/issues/601 |
| https://github.com/NotPellew/Thalvi | cargo-mutants | every-change | 24.0 | issue | 2026-11-13 | "PRs get a fast answer. Mutation testing runs on `main`, and a real failure there files one issue for the dispatcher." https://github.com/NotPellew/Thalvi/issues/406 |
| https://github.com/NotPellew/Thalvi | cargo-mutants | every-change | 24.0 | issue | 2026-11-13 | "Every Rust PR runs every CI job, Windows included, plus eight advisory mutants shards. PRs wait for all of that, and survivors appear only as capped annotations." https://github.com/NotPellew/Thalvi/pull/416 |
| https://github.com/NotPellew/Thalvi | cargo-mutants | every-change | 24.0 | issue | 2026-11-20 | "Its Heavy run hit the existing timeout in mutation shard 5, so the five qualification runs temporarily omitted the mutation matrix on the qualification branch." https://github.com/NotPellew/Thalvi/pull/607 |
| https://github.com/sandreialexandru/Smart-Heating-Control | stryker | every-change | 120.4 | duration | - | median of 10 runs, `.github/workflows/mutation.yml` job `card` |
| https://github.com/ttu/emergency-supply-tracker | stryker | scheduled | 107.0 | duration | - | median of 6 runs, `.github/workflows/mutation-testing.yml` job `mutation-test` |
| https://github.com/warpllm/warpllm | cargo-mutants | scheduled | 172.5 | duration | - | median of 10 runs, `.github/workflows/cron-weekly-cargo-mutants.yml` job `cargo-mutants` |

## Information (not pain, not counted)

- complaint-only or timeout texts (hand-read `information`): 15
  - halildeu/platform-web commit:940c4c4b83d5d0b5149052834ff213c4e034b430: "**Chart wrappers excluded** — tests render ECharts canvases that timeout under mutation analysis. Wrappers covered via option-shape + visual regression." https://github.com/Halildeu/platform-web/commit/940c4c4b83d5d0b5149052834ff213c4e034b430
  - halildeu/platform-web issue:200: "**Chart wrappers excluded** — tests render ECharts canvases that timeout under mutation analysis. Wrappers covered via option-shape + visual regression." https://github.com/Halildeu/platform-web/pull/200
  - manji-0/rdra-ish-dsl issue:204: "CPU cost is high. Each mutant rebuilds and reruns the corpus, which takes minutes." https://github.com/manji-0/rdra-ish-dsl/issues/204
  - notpellew/thalvi issue:247: "On a GitHub runner that is about 21s per mutant, so a whole-workspace run would take about 18 hours. Hence diff-only." https://github.com/NotPellew/Thalvi/pull/247
  - notpellew/thalvi issue:395: "#416 already made PR steps change-aware and moved diff-scoped mutation testing to the heavy tier." https://github.com/NotPellew/Thalvi/issues/395
  - notpellew/thalvi issue:403: "On #384 `ce46e6a`, shards 2 and 4 hit the 60-minute step limit after about 49 and 78 of 127 mutants. Both were green." https://github.com/NotPellew/Thalvi/pull/403
  - notpellew/thalvi issue:414: "on the main PC, 250 cargo-mutants runs wrote 577 GiB of 680 GiB in 4.5 hours on 12–13 Nov." https://github.com/NotPellew/Thalvi/issues/414
  - notpellew/thalvi issue:421: "`AGENTS.md` reads as an order to run `cargo mutants` locally (250 runs wrote 577 GiB in 4.5 hours on 12–13 Nov)" https://github.com/NotPellew/Thalvi/pull/421
  - notpellew/thalvi issue:514: "A mutant that stops an event is caught only after minutes, or reported as a timeout, and shard 4 overran its 60-minute step." https://github.com/NotPellew/Thalvi/pull/514
  - notpellew/thalvi issue:529: "**`mutants (1)`**: the shard ran out of its 60-minute step." https://github.com/NotPellew/Thalvi/pull/529
  - notpellew/thalvi issue:621: "All eight shards also hit the separate 60-minute action cap." https://github.com/NotPellew/Thalvi/pull/621
  - notpellew/thalvi issue:733: "On 2026-11-26 four dev-job jobs (two `cargo mutants`) pushed the load to about 70 on 16 threads." https://github.com/NotPellew/Thalvi/issues/733
  - notpellew/thalvi issue:754: "Running these for hours on the owner's main PC competes with training and interactive work." https://github.com/NotPellew/Thalvi/pull/754
  - psyhfm/staff-engagement-poc issue:11: "**Stryker is local-only** (not in CI) for runtime reasons." https://github.com/psyHFM/Staff-Engagement-POC/pull/11
  - psyhfm/staff-engagement-poc issue:28: "Deferred (user-run heavy steps): PITest/JaCoCo on employee (Group 5.4) and local Stryker run (6.6)." https://github.com/psyHFM/Staff-Engagement-POC/pull/28
- narrowing changes whose text mentions a timeout: 1
  - Halildeu/platform-web 940c4c4
- configured-not-running: 5
  - 3rikF/ConsoleProgress
  - Syavne/d-OAuth-Server
  - clementefalcone/goya-ledger
  - kotteletfisk/mtogo
  - tongxin779977/VectaHub
- uses-action matches: 0
- excluded maintainer repositories that run mutation testing in CI: 0

## Hand check (AC4)

samples: pain-yes 11, running 20, not-running 10, tool-present-unlinked 10, rejected 10, uses-action 0; missing verdicts 61; failures none; rule fix required: no.

- pain-yes: JoaoPucci/ani-gui, NotPellew/Thalvi, anesis-dev/anesis-cli, boredompeaks/perfume-store-backend, breimanntools/aaanalysis, erenmeren/alice, ext-sakamoro/ALICE-Zip, lucasreali/hive, sandreialexandru/Smart-Heating-Control, ttu/emergency-supply-tracker, warpllm/warpllm
- running: DhirendraHudda98/ParkIndia, Gusto/baerly-storage, Halildeu/platform-web, JoaoPucci/ani-gui, Lex-Studios/Stellar-Spend, NotPellew/Thalvi, SuarezPM/kitty-code, anesis-dev/anesis-cli, boredompeaks/perfume-store-backend, breimanntools/aaanalysis, codeigniter4/shield, eclipxe13/enum, erenmeren/alice, ext-sakamoro/ALICE-Zip, lucasreali/hive, manji-0/rdra-ish-dsl, psyHFM/Staff-Engagement-POC, sandreialexandru/Smart-Heating-Control, ttu/emergency-supply-tracker, warpllm/warpllm
- not-running: BestDevOfc/CTFs_and_hacking_solutions, CSCI-435-SE/excalidraw, clementefalcone/goya-ledger, ensj/trade-blotter, hongyime/sgConnectSphere2026, jmandel/smart-permission-tickets-ri, noam0127/beagu-index, radarlabs/radar-sdk-js, shivyadavus/open-kioku, triciaaleee/SPM-G6T5
- tool-present-unlinked: Azure/aks-durable-agents, Raftersecurity/rafter-secrets, Shehabhub/ORVION, TrillionniumFoundation/HeptaKernel, Vaddi-Srisanth/Ion_IDE, assertpy/assertpy, evelagin/evetis-wb-analytics, lecomputeur/vibez, luis-mc/dev-standards, unicity-sphere/sphere-sdk
- rejected: gusto/baerly-storage|issue:400, halildeu/platform-web|issue:103, halildeu/platform-web|issue:1036, halildeu/platform-web|issue:917, lex-studios/stellar-spend|issue:1223, lex-studios/stellar-spend|issue:1522, lex-studios/stellar-spend|issue:1560, lex-studios/stellar-spend|issue:668, notpellew/thalvi|issue:304, psyhfm/staff-engagement-poc|issue:33

## Budget

- chunk 1: 150 candidates, 2573 requests, 17.15 per candidate, 129.0 per running repository, X-RateLimit-Remaining {'core': 3646}, 102.7 min, methods ['GET'], stopped None
- chunk 2: 150 candidates, 2721 requests, 18.14 per candidate, 66.2 per running repository, X-RateLimit-Remaining {'core': 698}, 127.2 min, methods ['GET'], stopped None
- pool: 58715, requests per candidate observed 17.15, requests per running repository observed 129.0, X-RateLimit-Remaining observed {'core': 3646}, fits 24 h: no

## Limits

- Files read on default branches only; public repositories only; GitHub Actions only.
- Code search is legacy code search (punctuation ignored, 1,000 results per query); unread hits of truncated leaves are counted in N as possible repositories.

## Desk survey (§6)

Date checked: 2026-11-25

| product | what is sold | public price | official URL | status (VERIFIED quote / UNVERIFIED) |
|---|---|---|---|---|
| mutant (Ruby, mbj/mutant) | Commercial subscription to run mutant on commercial code, per developer (identified by git author email), any number of private repos | 30$ / 1 month; 250$ / 1 year (also 30€ / 250€); "per developer using mutant on any number of repositories" | https://github.com/mbj/mutant/blob/main/docs/commercial.md | VERIFIED: "Costs are **per developer using mutant on any number of repositories**." Table rows: "USD \| 1 month \| 30$" and "USD \| 1 year \| 250$". (A search summary of older docs cited $300/year; the current page says 250$.) |
| Arcmutate | Commercial extensions/plugins for PIT (pitest), Java/Kotlin mutation testing | none published (could not check) | https://www.arcmutate.com/ | UNVERIFIED: host does not resolve from this sandbox (network allowlist); web search returned no pricing page. |
| Stryker Dashboard | Hosted storage and display of Stryker mutation reports, plus a mutation-score badge | none published (no paid tier found) | https://dashboard.stryker-mutator.io/ (source: https://github.com/stryker-mutator/stryker-dashboard) | UNVERIFIED for price: dashboard site blocked from sandbox. GitHub repo page opened: "the place to host your mutation testing reports online"; Apache-2.0; it mentions no pricing. |
| Mutahunter (codeintegrity-ai) | Open-source LLM-based mutation testing tool; you pay the LLM provider for tokens. No hosted or paid tier found | none published (AGPL-3.0; LLM API cost per run) | https://github.com/codeintegrity-ai/mutahunter | VERIFIED (no-price offer): "Open Source, Language Agnostic Mutation Testing"; README sample shows "Total Cost: $0.00060 USD" (LLM spend). |
| Mutator (mutator.app) | Web-based (hosted) mutation testing and code-transformation tool | none published (GetApp lists free trial / free version) | https://mutator.app/ | UNVERIFIED: host blocked from sandbox. Only third-party listings (GetApp/Capterra) seen, with no price. |
| Diffblue Cover | AI unit-test generation for Java. Not confirmed to sell mutation testing | n/a (not checked) | https://www.diffblue.com/pricing | UNVERIFIED: host blocked from sandbox. Mutation testing was not confirmed as a product feature, so it is listed only as an excluded candidate. |

Excluded: Meta ACH (mutation-guided LLM test generation, arXiv 2501.12862) and Sapienz are internal research systems, not products for sale. No Codecov/Sentry mutation-testing offer was found.

Limits: this sandbox's network allowlist blocked most vendor domains (arcmutate.com, dashboard.stryker-mutator.io, mutator.app, diffblue.com), so only pages on GitHub could be opened. Rows marked UNVERIFIED rely on search snippets or nothing and should be re-checked from an unrestricted network. No vendor was contacted. None of the products found sells "faster mutation runs" as a separately priced service.

