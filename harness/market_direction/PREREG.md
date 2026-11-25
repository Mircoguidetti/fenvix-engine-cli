# PREREG: market direction check (suite growth with agents; where the money goes)

Committed before any data is fetched (AC1). Spec: "Market direction check" (coordinator prompt of 2026-11-24, rev 3
gate 7/10) with quality-gate notes 1-16 applied; notes 1-15 are copied verbatim in "Gate notes" below and are part
of the rules. Rules reused (not code) from the db-serial-count PREREG (`origin/claude/db-serial-count`,
`harness/db_serial_count/PREREG.md`, same rules as spec rev 5): §1 (discovery bisection), §2 item 2 ("§2.2" here:
test steps), §3 items 2-4 ("§3.2-§3.4" here: job matching, step matching, median), and its rate rule ("rule 7").
Any change after this commit is reported on its own line in `REPORT.md` under "Changes after PREREG", with its
justification, before any result, and needs the coordinator's approval.

**Launch date:** the UTC date of this commit = **2026-11-24**. "Launch date" below always means this date.

## Line (memo, verbatim, 15 Dec 2026)

If test suites in agent-using repositories do not grow faster than in the matched control group (median 6-month
growth), AND disclosed 2025-2026 funding for AI evaluation tools is at least 3 times that of test speed and
reliability tools, the market choice is reopened with a new /office-hours after the 22 Dec verdict. If either does
not hold, the direction stands and the numbers are recorded.

## Constants

| Name | Value |
|---|---|
| Launch date | 2026-11-24 |
| Staleness cut (`pushed_at`, control `pushed:>=`) | launch - 30 d = 2026-10-25 |
| T0 upper bound | 2026-05-24 (inclusive) |
| T0_MIN | **2026-04-01** (second commit, after the §0.3 probe, before any candidate is read): oldest listed runs nodejs/node 2025-12-21, python/cpython 2025-12-28, microsoft/vscode 2025-12-12 (day bisection; each listing `total_count` 40,000 > 1,000; `results/probe/retention.json`, workflow run 45463684419); latest 2025-12-28 + 90 d = 2026-03-28, rounded up to 2026-04-01 |
| T0_MIN if the retention probe fails (note 9) | launch - 400 d + 90 d = 2026-01-18, rounded up to the first of a month = **2026-02-01** |
| D0 window | `created_at` in [T0 - 90 d, T0) |
| D1 window | `created_at` in [T0 + 182 d, min(T0 + 272 d, read time)] |
| Runs per window | 10 (median = mean of the 5th and 6th sorted values, seconds) |
| Pairs | stop at 200 complete pairs; fewer than 100 at the end -> Part 1 `NO DECISION` |
| Reading budget | 24 h after discovery; 48 h if fewer than 100 pairs are projected after 10 pairs; never past 2026-12-13 23:59 UTC |
| Discovery budget | 24 h |
| Controls tested per agent repository | at most 100 |
| Seeds | frame `random.Random(1)`; control `random.Random(<agent repo id>)`; bootstrap `random.Random(2)`; hand check `random.Random(3)` |
| Funding window | 2025-01-01 to 2026-11-24 (inclusive) |
| R threshold | R >= 3 |
| Part 2 failure | more than 25% of the 39 seed companies `UNVERIFIED` |
| User-Agent | `fenvix-research` (GitHub API and web fetches) |
| Web fetch tool | Python `requests` 2.34.2, redirects followed manually (at most 5), timeout 30 s, GET only |
| YAML | PyYAML (`yaml.safe_load`) |

## Gate notes (rev 3 gate, verbatim; part of the rules)

