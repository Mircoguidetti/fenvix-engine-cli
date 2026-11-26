# PREREG: public count of agent repositories with agent-test non-determinism pain

Pre-registered before any data (spec `agent-determinism-count` rev 4, gate 7/10; founder decisions D2 = A, D3 = A,
"manda" 2026-11-25). Code: `harness/agent_determinism_count/` on branch `claude/agent-determinism-count` from
`origin/claude/release-1` 9ac63d6. Read-only on public data; every request is GET; nothing is merged.
Any later change to a rule, regex, query, list or budget is listed in `CHANGES.md` (printed at the top of REPORT.md)
with its reason, before any result. The code constants live in `rules.py`; the appendix below is generated from it.

## Decision line (memo; threshold ASSUMED by the coordinator)

**Reading time (founder decision "lettura A", 2026-11-26 19:01Z, main-ceo-review-adc-reading-time-20261126-190500.md;
CHANGES.md item 21).** Reading time must not decide the idea. There is no 24 h reading cap: reading goes on, in §4.1
order, until 50 pain-yes members are confirmed (CONTINUE) or until 15 Dec 2026. With fewer than 50 at that point the
outcome is `NOT ENOUGH DATA`, reported with the read count, the rate and the projected count over the whole pool with
its interval; DROP only if the upper bound of that projection is below 50. The membership and pain rules are
unchanged. The `DROP (memo line)` and the early `DROP: bounds ...` below no longer apply. Implementation
(coordinator 2026-11-26 19:04Z):
1. The projection is over the candidate pool. Per stratum it is the rate times the stratum's candidates (pool.json,
   after the rebuild), summed. The point uses pain yes / read, the lower bound the Wilson 95% lower bound of pain yes,
   and the upper bound the Wilson 95% upper bound of A_s (pain yes + unknown + uncertain, as in §5). A fully read
   stratum projects its own counts. N_s is not used: it counts unread hits, and the DROP condition would be
   unreachable.
2. No early DROP. Reading goes on until 50 confirmed pain yes, then CONTINUE at once (after that chunk's second reads
   and AC4), or until the stop.
3. The stop stays at 2026-12-14 12:00 UTC (HARD_STOP), so REPORT lands before 15 Dec. At the stop, with AC4 passed:
   `DROP: <read> read, pain yes <P> (rate r); projected ... upper <u> < 50.` when the summed upper bound is below 50,
   else `NOT ENOUGH DATA: <read> read, pain yes <P> (rate r); projected over the candidate pool <point> (95% <lo> to
   upper <up>).`

By 15 Dec 2026: if fewer than **50** public agent repositories show agent-test non-determinism pain, the
"deterministic for agents" second use is dropped and the 24 Nov answer stands. CONTINUE needs 50 actual member
repositories with pain `yes` (all strata) and the AC4 hand check passing.

