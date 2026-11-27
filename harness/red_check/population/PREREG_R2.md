# C5.3 revision 2: repositories first (pre-registration)

Revision of `PREREG.md` (rev 1), decided by the founder on 2026-11-27 (R1 = A, `/plan-eng-review`, brain
`gstack/projects/Mircoguidetti-new-brain/main-eng-review-c53-population-20261127.md`), relayed by the coordinator.
**Reason:** rev 1 selected 0 repositories (`REPORT.md`): reading the repositories with the most agent PRs first gave
young repositories without test CI (751 PRs too young; 41 of 830 PRs read had a failed job; none of 53 failed-job
logs matched a runner pattern). Rev 2 chooses repositories that have test CI first, then reads their agent PRs, and
widens the runner patterns. Written and committed before any request of rev 2. Rev 1's rules, code and results stay
as they are; rev 2 writes to `results_r2/`. Everything not named here is as in rev 1 (transport, exclusion reasons,
per-PR reading 2.4 steps 1-6, job matching 2.6, selection 2.7, oracle 2.8, storage, hand check 2.11).

## R2.1 Candidate repositories

The repositories of rev 1's pool (`results/pool.jsonl.gz`: agent PRs created in [2026-09-28, 2026-11-27), D =
2026-11-27, families and family rules of rev 1), after rev 1's owner exclusions. No new search request.

## R2.2 Screening (GitHub GraphQL from the workflow, `GITHUB_TOKEN`, 20 repositories per query)

Per repository, at its default branch head: `createdAt`, `isFork`, `isArchived`, `isPrivate`, every file directly in
`.github/workflows/` (name and text) and the root `package.json` (text). A repository is **eligible** when all hold:
1. not a fork, not archived, not private; readable (a missing repository → `repo_unreadable`);
2. **older**: created at least 365 days before D (before 2025-11-27) → else `repo_too_young_r2`;
3. **test CI**: at least one workflow file (`.yml`/`.yaml`) whose text contains `pull_request` (any trigger form) and
   runs a supported runner, i.e. one of its lines, ignoring the part after a `#` comment marker, matches
   - direct: `\b(vitest|jest|pytest)\b` or `\bnode\s+(?:--[\w-]+(?:=\S+)?\s+)*--test\b`; or
   - wrapper: `\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b` or `\bnpm\s+t\b`, and the root `package.json`'s
     `scripts.test` matches `\b(vitest|jest)\b` or `\bnode\s+(?:--[\w-]+(?:=\S+)?\s+)*--test\b`;
   → else `no_test_ci`.
Recorded per repository (`results_r2/screen.jsonl`): the fields above, the matching workflow file names and which rule
matched, the verdict. Workflow texts are not stored. GraphQL requests are counted apart from the REST cap. A chunk
stops before its next query when the GraphQL `remaining` < 20% of its `limit`.

## R2.3 Order and agent PRs

- Order: eligible repositories by their number of rev-1 pool PRs (descending), then `full_name` ascending
  (case-insensitive).
- Agent PRs of a repository: `pulls?state=all&sort=created&direction=desc&per_page=100`, pages 1-3, stopping after
  the first page whose last PR was created before D-60 days. Kept: PRs created in [D-60, D) by a family rule —
  copilot: author login `Copilot`; devin: `devin-ai-integration[bot]`; jules: `google-labs-jules[bot]` (the only
  author logins of these families in rev 1's pool); codex: head ref starting `codex/` and body containing
  `chatgpt.com/codex`; claude_code: body matching `Generated with \[?Claude Code` (case-insensitive). A non-200 on
  page 1 → the repository is skipped with `pulls_unreadable`.
- Then rev 1's 2.3 PR-level 30-day rule (always satisfied for eligible repositories) and 2.4: newest first, at most
  40 PRs per repository, steps 1-6 unchanged. Stops: 30 repositories read (checked before each PR) or 10,000 REST
  requests (pull listings included), whichever first.

## R2.4 Runner of a failed job (widened 2.5)

Line cleaning as rev 1 (byte-order mark, timestamp prefix, ANSI escapes), plus the private-mode escapes
`\x1b\[\?[0-9;]*[A-Za-z]`. Each pattern is tried on the cleaned line and, when the line starts with a workspace
prefix, on the line with that one prefix removed. Workspace prefixes: `^[@\w./-]+:[\w-]*test[\w-]*:\s+` (turbo,
`pkg:test: `), `^[@\w./-]+ [\w-]*test[\w-]*:\s+` (pnpm -r, `packages/web test: `), `^\[[@\w./-]+\]:?\s+` (yarn
workspaces foreach, `[web]: `).

| Runner | Pattern (failure count group >= 1) | Change |
|---|---|---|
| vitest | `^\s*Test Files\s+(\d+) failed` | unchanged |
| jest | `^Tests:\s+(\d+) failed` | unchanged |
| node-test | `^(?:ℹ\|#) fail (\d+)\s*$` | unchanged |
| pytest | `^(?:=+ )?(?:\d+ \w+, )*(\d+) failed(?:, \d+ \w+)* in [\d.]+s(?: \([\d:]+\))?(?: =+)?\s*$` | the `=` banner is optional (`pytest -q`), the counts list is explicit |

Exactly one runner → that runner; none → `no_runner`; two or more → `ambiguous_runner`. New fixtures (each fails on
rev 1's patterns, a test shows it): `pytest-q.log`, `turbo-vitest.log`, `pnpm-r-jest.log`, `yarn-foreach-node-test.log`;
negatives: `pytest-q-pass.log`, `turbo-pass.log`.

## R2.5 Unchanged

Selection 2.7 (count >= 3 qualifying PRs, top 6, ties by name, at most 12 PRs by `Random(3)`), oracle 2.8, hand check
2.11 (`Random(4)`, then `Random(5)` after a rule fix), storage rules (full logs only as the workflow artifact), on the
rev-2 rows `results_r2/prs.jsonl.gz`. Fewer than 6: report; the coordinator decides.

## R2.6 Revision 2.1: all eligible repositories (2026-11-27, before any request under it)

Founder decision R1 = A (`/plan-eng-review`, brain `gstack/projects/Mircoguidetti-new-brain/main-eng-review-c53-rev2-20261127.md`),
relayed by the coordinator. **Reason:** under R2.3 the 30-repository stop ended the reading with 1 repository selected
(REPORT_R2.md); the 30th repository read (qontinui/qontinui-runner) had 1 of its PRs read. **Change:** the
30-repository stop is replaced by reading all 172 eligible repositories in R2.3's order, resuming where the reading
stopped (the 30th repository's remaining PRs first); the reading stops before the next PR once 6 repositories have
>= 3 qualifying PRs (unique URLs, counting the rows already recorded), or at the end of the list. Every other rule is
unchanged: the 10,000-request REST cap still applies (3,365 used before this change) and can end the reading first;
kyegomez/swarms stays selected; selection, hand check and oracle as before, on all rev-2 rows.