1. Pre-register in PREREG, before any fetch: seed name -> exact home URL table (follow up to 5 redirects, classify the final page, record final URL and status); per company fixed WebSearch queries `"<name>" raises`, `"<name>" funding round 2025`, `"<name>" funding round 2026`, plus the company's own blog/newsroom/press page if linked from the home page; every result logged in queries.md; a round counts only if a logged result finds it; companies.csv fetched, classified and committed before any funding amount is read.
2. Drop `tests?|testing` from EW (AI + testing without eval/observab/monitor -> borderline); add fixture "AI-powered end-to-end testing" -> borderline.
3. h1 extraction: each tag replaced by a space, then whitespace collapsed, HTML entities decoded; case rules apply to the decoded text; name the fetch tool (curl or requests) in PREREG.
4. Rate: the "< 50 remaining" rule applies to the core resource only; code search paced at 9/min, repository search 25/min; on 403/429 with Retry-After or X-RateLimit-Reset wait and retry, never `error`. The db-serial-count session may be running code-search discovery on a shared token: if so, halve code search to 4/min until it ends.
5. 2.2: "all results returned by the tool, count recorded" (not "first 20").
6. Keep only hits with path == F for all three search forms; add drop reason `no_root_file` (1.2.2, AC3).
7. A workflow file whose only trigger is `on: workflow_call` is skipped when picking WF.
8. Runs: use `/repos/{r}/actions/workflows/<WF file>/runs`; enforce half-open bounds on created_at in code; print the default-branch rename as a limit.
9. Retention probe failure for any repo -> T0_MIN = launch - 400 d + 90 d, rounded up to the first of the month; failure recorded.
10. A run whose job has no resolving §2.2 step at head_sha, or whose test step is not success -> no value.
11. Control check order: the 9 agent-path checks, then 1.2 step 3, then runs.
12. Verdict unit tests cover 4 x 3 = 12 combinations (BLOCKED is a Part 1 state); check.py also reads companies.csv and the probe/ statuses.
13. R when F_T = F_E = 0 is R = 0: mark it **Interpretation (PREREG)**; public/division status judged at the round date; borderline companies' rounds are collected for the sensitivity lines.
14. Print as a limit: T0 counts only AGENTS.md/CLAUDE.md (an earlier .cursorrules or copilot instructions file gives a late T0).
15. 1.5 match = dependency-name equality after normalising `-` and `_`.

Note 16 (coordinator, route): the work session's proxy returned 403 for REST reads of other repositories and the
`GITHUB_TOKEN` workflow route got 429 on code search in the db-serial-count session. Both are probed in §0.5; if
work-session REST reads of other repositories are refused, all non-search reads go through the `GITHUB_TOKEN` workflow
route (`.github/workflows/market-direction.yml`, built as db-serial-count §5: request files, commit-back, <= 5 h per
run), and code search stays in the work session. The probe is recorded in `probe/`.

## §0 Pre-registration and probes (raw JSON under `probe/`)

1. This file is the first commit. Launch date as above.
2. **Search probe**, per file name F in {`AGENTS.md`, `CLAUDE.md`} separately; forms tried in order until one returns
   HTTP 200 with `total_count` > 0: (a) `filename:F path:/`; (b) `filename:F`; (c) `<STEM> filename:F` (`AGENTS` /
   `CLAUDE`). For all three forms only hits whose `path` is exactly `F` are kept (note 6). The form used per file is
   recorded. If no form works for either file, Part 1 is `BLOCKED`.
3. **Retention probe:** for `nodejs/node`, `python/cpython`, `microsoft/vscode`, the oldest run listed by
   `GET /repos/{r}/actions/runs?per_page=1&page=<last>` (last page from the `Link` header).
   `T0_MIN` = the latest of the three oldest dates + 90 days, rounded up to the first of a month, and not earlier than
   2025-01-01. Written into this file (second commit) after the probe and before any candidate is read.
   **Interpretation (PREREG):** the runs listing serves at most 1,000 results per query; when a repository's
   `total_count` > 1,000 the last page is the 1,000th newest run, not the oldest listed run. In that case the oldest
   listed run is found by day bisection on `created=<YYYY-MM-DD` (per_page=1; `total_count` > 0 means a run was
   created before that date) between 2015-01-01 and launch: the oldest listed run's date is the day D with
   `created=<D` empty and `created=<D+1` non-empty. If the
   oldest date cannot be determined for any repository (an error, or no run at all), the probe has failed and note 9
   applies.
4. **Web probe (Part 2 feasibility):** GET the home pages of Blacksmith, Trunk, Braintrust, Arize AI and Galileo (URLs
   from the seed table) and two news URLs (the first two funding articles returned by the first §2.2 query), with the
   Part 2 fetch tool; status and the first 2 KB of each committed under `probe/web/`.
