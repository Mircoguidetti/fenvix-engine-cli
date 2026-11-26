<<status>>
DONE

<<changes>>
1. 2026-11-25, after the §0 probe, before chunk 1 (no frame data read): Codex agent commits. The probe shows the
   Codex commits of `pawelekbyra/polutek-pl#1281` with no linked author login (`author: null`; git author name equals
   the pull request author). Under PREREG §1.6 (author login equals the pull request author) every Codex commit would
   be `human`. Changed rule: on a pull request whose head ref starts with `codex/`, a commit is the agent's when its
   author login equals the pull request author **or is null** (no linked GitHub account). The commit listing trim now
   also keeps `commit.author.name` (reported, not used by the rule). Code: `rules.is_agent_commit`; test
   `test_agent_commits`.

2. 2026-11-25, after Count A's last chunk, before any Count A result was reported: rules (ii) and (iv) of §1.7,
   under PREREG §1.9 / gate rev 4 note 5. The 30-row `not-wasted` sample (19 rows: fewer than 30 `not-wasted`, so
   all) had **9 misses**: agent commits that plainly fix an X that was red on the base and were not `wasted`
   (`handread_a_sample.jsonl`). Two rule gaps explain them: the fix message rule wanted a CI word within 30
   characters after the verb ("Fixes `TS2322` compilation error during Docker build", "Fixing Portal Build",
   "fix(proto): ... CI runs -D rustdoc::broken_intra_doc_links"), and a commit at which X turns green with no fix
   wording (a mise hash, a rustls bump, a gitops validator change) has no rule at all, because the evidence rule (i)
   finds failure files for only 8.7% of rateable pull requests. Changed rules: (ii) a fix verb (`fix`, `fixes`,
   `fixed`, `fixing`, `repair*`, `resolve*`, `unbreak*`, `unblock*`) anywhere in the message **and** a CI term
   (`ci`, `build(s)`, `test(s)`, `check(s)`, `pipeline(s)`, `lint*`, `clippy`, `workflow(s)`, `e2e`, `compile*`,
   `compilation`, `type-check*`, `rustdoc`) anywhere in the message, same NEW_RED guard; new (iv): the agent commit at
   which X passes (the window end when X's state there is `pass`). Rule (i) and (iii) are unchanged. Every Count A
   row was re-run offline from the committed raw responses (`rerun_a.py`, no request; rows before the change kept as
   `results/a_rows_rule1.jsonl`): 11 rows became `wasted`, none left it; only those 11, and the commits newly hit
   on 2 rows already read, were newly hand-read. The sample is not drawn again (it stays the pre-change draw), and
   with more than 3 misses no miss adjustment applies. Code: `rules.fix_message`, `rules.wasted_reasons`
   (`turns_green`), `pipeline.count_a`; tests `test_wasted_rules`, `test_fix_message_change_2`,
   `test_commit_after_x_passes_again_not_counted`, `test_already_red_at_commit_two_of_four_then_green_is_rateable`.

<<probe>>
Run 45569492615 (2026-11-25), 77 requests, every endpoint HTTP 200 (`results/probe/endpoints.json`, raw JSON
`results/probe/raw.json`, tree listings cut to 200 entries). Logins (`results/probe/logins.json`): Copilot pull
request author `Copilot`, commit author `Copilot` (git name `copilot-swe-agent[bot]`); Devin
`devin-ai-integration[bot]` for both; Jules `google-labs-jules[bot]` for both; Codex pull request author
`pawelekbyra`, commit author login null; Claude Code pull request author `noahgift`, commit author `noahgift`, no
commit with the Claude trailer (that pull request's commits count as human: the undercount the spec lists).
`claude[bot]` was not seen.

<<budget>>
Budget: 24 h from `budget_start` 2026-11-25T07:40:22Z (first frame request) to 2026-11-26T07:40:22Z. Count A ran
chunks 1-3 (all 1,500 frame pull requests, 10.9 h, under its 14 h cap). Count B ran chunks 4-6 from 18:39Z until the
24 h end stopped chunk 6 (`budget (24 h) reached`). Count B did **not** fit: after its first chunk (139 repositories,
{{req_per_issue}} requests per issue) the remaining 1,032 repositories projected to about 37 h at the observed rate
(GITHUB_TOKEN rate-limit sleeps, not the 3,600/h ceiling), against 7.2 h left. {{b_repos}} of the 1,171 repositories
were reached in the seeded order; the other 758 were never read. One repository was interrupted by the 24 h end and
is kept as `partial-budget` (its read issues count), per §3.

Chunk 4's job hit the workflow's 340-minute job timeout: the Chunks step was cancelled at 2026-11-26T00:19:54Z
inside a repository, before it wrote its summary line; the commit step still committed its 139 finished rows and its
raw file. That repository was not in the rows and was read again from the start in chunk 5. The chunk 4 line of
`results/chunks.jsonl` was written afterwards from `results/raw/b_4.jsonl.gz` and the job's step times, and is marked
`reconstructed`; `verify.py` (`check_chunks`) re-derives its items, requests and first/last item from the raw file
(test `test_reconstructed_chunk_line_checked_against_raw`). The requests spent on the cancelled repository are not
known, so the request totals here are a lower bound. This is a bookkeeping fix, not a rule, regex or budget change.

Chunk 4 also checked out the branch before change 2, and its results commit wrote back the pre-change
`results/a_rows.jsonl` and removed `results/a_rows_rule1.jsonl`; both were restored byte for byte from 7745c6d
(fb9e16e) before chunk 5 started. `verify.py` replays every A row and checks the rule-1 file against them.

<<hand_a>>
All {{a_auto_wasted}} automatic `wasted` pull requests were read commit by commit (`handread_a.jsonl`). {{a_wasted}} stay `wasted`; {{a_hand_to_not}} become
`not-wasted` because every wasted commit is product work or a sync that happens to fix X, not a fix of X:
`pobre-lingo#279` (R-product), `termux#1210` (R-product), `DbContextBuilder#759` (R-product), `Zorven#515` (R-sync),
and `okoskabet#74` (R-own, positive evidence: the red check is the agent's own earlier breakage). Most surviving
wasted commits are W-msg (fix-the-build commits after the red was already on the base); W-file {{a_code_w_file}}, W-ci {{a_code_w_ci}}. The
not-wasted sample (all 19 pre-change rows, `random.Random(3)` would draw 30) had 9 misses, which triggered change 2;
under the changed rules 11 more rows became `wasted`, and they are among the 20 read here.

<<hand_b>>
Marks: `same-issue` = the pull request works on this issue's own change, whole or a part; `not-attempt` = linked but
not work on the issue: a docs-only companion of another agent pull request, a backport or forward port, a re-land or
cherry-pick of another pull request, a release promotion, a placeholder draft, or a pull request that serves another
issue (`handread_b.jsonl`, notes per issue). Most competing issues are not a race: {{b_hand_comp_lost}} of the {{b_hand_comp_issues}} sampled competing
issues lose the class once companions and backports are taken out, and of the 34 that keep it most are one agent's
planned slices or stacked parts. Independent overlapping attempts at the same change (a real race: two fixes of one
bug, or an agent retried) were seen on about 13 of the 60 (e.g. Copilot retried 9 times on `api-mcp#117`; Claude
Code and Devin both fixed `prefect#23239`). Read this way the race is rarer than Rate B, which already is under 5%.

<<decision>>
(a) Rate A {{a_rate}} is under 20%, but only {{a_files_share}} of rateable pull requests have `files` evidence
(floor 40%), so (a) is NOT ENOUGH DATA under §1.8 (gate rev 4 note 1), not DROP. (b) Rate B {{b_rate}} (Wilson
{{b_lo}} to {{b_hi}}) on {{b_addressed}} agent-addressed issues (>= 200) is under 5%: DROP. The whole Wilson interval
is under 5%, and the hand read points lower still, but the decision uses the point estimate.

<<limits>>
- Count B read {{b_repos}} of 1,171 repositories (seeded order, so the read part is a random draw of the frame's
  repositories, not the first by size or date); the other 758 were not read. Within those read, {{b_repos_truncated}} hit the 10-page
  issue cap (`truncated`), so very active repositories contribute only their latest 1,000 closed issues.
- Rate B is dominated by Claude Code ({{claude_code_b_addressed}} of {{b_addressed}} agent-addressed issues); Codex has no agent-addressed issue in
  the read part (its pull requests carry no closing keyword or head-ref issue number that the link rule needs).
- Count B links need a closing keyword or the issue number in the head ref; issues worked on without either are not
  agent-addressed, which undercounts both numerator and denominator.
- Count A: `files` evidence exists for only {{a_files_share}} of rateable pull requests, so rule (i) rarely applies and
  rules (ii)/(iv) carry the count; Rate A is a message- and state-based count, which the hand read checks.
- Count A sees only commits visible after force-pushes; Claude Code commits count as the agent's only with the
  author login rule, so its agent commits may be undercounted.
- Request totals are a lower bound (chunk 4's cancelled repository).
- Found in the pre-landing review and counted from the committed raw responses (disclosed, not changed: the
  rules are pre-registered). Count B's `skipped-no-agent` test reads one page of the 100 newest pull requests: 75 of
  the 129 skipped repositories had a full page and in 37 all 100 were created after RACE_FROM, so agent pull requests
  opened earlier in the window were not seen there; the read set leans away from the busiest repositories, so "random
  draw" holds for the order, not for which repositories were kept. Count A's base workflow-run listing stops at 3
  pages (`MAX_RUN_PAGES`) with no flag in the row: 82 frame pull requests hit a full third page (57 not rateable, 19
  no-later-commit, 4 not-wasted, 2 wasted), where a cut listing can hide an ALREADY_RED X. The PR's own commits are
  excluded from base evidence using the first 100 only (7 rows have more). `commits/{sha}/status` is read without
  paging (30 statuses per page), so a commit with more than 30 status contexts loses the rest.
- `verify.py` re-derives the marked numbers by replaying the raw responses through the same code: it proves the
  report matches the data and the code, not that the code is right; raw files are not hashed.

<<acceptance>>
- AC1 PREREG before data: pass. `PREREG.md` was committed in 73623f9 (2026-11-25T07:36:29Z); the first results commit
  is 91426cc (07:39:00Z, the §0 probe, which does not start the budget); `budget_start` is 07:40:22Z.
- AC2 tests with fixtures: pass (41 tests, each with `protects=`, `fails_when=`, `no_claim=`).
- AC3 REPORT numbers re-derived: pass. Every result number in the tables and result lines is marked with its key;
  `verify.py` replays the rows from the raw responses, re-derives every marked value and exits 0. Some counts in the
  hand-written notes (repositories left, hours, hand-read tallies) are not marked and were checked by hand.
- AC4 hand reads applied: pass (Count A: 20 wasted pull requests and the 19-row sample; Count B: 60 + 60 issues).
- AC5 GET only, writes only to this branch, no search endpoint: pass (`LiveSource` sends GET only, tested; no
  `search/` path in the code; every commit is on `claude/agent-tools-count`; no issue, comment, review, star or fork).
