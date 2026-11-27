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

**KEEP READING: read 115, running 10, pain yes 4, U_R×N 24699.2, U_P×N 22580.0.**

covered: GitHub Actions, tools stryker (JS/.NET/Scala), mutmut, cosmic-ray, PIT (Maven, Gradle), cargo-mutants, Infection, mutant, go-mutesting, gremlins, Mull, Muter, mutatest; not covered: other CI systems, private repositories, tools not listed.

read 115, running 10, not-running 77, uncertain 28; pain yes 4, unknown 2, no 4; N 58715; U_R 0.42066 (U_R×N 24699.2), U_P 0.38457 (U_P×N 22580.0); whole frame read: no; truncated leaves: 2; incomplete leaves: 0; hand check: not passed.

## Discovery

leaves 341, candidates 57499, unread hits on truncated leaves 1216, N 58715.
DROP reachable via U_P at r >= 11275 (assumes no uncertain or unknown rows).

Observed uncertain share 0.243; DROP still reachable within the frame: no.

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

- candidates 57499 -> rows 150 -> excluded 35 (maintainer 1, stale 34) -> read 115
- has-mutation-job 12, unresolved 2, tool-present-unlinked 26, no-mutation 75, error 0
- running 10, configured-not-running 2, uncertain with a mutation job 0 (runs cap 0, unsupported 0)
- duration read 10, duration pain 4
- pain yes 4, unknown 2, no 4

Pain unknown reasons (a repository can have several): history-error 2

## Per tool (running repositories)

| tool | running | every-change | scheduled | manual | other | median duration min (quartiles) | machine min per run (median) | wrapped |
|---|---|---|---|---|---|---|---|---|
| stryker | 4 | 1 | 3 | 0 | 0 | 2.7 (Q1 1.1, Q3 29.9) | 2.7 | 0 |
| mutmut | 1 | 0 | 1 | 0 | 0 | 347.0 (one value) | 347.0 | 0 |
| cargo-mutants | 3 | 1 | 1 | 1 | 0 | 38.3 (Q1 28.2, Q3 166.7) | 253.0 | 0 |
| infection | 2 | 1 | 1 | 0 | 0 | 0.5 (Q1 0.4, Q3 0.6) | 0.5 | 0 |

## Pain list

| repository | tool | frequency | minutes | kind | date | quote / evidence |
|---|---|---|---|---|---|---|
| https://github.com/anesis-dev/anesis-cli | cargo-mutants | scheduled | 295.2 | duration | - | median of 8 runs, `.github/workflows/ci.yml` job `mutants` |
| https://github.com/breimanntools/aaanalysis | mutmut | scheduled | 347.0 | duration | - | median of 10 runs, `.github/workflows/mutation_nightly.yml` job `nightly` |
| https://github.com/ext-sakamoro/ALICE-Zip | cargo-mutants | every-change | 38.3 | duration | - | median of 10 runs, `.github/workflows/quality-deep.yml` job `mutants` |
| https://github.com/ttu/emergency-supply-tracker | stryker | scheduled | 107.0 | duration | - | median of 6 runs, `.github/workflows/mutation-testing.yml` job `mutation-test` |

## Information (not pain, not counted)

- complaint-only or timeout texts (hand-read `information`): 3
  - halildeu/platform-web commit:940c4c4b83d5d0b5149052834ff213c4e034b430: "**Chart wrappers excluded** — tests render ECharts canvases that timeout under mutation analysis. Wrappers covered via option-shape + visual regression." https://github.com/Halildeu/platform-web/commit/940c4c4b83d5d0b5149052834ff213c4e034b430
  - halildeu/platform-web issue:200: "**Chart wrappers excluded** — tests render ECharts canvases that timeout under mutation analysis. Wrappers covered via option-shape + visual regression." https://github.com/Halildeu/platform-web/pull/200
  - manji-0/rdra-ish-dsl issue:204: "CPU cost is high. Each mutant rebuilds and reruns the corpus, which takes minutes." https://github.com/manji-0/rdra-ish-dsl/issues/204
- narrowing changes whose text mentions a timeout: 1
  - Halildeu/platform-web 940c4c4
- configured-not-running: 2
  - clementefalcone/goya-ledger
  - kotteletfisk/mtogo
- uses-action matches: 0
- excluded maintainer repositories that run mutation testing in CI: 0

## Hand check (AC4)

samples: pain-yes 4, running 10, not-running 10, tool-present-unlinked 10, rejected 10, uses-action 0; missing verdicts 44; failures none; rule fix required: no.

- pain-yes: anesis-dev/anesis-cli, breimanntools/aaanalysis, ext-sakamoro/ALICE-Zip, ttu/emergency-supply-tracker
- running: DhirendraHudda98/ParkIndia, Gusto/baerly-storage, Halildeu/platform-web, Lex-Studios/Stellar-Spend, anesis-dev/anesis-cli, breimanntools/aaanalysis, eclipxe13/enum, ext-sakamoro/ALICE-Zip, manji-0/rdra-ish-dsl, ttu/emergency-supply-tracker
- not-running: RedGarland/the-blue-fern-co-dispatches, danthespal/Backport, indonetsoft-acc/api, joshvern/citylens-web, loophp/phptree, lyse-labs/lyse, povio/ai-reviewer, priyamsinghjhs/kareshafaa, rowan-vr/memuki, triciaaleee/SPM-G6T5
- tool-present-unlinked: AtyaLibraries/Atya.Templates.UiAutomation, Azure/aks-durable-agents, TOOleksandr-0101/TeleBlast, callstack/agent-device, civictechdc/dc-reentry-unlocked, coreyleavitt/sello, deniskorbakov/skeleton-php-docker, evelagin/evetis-wb-analytics, lml-layer-system/agent-buccet, luis-mc/dev-standards
- rejected: gusto/baerly-storage|issue:142, gusto/baerly-storage|issue:84, halildeu/platform-web|issue:1086, halildeu/platform-web|issue:1096, halildeu/platform-web|issue:1178, halildeu/platform-web|issue:1179, halildeu/platform-web|issue:839, halildeu/platform-web|issue:937, lex-studios/stellar-spend|issue:1572, lex-studios/stellar-spend|issue:1576

## Budget

- chunk 1: 150 candidates, 2573 requests, 17.15 per candidate, 129.0 per running repository, X-RateLimit-Remaining {'core': 3646}, 102.7 min, methods ['GET'], stopped None
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