5. **Route:** code search from the work session (`gh api -X GET search/code`). Probes: (i) work session
   `GET /repos/nodejs/node`; (ii) work session `X-RateLimit-Limit` of the core resource; (iii) workflow
   `GET /repos/nodejs/node`, a repository search and a code search with `GITHUB_TOKEN`. If (i) is refused, every
   non-search read goes through the workflow route (note 16). Repository search runs on the route whose probe returned
   HTTP 200 (the workflow route preferred, because the pair loop runs there). Otherwise all non-code-search reads run in
   the work session if its core limit is >= 5,000/h, else in the workflow. Rate rule (rule 7 with note 4):
   User-Agent `fenvix-research`; when the **core** `X-RateLimit-Remaining` < 50, sleep until reset; code search <= 9
   requests/min (4/min while the db-serial-count discovery is running on a shared token; it was running at launch, so
   4/min applies until its branch shows discovery finished); repository search <= 25 requests/min; on 403/429 with
   `Retry-After` or `X-RateLimit-Reset`, wait and retry (never `error`). File contents are cached by blob sha (and by
   (repo, ref, path) within a run). Within each candidate the cheapest checks run first (the order of 1.2).

## Part 1: suite growth, agent repositories vs matched control

### 1.1 Frame

For each file F, the probe's query form (§0.2) is bisected by `size:` as in db-serial-count §1: each query starts as one
range `size:0..400000` and is bisected (`size:a..m`, `size:m+1..b`, m = floor((a+b)/2)) until every split has
`total_count` <= 1,000 or is a single size value. Every split records `total_count`, `incomplete_results`, results
read and `truncated = total_count > 1000 or incomplete_results`. A leaf with `incomplete_results: true` is retried up
to 3 times and its largest `total_count` kept; still incomplete -> marked `incomplete`. Single-size leaves over 1,000
are read to the 1,000-result cap and marked truncated. Leaf splits are fetched (all pages, 100 per page) in an order
shuffled with `random.Random(1)` (one shuffle of the list of (F, range) leaves sorted by (F, a)), so a frame cut by
the budget is not size-biased. Only hits with `path` == F are kept (note 6). Candidates = distinct repositories over
all fetched leaves; sorted by `html_url`, then `random.Random(1).shuffle` once; read in that order. Discovery budget:
24 h; if exceeded, read what was found and print the frame as truncated. If the frame is read to the end before the
stop rule, Part 1 is evaluated with the pairs it has.

### 1.2 Reading an agent candidate (filters applied as read; every failure -> `dropped.csv`, one reason)

1. `GET /repos/{r}`: drop `excluded` if fork, archived, `stargazers_count` < 10, or `pushed_at` older than
   2026-10-25 (launch - 30 d); drop `no_language` if `language` is null.
2. **T0** = the minimum committer date over all commits on the default branch that touch the root `AGENTS.md` or
   `CLAUDE.md` (commits API `?path=<file>&sha=<default>&per_page=100`, all pages, both files). Neither file has a
   commit on the default branch -> `no_root_file` (note 6). Drop `t0_out_of_range` unless `T0_MIN` <= T0 <=
   2026-05-24 (date compared as UTC timestamps; upper bound 2026-05-24T23:59:59Z). Limits printed: `path` is
   case-sensitive and does not follow renames; a renamed default branch is read under its current name; T0 counts only
   AGENTS.md/CLAUDE.md (note 14).
3. **Test job at T0:** the default-branch commit at T0 (`commits?sha=<default>&until=<T0>&per_page=1`); list
   `.github/workflows` at that commit (contents API `?ref=<sha>`; `.yml` and `.yaml` only); files by path, jobs in file
   order; a file whose only trigger is `workflow_call` is skipped (note 7); jobs with `uses:` (reusable calls) have no
   steps and are skipped. The first job with a §2.2 candidate test step whose script resolves (resolution read at the
   T0 commit) is the measured job; its file path is `WF`, its key is the job key. No job with a candidate step ->
   `no_test_step`; candidate steps exist but none resolves -> `unresolved`; no `.github/workflows` at T0 ->
   `no_test_step`.
