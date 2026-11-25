# Agent tools count: pre-registration

Committed before any data request (probe or main run). Spec: new-brain
`gstack/projects/Mircoguidetti-fenvix-engine-cli/specs/` agent tools count, LAUNCHED rev 4 (gate 7/10,
`20261125-agent-tools-count-gate-rev4.md`), with the gate rev 3 and rev 4 notes, which govern where they differ from
the body. Where the spec leaves a choice open, the choice is written here (marked **Interpretation**) before any
data is read. Any later change is listed on its own line in REPORT.md, with its justification, before any result.

Code: `rules.py` (every rule and regex), `pipeline.py` (reads, Count A per pull request, Count B per repository),
`job.py` (chunks), `common.py` (`seeded_order`, copied verbatim). Base-side rule copied from Count 2
(`origin/claude/agent-pr-scan-count2` 3aee9ba, `pipeline.py` / `rules.py`).

## Decision lines (founder, fixed; not to reopen), by 15 Dec 2026

- **(a) where it breaks:** if fewer than 20% of already-red agent pull requests show at least one wasted agent
  commit, "where it breaks" is dropped.
- **(b) the race:** if fewer than 5% of agent-addressed issues received 2 or more competing agent pull requests,
  "the race" is dropped.
- Decisions use the point estimate (exact fractions, so 19/95 = 20.0% is CONTINUE); the Wilson 95% interval
  (z = 1.96) is printed. Output lines, exactly:
  `(a) where it breaks: CONTINUE|DROP|NOT ENOUGH DATA (Rate A <x>% vs 20%, files evidence <e>%)` and
  `(b) the race: CONTINUE|DROP|NOT ENOUGH DATA (Rate B <y>% vs 5%, agent-addressed <m>)`.
- (a) is `NOT ENOUGH DATA` instead of DROP when Rate A < 20% and (1) fewer than 40% of rateable pull requests have
  `files` evidence for at least one X, or (2) the 30-row `not-wasted` sample has 1-3 misses and the miss-adjusted
  Rate A = (wasted + misses/30 x not-wasted) / rateable is at least 20% (gate rev 4 note 1). With more than 3
  misses the rule is fixed (a listed change), every rateable pull request is re-run, and only rows that become
  `wasted` are newly hand-read (gate rev 4 note 5).
- (b) is decided only with at least 200 `agent-addressed` issues; fewer -> `NOT ENOUGH DATA`.

## Dates and seeds

- `LAUNCH` (planned date of the first data request) = **2026-11-25**. `RACE_FROM` = LAUNCH - 90 days =
  **2026-08-27T00:00:00Z**. A slip of LAUNCH is a listed change (RACE_FROM stays as written here unless listed).
- Seeds: Count B repository order `seeded_order({"all": [{"url": r} for r in sorted(repos)]}, seed=2)`;
  Count A `not-wasted` sample `random.Random(3).sample(sorted(urls), 30)`; Count B competing sample
  `random.Random(4).sample(sorted(keys), 60)` if more than 60; non-competing agent-addressed sample
  `random.Random(5).sample(sorted(keys), 60)` (all if 60 or fewer). Issue keys are `"<owner>/<repo>#<number>"`.

## §0 Probe

