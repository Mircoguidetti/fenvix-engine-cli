# Count 2 pre-registration: is an agent pull request's red already red on the base?

Committed before any Count 2 result (probe or main run). Spec: new-brain
`gstack/projects/Mircoguidetti-fenvix-engine-cli/specs/20261124-agent-pr-scan-count2.md` (md5
1de362e09ce9aa6a62a3fb0184fe1e82). Where the spec leaves a choice open, the choice is written here (marked
**Interpretation**) before any data is read. Any later change is listed on its own line in REPORT.md with its
justification, before any result.

## Decision rule for idea 3 (22 Dec; threshold ASSUMED, the founder may change it before 22 Dec)

- Primary rate (pooled, all five families) = ALREADY_RED / (ALREADY_RED + NEW_RED).
- Validity ceiling: if NO_BASE_SIGNAL + UNREADABLE > 50% of PRs with a failed check, the decision sentence is exactly
  `No decision under the rule: the measured share is not valid; the founder decides.` and the primary rate is shown
  only as indicative.
- Otherwise, on the point estimate: rate >= 20% gives exactly
  `Idea 3 moves forward: the primary rate is at least 20%.`; rate < 20% gives exactly
  `Idea 3 is parked: the primary rate is below 20%.`
- If ALREADY_RED + NEW_RED = 0 there is no rate; the invalid-result sentence is used.
- The Wilson 95% interval (z = 1.96) is reported either way, pooled and per family.

## Sample

- Pools: the first scan's merged pools `harness/agent_pr_scan/search_rows/count1_<family>.jsonl.gz` plus
  closed-unmerged pools collected now by `closed_collect.py`: same COUNT1 queries, month windows (2026-05-01 to
  2026-11-15), week splits and 3-page cap, with `is:merged` -> `is:closed is:unmerged` and `merged:<w>` ->
  `closed:<w>`. Closed rows are keyed by their closed month. Merged and closed rows go into one pool per
  (family, month), de-duplicated by URL, before `common.seeded_order` (seed 1).
- Family rules (first scan, REPORT.md Deviations 6-7): Codex needs the body marker `chatgpt.com/codex`; Claude Code
  needs "Generated with Claude Code" in the body; Copilot, Devin and Jules by author app.
- Interleave: one PR per family in turn, families in the order copilot, devin, jules, codex, claude_code
  (**Interpretation**: the first scan ran Claude Code as a separate phase; here all five are interleaved in one
  order so the 3-per-repository cap applies once).
- Exclusions (as `count1_run.py`): owner in {mircoguidetti, github, anthropics, openai} plus vendor owners from
  `rules_check.jsonl` (microsoft); fork; archived; repository not returned by `search/repositories`; repository
  created less than 30 days before `merged_at` (merged rows) or `closed_at` (closed rows). Repository metadata from
  `search/repositories` (cache seeded from the first scan's `repo_meta.jsonl`). At most 3 PRs read per repository
  (counted over PRs read, as in `count1_run.py`).
- Quota: PRs are read in draw order; a family's PRs are skipped once it has 40 rateable PRs (ALREADY_RED +
  NEW_RED). Stop when all five families have 40 (target 200) or 1,500 PRs have been read (hard cap; a PR is
  "read" when its `pulls/{n}` request is made), or the draw is exhausted.
- Probe (Part 1): the first 5 PRs of this draw (after exclusions). They are processed by the same pipeline and are
  the first 5 PRs of the sample (not re-read); in addition, for each probe PR one base-branch run list
  (`actions/runs?branch=<base.ref>&per_page=20`) is read whatever the head result.

## Per-PR data (route 1, GitHub Actions with GITHUB_TOKEN, read-only, User-Agent `fenvix-research`)

- `pulls/{n}`: `head.sha` (last head commit), `base.ref`, `created_at`, `merged_at`, `closed_at`.
- Head: `checks()` copied from `harness/dep_verdict/ci_status.py`, keeping `started_at`, `completed_at`,
  `check_suite.id`, and status `created_at`; `actions/runs?head_sha=<sha>`; `/jobs` of every head workflow run
  that contains a failed check (job id = check-run id, recorded as confirmed or not).