4. **Runs:** `GET /repos/{r}/actions/workflows/<WF file name>/runs?branch=<default>&status=success&created=<start>..<end>&per_page=100`
   (all pages; note 8), ISO 8601 UTC timestamps; runs whose `event` starts with `pull_request` are dropped; the
   half-open bound is enforced in code on `created_at`. Sub-ranges of 7 days anchored at T0; a sub-range with
   `total_count` > 1,000 is split into days, a day over 1,000 into hours.
   - **D0 runs:** `created_at` in [T0 - 90 d, T0), sub-ranges walked backwards from T0 (newest first within each); the
     10 newest runs with a value.
   - **D1 runs:** `created_at` in [T0 + 182 d, min(T0 + 272 d, read time)], sub-ranges walked forwards from T0 + 182 d
     (oldest first within each); the 10 oldest runs with a value.
   - Fewer than 10 in a window -> `too_few_runs`; but if the window is entirely before the repository's oldest listed
     run -> `retention`. **Interpretation (PREREG):** the "one extra call" is
     `GET /repos/{r}/actions/runs?created=<<window end>&per_page=1`; `total_count` = 0 means no listed run of the
     repository is older than the window's end, i.e. the window is entirely before the oldest listed run.
5. **Value of a run:** fetch `WF` at the run's `head_sha` (contents API `?ref=`); find the measured job by its key
   (missing at that commit -> no value); jobs `GET /actions/runs/{id}/jobs?filter=latest&per_page=100` (all pages);
   match the API job by §3.2; per matrix leg (each matching API job), the sum of `completed_at - started_at` (seconds)
   of every §2.2 test step of that job (resolution read at `head_sha`), each matched to an API step by §3.3, all with
   `conclusion: success`; a leg with any test step unmatched or not success gives no value; the run's value = the
   maximum over legs with a value (note 10: no resolving §2.2 step at `head_sha`, or a test step not success, -> no
   value). Only legs whose API job has `conclusion: success` count (§3.2). **Job level:** if any run examined in
   either window returns a matched job with an empty `steps` list, the repository restarts at job level: every run's
   value = the maximum over legs of the job's `completed_at - started_at`, both windows re-selected; marked
   `job_level`. Levels are never mixed within a repository. An API error after one retry -> `error`.
6. **D0, D1** = medians of the 10 values (mean of 5th and 6th). D0 = 0 -> `zero_duration`. **g = D1 / D0.**

### 1.3 Control (one per agent repository; pairs processed serially in agent order)

Repository search `language:"<L>" stars:<floor(0.5*s)>..<ceil(1.5*s)> pushed:>=2026-10-25 archived:false fork:false`
with `sort=updated`, all pages up to 1,000 results (100 per page), raw pages committed under `control_search/`;
dedupe; drop every repository that is in the agent frame (1.1) and the agent repository itself; sort by repository
id; `random.Random(<agent repo id>).shuffle`; test in that order, at most 100. L, s = the agent repository's
`language` and `stargazers_count` today. **Interpretation (PREREG):** stars stand for "similar size and activity".
Eligible when, in this order (note 11):
1. none of `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules`, `.windsurfrules`, `.clinerules`,
   `.github/copilot-instructions.md`, `.github/instructions/`, `.cursor/rules/` appears in default-branch history up
   to T0 + 272 d (`commits?sha=<default>&path=<p>&until=<T0+272d>&per_page=1`, each must return an empty list;
   a trailing `/` is stripped for the API path);
2. it passes 1.2 step 3 at the agent repository's T0 (the control's default-branch commit at T0);
3. it passes 1.2 steps 4-6 with the agent repository's T0;
4. it is not already used as a control.
No eligible control among the first 100 -> the agent repository is dropped `no_control`. Every control check is
appended to `control_checks.jsonl` (repository, each path query and its result, outcome). Limits printed: matching
uses today's language and stars; agent use by commit trailers is not checked.

### 1.4 Stop and statistic

Read agent candidates until **200 complete pairs** or the reading budget ends. Budget: 24 h after discovery. After the
first 10 complete pairs, REPORT prints calls per complete pair and the projected pairs in 24 h; if fewer than 100
are projected the budget becomes 48 h (never past 2026-12-13 23:59 UTC). Fewer than **100 complete pairs** at the
end -> Part 1 = `NO DECISION`. Pairs keep agent read order.

- **Faster** (memo, literal) = `median(g_agent) > median(g_control)` over complete pairs (median of n values: the
  middle value, or the mean of the two middle values). A tie is "not faster".
- Information only: difference of medians (agent - control) with a 95% bootstrap interval: 10,000 resamples of
  pairs, `rng = random.Random(2)`, each resample `[pairs[rng.randrange(n)] for _ in range(n)]`, interval = sorted
  differences at indexes 249 and 9,749.