Raw (untrimmed) JSON committed under `results/probe/`, one Count 2 pull request per family, each an
`ALREADY_RED` row of Count 2 (first in Count 2's read order per family), and one repository:

- Copilot `lxndrp/lzug#254`, Devin `colombo-labs/movicol-frontend#23`, Jules `takaraflow/drive-collector-js#383`,
  Codex `pawelekbyra/polutek-pl#1281`, Claude Code `paiml/aprender#1339`; repository `lxndrp/lzug`.
- Endpoints: `pulls/{n}`, `pulls/{n}/commits`, `pulls/{n}/files`, `pulls/{n}/reviews`, `commits/{sha}/check-runs`,
  `commits/{sha}/status`, `actions/runs?head_sha=`, `actions/runs/{id}/jobs`, `actions/runs/{id}`,
  `check-runs/{id}`, `check-runs/{id}/annotations`, `commits/{sha}`, `git/trees/{sha}?recursive=1`, the contents
  API, `issues/{n}/timeline`, `repos/{r}/issues?state=closed&since=`, `repos/{r}/pulls`.
- Recorded: pull request author logins and commit author logins per family. An endpoint not answering HTTP 200 is
  listed; if `pulls/{n}/commits`, check runs or `issues/{n}/timeline` fail, REPORT's first line is `BLOCKED`.
- The expected logins (`Copilot`, `devin-ai-integration[bot]`, `google-labs-jules[bot]`) are the ones in
  `rules.COMMIT_LOGINS` / `rules.PR_LOGINS`; if the probe shows other logins, the constants are corrected before
  chunk 1 and the correction is a listed change.
- The probe does not start the 24 h budget; the first frame request does.

## §1 Count A: wasted agent commits on reds that were already there

Frame: the 1,500 pull requests of Count 2's `results/rows.jsonl` at 3aee9ba, in that file's order
(`frame.jsonl`, md5 `c134bf6bd9e7ba83fd010b8d193b8d11`; `pos` 0-1499).

1. Reads: `pulls/{n}` (author login, head ref, body, commit count); `pulls/{n}/commits?per_page=100` pages 1-3;
   more than 250 commits -> `uncertain`. `issues/{n}/timeline` (all pages): `head_ref_force_pushed` events counted,
   reported only.
2. Every commit c in order: `commits/{sha}/check-runs?per_page=100` (every page, no cap), `commits/{sha}/status`,
   and `actions/runs?head_sha=<sha>&per_page=100` (every page). **Interpretation**: the run listing is read only
   when the commit has at least one Actions check run (app `github-actions`); a commit without one needs no
   Actions identity. `/jobs` of each run with a failed check (Count 2). Identities exactly as Count 2:
   `<workflow name> / <job name>` for Actions (workflow name from the run with the check run's check suite),
   `name` for other check runs, `context` for statuses. **Interpretation**: statuses and check runs are separate
   identity namespaces (a status and a check run with the same name are different X).
3. Already red at c: each commit is judged exactly as Count 2 judges a head commit (`judge_commit` =
   Count 2's `run_pr` without the secondary rule): failed = check runs `failure`, `timed_out`, `startup_failure`;
   statuses `failure`, `error`; window from = min(PR `created_at`, earliest S of c's failed checks) - 7 days,
   to = latest S; `pick_primary` (most recent completed base result with a signal, started in [S - 7 days, S));
   `MAX_RUN_PAGES = 3`, `MAX_JOB_READS = 20`, `MAX_BASE_COMMITS = 30`; one response cache per pull request.
   X is already red at c when its verdict is `ALREADY_RED`. k(X) = first such commit (1-based position);
   T = X's `completed_at` at k (status `updated_at`). B(X) = the base result that decided it: for Actions the base
   job (`base.job_id` = its check run id) and the base run's `head_sha`; for other check runs the base check run
   id (`check_id`, gate rev 3 note 1) and base commit; statuses have none.
4. Rateable: at least one X. A commit after k is judged for each X separately.
5. Evidence (X's check run at k, and B(X)'s check run): `check-runs/{id}` and
   `check-runs/{id}/annotations?per_page=100` (first page). Candidates: annotation `path` with
   `annotation_level == "failure"`, leading `./` stripped, excluded when `path == ".github"` or
   `path.startswith(".github/")`; plus paths matched in `output.title`, `output.summary`, `output.text` (each
   truncated to 30,000 characters in the stored response) by this regex, flags `re.MULTILINE`, case-sensitive,
   applied line by line, skipping lines that match `\bPASS(ED)?\b` (case-sensitive) or contain `✓`:

   ```
   (?:^|[\s("'`])(?:/home/runner/work/[^/\s]+/[^/\s]+/|\./)?((?:[\w.-]+/)*[\w.-]+\.(?:jsx|tsx|mjs|cjs|js|ts|py|rb|go|rs|java|kt|php|cs|swift|scala|exs|ex|vue|svelte|cpp|c|h|dart))(?![\w.])(?::\d+(?::\d+)?)?
   ```

   Group 1 is the path; a leading `./` is stripped. Excluded: any path with a directory component equal to
   `node_modules`, `vendor`, `.venv`, `site-packages`, `dist` or `build`. Kept: candidates that are blob entries of
   `git/trees/<commit>?recursive=1` (X: the commit at k; B(X): the base commit, gate rev 3 note 12); if the tree is
   `truncated`, a candidate not in the listing is checked with `contents/{path}?ref=<commit>` (`type == "file"`).
   Classes: `files` (at least one failure file), `none` (also for statuses and when a read fails). Each failure
   file of X is marked `in-base` `yes` / `no` / `base-unknown` (B(X) has no failure file). Limits: a path followed
   by a sentence-final period, container (`/__w/`), macOS (`/Users/runner/`) and Windows paths are not captured.
6. Agent commits: Copilot, Devin, Jules: commit author login in `{"Copilot"}`, `{"devin-ai-integration[bot]"}`,
   `{"google-labs-jules[bot]"}`. Claude Code: message matches `Co-Authored-By: Claude|Generated with \[?Claude Code`
   (case-insensitive) or commit author login `claude[bot]` (gate rev 3 note 6; **Interpretation**: applied
   whether or not the probe sees it). Codex: head ref starts with `codex/` and commit author login equals the pull
   request author. Other commits are `human`. A commit with 2 or more parents is never wasted.
7. Wasted commit for X: an agent commit with position > k, committer date > T, position <= end(X), fewer than 2
   parents, and one of:
   - (i) `commits/{sha}` lists a failure file of X;
   - (ii) its message matches, case-insensitive,
     ```
     \b(fix(e[sd])?|repair(ed)?|resolve[sd]?)\b[^.\n]{0,30}\b(failing|broken|flaky|red)?\s*(tests?|ci|build|checks?|pipeline|lint)\b
     ```
     and no `NEW_RED` check failed on the latest earlier commit that has at least one check run or status
     (**Interpretation**: no such earlier commit -> the guard does not block);
   - (iii) `commits/{sha}` lists the workflow file that defines X (the `path` of X's workflow run at k), or a
     reusable workflow it calls: `uses: ./.github/workflows/<f>` or `uses: <this repo>/.github/workflows/<f>@ref`
     in the caller file at k (`contents/<path>?ref=<sha_k>`, read only when a window commit changes another file
     under `.github/workflows/`). Composite actions under `.github/actions/` are not covered (limit).
   end(X) = the first position j > k where X passes (a completed check run or status of identity X with conclusion
   `success`, and no failed result of X at j) or X fails with verdict `NEW_RED` (gate rev 4 note 4); else the last
   commit. **Interpretation**: end(X) is inclusive (the commit that turns X green, or the one judged NEW_RED, is
   in the window).
8. Result: `wasted` (a wasted commit for some X), `not-wasted` (an agent commit with position > k and date > T for
   some X, none wasted; **Interpretation**: merge commits do not count as such a commit), `no-later-commit`
   (counted as not wasted), `uncertain` (more than 250 commits; `pulls/{n}`, the commit listing, a commit's checks,
   or a window commit's `commits/{sha}` unreadable after the source's retries), `not-rateable` (no X).
   Rate A = wasted / (wasted + not-wasted + no-later-commit), pooled and per family (Count 2's family), with
   Wilson. Files evidence share = rateable pull requests with `files` evidence for at least one X / rateable.
9. Hand read: every `wasted` pull request (codes `W-file`, `W-msg`, `W-ci`, `R-product`, `R-own`, `R-sync`, one or
   more per wasted commit; `R-own` only on positive evidence: the failure file was changed by an agent commit
   before k, or B(X) names other files and not this one) and `random.Random(3).sample(sorted(not-wasted urls), 30)`
   (fewer than 30 -> all). A `wasted` pull request whose codes are all R-* becomes `not-wasted`; Rate A uses the
   hand-read `wasted` set. A sample miss is reported with the rule that missed it.
10. Information lines as spec §1.10. `human_after` = non-merge human commits with position > the smallest k.

## §2 Count B: competing agent pull requests for one issue

Repositories: the frame's 1,171 distinct repositories in `seeded_order` seed 2 (`job.b_order()`).

1. `pulls?state=all&sort=created&direction=desc&per_page=100` (first page): no agent pull request (family markers
   below, on the list item: author login, head ref, body) created on or after RACE_FROM -> `skipped-no-agent`.
2. `issues?state=closed&since=RACE_FROM&sort=updated&direction=desc&per_page=100`, at most 10 pages; items without
   `pull_request` with `closed_at` >= RACE_FROM (de-duplicated by number); 10 full pages -> `truncated`.
3. `issues/{n}/timeline?per_page=100` (all pages): `cross-referenced` events with `source.issue.pull_request` set
   and `source.issue.repository.full_name` equal to this repository (case-insensitive). Linked when (a) the body
   (`source.issue.body`) has, by `finditer`, a match of (case-insensitive)
   ```
   \b(close[sd]?|fix(e[sd])?|resolve[sd]?):?\s+(?:(?P<repo>[\w.-]+/[\w.-]+)?#|https://github\.com/(?P<urlrepo>[\w.-]+/[\w.-]+)/issues/)(?P<num>\d+)(?!\d)
   ```
   with `num` = the issue and any captured repository equal to this one (case-insensitive), or (b) the head ref
   matches `(^|[/_-])<n>([/_-]|$)`. Same rule in numerator and denominator.
4. Agent pull request (Count 2's markers): author login `Copilot`, `devin-ai-integration[bot]`,
   `google-labs-jules[bot]`; Codex = head ref starts with `codex/` and body matches `chatgpt\.com/codex`; Claude
   Code = body matches `Generated with \[?Claude Code` (case-insensitive). **Interpretation** (gate rev 3 note 7):
   `pulls/{m}` is read only for a cross-referenced pull request that could be an agent's by login or body marker
   and whose head ref is needed (no closing keyword, or a Codex body marker without an agent login). For each
   linked agent pull request `pulls/{m}/files?per_page=20` is read (hand read).
5. Classes: `agent-addressed` = at least one linked agent pull request; `competing` = 2 distinct ones a, b with
   `a.created_at < end(b)` and `b.created_at < end(a)`, end = `merged_at`, else `closed_at`, else infinity (times
   from the cross-reference's `source.issue`); `sequential` = 2 or more, no overlapping pair; `single` = one.
   Family of an issue = family of its earliest-created linked agent pull request. **Interpretation**: an issue
   whose timeline cannot be read is not counted (reported).
6. Labels (competing only): `pulls/{m}` (head sha), `pulls/{m}/reviews`, check runs of the head sha (all pages);
   `first-opened`, `first-green` (green = every check run completed with `success`, `skipped` or `neutral` and none
   `failure`, `timed_out`, `cancelled`, `action_required`; time = latest `completed_at`; no check run = not green),
   `only-green`, `reviewed` (an `APPROVED` review the others lack), `other`, `none-merged`; the merged one = the
   earliest merged.
7. Hand read as spec §2.6; it does not change Rate B. Rate B = competing / agent-addressed, pooled and per family,
   Wilson.

## §3 Budget and execution

- Route: GitHub Actions in this repository (`.github/workflows/agent-tools-count.yml`, `GITHUB_TOKEN`, GET only,
  User-Agent `fenvix-research`), one request per second at most (ceiling about 3,600 per hour), sleeping until the
  reset when `X-RateLimit-Remaining` < 500. Results committed back to this branch by the job.
- One 24 h budget from the first data request (`budget_start` in `results/checkpoint.json`). Count A first, in
  frame order, for at most 14 h (gate rev 4 note 3); Count B in the remaining time, at least 10 h, until 24 h.
- Chunks `requests/<n>.json` = `{"chunk": n, "part": "A"|"B", "items": [...], "max_minutes": 320}`; the job stops
  before the next item after 320 minutes. **Interpretation**: a Count B repository interrupted by the chunk limit
  is read again from the start in the next chunk; one interrupted by the 24 h end is kept as `partial-budget`
  (its read issues count). After chunk 1 REPORT prints requests per pull request and `fits 24 h: yes|no`
  (projected at 3,600 per hour); after Count B's first chunk, requests per issue and `fits remaining budget`.

## Rule changes after this file

None at commit time. Any change is listed in REPORT.md before any result.
