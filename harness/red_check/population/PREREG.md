# C5.3: the 6 measurement repositories (pre-registration)

Spec: C4 + C5.3 rev 2 (2026-11-25), part 2. Written and committed before any request of steps 2.2-2.6 (the probe of
2.1 excepted: `routes.md`). Any later change is one line in `REPORT.md` with its justification, written before any
result it affects. Public data only, read-only requests; no contact with any repository owner.

## Transport

- 2.2 (`pool.py`): GitHub issue search from the session's own `gh api` (the account's search budget), at most 1
  request per 3 s, 60 s back-off on a secondary-limit 403 (at most 8 attempts per request).
- 2.3-2.8 (`collect.py`): route 1 (`routes.md`): workflow `.github/workflows/red-check-population.yml`, request files
  pushed to `claude/red-check-c53`, `GITHUB_TOKEN`, User-Agent `fenvix-research`, at most 1 request per second.
  A chunk stops before its next PR when `X-RateLimit-Remaining` < 20% of `X-RateLimit-Limit`, or after the request
  file's `max_minutes`; its checkpoint is committed with its results and the next chunk resumes from it.
- Every request of 2.3-2.8 (repository metadata, log blobs and their API redirects included) counts toward the
  10,000 cap of 2.4.

## 2.2 Window and pool

- D = the UTC date on which `pool.py` starts; window [D-60 days, D). Nine windows of 7 days (`created:A..B`, both
  dates inclusive), the last one 4 days: window i (0-8) is [D-60+7i, min(D-60+7i+6, D-1)].
- Queries = Count 1's `COUNT1` with `is:merged` removed (any state):
  - copilot `is:pr is:public author:app/copilot-swe-agent`
  - devin `is:pr is:public author:app/devin-ai-integration`
  - jules `is:pr is:public author:app/google-labs-jules`
  - codex `is:pr is:public head:codex/`
  - claude_code `is:pr is:public "Generated with Claude Code"`
- At most 3 pages of 100 per (family, window), `search/issues`; a window whose `total_count` is above the rows read is
  recorded as truncated (`results/pool_windows.jsonl`).
- Family rules (Count 2): codex needs `chatgpt.com/codex` in the body; claude_code needs "Generated with Claude Code"
  (`Generated with \[?Claude Code`, case-insensitive) in the body; copilot, devin and jules by the author app of the query.
- Pool rows de-duplicated by URL; a URL found by two families keeps the first in the order copilot, devin, jules, codex,
  claude_code and records every family that found it (`families`).

## 2.3 Static exclusions

- Repository level, no request: owner (case-insensitive) in {mircoguidetti, github, anthropics, openai, microsoft}.
- Repository level, from `GET repos/{o}/{r}` (fetched lazily: only for the repository about to be read in 2.4's
  order, cached, counted in the cap): fork, archived, private → excluded with that reason; a non-200 →
  `repo_unreadable`. The next repository in the order is taken.
- PR level: repository created less than 30 days before the PR's `created_at` → `repo_too_young` (the repository's
  other PRs stay).
- Change from Count 2 (stated by the spec): metadata from `GET repos/{o}/{r}`, not `search/repositories`.

## 2.4 Repository order and reading

- Order: repositories by number of pool PRs after the owner exclusions (descending), then `full_name` ascending
  (case-insensitive). Metadata exclusions are applied when a repository's turn comes; the order is not recomputed.
- Within a repository: its pool PRs (after `repo_too_young`) newest `created_at` first, at most 40 read.
- Stop: when 30 repositories have been read (a repository counts as read once at least one of its PRs was read), or
  when 10,000 requests have been made, whichever comes first. Both are checked before each PR: a PR already started
  is finished, so the total can pass 10,000 by at most one PR's requests (reported). The stop reason and both counts
  are in REPORT.
- Per PR (`collect.py`):
  1. `pulls/{n}`: `head.sha`, `base.sha`, `base.ref`, `created_at`, `state`. Non-200 → `pr_unreadable`.
  2. `actions/runs?head_sha=<head.sha>&per_page=100` (one page), then `actions/runs/{id}/jobs?per_page=100` of each
     run with conclusion `failure` or `timed_out`. Non-200 on the runs list → `runs_unreadable`; a jobs list non-200
     is recorded and that run gives no candidate.
  3. Candidate jobs: conclusion `failure` or `timed_out`; no value of `labels` matches `/windows|macos/i`.
  4. Log of each candidate job (`actions/jobs/{id}/logs`, `ghrest.Client.get_log`), at most 3 per PR in job-id order;
     runner of each readable log by 2.5.
  5. A PR qualifies at this step when at least one candidate job has a readable log (blob 200, non-empty) and exactly
     one runner; the qualifying job is the lowest job id among those. Otherwise the verdict is `no_candidate_job`
     (no candidate), `no_readable_log` or `no_single_runner`.
  6. Qualifying PRs only: `compare/{base.sha}...{head.sha}` → `merge_base_commit.sha` = B0 (non-200 →
     `compare_unreadable`). The qualifying job's run `path` (any `@<ref>` suffix removed) read with
     `contents/{path}?ref=<head.sha>` and `?ref=<B0>`. B0's file: 404 → `job_absent_at_base`; other non-200 →
     `workflow_unreadable`; YAML that does not parse to a mapping with a `jobs` mapping → `workflow_unparseable`
     (the last two reasons are added by this PREREG: the spec names no reason for them). Then 2.6 at B0:
     not found → `job_absent_at_base`; reusable-workflow job → `reusable_workflow_job`. Else verdict `qualifying`.