### 1.5 Evaluation setup (information only)

At the default-branch commit at T0 + 182 d (`commits?sha=<default>&until=<T0+182d>&per_page=1`), a repository has an
AI evaluation setup when a dependency file at the root or one level down (`package.json`, `pyproject.toml`,
`requirements*.txt`, `setup.cfg`, `Pipfile`) names at least one of `promptfoo`, `deepeval`, `ragas`, `langsmith`,
`braintrust`, `inspect-ai`, `inspect_ai`, `trulens`, `trulens-eval`, `arize-phoenix`, `langfuse` (match =
dependency-name equality after lower-casing and normalising `-` and `_`, note 15; npm scoped names compare on the full
name), or a git dependency on `openai/evals`, or a file `promptfooconfig.yaml`/`.yml` exists at the root or one level
down. Share reported for agent and control groups (complete pairs only).

## db-serial-count rules reused (verbatim from its PREREG)

**§2.2 Test steps:** split each step's `run:` into commands on newlines, `&&`, `||`, `;` and `|` (outside quotes);
drop every command matching
`\b(pip3?|python3? -m pip|uv pip|poetry|gem|bundle|npm|yarn|pnpm|apt(-get)?|brew|go)\s+(install|i|add|ci|get|mod download)\b`
and every command where the runner word is followed by `--help`/`--version`; then every step with a remaining
command that matches a runner command, in order, is a candidate test step:
`\b(jest|vitest|mocha|pytest|python -m pytest|tox|nox|manage\.py test|rspec|rails test|bin/rails test|rake (test|spec)\b|go test|node --test|make test[\w-]*)\b`,
or `\b(npm|yarn|pnpm)\b( run)? (test[\w:-]*)\b`. `make` targets are resolved in the `Makefile`, `tox`/`nox` in
`tox.ini`/`noxfile.py` commands, `rake test|spec` maps to Rails minitest / RSpec, all up to 3 levels like package
scripts. For a package-manager script, resolve the script in the job's `working-directory` `package.json` (root if
none), recursively through `npm run`/`yarn`/`pnpm` up to 3 levels; a script not found (workspaces, monorepo tools) ->
`unresolved`. A target that resolves to no runner command = not a test step; a missing or variable-only target =
unresolved. Working-directory precedence: step > job `defaults.run` > workflow `defaults.run` > root. Monorepo tools
(`turbo`, `lerna`, `nx`, npm/yarn/pnpm workspace flags) -> unresolved; Make, tox and nox as in its interpretations 4-5.
**A step "resolves"** when resolution returns at least one runner line without raising `unresolved`.

**§3.2 Jobs:** the job pattern = the YAML job's `name:` (or key) with each `${{ ... }}` replaced by `.*`, anchored; an
API job matches when its full `name`, or its `name` with one trailing ` (...)` removed, matches the pattern; it must
have `conclusion: success`. Matrix legs = every matching API job of the run.

**§3.3 Step:** the API step whose `name` matches the YAML step's `name:` (each `${{ ... }}` as `.*`, anchored); for an
unnamed step, the API name starting with `Run ` + the first 40 characters of the `run:` first line; when several steps
match, the one at the same position among matches in step order. Duration = `completed_at - started_at`, only for a
step with `conclusion: success`.

**§3.4 Median:** exactly 10 runs with a value, sorted; median = mean of the 5th and 6th values.

**Covered runners** (limit, printed): those listed in §2.2; PHPUnit/Laravel, Maven/Gradle, cargo, dotnet and other
stacks are not test steps here.

## Part 2: money, 2025-01-01 to 2026-11-24

### 2.1 Seed list (closed; additions only from 2.2) and home URLs (note 1)

Each URL is fetched with GET, redirects followed (at most 5); the final page is classified; final URL and status
recorded. Being on the list does not decide the category: 2.3 does.