- `CONTINUE: <P> agent repositories with agent-test non-determinism pain.` when P >= 50 and AC4 passes; reading
  stops at the first chunk where it holds (after that chunk's second reads and AC4).
- `DROP: bounds S1 <a>, S2 <b>, S3 <c>, total <t> < 50.` (statistical early exit) when B_S1, B_S2, B_S3 are all
  defined and their sum < 50; checked after each chunk (AC4 run first).
- `DROP (memo line): <P> found < 50; bounds ...` (founder D2 = A) when the 24 h reading budget (from the end of
  discovery) ends, or 2026-12-14 12:00 UTC is reached, or discovery exceeded 24 h and the remaining reading budget
  ends, without CONTINUE. AC4 runs on the read rows first. Printed with read, members, pain yes/unknown, uncertain,
  candidates per stratum, N_s, every B_s (or `undefined`) and the "not covered" list.
- `NO DECISION` only when reading never started: BLOCKED (no code-search route answers 200), the pre-pass stop
  (projected discovery > 20 h, the session messages the coordinator), or the hard stop before the first candidate.
  Also (gate note 12) when a rule refined once after a second-read or AC4 failure fails again.
- REPORT first line: CONTINUE / DROP / DROP (memo line) -> `DONE`; pre-pass stop -> `NOT DONE`; probe failure ->
  `BLOCKED`; still reading -> `NOT DONE`.

## Constants

`WINDOW_START = 2026-01-01`, `HISTORY_START = 2024-01-01`, `QUERY_CAP = 20,000`, `TEXT_CAP = 40`, request cap 300
per candidate, recording files fetched per repository 200, manifests read per repository 100 (`MANIFEST_CAP`),
blobs read as text at most 2,000,000 bytes (larger manifest/workflow/script -> API error), recording blobs at most
5,000,000 bytes (larger -> `recording-unread`), runs
inspected per test workflow 20, comments fetched for the first 40 non-candidate hits per member, repository-search
results read 100 per query, first-phase reads 300 per stratum, chunk size 150, hard stop `2026-12-14T12:00:00Z`,
reading budget 24 h, discovery budget 24 h, pre-pass stop above 20 h, code search <= 9 requests/min, issues and
commits search together <= 25 requests/min, z = 1.96 (z² = 3.8416). Seeds: candidate order `random.Random(1)`
(each stratum separately), second-read rejected sample `random.Random(2 + chunk)`.

`LAUNCH` is the UTC date of the first discovery request (pre-pass included), written once to
`results/launch.json` and printed in REPORT.md; issues and commits discovery ranges are `2024-01-01..LAUNCH`.

## Definitions

- **Agent library.** Python (names normalised per PEP 503: lower case, runs of `-_.` -> `-`): `langchain`,
  `langchain-*`, `langgraph`, `langgraph-*`, `crewai`, `crewai-tools`, `pyautogen`, `autogen-agentchat`,
  `autogen-core`, `autogen-ext`, `ag2`, `llama-index`, `llama-index-*`, `openai-agents`, `pydantic-ai`,
  `pydantic-ai-slim`, `smolagents`, `agno`, `phidata`, `google-adk`, `semantic-kernel`, `claude-agent-sdk`,
  `strands-agents`, `haystack-ai`, `dspy`, `dspy-ai`. npm (lower case, exact key or scope prefix): `langchain`,
  `@langchain/*`, `@openai/agents`, `ai` (exact key), `@ai-sdk/*`, `llamaindex`, `@llamaindex/*`, `@mastra/core`,
  `@anthropic-ai/claude-agent-sdk`. Python names are matched in Python manifests, npm names in `package.json`.
  **Interpretation:** `langchain` and `llama-index` count even when used for retrieval; REPORT splits every count by
  library and prints P without the repositories whose only libraries match
  `^(langchain|llama-?index|llamaindex|@langchain/|@llamaindex/)` (information; the decision uses P).
- **Manifests** (default branch, any depth; skipped when a directory segment is `node_modules`, `vendor`,
  `site-packages`, `.venv`, `venv`, `dist` or `build`): basename matching `requirements.*\.txt`, `pyproject.toml`
  (PEP 621 `project.dependencies` runtime, `project.optional-dependencies` optional/extras, PEP 735
  `dependency-groups` dev/test, `tool.poetry.dependencies` runtime (optional/extras when `optional = true`),
  `tool.poetry.dev-dependencies` and `tool.poetry.group.*.dependencies` dev/test, `tool.pdm.dev-dependencies`
  dev/test, `tool.uv.dev-dependencies` dev/test), `setup.py` (regex on the `install_requires=[...]` and
  `extras_require={...}` string literals; a non-literal value -> `manifest-error`; never executed), `setup.cfg`
  (`configparser`: `[options] install_requires`, `[options.extras_require]`), `Pipfile` (`[packages]` runtime,
  `[dev-packages]` dev/test), `environment.yml` (conda names and the `pip:` list, runtime), `package.json`
  (`dependencies` and `peerDependencies` runtime, `devDependencies` dev/test, `optionalDependencies`
  optional/extras). A manifest with an unexpected shape (e.g. a list where a table is expected) is a
`manifest-error`. A requirements file whose basename contains `dev`, `test`, `lint`, `ci` or `doc` is dev/test,
  else runtime. A manifest that does not parse (TOML, JSON, YAML, INI) -> `manifest-error`. Manifests are read in
  order of depth then path, at most 100 (`MANIFEST_CAP`); more than 100 without a library found -> `uncertain`
  (implementation rule fixed here).
- **Member repository:** public, not a fork, not archived, `pushed_at` >= `WINDOW_START`, not excluded, with (a) an
  agent library in a manifest and (b) tests running in CI in 2026 (§2.3).
- **Pain** (members only): `recording` (§3.1) or `text` (§3.2-§4). `marker` (`@pytest.mark.flaky`, `--reruns`,
  `jest.retryTimes`, vitest `retry:`, `skipif(...<PROVIDER>_API_KEY...)`) is information only, searched in the
  fetched manifests (regex in the appendix); it never makes pain.
- **Recording** (`recording`): a text file (`.yaml`, `.yml`, `.json`, `.har`) on the default branch that either has a
  directory segment `cassettes`, `cassette`, `vcr`, `vcr_cassettes`, `recordings`, `__recordings__` or a directory
  ending in `fixtures/vcr` or `__snapshots__/vcr` (path rule), or lies under a directory segment `test`, `tests`,
  `spec`, `fixtures` or `__tests__` and parses (JSON, else YAML) to the VCR shape (`interactions[].request.uri`) or
  the HAR shape (`log.entries[].request.url`) (shape rule); whose content contains a host (§Hosts, plain substring,
  case-insensitive); and whose last commit (`commits?path=<file>&sha=<default branch>&per_page=1`, committer date)
  is >= `HISTORY_START`. **Interpretation:** the memo's "dated" means on or after `HISTORY_START` for texts and
  recordings. Files under the skipped vendored directories above are not recording candidates (implementation
  rule fixed here). Also a declared dependency on a model-answer recording package (§0.2d list) in a manifest
  whose last commit (committer date) is >= `HISTORY_START`.
- **Hosts:** `api.openai.com`, `openai.azure.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`,
  `aiplatform.googleapis.com`, `bedrock-runtime.`, `api.mistral.ai`, `api.groq.com`, `api.cohere.com`,
  `api.cohere.ai`, `api.together.xyz`, `api.fireworks.ai`, `openrouter.ai/api`, `api.deepseek.com`, `api.x.ai`,
  `api.perplexity.ai`, `cognitiveservices.azure.com`.
- **Text** (`text`): a commit, pull request or issue of the repository, created on or after `HISTORY_START` (commit:
  committer date), confirmed by both readers under §4 item 1b. **Interpretation:** mocking counts only when the
  text says a test that called a live model was replaced by a mock because of varying output or cost; mocking a
  model in unit tests from the start is ordinary practice and is not pain.

## §0 Probes (after the coordinator's "search budget free" message only)

`ghapi.py` refuses every search request (code, issues, commits) while `results/search_budget_free.json` is missing;
the session writes that file (time and quote) when the message arrives. Probes (`probe.py`, raw JSON committed):

- (a) `api.openai.com path:cassettes` and `api.openai.com path:tests/cassettes` from the session (`gh api`) and from
  the workflow (`GITHUB_TOKEN`): code search uses the route with the larger `total_count` (session on a tie).
- (b) one query of each §1 shape (code: each path shape and each `filename:` shape; issues: a p×m query, a quoted
  p×m query, a cost query with `(llm OR openai OR agent)`; commits: a p×m query, a quoted one, a no-model cost query
  and a model cost query) and each §3.2 shape on `langchain-ai/langchain`; the nested-path check
  (`api.openai.com path:cassettes` returns a path such as `tests/cassettes/x.yaml`); the OR check
  count(`A OR B`) >= max(count(`A`), count(`B`)) for issues and for commits (A = `repo:langchain-ai/langchain
  flaky`, B = `... nondeterministic`): if it fails on issues, the S2 cost family and the §3.2 issues queries are
  split into single terms; if it fails on commits, the §3.2 commits queries are split into single terms; the
  `is:issue`/`is:pr` check: when the plain query answers 422 and both typed ones answer 200, every issues query runs
  twice (with `is:issue` and with `is:pr`) and the pre-pass counts both. A shape answered 422, an error, or
  `total_count` 0 is fixed (listed in CHANGES.md) or dropped before discovery and listed, never recorded as 0 (an
  OR probe that did not answer 200 counts as a failed OR check; a §3.2 shape answering 0 on the known repository
  counts as dropped): a
  dropped §1 shape goes under "not covered"; a dropped §3.2 shape makes every member's pain at most `unknown` unless
  `yes`.
- (c) one §1.B issues query and one §1.C commits query from both routes: issues/commits search uses the session
  when it answers 200 without 429, else the workflow.
- (d) `pypi.org/pypi/<name>/json` and `registry.npmjs.org/<name>` for `pytest-agentcontract`, `coding-agent-vcr`,
  `cendor-cassette`, `evalcraft` (both registries), `pytest-recording`, `vcrpy`, `pytest-vcr` (PyPI),
  `@pollyjs/core`, `nock` (npm): a name that exists and whose PyPI `info.summary` or npm `description` matches
  `MODEL_RE` goes on the model-answer recording list; `vcrpy`, `pytest-recording`, `pytest-vcr`, `@pollyjs/core`,
  `nock` never do. The GitHub repositories named in those packages' `repository`/`project_urls` are excluded.
- Neither code-search route answers 200 -> REPORT first line `BLOCKED`, decision NO DECISION.
- `probe.py decide` computes `results/probe_decisions.json` from the probe files by these rules.

## §1 Discovery

Every query is bisected: code search by `size:` from `size:0..400000` (halving; leaf at a single size); issues and
commits search by date from `2024-01-01..LAUNCH` (halving in days; leaf at a single day), the range replacing the
query's own `created:>=2024-01-01` / `committer-date:>=2024-01-01` qualifier. A node with `total_count` > 1,000 and
a splittable range is split; a leaf reads every page (100 per page) up to 1,000 results; a leaf whose first page
reports `incomplete_results` is retried 3 times (largest `total_count` kept) and is `incomplete` if still so (a page
error or an incomplete page also marks it); a leaf is `truncated` when `total_count` exceeds the results read or it
is incomplete. Each leaf records `total_count`, `incomplete_results`, results read, `truncated`.

**Pre-pass:** one unbisected request per query records `total_count`; REPORT prints per query the projected
requests `ceil(tc/100) + 2·ceil(tc/1000)` (10 for a capped query) and per family the hours (code at 9/min;
issues+commits at 25/min); projected discovery time = the larger family time. A query with pre-pass
`total_count` > `QUERY_CAP` is not bisected: its first 1,000 results (10 pages, default best-match order) are read
and the rest enters N_s (`capped-query`, listed). If the projected discovery time still exceeds 20 h, the session
stops before bisection and messages the coordinator. Also printed: N_s = Σ pre-pass `total_count` of the stratum's
queries (hits, an upper bound), the equal-split planned reads and the zero-count bound.

**Strata and queries** (verbatim list in the appendix): A (S1, code search) 10 host terms × 4 path shapes, plus each
model-answer recording package × 3 `filename:` shapes; B (S2, issues search) 12 pain terms × 18 model terms plus 13
cost/skip queries; C (S3, commits search) 12 × 18 plus 9 model cost queries (with `test` appended when the query has
no `test` word) plus 4 no-model cost queries × {`llm`, `openai`, `agent`}.

**Candidates:** distinct repositories (case-insensitive) over all leaves; each belongs to the first stratum it
appears in (S1, then S2, then S3) and keeps every hit (query, URL, stratum, text). Order: within each stratum sort by
`html_url`, then `random.Random(1).shuffle` once; read S1 until 300 of S1 are read (or S1 ends), then S2 and S3 one
to one until each has 300 read (or ends), then the rest of S1, then the rest of S2 and S3 one to one (the shorter
one's tail appended). Excluded candidates are not read; a chunk takes at most the reads its phase still needs, so a
phase never overshoots 300 within a chunk (`rules.plan_next`).

**N_s** = distinct candidates of s + Σ max(0, `total_count` − read) over the truncated leaves of s. Discovery stopped
at 24 h (gate note 3): each unfinished query adds max(0, pre-pass `total_count` − Σ `total_count` of its finished
leaves) to N_s as a truncated leaf, listed under "not covered".

**Population size** (information only): one `total_count` per library name (prefix names by their stem) ×
{`filename:requirements.txt`, `filename:pyproject.toml`, `filename:package.json`}; file hits, not repositories.

**Exclusions** (from `GET /repos/{r}`): fork; archived; `pushed_at` < `WINDOW_START`; owner `mircoguidetti`;
owners `langchain-ai`, `crewAIInc`, `run-llama`, `ag2ai`, `agno-agi`, `mastra-ai`, `pydantic`, `kevin1024`,
`ktosiek`, `nock`, `deepset-ai`, `strands-agents`; repositories `Netflix/pollyjs`, `kiwicom/pytest-recording`,
`microsoft/autogen`, `microsoft/semantic-kernel`, `openai/openai-agents-python`, `openai/openai-agents-js`,
`vercel/ai`, `huggingface/smolagents`, `google/adk-python`, `phidatahq/phidata`, `stanfordnlp/dspy`; repositories
matching `google/adk-*` and `anthropics/claude-agent-sdk-*`; the §0.2d recording packages' source repositories
(case-insensitive). Excluded candidates with discovery hits are listed as information.

**S3 extension (founder decision, 2026-11-26, main-eng-review-adc-s3-extension-20261126-112500.md; CHANGES.md
item 10).** One extension of S3 on the session route covers only the S3 queries the 24 h budget left unstarted (88)
or unfinished (1). Rules, shapes and caps are unchanged. It has a hard stop 6 h after its own first request, and any
query not done by then stays truncated with its pre-pass total_count (gate note 3). Its state, splits and leaf parts
are kept apart (`discovery_state_s3ext.json`, `splits_s3ext.jsonl`, `leaves_s3ext/`). The build merges them before
S3 is read further; reading chunks already started may continue.

## §2 Membership (workflow chunks, `pipeline.py`)

1. `GET /repos/{r}/git/trees/{default_branch}?recursive=1` (409 = empty repository: no files). `truncated: true` ->
   contents API: the root listing, the listing of every first-level directory (manifests only; hidden and skipped
   directories not listed) and `.github/workflows`; mark `tree-truncated`: no library found -> `uncertain`; for a
   member, pain cannot be `no`.
2. Libraries (Definitions). Found -> `agent-lib = yes` (names, kind, file). None and no `manifest-error`, no
   manifest cap, tree not truncated -> `no-agent-lib` (non-member). Otherwise -> `uncertain`.
3. Tests in CI (only when `agent-lib = yes`): every `.github/workflows/*.yml|*.yaml` parsed with PyYAML 6.0.2
   (`on:` read as key `True` handled); a workflow that does not parse and contains `test` (case-insensitive) or an
   `on:` that is not a string, list or mapping -> `uncertain` flag. Commands split on newlines, `&&`, `||`, `;`,
   `|` outside quotes; install commands (`INSTALL_RE`) and `--help`/`--version` dropped; prefixes stripped
   (`STRIP_RES`) with runner matching before and after stripping (gate note 7); scripts resolved up to 3 levels
   (npm/yarn/pnpm/bun `package.json` scripts in the step's working directory, make targets with prerequisites and
   `-C`, and tox/nox, which already match `RUNNER_RE`). A `run:` or `name:` that is not a scalar is never converted
   to text (YAML alias expansion): such a `run:` is not a test step and such a job is named by its key. A step is
   a test step when a command matches `RUNNER_RE`,
   `PM_RE` or `STRIPPED_RUNNER_RE` or resolves to one, or it `uses:` an action whose name (before `@`) contains
   `pytest` or `test` and none of `report`, `summary`, `publish`, `coverage` (case-insensitive). A
   `workflow_call` workflow runs through its local callers (job name `<caller> / <callee>`) and itself when it has
   other triggers; without a caller and other triggers -> `uncertain` flag; a caller that itself has only
   `workflow_call` is not followed further -> `uncertain` flag. An `on:` that is not a string, list or mapping ->
   `uncertain` flag (whatever the file contains). For each workflow file running a test
   job: `GET actions/workflows/{file}/runs?created=>=2026-01-01&per_page=100`, newest first, inspect at most 20 runs
   (jobs API, `per_page=100`, paginated). `ci-tests = yes` when an inspected run has the test job (`job_matches`)
   with `conclusion` `success` or `failure` and a test step (`pick_api_step`) whose conclusion is neither `skipped`
   nor null. A workflow with none in its 20 inspected runs while more exist -> `uncertain`; a workflow where the
   job concluded but no test step was found among its API steps -> `uncertain`; runs listing 404 -> no runs. Any
   workflow yes -> yes (stop); else any uncertain or flag -> `uncertain`; else, when the tree was truncated
   (subdirectory scripts not fetched) -> `uncertain`; else `no-ci-tests` (non-member).
4. Request cap: at most 300 distinct core REST paths per candidate (membership, recordings and the later comment
   pass together; a blob read both as text and as a recording counts twice). Cap during membership ->
   `uncertain`; during the pain read -> pain `unknown` unless already `yes`. An API error after one retry, or any
   unexpected response shape (the same row live and in replay): during membership -> `uncertain`; during the pain
   read -> pain `unknown` unless `yes`.
5. Class: `member`, `non-member` (`no-agent-lib`, `no-ci-tests`), `uncertain`, `excluded` (not read).

## §3 Pain read (members)

1. **Recordings:** the tree's recording candidates sorted by path, the first 200 fetched (blob API; more ->
   `recording-capped`); each that meets the path or shape rule and holds a host gets its last-commit date; the first
   dated >= `HISTORY_START` -> pain `yes` (`recording`); earlier hits are kept and the next file is checked; a hit
   whose last commit cannot be dated -> `recording-undated`; a file above the size cap or returned without text ->
   `recording-unread` (both: pain at most `unknown`). Then manifests declaring a model-answer recording package
   (dated by the manifest's last commit; undated -> `recording-undated`).
2. **Repository texts** (members without a recording `yes`): `search/issues` `repo:<r> created:>=2024-01-01 (flaky
   OR nondeterministic OR "non-deterministic" OR intermittent OR unstable)` and, for m in {`llm`, `openai`,
   `agent`, `model`, `prompt`}, `repo:<r> created:>=2024-01-01 <m> (skip OR disable OR expensive OR cost OR mock)`;
   `search/commits` the same six with `committer-date:>=2024-01-01`; first 100 results each (`per_page=100`); a
   query with `total_count` > 100 or `incomplete_results` -> `text-capped`; an error after the 429 retries ->
   `text-error`; a member never searched -> `texts-missing`. The member's texts are its S2/S3 discovery hits plus
   these hits (distinct by URL, dated >= `HISTORY_START`). For issue/PR texts whose title + body do not match both
   regexes, the comments (`issues/{n}/comments?per_page=100`, first page) are fetched for the first 40 such texts in
   reading order; the text becomes title + body + comments. A missing, errored or capped comment pass where comments
   were needed -> `comments-missing` / `comments-incomplete` (pain at most `unknown`). On the session route the
   comment pass runs in the workflow (`requests/<n>c.json`) after the chunk's searches are committed. A text is a
   **text candidate** when it matches both `PAIN_RE` and `MODEL_RE`; other search hits are listed as `filtered`.

## §4 Hand reads and pain

1. Order: a member's candidates, discovery hits first, then the rest; each part newest first (ties by URL). Reading
   stops at the first text both readers confirm; while a `confirmed` first read awaits its second read, no further
   text of that member is read. At most 40 texts per member; more candidates than 40 without a `yes` -> `unknown`.
1b. First read (the work session) — **rule text, given verbatim to both readers**: `confirmed` only if the text meets
   all of: (i) it names a test, test suite, eval or CI job of this repository; (ii) that test involves a model or
   agent call (names a model, provider, the agent, an LLM, a prompt or an agent library); (iii) it says the test is
   flaky or non-deterministic because of that call (varying output, provider errors, rate limits, latency), or that
   it was retried, skipped, disabled (including moved out of the CI run), marked xfail or recorded because of
   varying output or cost, or that a test calling a live model was replaced by a mock because of varying output or
   cost; (iv) dated on or after `HISTORY_START`. Text that only complains about model quality, or a flaky test whose
   stated cause is not the model call (database, network to another service, timing of the test's own code) ->
   `rejected`. Not enough text to decide (i)-(iii) -> `unclear`. One-line quote, URL and reason (`varying-output`,
   `provider-errors`, `cost`) recorded for every `confirmed` and `unclear`.
2. Second read: a fresh general-purpose subagent with the prompt `second_read_prompt.md` (committed before the
   first second read), given only the text, its URL and the rule text; it reads every `confirmed`, every `unclear`
   and a random 20 `rejected` of the chunk (`random.Random(2 + chunk)`; all when fewer than 20). Final label:
   confirmed only when both say confirmed; a first `confirmed` with a second other label -> `unclear`; a first
   `unclear` -> `unclear`; a first `rejected` stays `rejected` unless the second reader says `confirmed` ->
   `unclear` (**Interpretation**, conservative). A `confirmed` or `unclear` first read without its second read is
   `pending`. More than 2 of the 20 sampled `rejected` labelled `confirmed` by the second reader -> stop, refine the
   rule text once as a listed change and re-read every text with both readers; a second such failure -> stop,
   message the coordinator, NO DECISION.
3. Pain per member: `yes` (a recording, or a text with final label `confirmed`, within the first 40 in order);
   `unknown` (not `yes`, and any of: an `unclear` or `pending` text within the first 40, more than 40 candidates,
   `text-error`, `text-capped`, `texts-missing`, `comments-missing`, `comments-incomplete`, `tree-truncated`,
   `recording-capped`, `recording-unread`, `recording-undated`, `request-cap`, `api-error`,
   `text-shape-dropped` (§0.2b: a §3.2 probe shape not answering 200 with hits), `recording-handcheck-failed` (an
   AC4-failed recording: later files and texts were never read)); `no` otherwise. **Interpretation:** "a text candidate not yet
   read twice" is read as a text whose second read is required (first `confirmed` or `unclear`) and missing; a
   `rejected` first read outside the sample is final.

## §5 Stop rule and budget

Per stratum s: `read_s` = non-excluded rows; `A_s` = `uncertain` + pain `yes` + pain `unknown`; `U_s` = Wilson 95%
upper bound of `A_s/read_s` (z = 1.96); `B_s` = `A_s` when every candidate of s has a row and no leaf of s is
truncated or incomplete; else `U_s × N_s` when `read_s` >= 300 and no leaf of s is incomplete; else undefined.
Decisions as above. After discovery REPORT prints N_s, the zero-count bound Σ 3.8416·N_s/(n_s + 3.8416) and the
equal-split reads `n_s = max(300, ceil(3·3.8416·N_s/50 − 3.8416))`. After chunk 1: requests per candidate (median,
p90, max), text candidates per member, texts read per hour, search requests per member, `X-RateLimit-Remaining`,
and whether the plan fits 24 h.

**AC4 hand check** (`results/handcheck.json`, before any CONTINUE or DROP): every recording `yes` (up to 30) and
every text `yes` (up to 30) checked against the file or text; 10 random `non-member` and 10 random members with
pain `no` (texts and tree re-checked) and every recording-package hit; a failure is reclassified (recording -> not
a recording; text -> second label rejected) and counts recomputed; more than 3 failed -> stop, fix the rule once as
a listed change and re-run it; a second failure -> NO DECISION.

Execution: every workflow request file without a `results/requests_done/<name>` marker runs (a newer push cancels
a pending run of the same concurrency group; a request stopped at the job-wide deadline, 320 minutes after the job
starts, is resumed by the next push; a rate-limit sleep that would pass the deadline stops the request cleanly). A
row is written after its raw record; verify ignores a raw record without a row and replays the last raw record per
candidate. Discovery in the work session (harness-tracked background task, two families in parallel, checkpoints
`results/discovery_state_<family>.json` committed every 30 minutes); §2-§3.1 and the REST part of §3.2 in workflow
chunks of up to 150 candidates; repository searches on the route §0.2c chose. The session sleeps on the observed
`X-RateLimit-Remaining` (< 50 -> until reset); User-Agent `fenvix-research`.

## Appendix: queries and regexes (generated from `rules.py`)

<!-- generated: python3 prereg_appendix.py --write -->

### Regexes

- `PAIN_RE`: `(?i)\b(flak\w*|non-?determinis\w*|nondetermin\w*|intermittent\w*|random(ly)?\s+fail\w*|fails?\s+randomly|inconsistent|unstable|var(y|ies|ying)|different\s+(outputs?|answers?|results?|responses?)|reproduc\w*|temperature|seed|xfail\w*|retr(y|ies|ied|ying)|re-?run\w*|skip\w*|disabl\w*|expensive|costs?|costly|tokens?|rate[- ]?limit\w*|mock\w*|cassettes?|record\w*|replay\w*)\b`
- `MODEL_RE`: `(?i)\b(llms?|gpt[\w.-]*|openai|anthropic|claude|gemini|mistral|models?|agents?|langchain|langgraph|crewai|autogen|llama[ -]?index|pydantic[- ]ai|ai[- ]sdk|prompts?|completions?|evals?)\b`
- `MARKER_RE`: `@pytest\.mark\.flaky|--reruns\b|jest\.retryTimes|\bretry\s*:\s*\d|skipif\([^)]*(OPENAI|ANTHROPIC|GOOGLE|GEMINI|MISTRAL|GROQ)_API_KEY`
- `INSTALL_RE`: `\b(pip3?|python3? -m pip|uv pip|poetry|gem|bundle|npm|yarn|pnpm|bun|apt(-get)?|brew|go)\s+(install|i|add|ci|get|mod download)\b`
- `RUNNER_RE`: `\b(jest|vitest|mocha|pytest|python3? -m pytest|tox|nox|manage\.py test|rspec|rails test|bin/rails test|rake (test|spec)\b|go test|node --test|make test[\w-]*|bun test|deno test|python3? -m unittest|hatch test|nx test|turbo (run )?test[\w:-]*)\b`
- `STRIPPED_RUNNER_RE`: `^(unittest|pytest)\b`
- `PM_RE`: `\b(npm|yarn|pnpm|bun)\b( run)? (test[\w:-]*)\b`
- `HELP_RE`: `\s--(help|version)\b`
- `ACTION_TEST_RE`: `(?i)pytest|test`
- `ACTION_NOT_RE`: `(?i)report|summary|publish|coverage`
- `RETRIEVAL_ONLY`: `^(langchain|llama-?index|llamaindex|@langchain/|@llamaindex/)`
- `STRIP_RES` (applied repeatedly, in order): `^[A-Za-z_][A-Za-z0-9_]*=(\"[^\"]*\"|'[^']*'|\S*)\s+`, `^env(\s+-\S+)*\s+`, `^\./`, `^node_modules/\.bin/`, `^(poetry|uv|pdm|hatch|pipenv) run\s+`, `^python3? -m\s+`, `^npx( -y| --yes)?\s+`, `^npm exec( --)?\s+`, `^pnpm (exec|dlx)\s+`, `^yarn dlx\s+`, `^bunx\s+`

### §1 discovery queries (default probe outcome; the variants follow the §0.2b rules)

#### A / S1, search/code (40 queries)

- `api.openai.com path:cassettes`
- `api.openai.com path:cassette`
- `api.openai.com path:recordings`
- `api.openai.com path:vcr`
- `api.anthropic.com path:cassettes`
- `api.anthropic.com path:cassette`
- `api.anthropic.com path:recordings`
- `api.anthropic.com path:vcr`
- `generativelanguage.googleapis.com path:cassettes`
- `generativelanguage.googleapis.com path:cassette`
- `generativelanguage.googleapis.com path:recordings`
- `generativelanguage.googleapis.com path:vcr`
- `openai.azure.com path:cassettes`
- `openai.azure.com path:cassette`
- `openai.azure.com path:recordings`
- `openai.azure.com path:vcr`
- `bedrock-runtime path:cassettes`
- `bedrock-runtime path:cassette`
- `bedrock-runtime path:recordings`
- `bedrock-runtime path:vcr`
- `api.mistral.ai path:cassettes`
- `api.mistral.ai path:cassette`
- `api.mistral.ai path:recordings`
- `api.mistral.ai path:vcr`
- `api.groq.com path:cassettes`
- `api.groq.com path:cassette`
- `api.groq.com path:recordings`
- `api.groq.com path:vcr`
- `api.cohere path:cassettes`
- `api.cohere path:cassette`
- `api.cohere path:recordings`
- `api.cohere path:vcr`
- `openrouter.ai path:cassettes`
- `openrouter.ai path:cassette`
- `openrouter.ai path:recordings`
- `openrouter.ai path:vcr`
- `api.deepseek.com path:cassettes`
- `api.deepseek.com path:cassette`
- `api.deepseek.com path:recordings`
- `api.deepseek.com path:vcr`

#### B / S2, search/issues (229 queries)

- `is:public created:>=2024-01-01 flaky llm test`
- `is:public created:>=2024-01-01 flaky openai test`
- `is:public created:>=2024-01-01 flaky anthropic test`
- `is:public created:>=2024-01-01 flaky claude test`
- `is:public created:>=2024-01-01 flaky gemini test`
- `is:public created:>=2024-01-01 flaky gpt test`
- `is:public created:>=2024-01-01 flaky "model output" test`
- `is:public created:>=2024-01-01 flaky prompt test`
- `is:public created:>=2024-01-01 flaky eval test`
- `is:public created:>=2024-01-01 flaky langchain test`
- `is:public created:>=2024-01-01 flaky langgraph test`
- `is:public created:>=2024-01-01 flaky crewai test`
- `is:public created:>=2024-01-01 flaky autogen test`
- `is:public created:>=2024-01-01 flaky llamaindex test`
- `is:public created:>=2024-01-01 flaky "llama-index" test`
- `is:public created:>=2024-01-01 flaky "pydantic-ai" test`
- `is:public created:>=2024-01-01 flaky "ai sdk" test`
- `is:public created:>=2024-01-01 flaky agent test`
- `is:public created:>=2024-01-01 flakiness llm test`
- `is:public created:>=2024-01-01 flakiness openai test`
- `is:public created:>=2024-01-01 flakiness anthropic test`
- `is:public created:>=2024-01-01 flakiness claude test`
- `is:public created:>=2024-01-01 flakiness gemini test`
- `is:public created:>=2024-01-01 flakiness gpt test`
- `is:public created:>=2024-01-01 flakiness "model output" test`
- `is:public created:>=2024-01-01 flakiness prompt test`
- `is:public created:>=2024-01-01 flakiness eval test`
- `is:public created:>=2024-01-01 flakiness langchain test`
- `is:public created:>=2024-01-01 flakiness langgraph test`
- `is:public created:>=2024-01-01 flakiness crewai test`
- `is:public created:>=2024-01-01 flakiness autogen test`
- `is:public created:>=2024-01-01 flakiness llamaindex test`
- `is:public created:>=2024-01-01 flakiness "llama-index" test`
- `is:public created:>=2024-01-01 flakiness "pydantic-ai" test`
- `is:public created:>=2024-01-01 flakiness "ai sdk" test`
- `is:public created:>=2024-01-01 flakiness agent test`
- `is:public created:>=2024-01-01 nondeterministic llm test`
- `is:public created:>=2024-01-01 nondeterministic openai test`
- `is:public created:>=2024-01-01 nondeterministic anthropic test`
- `is:public created:>=2024-01-01 nondeterministic claude test`
- `is:public created:>=2024-01-01 nondeterministic gemini test`
- `is:public created:>=2024-01-01 nondeterministic gpt test`
- `is:public created:>=2024-01-01 nondeterministic "model output" test`
- `is:public created:>=2024-01-01 nondeterministic prompt test`
- `is:public created:>=2024-01-01 nondeterministic eval test`
- `is:public created:>=2024-01-01 nondeterministic langchain test`
- `is:public created:>=2024-01-01 nondeterministic langgraph test`
- `is:public created:>=2024-01-01 nondeterministic crewai test`
- `is:public created:>=2024-01-01 nondeterministic autogen test`
- `is:public created:>=2024-01-01 nondeterministic llamaindex test`
- `is:public created:>=2024-01-01 nondeterministic "llama-index" test`
- `is:public created:>=2024-01-01 nondeterministic "pydantic-ai" test`
- `is:public created:>=2024-01-01 nondeterministic "ai sdk" test`
- `is:public created:>=2024-01-01 nondeterministic agent test`
- `is:public created:>=2024-01-01 "non-deterministic" llm test`
- `is:public created:>=2024-01-01 "non-deterministic" openai test`
- `is:public created:>=2024-01-01 "non-deterministic" anthropic test`
- `is:public created:>=2024-01-01 "non-deterministic" claude test`
- `is:public created:>=2024-01-01 "non-deterministic" gemini test`
- `is:public created:>=2024-01-01 "non-deterministic" gpt test`
- `is:public created:>=2024-01-01 "non-deterministic" "model output" test`
- `is:public created:>=2024-01-01 "non-deterministic" prompt test`
- `is:public created:>=2024-01-01 "non-deterministic" eval test`
- `is:public created:>=2024-01-01 "non-deterministic" langchain test`
- `is:public created:>=2024-01-01 "non-deterministic" langgraph test`
- `is:public created:>=2024-01-01 "non-deterministic" crewai test`
- `is:public created:>=2024-01-01 "non-deterministic" autogen test`
- `is:public created:>=2024-01-01 "non-deterministic" llamaindex test`
- `is:public created:>=2024-01-01 "non-deterministic" "llama-index" test`
- `is:public created:>=2024-01-01 "non-deterministic" "pydantic-ai" test`
- `is:public created:>=2024-01-01 "non-deterministic" "ai sdk" test`
- `is:public created:>=2024-01-01 "non-deterministic" agent test`
- `is:public created:>=2024-01-01 "non deterministic" llm test`
- `is:public created:>=2024-01-01 "non deterministic" openai test`
- `is:public created:>=2024-01-01 "non deterministic" anthropic test`
- `is:public created:>=2024-01-01 "non deterministic" claude test`
- `is:public created:>=2024-01-01 "non deterministic" gemini test`
- `is:public created:>=2024-01-01 "non deterministic" gpt test`
- `is:public created:>=2024-01-01 "non deterministic" "model output" test`
- `is:public created:>=2024-01-01 "non deterministic" prompt test`
- `is:public created:>=2024-01-01 "non deterministic" eval test`
- `is:public created:>=2024-01-01 "non deterministic" langchain test`
- `is:public created:>=2024-01-01 "non deterministic" langgraph test`
- `is:public created:>=2024-01-01 "non deterministic" crewai test`
- `is:public created:>=2024-01-01 "non deterministic" autogen test`
- `is:public created:>=2024-01-01 "non deterministic" llamaindex test`
- `is:public created:>=2024-01-01 "non deterministic" "llama-index" test`
- `is:public created:>=2024-01-01 "non deterministic" "pydantic-ai" test`
- `is:public created:>=2024-01-01 "non deterministic" "ai sdk" test`
- `is:public created:>=2024-01-01 "non deterministic" agent test`
- `is:public created:>=2024-01-01 intermittent llm test`
- `is:public created:>=2024-01-01 intermittent openai test`
- `is:public created:>=2024-01-01 intermittent anthropic test`
- `is:public created:>=2024-01-01 intermittent claude test`
- `is:public created:>=2024-01-01 intermittent gemini test`
- `is:public created:>=2024-01-01 intermittent gpt test`
- `is:public created:>=2024-01-01 intermittent "model output" test`
- `is:public created:>=2024-01-01 intermittent prompt test`
- `is:public created:>=2024-01-01 intermittent eval test`
- `is:public created:>=2024-01-01 intermittent langchain test`
- `is:public created:>=2024-01-01 intermittent langgraph test`
- `is:public created:>=2024-01-01 intermittent crewai test`
- `is:public created:>=2024-01-01 intermittent autogen test`
- `is:public created:>=2024-01-01 intermittent llamaindex test`
- `is:public created:>=2024-01-01 intermittent "llama-index" test`
- `is:public created:>=2024-01-01 intermittent "pydantic-ai" test`
- `is:public created:>=2024-01-01 intermittent "ai sdk" test`
- `is:public created:>=2024-01-01 intermittent agent test`
- `is:public created:>=2024-01-01 "randomly fails" llm test`
- `is:public created:>=2024-01-01 "randomly fails" openai test`
- `is:public created:>=2024-01-01 "randomly fails" anthropic test`
- `is:public created:>=2024-01-01 "randomly fails" claude test`
- `is:public created:>=2024-01-01 "randomly fails" gemini test`
- `is:public created:>=2024-01-01 "randomly fails" gpt test`
- `is:public created:>=2024-01-01 "randomly fails" "model output" test`
- `is:public created:>=2024-01-01 "randomly fails" prompt test`
- `is:public created:>=2024-01-01 "randomly fails" eval test`
- `is:public created:>=2024-01-01 "randomly fails" langchain test`
- `is:public created:>=2024-01-01 "randomly fails" langgraph test`
- `is:public created:>=2024-01-01 "randomly fails" crewai test`
- `is:public created:>=2024-01-01 "randomly fails" autogen test`
- `is:public created:>=2024-01-01 "randomly fails" llamaindex test`
- `is:public created:>=2024-01-01 "randomly fails" "llama-index" test`
- `is:public created:>=2024-01-01 "randomly fails" "pydantic-ai" test`
- `is:public created:>=2024-01-01 "randomly fails" "ai sdk" test`
- `is:public created:>=2024-01-01 "randomly fails" agent test`
- `is:public created:>=2024-01-01 "fails randomly" llm test`
- `is:public created:>=2024-01-01 "fails randomly" openai test`
- `is:public created:>=2024-01-01 "fails randomly" anthropic test`
- `is:public created:>=2024-01-01 "fails randomly" claude test`
- `is:public created:>=2024-01-01 "fails randomly" gemini test`
- `is:public created:>=2024-01-01 "fails randomly" gpt test`
- `is:public created:>=2024-01-01 "fails randomly" "model output" test`
- `is:public created:>=2024-01-01 "fails randomly" prompt test`
- `is:public created:>=2024-01-01 "fails randomly" eval test`
- `is:public created:>=2024-01-01 "fails randomly" langchain test`
- `is:public created:>=2024-01-01 "fails randomly" langgraph test`
- `is:public created:>=2024-01-01 "fails randomly" crewai test`
- `is:public created:>=2024-01-01 "fails randomly" autogen test`
- `is:public created:>=2024-01-01 "fails randomly" llamaindex test`
- `is:public created:>=2024-01-01 "fails randomly" "llama-index" test`
- `is:public created:>=2024-01-01 "fails randomly" "pydantic-ai" test`
- `is:public created:>=2024-01-01 "fails randomly" "ai sdk" test`
- `is:public created:>=2024-01-01 "fails randomly" agent test`
- `is:public created:>=2024-01-01 xfail llm test`
- `is:public created:>=2024-01-01 xfail openai test`
- `is:public created:>=2024-01-01 xfail anthropic test`
- `is:public created:>=2024-01-01 xfail claude test`
- `is:public created:>=2024-01-01 xfail gemini test`
- `is:public created:>=2024-01-01 xfail gpt test`
- `is:public created:>=2024-01-01 xfail "model output" test`
- `is:public created:>=2024-01-01 xfail prompt test`
- `is:public created:>=2024-01-01 xfail eval test`
- `is:public created:>=2024-01-01 xfail langchain test`
- `is:public created:>=2024-01-01 xfail langgraph test`
- `is:public created:>=2024-01-01 xfail crewai test`
- `is:public created:>=2024-01-01 xfail autogen test`
- `is:public created:>=2024-01-01 xfail llamaindex test`
- `is:public created:>=2024-01-01 xfail "llama-index" test`
- `is:public created:>=2024-01-01 xfail "pydantic-ai" test`
- `is:public created:>=2024-01-01 xfail "ai sdk" test`
- `is:public created:>=2024-01-01 xfail agent test`
- `is:public created:>=2024-01-01 unstable llm test`
- `is:public created:>=2024-01-01 unstable openai test`
- `is:public created:>=2024-01-01 unstable anthropic test`
- `is:public created:>=2024-01-01 unstable claude test`
- `is:public created:>=2024-01-01 unstable gemini test`
- `is:public created:>=2024-01-01 unstable gpt test`
- `is:public created:>=2024-01-01 unstable "model output" test`
- `is:public created:>=2024-01-01 unstable prompt test`
- `is:public created:>=2024-01-01 unstable eval test`
- `is:public created:>=2024-01-01 unstable langchain test`
- `is:public created:>=2024-01-01 unstable langgraph test`
- `is:public created:>=2024-01-01 unstable crewai test`
- `is:public created:>=2024-01-01 unstable autogen test`
- `is:public created:>=2024-01-01 unstable llamaindex test`
- `is:public created:>=2024-01-01 unstable "llama-index" test`
- `is:public created:>=2024-01-01 unstable "pydantic-ai" test`
- `is:public created:>=2024-01-01 unstable "ai sdk" test`
- `is:public created:>=2024-01-01 unstable agent test`
- `is:public created:>=2024-01-01 retry llm test`
- `is:public created:>=2024-01-01 retry openai test`
- `is:public created:>=2024-01-01 retry anthropic test`
- `is:public created:>=2024-01-01 retry claude test`
- `is:public created:>=2024-01-01 retry gemini test`
- `is:public created:>=2024-01-01 retry gpt test`
- `is:public created:>=2024-01-01 retry "model output" test`
- `is:public created:>=2024-01-01 retry prompt test`
- `is:public created:>=2024-01-01 retry eval test`
- `is:public created:>=2024-01-01 retry langchain test`
- `is:public created:>=2024-01-01 retry langgraph test`
- `is:public created:>=2024-01-01 retry crewai test`
- `is:public created:>=2024-01-01 retry autogen test`
- `is:public created:>=2024-01-01 retry llamaindex test`
- `is:public created:>=2024-01-01 retry "llama-index" test`
- `is:public created:>=2024-01-01 retry "pydantic-ai" test`
- `is:public created:>=2024-01-01 retry "ai sdk" test`
- `is:public created:>=2024-01-01 retry agent test`
- `is:public created:>=2024-01-01 rerun llm test`
- `is:public created:>=2024-01-01 rerun openai test`
- `is:public created:>=2024-01-01 rerun anthropic test`
- `is:public created:>=2024-01-01 rerun claude test`
- `is:public created:>=2024-01-01 rerun gemini test`
- `is:public created:>=2024-01-01 rerun gpt test`
- `is:public created:>=2024-01-01 rerun "model output" test`
- `is:public created:>=2024-01-01 rerun prompt test`
- `is:public created:>=2024-01-01 rerun eval test`
- `is:public created:>=2024-01-01 rerun langchain test`
- `is:public created:>=2024-01-01 rerun langgraph test`
- `is:public created:>=2024-01-01 rerun crewai test`
- `is:public created:>=2024-01-01 rerun autogen test`
- `is:public created:>=2024-01-01 rerun llamaindex test`
- `is:public created:>=2024-01-01 rerun "llama-index" test`
- `is:public created:>=2024-01-01 rerun "pydantic-ai" test`
- `is:public created:>=2024-01-01 rerun "ai sdk" test`
- `is:public created:>=2024-01-01 rerun agent test`
- `is:public created:>=2024-01-01 "tests are expensive" (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "expensive tests" (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "api costs" test (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "token cost" test (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "skip llm" (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "llm tests" (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "live llm" (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "real llm" test (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "mock the llm" (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "mock llm" (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 "record and replay" llm (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 cassette llm (llm OR openai OR agent)`
- `is:public created:>=2024-01-01 vcr openai (llm OR openai OR agent)`

#### C / S3, search/commits (237 queries)

- `committer-date:>=2024-01-01 flaky llm test`
- `committer-date:>=2024-01-01 flaky openai test`
- `committer-date:>=2024-01-01 flaky anthropic test`
- `committer-date:>=2024-01-01 flaky claude test`
- `committer-date:>=2024-01-01 flaky gemini test`
- `committer-date:>=2024-01-01 flaky gpt test`
- `committer-date:>=2024-01-01 flaky "model output" test`
- `committer-date:>=2024-01-01 flaky prompt test`
- `committer-date:>=2024-01-01 flaky eval test`
- `committer-date:>=2024-01-01 flaky langchain test`
- `committer-date:>=2024-01-01 flaky langgraph test`
- `committer-date:>=2024-01-01 flaky crewai test`
- `committer-date:>=2024-01-01 flaky autogen test`
- `committer-date:>=2024-01-01 flaky llamaindex test`
- `committer-date:>=2024-01-01 flaky "llama-index" test`
- `committer-date:>=2024-01-01 flaky "pydantic-ai" test`
- `committer-date:>=2024-01-01 flaky "ai sdk" test`
- `committer-date:>=2024-01-01 flaky agent test`
- `committer-date:>=2024-01-01 flakiness llm test`
- `committer-date:>=2024-01-01 flakiness openai test`
- `committer-date:>=2024-01-01 flakiness anthropic test`
- `committer-date:>=2024-01-01 flakiness claude test`
- `committer-date:>=2024-01-01 flakiness gemini test`
- `committer-date:>=2024-01-01 flakiness gpt test`
- `committer-date:>=2024-01-01 flakiness "model output" test`
- `committer-date:>=2024-01-01 flakiness prompt test`
- `committer-date:>=2024-01-01 flakiness eval test`
- `committer-date:>=2024-01-01 flakiness langchain test`
- `committer-date:>=2024-01-01 flakiness langgraph test`
- `committer-date:>=2024-01-01 flakiness crewai test`
- `committer-date:>=2024-01-01 flakiness autogen test`
- `committer-date:>=2024-01-01 flakiness llamaindex test`
- `committer-date:>=2024-01-01 flakiness "llama-index" test`
- `committer-date:>=2024-01-01 flakiness "pydantic-ai" test`
- `committer-date:>=2024-01-01 flakiness "ai sdk" test`
- `committer-date:>=2024-01-01 flakiness agent test`
- `committer-date:>=2024-01-01 nondeterministic llm test`
- `committer-date:>=2024-01-01 nondeterministic openai test`
- `committer-date:>=2024-01-01 nondeterministic anthropic test`
- `committer-date:>=2024-01-01 nondeterministic claude test`
- `committer-date:>=2024-01-01 nondeterministic gemini test`
- `committer-date:>=2024-01-01 nondeterministic gpt test`
- `committer-date:>=2024-01-01 nondeterministic "model output" test`
- `committer-date:>=2024-01-01 nondeterministic prompt test`
- `committer-date:>=2024-01-01 nondeterministic eval test`
- `committer-date:>=2024-01-01 nondeterministic langchain test`
- `committer-date:>=2024-01-01 nondeterministic langgraph test`
- `committer-date:>=2024-01-01 nondeterministic crewai test`
- `committer-date:>=2024-01-01 nondeterministic autogen test`
- `committer-date:>=2024-01-01 nondeterministic llamaindex test`
- `committer-date:>=2024-01-01 nondeterministic "llama-index" test`
- `committer-date:>=2024-01-01 nondeterministic "pydantic-ai" test`
- `committer-date:>=2024-01-01 nondeterministic "ai sdk" test`
- `committer-date:>=2024-01-01 nondeterministic agent test`
- `committer-date:>=2024-01-01 "non-deterministic" llm test`
- `committer-date:>=2024-01-01 "non-deterministic" openai test`
- `committer-date:>=2024-01-01 "non-deterministic" anthropic test`
- `committer-date:>=2024-01-01 "non-deterministic" claude test`
- `committer-date:>=2024-01-01 "non-deterministic" gemini test`
- `committer-date:>=2024-01-01 "non-deterministic" gpt test`
- `committer-date:>=2024-01-01 "non-deterministic" "model output" test`
- `committer-date:>=2024-01-01 "non-deterministic" prompt test`
- `committer-date:>=2024-01-01 "non-deterministic" eval test`
- `committer-date:>=2024-01-01 "non-deterministic" langchain test`
- `committer-date:>=2024-01-01 "non-deterministic" langgraph test`
- `committer-date:>=2024-01-01 "non-deterministic" crewai test`
- `committer-date:>=2024-01-01 "non-deterministic" autogen test`
- `committer-date:>=2024-01-01 "non-deterministic" llamaindex test`
- `committer-date:>=2024-01-01 "non-deterministic" "llama-index" test`
- `committer-date:>=2024-01-01 "non-deterministic" "pydantic-ai" test`
- `committer-date:>=2024-01-01 "non-deterministic" "ai sdk" test`
- `committer-date:>=2024-01-01 "non-deterministic" agent test`
- `committer-date:>=2024-01-01 "non deterministic" llm test`
- `committer-date:>=2024-01-01 "non deterministic" openai test`
- `committer-date:>=2024-01-01 "non deterministic" anthropic test`
- `committer-date:>=2024-01-01 "non deterministic" claude test`
- `committer-date:>=2024-01-01 "non deterministic" gemini test`
- `committer-date:>=2024-01-01 "non deterministic" gpt test`
- `committer-date:>=2024-01-01 "non deterministic" "model output" test`
- `committer-date:>=2024-01-01 "non deterministic" prompt test`
- `committer-date:>=2024-01-01 "non deterministic" eval test`
- `committer-date:>=2024-01-01 "non deterministic" langchain test`
- `committer-date:>=2024-01-01 "non deterministic" langgraph test`
- `committer-date:>=2024-01-01 "non deterministic" crewai test`
- `committer-date:>=2024-01-01 "non deterministic" autogen test`
- `committer-date:>=2024-01-01 "non deterministic" llamaindex test`
- `committer-date:>=2024-01-01 "non deterministic" "llama-index" test`
- `committer-date:>=2024-01-01 "non deterministic" "pydantic-ai" test`
- `committer-date:>=2024-01-01 "non deterministic" "ai sdk" test`
- `committer-date:>=2024-01-01 "non deterministic" agent test`
- `committer-date:>=2024-01-01 intermittent llm test`
- `committer-date:>=2024-01-01 intermittent openai test`
- `committer-date:>=2024-01-01 intermittent anthropic test`
- `committer-date:>=2024-01-01 intermittent claude test`
- `committer-date:>=2024-01-01 intermittent gemini test`
- `committer-date:>=2024-01-01 intermittent gpt test`
- `committer-date:>=2024-01-01 intermittent "model output" test`
- `committer-date:>=2024-01-01 intermittent prompt test`
- `committer-date:>=2024-01-01 intermittent eval test`
- `committer-date:>=2024-01-01 intermittent langchain test`
- `committer-date:>=2024-01-01 intermittent langgraph test`
- `committer-date:>=2024-01-01 intermittent crewai test`
- `committer-date:>=2024-01-01 intermittent autogen test`
- `committer-date:>=2024-01-01 intermittent llamaindex test`
- `committer-date:>=2024-01-01 intermittent "llama-index" test`
- `committer-date:>=2024-01-01 intermittent "pydantic-ai" test`
- `committer-date:>=2024-01-01 intermittent "ai sdk" test`
- `committer-date:>=2024-01-01 intermittent agent test`
- `committer-date:>=2024-01-01 "randomly fails" llm test`
- `committer-date:>=2024-01-01 "randomly fails" openai test`
- `committer-date:>=2024-01-01 "randomly fails" anthropic test`
- `committer-date:>=2024-01-01 "randomly fails" claude test`
- `committer-date:>=2024-01-01 "randomly fails" gemini test`
- `committer-date:>=2024-01-01 "randomly fails" gpt test`
- `committer-date:>=2024-01-01 "randomly fails" "model output" test`
- `committer-date:>=2024-01-01 "randomly fails" prompt test`
- `committer-date:>=2024-01-01 "randomly fails" eval test`
- `committer-date:>=2024-01-01 "randomly fails" langchain test`
- `committer-date:>=2024-01-01 "randomly fails" langgraph test`
- `committer-date:>=2024-01-01 "randomly fails" crewai test`
- `committer-date:>=2024-01-01 "randomly fails" autogen test`
- `committer-date:>=2024-01-01 "randomly fails" llamaindex test`
- `committer-date:>=2024-01-01 "randomly fails" "llama-index" test`
- `committer-date:>=2024-01-01 "randomly fails" "pydantic-ai" test`
- `committer-date:>=2024-01-01 "randomly fails" "ai sdk" test`
- `committer-date:>=2024-01-01 "randomly fails" agent test`
- `committer-date:>=2024-01-01 "fails randomly" llm test`
- `committer-date:>=2024-01-01 "fails randomly" openai test`
- `committer-date:>=2024-01-01 "fails randomly" anthropic test`
- `committer-date:>=2024-01-01 "fails randomly" claude test`
- `committer-date:>=2024-01-01 "fails randomly" gemini test`
- `committer-date:>=2024-01-01 "fails randomly" gpt test`
- `committer-date:>=2024-01-01 "fails randomly" "model output" test`
- `committer-date:>=2024-01-01 "fails randomly" prompt test`
- `committer-date:>=2024-01-01 "fails randomly" eval test`
- `committer-date:>=2024-01-01 "fails randomly" langchain test`
- `committer-date:>=2024-01-01 "fails randomly" langgraph test`
- `committer-date:>=2024-01-01 "fails randomly" crewai test`
- `committer-date:>=2024-01-01 "fails randomly" autogen test`
- `committer-date:>=2024-01-01 "fails randomly" llamaindex test`
- `committer-date:>=2024-01-01 "fails randomly" "llama-index" test`
- `committer-date:>=2024-01-01 "fails randomly" "pydantic-ai" test`
- `committer-date:>=2024-01-01 "fails randomly" "ai sdk" test`
- `committer-date:>=2024-01-01 "fails randomly" agent test`
- `committer-date:>=2024-01-01 xfail llm test`
- `committer-date:>=2024-01-01 xfail openai test`
- `committer-date:>=2024-01-01 xfail anthropic test`
- `committer-date:>=2024-01-01 xfail claude test`
- `committer-date:>=2024-01-01 xfail gemini test`
- `committer-date:>=2024-01-01 xfail gpt test`
- `committer-date:>=2024-01-01 xfail "model output" test`
- `committer-date:>=2024-01-01 xfail prompt test`
- `committer-date:>=2024-01-01 xfail eval test`
- `committer-date:>=2024-01-01 xfail langchain test`
- `committer-date:>=2024-01-01 xfail langgraph test`
- `committer-date:>=2024-01-01 xfail crewai test`
- `committer-date:>=2024-01-01 xfail autogen test`
- `committer-date:>=2024-01-01 xfail llamaindex test`
- `committer-date:>=2024-01-01 xfail "llama-index" test`
- `committer-date:>=2024-01-01 xfail "pydantic-ai" test`
- `committer-date:>=2024-01-01 xfail "ai sdk" test`
- `committer-date:>=2024-01-01 xfail agent test`
- `committer-date:>=2024-01-01 unstable llm test`
- `committer-date:>=2024-01-01 unstable openai test`
- `committer-date:>=2024-01-01 unstable anthropic test`
- `committer-date:>=2024-01-01 unstable claude test`
- `committer-date:>=2024-01-01 unstable gemini test`
- `committer-date:>=2024-01-01 unstable gpt test`
- `committer-date:>=2024-01-01 unstable "model output" test`
- `committer-date:>=2024-01-01 unstable prompt test`
- `committer-date:>=2024-01-01 unstable eval test`
- `committer-date:>=2024-01-01 unstable langchain test`
- `committer-date:>=2024-01-01 unstable langgraph test`
- `committer-date:>=2024-01-01 unstable crewai test`
- `committer-date:>=2024-01-01 unstable autogen test`
- `committer-date:>=2024-01-01 unstable llamaindex test`
- `committer-date:>=2024-01-01 unstable "llama-index" test`
- `committer-date:>=2024-01-01 unstable "pydantic-ai" test`
- `committer-date:>=2024-01-01 unstable "ai sdk" test`
- `committer-date:>=2024-01-01 unstable agent test`
- `committer-date:>=2024-01-01 retry llm test`
- `committer-date:>=2024-01-01 retry openai test`
- `committer-date:>=2024-01-01 retry anthropic test`
- `committer-date:>=2024-01-01 retry claude test`
- `committer-date:>=2024-01-01 retry gemini test`
- `committer-date:>=2024-01-01 retry gpt test`
- `committer-date:>=2024-01-01 retry "model output" test`
- `committer-date:>=2024-01-01 retry prompt test`
- `committer-date:>=2024-01-01 retry eval test`
- `committer-date:>=2024-01-01 retry langchain test`
- `committer-date:>=2024-01-01 retry langgraph test`
- `committer-date:>=2024-01-01 retry crewai test`
- `committer-date:>=2024-01-01 retry autogen test`
- `committer-date:>=2024-01-01 retry llamaindex test`
- `committer-date:>=2024-01-01 retry "llama-index" test`
- `committer-date:>=2024-01-01 retry "pydantic-ai" test`
- `committer-date:>=2024-01-01 retry "ai sdk" test`
- `committer-date:>=2024-01-01 retry agent test`
- `committer-date:>=2024-01-01 rerun llm test`
- `committer-date:>=2024-01-01 rerun openai test`
- `committer-date:>=2024-01-01 rerun anthropic test`
- `committer-date:>=2024-01-01 rerun claude test`
- `committer-date:>=2024-01-01 rerun gemini test`
- `committer-date:>=2024-01-01 rerun gpt test`
- `committer-date:>=2024-01-01 rerun "model output" test`
- `committer-date:>=2024-01-01 rerun prompt test`
- `committer-date:>=2024-01-01 rerun eval test`
- `committer-date:>=2024-01-01 rerun langchain test`
- `committer-date:>=2024-01-01 rerun langgraph test`
- `committer-date:>=2024-01-01 rerun crewai test`
- `committer-date:>=2024-01-01 rerun autogen test`
- `committer-date:>=2024-01-01 rerun llamaindex test`
- `committer-date:>=2024-01-01 rerun "llama-index" test`
- `committer-date:>=2024-01-01 rerun "pydantic-ai" test`
- `committer-date:>=2024-01-01 rerun "ai sdk" test`
- `committer-date:>=2024-01-01 rerun agent test`
- `committer-date:>=2024-01-01 "skip llm" test`
- `committer-date:>=2024-01-01 "llm tests" test`
- `committer-date:>=2024-01-01 "live llm" test`
- `committer-date:>=2024-01-01 "real llm" test`
- `committer-date:>=2024-01-01 "mock the llm" test`
- `committer-date:>=2024-01-01 "mock llm" test`
- `committer-date:>=2024-01-01 "record and replay" llm test`
- `committer-date:>=2024-01-01 cassette llm test`
- `committer-date:>=2024-01-01 vcr openai test`
- `committer-date:>=2024-01-01 "tests are expensive" llm`
- `committer-date:>=2024-01-01 "tests are expensive" openai`
- `committer-date:>=2024-01-01 "tests are expensive" agent`
- `committer-date:>=2024-01-01 "expensive tests" llm`
- `committer-date:>=2024-01-01 "expensive tests" openai`
- `committer-date:>=2024-01-01 "expensive tests" agent`
- `committer-date:>=2024-01-01 "api costs" test llm`
- `committer-date:>=2024-01-01 "api costs" test openai`
- `committer-date:>=2024-01-01 "api costs" test agent`
- `committer-date:>=2024-01-01 "token cost" test llm`
- `committer-date:>=2024-01-01 "token cost" test openai`
- `committer-date:>=2024-01-01 "token cost" test agent`

Plus, for each model-answer recording package `<pkg>` from §0.2d: `<pkg> filename:pyproject.toml`, `<pkg> filename:requirements.txt`, `<pkg> filename:package.json`.

If the §0.2b OR check fails on issues, each S2 cost query `... <q> (llm OR openai OR agent)` becomes three queries `... <q> llm`, `... <q> openai`, `... <q> agent`. If GitHub requires `is:issue`/`is:pr`, every issues query gets ` is:issue` and ` is:pr` appended (two queries).

### §3.2 repository queries (for repository `<r>`)

- `repo:<r> created:>=2024-01-01 (flaky OR nondeterministic OR "non-deterministic" OR intermittent OR unstable)`
- `repo:<r> created:>=2024-01-01 llm (skip OR disable OR expensive OR cost OR mock)`
- `repo:<r> created:>=2024-01-01 openai (skip OR disable OR expensive OR cost OR mock)`
- `repo:<r> created:>=2024-01-01 agent (skip OR disable OR expensive OR cost OR mock)`
- `repo:<r> created:>=2024-01-01 model (skip OR disable OR expensive OR cost OR mock)`
- `repo:<r> created:>=2024-01-01 prompt (skip OR disable OR expensive OR cost OR mock)`
- `repo:<r> committer-date:>=2024-01-01 (flaky OR nondeterministic OR "non-deterministic" OR intermittent OR unstable)`
- `repo:<r> committer-date:>=2024-01-01 llm (skip OR disable OR expensive OR cost OR mock)`
- `repo:<r> committer-date:>=2024-01-01 openai (skip OR disable OR expensive OR cost OR mock)`
- `repo:<r> committer-date:>=2024-01-01 agent (skip OR disable OR expensive OR cost OR mock)`
- `repo:<r> committer-date:>=2024-01-01 model (skip OR disable OR expensive OR cost OR mock)`
- `repo:<r> committer-date:>=2024-01-01 prompt (skip OR disable OR expensive OR cost OR mock)`

Single-term split (OR check failed for that kind): each `(a OR b OR ...)` group becomes one query per term, e.g. `repo:<r> created:>=2024-01-01 flaky`.