- Verdicts other than `qualifying` are exclusions with that reason.

## 2.5 Runner of a failed job

Each line of the log: a leading byte-order mark removed (logs start with `\ufeff`, `routes.md`), then the GitHub
timestamp prefix `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z ` and ANSI escapes `\x1b\[[0-9;]*[A-Za-z]` removed. Then:

| Runner | Pattern (any line), failure count group must be >= 1 |
|---|---|
| vitest | `^\s*Test Files\s+(\d+) failed` |
| jest | `^Tests:\s+(\d+) failed` |
| node-test | `^(?:ℹ\|#) fail (\d+)\s*$` |
| pytest | `^=+ .*?\b(\d+) failed\b.* in [\d.]+s.*=+\s*$` |

Exactly one runner matched → that runner; none → `no_runner`; two or more → `ambiguous_runner` (both excluded at job
level). The summary line kept for the excerpt is the first line matched by the detected runner (for
`ambiguous_runner`, the first matched line of any runner).

## 2.6 Job definition at B0

Input: the job's display name `N` from the jobs API.
- Reusable-workflow caller: if `N` has the form `<caller> / <inner>` and `<caller>` equals the key (or `name`) of a job
  in the workflow at B0 that has a job-level `uses:` → `reusable_workflow_job`.
- Otherwise each job of the workflow at B0 is tested; it matches when any of:
  (a) its `name` equals `N`;
  (b) its `name` contains `${{ ... }}` and `N` matches the anchored regex built from `name` with literal parts escaped
      (`re.escape`) and each `${{ ... }}` replaced by `.*`;
  (c) its `name` has no expression and equals `N` minus a trailing ` (<...>)` matrix suffix;
  (d) it has no `name` and its key equals `N` minus a trailing ` (<...>)` matrix suffix (or `N` itself).
  Exactly one job matching in total → found; zero or two or more → not found (`job_absent_at_base`).
- YAML parsed with PyYAML 6.0.2 (`yaml.safe_load`). Recorded per qualifying PR: `runs_on`, `services`
  (name → image), `matrix` (axes → value counts; an expression string is recorded as such; null when none),
  `container` (bool), `needs` (list), the `uses:` actions of its steps, `uses_secrets` (any `secrets.` other than
  `secrets.GITHUB_TOKEN`, or `vars.`, anywhere in the job), and `differs_at_head` (the job definition found by the
  same rule in the head workflow differs from B0's; null when the head workflow or job cannot be read).

## 2.7 Selection (`select_repos.py`: the spec's `select.py`, renamed so it does not shadow the stdlib module `select`)

Per read repository, count = its `qualifying` PRs. The 6 repositories with the highest count (ties: `full_name`
ascending, case-insensitive) among those with count >= 3. Per selected repository at most 12 PRs:
`random.Random(3).sample(sorted(urls), 12)` when it has more, else all. Fewer than 6 repositories with count >= 3:
those there are; REPORT says how many and that C5 cannot reach 6 (the coordinator decides; the window is not widened
and the threshold is not lowered).

## 2.8 Oracle coverage (recorded, not a filter)

For each selected PR: `actions/runs?head_sha=<B0>&event=push&per_page=100`; whether a completed run of the same
workflow `path` exists, and the conclusion of the job with display name `N` in it (newest such run;
`runs/{id}/jobs?per_page=100`). REPORT gives the share of selected PRs with such a job.

## 2.9 Storage

Committed: this file, the code, tests, `requests/`, `results/checkpoint.json`, `results/pool.jsonl.gz`,
`results/pool_windows.jsonl`, `results/prs.jsonl.gz` (every PR read: fields of 2.4, verdict, reason),
`results/excerpts/<job_id>.txt.gz` (for each candidate job with a matched summary line: that line and at most 200
lines before it, the sha256 and byte size of the full log), `results/oracle.jsonl`, `selected.json`, `handcheck.jsonl`,
`REPORT.md`. Full logs only as the workflow artifact `red-check-population-logs` (retention 90 days; never in git).

## 2.11 Hand check

Before `selected.json` is final: `random.Random(4).sample(sorted(qualifying job ids), 10)` (all if fewer); the session
reads each excerpt and writes in `handcheck.jsonl` the runner it sees and whether it agrees with 2.5. Any
disagreement: the rule is fixed (one line in REPORT), every verdict recomputed from the full logs of the artifact,
the sample redrawn with `Random(5)`. Excerpts exist only for matched jobs, so the hand check finds false matches but
not misses.