| Listed for | Company | Home URL |
|---|---|---|
| T | Blacksmith | https://www.blacksmith.sh/ |
| T | Depot | https://depot.dev/ |
| T | Namespace | https://namespace.so/ |
| T | BuildJet | https://buildjet.com/ |
| T | Ubicloud | https://www.ubicloud.com/ |
| T | WarpBuild | https://www.warpbuild.com/ |
| T | RunsOn | https://runs-on.com/ |
| T | Cirrus Runners | https://cirrus-runners.app/ |
| T | Trunk | https://trunk.io/ |
| T | BuildPulse | https://buildpulse.io/ |
| T | Launchable | https://www.launchableinc.com/ |
| T | Buildkite | https://buildkite.com/ |
| T | CircleCI | https://circleci.com/ |
| T | Harness | https://www.harness.io/ |
| T | Datadog | https://www.datadoghq.com/ |
| E | Braintrust | https://www.braintrust.dev/ |
| E | LangChain | https://www.langchain.com/ |
| E | Arize AI | https://arize.com/ |
| E | Galileo | https://galileo.ai/ |
| E | Patronus AI | https://www.patronus.ai/ |
| E | Confident AI | https://www.confident-ai.com/ |
| E | Promptfoo | https://www.promptfoo.dev/ |
| E | Humanloop | https://humanloop.com/ |
| E | Langfuse | https://langfuse.com/ |
| E | Weights & Biases | https://wandb.ai/ |
| E | Comet | https://www.comet.com/ |
| E | HoneyHive | https://www.honeyhive.ai/ |
| E | Ragas | https://www.ragas.io/ |
| E | Athina AI | https://www.athina.ai/ |
| E | Scorecard | https://www.scorecard.io/ |
| E | Judgment Labs | https://judgmentlabs.ai/ |
| E | Okareo | https://okareo.com/ |
| E | Maxim AI | https://www.getmaxim.ai/ |
| E | Freeplay | https://freeplay.ai/ |
| E | Vellum | https://www.vellum.ai/ |
| E | Raindrop | https://www.raindrop.ai/ |
| E | Laminar | https://www.lmnr.ai/ |
| E | Coval | https://www.coval.dev/ |
| E | Haize Labs | https://www.haizelabs.com/ |

**Interpretation (PREREG):** a company added by 2.2 gets its home URL from the result that names it (the company's own
domain when the result links it, else the first official site named in a logged result); the URL is written into
`companies.csv` before its page is fetched.

### 2.2 Additions and per-company funding queries

With the work session's WebSearch tool, fixed queries; **all results returned by the tool, count recorded** (note 5);
raw results logged in `queries.md`. Discovery queries: "CI test runner startup funding 2025", "flaky tests startup
raises 2025", "GitHub Actions runners startup raises", "LLM evaluation startup raises 2025", "LLM observability
startup funding 2025", "AI agent evaluation startup seed round 2026". A result counts only when its title or snippet
names a company and a round or amount dated in the window. A company named in a result as raising money in the window
is added and classified by 2.3.

Per company (seed and added; note 1), fixed queries: `"<name>" raises`, `"<name>" funding round 2025`,
`"<name>" funding round 2026`, plus the company's own blog/newsroom/press page if linked from its home page (fetched
with the Part 2 tool). Every result is logged in `queries.md`; a round counts only if a logged result finds it.
`companies.csv` is fetched, classified and committed **before any funding amount is read** (note 1): the discovery
queries are run and logged first (their snippets are read only for company names), companies are fetched and
classified and `companies.csv` committed, and only then are the per-company queries run and amounts read. Web search
mode: "standard".

### 2.3 Classification (mechanical)

Text = the first `<h1>` element in document order of a raw GET of the final home page (User-Agent
`fenvix-research`): its inner HTML with each tag replaced by a space, then whitespace collapsed, then HTML entities
decoded (note 3; Python `html.unescape`, then whitespace collapsed again and stripped); case rules apply to the
decoded text. If empty (no `<h1>` or empty text), the `content` of `<meta name="description">` (entities decoded,
whitespace collapsed). Quoted with final URL and access date.

- `AIW` = (case-sensitive) `\b(LLM|AI|GenAI)s?\b`, or (case-insensitive) `\b(agents?|agentic|models?)\b`.
- `EW` (case-insensitive) = `\b(eval\w*|observab\w*|monitor\w*|quality)\b` (note 2: `tests?|testing` removed).
- `CIW` = (case-sensitive) `\bCI\b`, or (case-insensitive)
  `\b(continuous integration|GitHub Actions|runners?|builds?|tests?|testing|test suites?|flaky)\b`.

