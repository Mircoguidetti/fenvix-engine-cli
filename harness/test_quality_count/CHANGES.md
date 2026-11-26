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