- Failed: check runs `failure`, `timed_out`, `startup_failure`; statuses `failure`, `error`. Not failed: check runs
  `success`, `cancelled`, `skipped`, `neutral`, `action_required`, `stale`; statuses `success`, `pending`.
- Denominator: PRs whose last head commit has at least one failed check.
- Identity: Actions check (app `github-actions`) -> `<workflow name> / <job name>`, the workflow name taken from
  the head workflow run whose `check_suite_id` equals the check run's check suite. Other check runs -> `name`.
  Statuses -> `context`. **Interpretation**: an Actions check whose workflow run cannot be found among the head
  runs has no identity and is UNREADABLE ("workflow run not found").
- Head time S of a failed check: check run `started_at`; for a status, its `created_at`.
- Window (one per PR, both rules): from = min(PR `created_at`, earliest S of its failed checks) - 7 days; to = latest
  S of its failed checks. Each check then uses only base runs that started before its own S and at most 7 days
  before it.
- Actions base runs: `actions/runs?branch=<base.ref>&created=<from>..<to>&per_page=100`, at most 3 pages; keep runs
  whose workflow `name` equals the identity's workflow name and whose head repository is the PR's repository
  (**Interpretation**: drops fork-side runs whose branch happens to share the base branch name). Walk newest-first
  by `run_started_at` from S; read `/jobs` of each and stop at the first run that contains a job with the
  identity's job name and a usable result. **Interpretation**: a contained job that is not completed, that
  started at or after S, or whose conclusion is neither failed nor `success` (cancelled, skipped, neutral, ...)
  gives no signal and the walk continues to the next older run; at most 20 `/jobs` reads per identity (cap
  reached -> NO_BASE_SIGNAL with reason "jobs cap").
- Non-Actions checks and statuses: `commits?sha=<base.ref>&since=<from>&until=<to>&per_page=30` (at most 30
  commits), walked newest-first in API order, `checks()` on each until the first commit that has a completed check
  run of that name from an app other than github-actions (or a status of that context) started before S and at
  most 7 days before S, with a failed or success result (pending / other conclusions: continue).

## Verdicts

- Per failed head check: most recent usable base result failed -> ALREADY_RED; success -> NEW_RED; none in the
  window -> NO_BASE_SIGNAL; API error (non-200, including 404 repository, 403/404 Actions disabled) on a base
  request needed for that check -> UNREADABLE with its reason.
- Per PR: ALREADY_RED if any failed check is; else NEW_RED if any is; else NO_BASE_SIGNAL if any is; else
  UNREADABLE.
- **Interpretation**: a PR whose `pulls/{n}` or head check reads fail (non-200) cannot be put in or out of the
  denominator. It is recorded as PR_UNREADABLE / HEAD_UNREADABLE, counted and reported, and is outside "PRs with a
  failed check", outside the rate and outside the quota.
- Secondary rate (reported, not used by the rule): a PR is already red if any failed head check's identity had any
  failed base result started in [PR `created_at` - 7 days, PR `created_at`). **Interpretation** (cost): for Actions,
  only base runs in the fetched listing whose workflow run conclusion is failed are opened (`/jobs`, at most 10
  per identity); for non-Actions checks, only the base commits already read for the primary walk are used. Where
  the PR was opened after `to`, the part of that 7-day window after `to` is not fetched.

## Hand check

Before any rate is computed: `random.Random(2).sample(sorted(urls_with_failed_check), 20)`. For each, from the
committed raw JSON: the failed head check and its identity; the base run chosen as most recent before S; its
conclusion; the verdict. Disagreements are fixed in the rule (one written line each in REPORT.md) or the code, then
all verdicts are recomputed.

## Rate limits

At most 1 request per second; a chunk stops before its next PR when `X-RateLimit-Remaining` < 20% of
`X-RateLimit-Limit`; `results/checkpoint.json` is committed with each chunk and the next request file resumes from
it.