Rules, in order: **T** when `CIW` matches and (`\bCI\b` case-sensitive, or case-insensitive `continuous integration`,
`GitHub Actions`, `\brunners?\b` or `\bflaky\b` matches); **E** when `AIW` and `EW` match; otherwise **T** when `CIW`
matches and `AIW` does not; everything else `borderline` (listed, not summed). Public companies and divisions of
public companies (judged at the round date, note 13) -> `public`, listed, not summed. A page that does not load
(final status != 200 or empty text) -> `UNVERIFIED`, listed, not summed.

Unit fixtures (expected): "maintain" -> borderline; "fastest" -> borderline; "remodel" -> borderline;
"AI-powered CI for faster tests" -> T; "Evaluate your LLM apps" -> E; "The fastest GitHub Actions runners" -> T;
"AI-powered end-to-end testing" -> borderline; plus a public company -> public, and a failed page -> UNVERIFIED.

### 2.4 Sum

Rounds announced in the window with a disclosed amount, from the company or a news outlet quoting the amount (URL,
date); when sources disagree, the company's own figure. Non-USD amounts are converted to USD through EUR at the ECB
reference rates of the announcement date (previous business day on weekends/holidays; source URL). Undisclosed rounds
and acquisitions are listed, not summed. `F_T`, `F_E` = sums over T and E companies. **R = F_E / F_T**; F_T = 0 and
F_E > 0 -> R = infinite; both 0 -> R = 0 (**Interpretation (PREREG)**, note 13). Borderline companies' rounds are
collected for the sensitivity lines (note 13).
Information only, per company: declared customer count (quote and URL, or "none") and public price (or "not public").
Sensitivity lines (information only, never the verdict): R without the single largest round in each category; R with
all `borderline` companies added to E; R with all `borderline` added to T.
**Part 2 failure rule:** if more than 25% of the seed companies (2.1) are `UNVERIFIED`, or the web probe (§0.4) or the
2.2 queries fetch no funding source at all, Part 2 = `NO DECISION`.

## Verdict (`REPORT.md` line 1, exactly one)

Part 1 in {faster = yes, faster = no, NO DECISION (fewer than 100 pairs), BLOCKED (§0.2)}; Part 2 in {R >= 3, R < 3,
NO DECISION}. Part 2 always runs.

- `REOPEN` when Part 1 faster = no **and** R >= 3.
- `STANDS` when Part 1 faster = yes, **or** R < 3 (each alone is enough).
- `BLOCKED` when Part 1 is `BLOCKED` and Part 2 is `NO DECISION`.
- `NO DECISION` in every other case.

Then: pairs complete and dropped by reason, median g agent / control, the information interval, step vs job level
counts, evaluation-setup shares, F_T, F_E, R and the three sensitivity lines, both tables, `T0_MIN`, calls per
complete pair (observed after the first 10 pairs), and the limits (frame = repositories with root agent files found by
legacy code search; covered runners per §2.2; matching on today's language and stars; funding = disclosed amounts
only; default-branch rename; T0 from AGENTS.md/CLAUDE.md only).

## Outputs

Branch `claude/market-direction-check` from `origin/claude/release-1` 9ac63d6, folder `harness/market_direction/`:
`PREREG.md`, `probe/`, `REPORT.md`, `pairs.csv`, `dropped.csv`, `control_checks.jsonl`, `control_search/`,
`funding_T.csv`, `funding_E.csv`, `companies.csv`, `queries.md`, `check.py`, scripts, `test_market_direction.py`.
Only `.github/workflows/market-direction.yml` may change outside that folder (when the workflow route is used).

## Amendment 1 (2026-11-24, before any leaf page is read): discovery reads page 1 of each leaf

Approved change (rule 3), coordinator message of 2026-11-24 18:54 UTC, verbatim: "Coordinator: your rule-3 proposal
is approved by the founder (gstack /plan-eng-review, D1 = A, recorded in new-brain
gstack/projects/Mircoguidetti-new-brain/main-eng-review-market-frame-20261124-185500.md). Apply it as written: bisect
fully, then fetch page 1 (100 hits) of each leaf in Random(1) leaf order; candidates = distinct repositories over
those pages; print the page-1 (best-match) bias as a limit. Amend PREREG with this change (quote this decision, commit
it) before any leaf page is read. Everything else stays as pre-registered." Confirmed 19:16 UTC: "run Part 1 to its
end".

