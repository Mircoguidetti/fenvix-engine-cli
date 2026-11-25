# Pre-registration: public count of repositories that run mutation testing in CI, and its time pain

Committed before any data (no search request, probe or REST read of a candidate before this file's commit).
Spec: test-quality-count rev 3 (gate 7/10, founder D7 = A, 2026-11-25). Every later change to a rule, regex, query,
threshold or budget is listed in `CHANGES.md` and at the top of `REPORT.md` with its justification, before any result.

## Decision line (founder, fixed; not reopened)

By 8 Dec 2026, if the research does not find at least **100** public repositories running mutation testing in CI, at
least **20** of which show time pain (a mutation job of **30 minutes** or more, or a dated commit or issue that
reduced, moved or disabled it for time or cost), the new-test quality idea is dropped.

- **CONTINUE**: `running` >= 100 and pain `yes` >= 20 (actual rows), and the AC4 hand check passes.
- **DROP (a)**: every candidate read, no leaf truncated or `incomplete`, and (`running` + `uncertain`) < 100 or
  (pain `yes` + pain `unknown` + `uncertain`) < 20.
- **DROP (b)**: read >= 300, no leaf `incomplete`, and U_R x N < 100 or U_P x N < 20 (Wilson 95% upper bounds,
  z = 1.96, of (running + uncertain) / read and (pain yes + pain unknown + uncertain) / read).
- **NO DECISION**: discovery exceeds 24 h, or the 24 h reading budget (from the end of discovery) ends first.

Every rule that could hide a mutation run in CI sends the repository to `uncertain` or pain `unknown`, never to "no".

## Constants

| Name | Value |
|---|---|
| `WINDOW_START` | `2026-01-01` (runs listed with `created>=2026-01-01`; candidates with `pushed_at` before it excluded) |
| `HISTORY_START` | `2024-01-01` (**Interpretation**: "dated" = on or after 1 Jan 2024) |
| Runs cap | 50 inspected runs per mutation job (newest first); duration from up to 10 run values |
| Duration pain | maximum over running mutation jobs of the median job wall time >= 30.0 minutes |
| History cap | 300 requests per repository (every §4 request counted, issues search included) |
| Chunk | up to 150 candidates per workflow chunk |
| Code search pace | <= 9 requests/min; issues search <= 25 requests/min; 429 waits parsed as `retry_seconds` (message wins: `try again in X(ms|s)`, then `Retry-After`, then reset, else 60 s) |
| User-Agent | `fenvix-research`; sleep when `X-RateLimit-Remaining` < 50 until reset |
| Order | candidates sorted by `html_url`, then `random.Random(1).shuffle(list)` once |

## §0 Probes (after the coordinator's "search budget free")

(a) `stryker path:.github/workflows` from the workflow (`GITHUB_TOKEN`) and from the work session
(`gh api -X GET search/code`); code search uses the route with the larger `total_count`. (b) One query of each §1.B
shape: `stryker filename:package.json` (term + `filename:`) and `mutants filename:mutants.toml path:.cargo`
(term + `filename:` + `path:`). (c) One real §4.3 issues query from both routes; §4.3 uses the route that answers
HTTP 200 without 429 (session preferred). A shape answered 422, an error, or `total_count` 0 is fixed or dropped
before discovery and listed in REPORT; never recorded as 0. Neither code-search route HTTP 200 -> REPORT first line
`BLOCKED`. Raw JSON committed under `results/probe_*.json`.

## §1 Discovery

Each query is bisected by `size:` (start `size:0..400000`, split at the midpoint until `total_count` <= 1,000 or a
single size). Per leaf: `total_count`, `incomplete_results`, results read, `truncated` (`total_count > 1000` or
`incomplete_results`). An incomplete leaf is retried 3 times, the largest `total_count` kept, else `incomplete`.

**A. Workflow files** (`path:.github/workflows`), one query per term: `stryker`, `mutmut`, `cosmic-ray`, `pitest`,
`mutationCoverage`, `cargo-mutants`, `"cargo mutants"`, `infection`, `mutant`, `go-mutesting`, `gremlins`,
`mull-runner`, `muter`, `mutatest`, `mutation`.

**B. Tool files**: `stryker filename:package.json`, `stryker filename:stryker.conf`, `stryker filename:stryker.config`,
`stryker filename:stryker-config.json`, `infection filename:composer.json`, `infection filename:infection.json`,
`infection filename:infection.json5`, `infection filename:infection.json.dist`,
`mutants filename:mutants.toml path:.cargo`, `mutmut filename:setup.cfg`, `mutmut filename:pyproject.toml`,
`cosmic-ray filename:cosmic-ray.toml`, `pitest filename:pom.xml`, `pitest filename:build.gradle`,
`pitest filename:build.gradle.kts`, `mutant filename:.mutant.yml`, `mutant filename:mutant.yml path:config`.

Candidates = distinct repositories (case-insensitive full name) over all leaves of both families; each keeps its hit
terms and files. N = distinct candidates + sum of max(0, `total_count` - results read) over truncated leaves. After
discovery REPORT prints each query's contribution to N (distinct repositories first found by it plus its unread hits)
and `DROP reachable via U_P at r >= max(300, floor(3.8416*N/20 - 3.8416) + 1)`.

Exclusions (from `GET /repos/{r}`, applied when the candidate is read, never counted as read): fork; archived;
`pushed_at` before `WINDOW_START`; owner (case-insensitive) in {mircoguidetti, stryker-mutator, boxed, sixty-north,
hcoles, pitest, arcmutate, szpak, sourcefrog, infection, mbj, mull-project, muter-mutation-testing, go-gremlins,
zimmski}. Excluded maintainer repositories that run mutation testing in CI are listed as information, not counted.

**Interpretation**: only GitHub Actions is covered; other CI systems are printed as a limit next to the decision.

## §2 Per-candidate exact check

1. **Files**: `GET /repos/{r}/git/trees/{default_branch}?recursive=1`. If `truncated: true`, fall back to the contents
   API for `.github/workflows` and the root of the repository (the §1.B tool files and the §2.4 script files:
   `package.json`, `Makefile`, `composer.json`, `justfile`, `Taskfile.yml`, `Rakefile`, and `.sh` files reached by
   a command). Workflow files: `.github/workflows/*.yml|*.yaml`. Tool files: basenames `package.json` (only listed),
   `stryker.conf*`, `stryker.config*`, `stryker-config.json`, `composer.json`, `infection.json*`, `.cargo/mutants.toml`,
   `setup.cfg`, `pyproject.toml`, `cosmic-ray.toml`, `pom.xml`, `build.gradle`, `build.gradle.kts`, `.mutant.yml`,
   `config/mutant.yml`. YAML parsed with PyYAML 6.0.2 (pinned), the `on:` -> `True` key restored to `on`.
2. **Commands**: each step `run:` split on newlines, `&&`, `||`, `;`, `|` outside quotes (backslash-newline joins).
   Install commands dropped: `INSTALL_RE` = `\b(pip3?|python3? -m pip|uv pip|poetry|gem|bundle|npm|yarn|pnpm|apt(-get)?|brew|go)\s+(install|i|add|ci|get|mod download)\b`
   extended with `\bcomposer\s+(require|install|update)\b`, `\bcargo\s+(install|binstall)\b`,
   `\bdotnet\s+tool\s+(install|update|restore)\b`, `\bgo\s+install\b`, `\bgem\s+install\b`, `\bpipx\s+install\b`.
   **Script resolution is tried on the raw command first** (gate note 5); then prefixes are stripped and resolution
   is tried again on the stripped command; then the stripped command is matched. Stripping is repeated until stable:
   leading `VAR=value` tokens; `env` with its `VAR=value` arguments and flags; a leading `./`; `node_modules/.bin/`;
   `poetry run`, `uv run`, `pdm run`, `hatch run`, `pipenv run`, `python3? -m`, `npx( -y| --yes)?`,
   `npm exec( --)?`, `pnpm (exec|dlx)`, `yarn dlx`, a bare `yarn <x>` only when `<x>` is not a `package.json`
   script, `bunx`, `dotnet tool run`, and a `+<toolchain>` argument after `cargo`.
3. **Mutation command** (regexes on the stripped command, case-sensitive as written):

| Tool | Command regex | Not a mutation run |
|---|---|---|
| StrykerJS / Stryker.NET / Stryker4s | `^stryker run\b`, `^dotnet[- ]stryker\b`, `^sbt\b.*\bstryker\b` | `stryker init`, `stryker --version` |
| mutmut | `^mutmut run\b` | `mutmut results\|show\|html` |
| cosmic-ray | `^cosmic-ray exec\b` | `cosmic-ray init`, `baseline` |
| PIT (Maven) | `^mvnw?\b` with an explicit goal `pitest:mutationCoverage`, `pitest:scmMutationCoverage` or `org.pitest:pitest-maven(:[\w.-]+)?:(scm)?[mM]utationCoverage`; or a lifecycle phase at or after the bound phase of a `pitest-maven` `<execution>` with goal `mutationCoverage`/`scmMutationCoverage` (default phase `verify`) in the root `pom.xml` `<build><plugins>`, in a child module `pom.xml` listed in `<modules>`, or in a `-P<profile>` the command activates; `pitest-maven` only in `<pluginManagement>` (execution phase reached) -> `unresolved`; a `<parent>` POM not in the repository with the phase at or after `verify` and no execution found -> `unresolved` (name `parent POM`, so it counts only with a tool term in the job or step name) | `mvn test`/`mvn package` with the execution bound to `verify` |
| PIT (Gradle) | `^gradlew?\b` with a task argument matching `^(:[\w-]+)*:?pitest\w*$`; a task not named `pitest*` while the root build file (or a build file that was a discovery hit) matches `dependsOn.*pitest` or `finalizedBy.*pitest` -> `unresolved` (**Interpretation**: the spec's `dependsOn(.*pitest` is read as the regex `dependsOn.*pitest`, so `check.dependsOn pitest` and `dependsOn("pitest")` both match) | `-x pitest`, `--exclude-task pitest` |
| cargo-mutants | `^cargo[- ]mutants\b` | `cargo install\|binstall cargo-mutants` |
| Infection | `^(php )?((vendor\|tools)/bin/\|bin/)?infection(\.phar)?\b` | `composer require ... infection` |
| mutant (Ruby) | `^(bundle exec )?mutant run\b` | |
| Go | `^go-mutesting\b`, `^gremlins unleash\b` | |
| Mull / Muter / mutatest | `^mull-runner\b`, `^muter(\s\|$)`, `^mutatest\b` | |

   A step `uses:` whose action name contains (case-insensitive) `stryker`, `mutmut`, `pitest`, `cargo-mutants`,
   `infection` or `mutation` is a mutation step (`uses-action`); every match is listed in REPORT and in the AC4 sample.
4. **Script resolution, up to 3 levels**: npm/yarn/pnpm scripts (`npm run X`, `npm test`, `yarn X`, `pnpm X`);
   `make` (any target, `-C dir`, prerequisites, recursive `make`/`$(MAKE)`); `tox -e X` (`[testenv:X] commands`);
   `nox -s X`; composer `scripts` (`composer X`, `composer run(-script) X`, string or list bodies, `@other`
   references, `@php` -> `php`); Rakefile tasks (`rake X`, `bundle exec rake X`, `bin/rake X`: the `sh "..."` /
   `sh '...'` / backtick lines of the named task's block, and its prerequisites); `just X` recipes (`justfile`,
   `Justfile`, `.justfile`; recipe lines and dependencies); `task X` (`Taskfile.yml|yaml`: `cmds` strings, `cmd:`
   and `task:` entries, `deps`); shell scripts (a command whose first token is a path ending in `.sh`, or
   `bash|sh [flags] <path>`: the file is fetched, comment lines dropped, lines split as commands). A missing
   script/target/task/file, or a fourth level, is an unresolved item named after it.
5. **Tool terms** (case-insensitive, word-bounded): `stryker`, `mutmut`, `cosmic-ray`, `pitest`, `mutationCoverage`,
   `cargo-mutants`, `cargo mutants`, `go-mutesting`, `gremlins`, `mull-runner`, `muter`, `mutatest`; `infection` only
   next to `php`, `vendor/bin`, `bin/`, `tools/`, `.phar` (`php\s+(\S+/)?infection`, `(vendor/bin|tools|bin)/infection`,
   `infection\.phar`) or anywhere in a `composer.json`; `mutant` only in a repository whose root `Gemfile` or a root
   `*.gemspec` names `mutant`; `mutation` only inside a script, target, job or step name. Generic
   `mutation`/`mutant` elsewhere is not a tool term.
6. **Row class**: `has-mutation-job` (a job with a mutation step); else `unresolved` (an unresolved item in a workflow
   job whose name contains a tool term, or which sits in a job or step whose name contains one); else
   `tool-present-unlinked` (a tool term in a workflow file, or in a script, target or file reached from a workflow
   step, with no mutation command linked); else `no-mutation`. An unresolvable command without a tool term in its
   name, job or step is ignored. `workflow_call` workflows are followed through their caller (job name
   `<caller> / <callee>`). `unsupported` = a `workflow_call` workflow with a mutation job and no caller in the
   repository, or an `on:` that does not parse. **Interpretation**: a workflow file that does not parse as YAML makes
   the row `uncertain` (`error`) only when its text matches `(?i)mutat|stryker|pitest|infection|mutmut|cosmic-ray|gremlins|muter|mull`; otherwise it is ignored.
7. **Frequency** of a mutation job: events from `on:`; a job-level `if:` built only from
   `github.event_name (==|!=) '<literal>'` atoms, `||`, `&&` and parentheses filters them; any other `if:` is ignored
   and flagged `if-complex`. `every-change` if `pull_request`, `pull_request_target`, `merge_group`, or `push`
   (unless its filter has `tags`/`tags-ignore` and no `branches`/`branches-ignore`) reaches it; else `scheduled`
   (`schedule`); else `manual` (`workflow_dispatch`, `release`, tags-only `push`); else `other`. For a called
   workflow, the caller's `on:` and the caller job's `if:` are used.
8. **Running** per mutation job: `GET /repos/{r}/actions/workflows/{file}/runs?created=>=2026-01-01&per_page=100`
   (`&event=schedule` when the job is reachable only by `schedule`), newest first, at most 50 runs inspected (jobs
   API per run). `running` when an inspected run has the job with `conclusion` `success` or `failure` and the mutation
   step found and not `skipped`. None in 50 inspected while more runs exist -> `uncertain`; none and no more ->
   `configured-not-running`. Repository: any mutation job `running` -> `running`; else any job `uncertain` ->
   `uncertain`; else `configured-not-running`, but `uncertain` if the repository also has an `unresolved` or
   `tool-present-unlinked` item.

Row status for the stop rule: `running`; `not-running` (`no-mutation`, `configured-not-running`); `uncertain`
(`unresolved`, `tool-present-unlinked`, `unsupported`, runs-cap case, API/YAML error after one retry).

## §3 Duration (running repositories only)

**Interpretation**: "a mutation job of 30 minutes or more" = the median, over up to 10 recent runs, of the mutation
job's wall time (`completed_at - started_at` of the job, longest leg).

From the runs already listed (same 50-run cap): each matching leg with `conclusion` `success` or `failure` and the
mutation step found and not `skipped` gives its wall time; a leg `cancelled` at its timeout gives a lower-bound
value equal to its wall time. Timeout: the mutation step's `timeout-minutes`, else the job's, else 360; a `${{ }}`
expression -> unknown, and a cancelled leg gives no value. "At its timeout" = wall time >= timeout - 1 minute. Run
value = longest leg; also recorded: sum over legs (machine minutes) and sum of the mutation steps' times (step
minutes), report only. Median over up to 10 run values (mean of the two middle values when even); fewer than 3 ->
`too_few_runs`. Repository duration = maximum median over running mutation jobs; **duration pain** = >= 30.0 min.
`wrapped` when the mutation command came through a Maven lifecycle phase, `npm|yarn|pnpm test`, or `make test*`.

## §4 History pain (running repositories without duration pain)

Hard cap 300 requests per repository; at the cap before history is complete, pain is `unknown` unless already `yes`.

1. **Commits**: `GET /repos/{r}/commits?path=.github/workflows&since=2024-01-01T00:00:00Z` and the same for each tool
   configuration file in the tree (`stryker.conf*`, `stryker.config*`, `stryker-config.json`, `infection.json*`,
   `.cargo/mutants.toml`, `cosmic-ray.toml`, `.mutant.yml`, `config/mutant.yml`) and for each script file §2.4 went
   through to reach a mutation command (gate note 8). For each listed commit one `GET /repos/{r}/commits/{sha}`.
   A file is fetched at the commit and at its parent (`contents?ref=`) only when a patch line touches a tool term or
   a flag below. **Interpretation**: for workflow files "flag" also covers `if:` lines and trigger keys (`on:`,
   `push`, `pull_request`, `pull_request_target`, `merge_group`, `schedule`, `workflow_dispatch`, `branches`, `tags`,
   `cron`), so a trigger edit on a mutation workflow is seen. A file added or deleted by the commit (status in
   `commits/{sha}`, or 404) is "absent", never `history-error`. Workflow pairs are compared per mutation job; in
   history a mutation step is a step whose stripped commands match §2.3 directly, which invokes a script, target or
   task whose name contains a tool term, or a `uses-action`. Kinds:
   - `moved-off-change`: a mutation job reachable by `every-change` at the parent is not at the commit; or, in one
     commit or in commits of one pull request (`GET /repos/{r}/commits/{sha}/pulls`), a mutation command removed from
     an `every-change` workflow and added to a `scheduled` or `manual` one;
   - `narrowed`: a flag added that limits mutants to changed code (`--incremental`, `incremental: true`, `--since`,
     `--in-diff`, `--git-diff-filter`, `--git-diff-lines`, `--git-diff-base`, `scmMutationCoverage`, `+GIT`,
     `withHistory`, `historyInputFile`, or a `--mutate`/`--paths-to-mutate`/`--file` value built from `git diff`);
   - `cut`: a limit added or lowered (`--shard`, `maxMutationsPerClass`, `max[_-]?mutants`, `mutation[_-]?limit`,
     `--sample`), or the `mutators`/`mutate` list shorter;
   - `disabled`: the mutation step or job removed (and not added elsewhere in the same commit or pull request),
     commented out, or given `if: false`.
   Non-YAML tool configs and script files are compared by flags added in `+` patch lines (not present in `-` lines),
   by a mutation command present in `-` lines and absent from `+` lines (`disabled`), and by the length of the
   `mutate`/`mutators` list where both versions parse. An API error or an unparsable fetched YAML -> `history-error`.
2. **Recall filter** (case-insensitive) on the commit message and its pull request title and body:
   `\b(slow\w*|speed( ?up)?|speeds?|faster|too long|takes?|took|time ?outs?|timed out|minutes?|mins?|hours?|hrs?|performance|expensive|costs?|costly|budget|billing|quota|ci (time|minutes)|resources?|heavy|save time|reduce time)\b`
   (gate note 11 added `speeds?`, `save time`, `reduce time`). A narrowing change with a match is a pain candidate.
3. **Issues and pull requests**: per tool found in the repository plus `mutation`:
   `repo:<r> <tool> (slow OR timeout OR minutes OR hours OR expensive) created:>=2024-01-01`, first 30 results, <= 25
   requests/min, on the §0.2c route. Query terms per tool: `stryker`, `mutmut`, `cosmic-ray`, `pitest`,
   `cargo-mutants`, `infection`, `mutant`, `go-mutesting`, `gremlins`, `mull`, `muter`, `mutatest`. Each hit is a
   pain candidate. A query that still errors after the 429 retries -> `history-error`.
4. **Hand read** (work session) of every pain candidate: `confirmed` only when the text says the mutation run was
   reduced, moved or disabled because of time or cost (one-line quote and URL recorded); complaint only or a
   `timeout-minutes` raise -> `information`; else `rejected`. Stored in `results/handreads.jsonl`.
5. **Pain**: `yes` = duration pain, or a `confirmed` candidate dated on or after 2024-01-01; `unknown` = not `yes`
   and any of `too_few_runs` on a mutation job, a `history-error`, a pain candidate not hand-read, the runs cap
   reached with fewer than 3 values, the 300-request cap reached; `no` otherwise.

## §5 Execution

Discovery in the work session as a harness-tracked task with `results/discovery_state.json` checkpoints committed every
30 minutes; §2-§4.3 in workflow chunks of up to 150 candidates (`requests/<n>.json`), rows committed back; after each
chunk the session does the §4.4 hand reads and the decision check, then pushes the next request file. The work
session never reads third-party REST itself: every text it hand-reads is stored in the committed rows.

## Hand check (AC4)

Before CONTINUE or DROP: all pain `yes` repositories (up to 40), 20 random `running`, 10 random `not-running`,
10 random `tool-present-unlinked`, 10 random rejected pain candidates and every `uses-action` match, each against the
workflow file, one run's job page and the quoted text. Random samples use `random.Random(2)` over the sorted repository
names. More than 2 of the 20 random `running` failing, or any running repository among the `not-running` or
`tool-present-unlinked` samples -> stop, fix the rule as a listed change, re-run on every read row.

## Limits printed next to the decision

Covered: GitHub Actions, the tools listed above. Not covered: other CI systems, private repositories, tools not
listed. Files read on default branches only; truncated leaves listed.