Justification (reported to the coordinator at §0): about 1.49M root files; bisection alone is about 6,000 split
queries (about 25 h at 4/min); fetching every leaf in full is about 30,000 requests and does not fit the 24 h
discovery budget.

Rule replacing §1.1's leaf fetch: after the bisection is complete for both files, the leaves (sorted by (F, a),
shuffled once with `random.Random(1)`) are fetched in that order, **page 1 only** (up to 100 hits, the API's default
best-match order); hits with `path` == F are kept; candidates = distinct repositories over those pages, sorted by
`html_url`, then `random.Random(1).shuffle` once. The 24 h discovery budget still applies. Limit printed in REPORT:
within a leaf, only the 100 best-match hits are in the frame (page-1 bias).

## Amendment 2 (2026-11-25, before the first resumed search request): discovery paused, fresh budgets

Approved change (rule 3), founder decision D3 = A (gstack /plan-eng-review R2, recorded in new-brain
gstack/projects/Mircoguidetti-new-brain/main-eng-review-market-frame-20261124-185500.md, approved 2026-11-25 05:44
UTC). Coordinator resume order of 2026-11-25 07:47 UTC, verbatim: "Resume market Part 1 discovery from your checkpoint
86a6d19 now: 1. Code search at most 9 requests/min. db-serial-count still sends a few code searches per chunk (≤9/min,
occasional): on any 429, wait as f2e649b retry_seconds and continue; never raise your rate to catch up. 2. Fresh 24 h
discovery budget starting at your first resumed search request; then your own 24 h leaf-reading budget starting when
discovery ends. 3. Record this as PREREG amendment 2 (date, reason: founder D3 = A, budgets above) in a commit before
the first resumed search request. 4. When discovery ends, message @parent at once with the pool line and end time
(test-quality-count waits for it), then continue reading."

Reason: at 4/min, with db-serial-count discovery at 9/min on the same account, GitHub's secondary limit returned
repeated 429s with waits of about 734 s; from 01:50 to 05:44 UTC no split completed (385 splits, 167 leaves at the
pause, commit 86a6d19). Discovery was paused at 05:44 UTC on the coordinator's order and resumed after db-serial-count
discovery ended (2026-11-25T07:46:27Z).

Rules replacing §1.1's budget and the rate in §1.0 for discovery: code search at most 9 requests/min; a 429 waits as
`ghapi.retry_seconds` and the rate is never raised to catch up. Bisection resumes from the saved state with a fresh
24 h budget starting at the first resumed search request. Leaf page-1 reading (Amendment 1) has its own 24 h budget
starting when bisection ends. If bisection reaches its 24 h budget before it is complete, discovery stops and the
coordinator is asked before any leaf page is read (this case is not covered by the decision). Everything else stays as
pre-registered.

## Amendment 3 (2026-11-25, during bisection): discovery hard stop extended by 6 h; truncated frame allowed

Approved change (rule 3), founder decision D1 = A (/plan-eng-review). Coordinator message of 2026-11-25 19:20 UTC,
verbatim: "Discovery budget extended by at most 6 h: hard stop 2026-11-26 13:48 UTC (instead of 07:48). If bisection
ends earlier, start leaf reading at once with its own 24 h (as amendment 2). If not finished at 13:48: discover.py
stops; read what was found; print the frame as truncated with the size bound reached for each query form. No need to
ask me again at 13:48 for that case. Nothing else changes: rate stays 9/min, same order, same stop rules."

Reason: the 429 rate rose again after 15:55 UTC (about 1.75 completed splits/min); about 2,000 CLAUDE.md splits
remained at 17:55 UTC, which did not fit the amendment-2 budget.

Rules replacing amendment 2's bisection budget: bisection hard stop 2026-11-26T13:48:26Z (the amendment-2 deadline
plus 6 h). If bisection completes earlier, leaf page-1 reading (Amendment 1) starts at once with its own 24 h. If it is
not complete at the hard stop, bisection stops, the leaves found so far are read (page 1, Random(1) order, own 24 h
budget), and REPORT prints the frame as truncated with, per query form, the size bound below which every size is in a
leaf ("complete", "sizes 0..N" or "not started"). This replaces amendment 2's "stop and ask" case.
