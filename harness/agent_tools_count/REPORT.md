DONE

# Agent tools count: wasted agent fixes on reds already there (A), competing agent pull requests (B)

Pre-registration: `PREREG.md` (committed before any data; see the git order below). Re-derivation: `python3 harness/agent_tools_count/verify.py` (exit 0). Report: `python3 harness/agent_tools_count/report.py`.

## Changes after the pre-registration (each with its justification, before any result)

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

## Route and budget

GitHub Actions in this repository (`.github/workflows/agent-tools-count.yml`, `GITHUB_TOKEN`, GET only). 6<!--chunks--> data chunks (3<!--chunks_a--> Count A, 3<!--chunks_b--> Count B), 53709<!--requests--> REST requests in all (probe included). Count A: 21661<!--requests_a--> requests, 14.4<!--req_per_pr--> per pull request, 10.9<!--a_hours--> h of workflow time. Count B: 30604<!--requests_b--> requests, 2.00<!--req_per_issue--> per issue read, 12.8<!--b_hours--> h.

Budget: 24 h from `budget_start` 2026-11-25T07:40:22Z (first frame request) to 2026-11-26T07:40:22Z. Count A ran
chunks 1-3 (all 1,500 frame pull requests, 10.9 h, under its 14 h cap). Count B ran chunks 4-6 from 18:39Z until the
24 h end stopped chunk 6 (`budget (24 h) reached`). Count B did **not** fit: after its first chunk (139 repositories,
2.00<!--req_per_issue--> requests per issue) the remaining 1,032 repositories projected to about 37 h at the observed rate
(GITHUB_TOKEN rate-limit sleeps, not the 3,600/h ceiling), against 7.2 h left. 413<!--b_repos--> of the 1,171 repositories
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

## §0 Probe

Run 45569492615 (2026-11-25), 77 requests, every endpoint HTTP 200 (`results/probe/endpoints.json`, raw JSON
`results/probe/raw.json`, tree listings cut to 200 entries). Logins (`results/probe/logins.json`): Copilot pull
request author `Copilot`, commit author `Copilot` (git name `copilot-swe-agent[bot]`); Devin
`devin-ai-integration[bot]` for both; Jules `google-labs-jules[bot]` for both; Codex pull request author
`pawelekbyra`, commit author login null; Claude Code pull request author `noahgift`, commit author `noahgift`, no
commit with the Claude trailer (that pull request's commits count as human: the undercount the spec lists).
`claude[bot]` was not seen.

## Count A: wasted agent commits on reds that were already there

Frame: Count 2's 1,500 pull requests in its read order; read: 1500<!--a_read-->. Results (after the hand read): rateable 115<!--a_rateable--> = wasted 15<!--a_wasted--> + not-wasted 13<!--a_not_wasted--> + no-later-commit 87<!--a_no_later-->; uncertain 6<!--a_uncertain-->; not rateable (no already-red X at any commit) 1379<!--a_not_rateable-->.

**Rate A = 15<!--a_wasted--> / 115<!--a_rateable--> = 13.0%<!--a_rate-->** (Wilson 95% 8.1%<!--a_lo--> to 20.4%<!--a_hi-->). Rateable pull requests with `files` evidence for at least one X: 10<!--a_files--> (8.7%<!--a_files_share-->; validity floor 40%).

| Family | read | rateable | wasted | not-wasted | no-later-commit | uncertain | Rate A | Wilson 95% | files evidence |
|---|---|---|---|---|---|---|---|---|---|
| Copilot | 288<!--copilot_a_read--> | 16<!--copilot_a_rateable--> | 0<!--copilot_a_wasted--> | 2<!--copilot_a_not_wasted--> | 14<!--copilot_a_no_later--> | 0<!--copilot_a_uncertain--> | 0.0%<!--copilot_a_rate--> | 0.0%<!--copilot_a_lo--> to 19.4%<!--copilot_a_hi--> | 12.5%<!--copilot_a_files_share--> |
| Devin | 218<!--devin_a_read--> | 11<!--devin_a_rateable--> | 1<!--devin_a_wasted--> | 0<!--devin_a_not_wasted--> | 10<!--devin_a_no_later--> | 1<!--devin_a_uncertain--> | 9.1%<!--devin_a_rate--> | 1.6%<!--devin_a_lo--> to 37.7%<!--devin_a_hi--> | 9.1%<!--devin_a_files_share--> |
| Jules | 326<!--jules_a_read--> | 37<!--jules_a_rateable--> | 8<!--jules_a_wasted--> | 6<!--jules_a_not_wasted--> | 23<!--jules_a_no_later--> | 1<!--jules_a_uncertain--> | 21.6%<!--jules_a_rate--> | 11.4%<!--jules_a_lo--> to 37.2%<!--jules_a_hi--> | 2.7%<!--jules_a_files_share--> |
| Codex | 280<!--codex_a_read--> | 22<!--codex_a_rateable--> | 0<!--codex_a_wasted--> | 1<!--codex_a_not_wasted--> | 21<!--codex_a_no_later--> | 1<!--codex_a_uncertain--> | 0.0%<!--codex_a_rate--> | 0.0%<!--codex_a_lo--> to 14.9%<!--codex_a_hi--> | 13.6%<!--codex_a_files_share--> |
| Claude Code | 388<!--claude_code_a_read--> | 29<!--claude_code_a_rateable--> | 6<!--claude_code_a_wasted--> | 4<!--claude_code_a_not_wasted--> | 19<!--claude_code_a_no_later--> | 3<!--claude_code_a_uncertain--> | 20.7%<!--claude_code_a_rate--> | 9.8%<!--claude_code_a_lo--> to 38.4%<!--claude_code_a_hi--> | 10.3%<!--claude_code_a_files_share--> |
| **All (pooled)** | 1500<!--a_read--> | 115<!--a_rateable--> | 15<!--a_wasted--> | 13<!--a_not_wasted--> | 87<!--a_no_later--> | 6<!--a_uncertain--> | 13.0%<!--a_rate--> | 8.1%<!--a_lo--> to 20.4%<!--a_hi--> | 8.7%<!--a_files_share--> |

Automatic `wasted` before the hand read: 20<!--a_auto_wasted--> (rules hit, pull requests: (i) 0<!--a_reason_i-->, (ii) 14<!--a_reason_ii-->, (iii) 4<!--a_reason_iii-->, (iv) 14<!--a_reason_iv-->). Hand read: 20<!--a_hand_n--> pull requests; codes W-file 2<!--a_code_w_file-->, W-msg 24<!--a_code_w_msg-->, W-ci 4<!--a_code_w_ci-->, R-product 5<!--a_code_r_product-->, R-own 1<!--a_code_r_own-->, R-sync 3<!--a_code_r_sync-->; 5<!--a_hand_to_not--> became `not-wasted`. Sample of 19<!--a_sample_n--> `not-wasted`: 9<!--a_misses--> misses (miss-adjusted Rate A n/a<!--a_miss_adj-->).

All 20<!--a_auto_wasted--> automatic `wasted` pull requests were read commit by commit (`handread_a.jsonl`). 15<!--a_wasted--> stay `wasted`; 5<!--a_hand_to_not--> become
`not-wasted` because every wasted commit is product work or a sync that happens to fix X, not a fix of X:
`pobre-lingo#279` (R-product), `termux#1210` (R-product), `DbContextBuilder#759` (R-product), `Zorven#515` (R-sync),
and `okoskabet#74` (R-own, positive evidence: the red check is the agent's own earlier breakage). Most surviving
wasted commits are W-msg (fix-the-build commits after the red was already on the base); W-file 2<!--a_code_w_file-->, W-ci 4<!--a_code_w_ci-->. The
not-wasted sample (all 19 pre-change rows, `random.Random(3)` would draw 30) had 9 misses, which triggered change 2;
under the changed rules 11 more rows became `wasted`, and they are among the 20 read here.

Information (§1.10):

- Rule (i) hits by `in-base` mark (failure files of wasted pull requests): yes 0<!--a_inbase_yes-->, no 0<!--a_inbase_no-->, base-unknown 0<!--a_inbase_base_unknown-->.
- Pull requests with an already-red X at any commit: 115<!--a_any_x--> of 1500<!--a_read-->.
- Rateable with k < last commit: 50<!--a_k_lt_last-->, Rate A on them 30.0%<!--a_k_lt_last_rate-->.
- Single-commit pull requests: 880<!--a_single_commit--> (rateable 44<!--a_single_commit_rateable-->).
- Force-push events: 138<!--a_force_events--> on 66<!--a_force_prs--> pull requests (force-pushed commits are invisible).
- X by kind (rateable): Actions 229<!--a_x_actions-->, other check run 19<!--a_x_check-->, status 30<!--a_x_status-->; Actions-only pull requests 90<!--a_actions_only-->, Rate A 14.4%<!--a_actions_only_rate-->.
- Copilot commits: 759<!--a_copilot_commits-->; with no check: 324<!--a_copilot_no_checks-->; all check runs `action_required`: 0<!--a_copilot_action_required-->.
- Rateable pull requests already red only through base runs of event `pull_request`: 11<!--a_pr_event_only--> (limit inherited from Count 2).
- Count 2's 95<!--a_c2_n--> `ALREADY_RED` pull requests here: wasted 7<!--a_c2_wasted-->, not-wasted 8<!--a_c2_not_wasted-->, no-later-commit 79<!--a_c2_no_later-->, uncertain 0<!--a_c2_uncertain-->, not rateable 1<!--a_c2_not_rateable-->.
- Human non-merge commits after k on rateable pull requests: 252<!--a_human_after--> on 17<!--a_human_after_prs--> pull requests (reported, never counted).

## Count B: competing agent pull requests for one issue

Repositories taken in the seeded order: 413<!--b_repos-->; read 284<!--b_repos_read--> (partial at the budget end 1<!--b_repos_partial-->), skipped (no agent pull request since RACE_FROM on the first page) 129<!--b_repos_skipped-->, unreadable 0<!--b_repos_unreadable-->, truncated at 10 issue pages 54<!--b_repos_truncated-->. Closed issues read: 15334<!--b_issues--> (timeline unreadable 0<!--b_timeline_errors-->).

Agent-addressed issues: 5395<!--b_addressed--> (single 4895<!--b_single-->, sequential 329<!--b_sequential-->, competing 171<!--b_competing-->). **Rate B = 171<!--b_competing--> / 5395<!--b_addressed--> = 3.2%<!--b_rate-->** (Wilson 95% 2.7%<!--b_lo--> to 3.7%<!--b_hi-->).

| Family (first linked agent pull request) | agent-addressed | competing | sequential | Rate B | Wilson 95% |
|---|---|---|---|---|---|
| Copilot | 598<!--copilot_b_addressed--> | 3<!--copilot_b_competing--> | 54<!--copilot_b_sequential--> | 0.5%<!--copilot_b_rate--> | 0.2%<!--copilot_b_lo--> to 1.5%<!--copilot_b_hi--> |
| Devin | 352<!--devin_b_addressed--> | 3<!--devin_b_competing--> | 6<!--devin_b_sequential--> | 0.9%<!--devin_b_rate--> | 0.3%<!--devin_b_lo--> to 2.5%<!--devin_b_hi--> |
| Jules | 111<!--jules_b_addressed--> | 1<!--jules_b_competing--> | 5<!--jules_b_sequential--> | 0.9%<!--jules_b_rate--> | 0.2%<!--jules_b_lo--> to 4.9%<!--jules_b_hi--> |
| Codex | 0<!--codex_b_addressed--> | 0<!--codex_b_competing--> | 0<!--codex_b_sequential--> | n/a<!--codex_b_rate--> | n/a<!--codex_b_lo--> to n/a<!--codex_b_hi--> |
| Claude Code | 4334<!--claude_code_b_addressed--> | 164<!--claude_code_b_competing--> | 264<!--claude_code_b_sequential--> | 3.8%<!--claude_code_b_rate--> | 3.3%<!--claude_code_b_lo--> to 4.4%<!--claude_code_b_hi--> |
| **All (pooled)** | 5395<!--b_addressed--> | 171<!--b_competing--> | 329<!--b_sequential--> | 3.2%<!--b_rate--> | 2.7%<!--b_lo--> to 3.7%<!--b_hi--> |

How the merged one was chosen (competing issues; labels combine): first-opened 86<!--b_label_first_opened-->, first-green 100<!--b_label_first_green-->, only-green 40<!--b_label_only_green-->, reviewed 10<!--b_label_reviewed-->, other 24<!--b_label_other-->, none-merged 6<!--b_label_none_merged-->.

Hand read (does not change Rate B): competing sample 60<!--b_hand_comp_issues--> issues, 293<!--b_hand_comp_links--> links, 43<!--b_hand_comp_not_attempt_links--> marked not-attempt, 26<!--b_hand_comp_lost--> issues with fewer than 2 same-issue links (share 43.3%<!--b_hand_comp_share-->); agent-addressed sample 60<!--b_hand_rest_issues--> issues, 70<!--b_hand_rest_links--> links, 4<!--b_hand_rest_not_attempt_links--> not-attempt, 3<!--b_hand_rest_lost--> issues without a same-issue link (share 5.0%<!--b_hand_rest_share-->). Symmetric corrected rate (information only): 1.9%<!--b_corrected-->.

Marks: `same-issue` = the pull request works on this issue's own change, whole or a part; `not-attempt` = linked but
not work on the issue: a docs-only companion of another agent pull request, a backport or forward port, a re-land or
cherry-pick of another pull request, a release promotion, a placeholder draft, or a pull request that serves another
issue (`handread_b.jsonl`, notes per issue). Most competing issues are not a race: 26<!--b_hand_comp_lost--> of the 60<!--b_hand_comp_issues--> sampled competing
issues lose the class once companions and backports are taken out, and of the 34 that keep it most are one agent's
planned slices or stacked parts. Independent overlapping attempts at the same change (a real race: two fixes of one
bug, or an agent retried) were seen on about 13 of the 60 (e.g. Copilot retried 9 times on `api-mcp#117`; Claude
Code and Devin both fixed `prefect#23239`). Read this way the race is rarer than Rate B, which already is under 5%.

## Decision

```
(a) where it breaks: NOT ENOUGH DATA (Rate A 13.0% vs 20%, files evidence 8.7%)
(b) the race: DROP (Rate B 3.2% vs 5%, agent-addressed 5395)
```

(a) Rate A 13.0%<!--a_rate--> is under 20%, but only 8.7%<!--a_files_share--> of rateable pull requests have `files` evidence
(floor 40%), so (a) is NOT ENOUGH DATA under §1.8 (gate rev 4 note 1), not DROP. (b) Rate B 3.2%<!--b_rate--> (Wilson
2.7%<!--b_lo--> to 3.7%<!--b_hi-->) on 5395<!--b_addressed--> agent-addressed issues (>= 200) is under 5%: DROP. The whole Wilson interval
is under 5%, and the hand read points lower still, but the decision uses the point estimate.

## Limits

- Count B read 413<!--b_repos--> of 1,171 repositories (seeded order, so the read part is a random draw of the frame's
  repositories, not the first by size or date); the other 758 were not read. Within those read, 54<!--b_repos_truncated--> hit the 10-page
  issue cap (`truncated`), so very active repositories contribute only their latest 1,000 closed issues.
- Rate B is dominated by Claude Code (4334<!--claude_code_b_addressed--> of 5395<!--b_addressed--> agent-addressed issues); Codex has no agent-addressed issue in
  the read part (its pull requests carry no closing keyword or head-ref issue number that the link rule needs).
- Count B links need a closing keyword or the issue number in the head ref; issues worked on without either are not
  agent-addressed, which undercounts both numerator and denominator.
- Count A: `files` evidence exists for only 8.7%<!--a_files_share--> of rateable pull requests, so rule (i) rarely applies and
  rules (ii)/(iv) carry the count; Rate A is a message- and state-based count, which the hand read checks.
- Count A sees only commits visible after force-pushes; Claude Code commits count as the agent's only with the
  author login rule, so its agent commits may be undercounted.
- Request totals are a lower bound (chunk 4's cancelled repository).

## Acceptance criteria

- AC1 PREREG before data: pass. `PREREG.md` was committed in 73623f9 (2026-11-25T07:36:29Z); the first results commit
  is 91426cc (07:39:00Z, the §0 probe, which does not start the budget); `budget_start` is 07:40:22Z.
- AC2 tests with fixtures: pass (41 tests, each with `protects=`, `fails_when=`, `no_claim=`).
- AC3 REPORT numbers re-derived: pass. Every number in REPORT.md is marked with its key; `verify.py` replays the rows
  from the raw responses, re-derives every marked value and exits 0.
- AC4 hand reads applied: pass (Count A: 20 wasted pull requests and the 19-row sample; Count B: 60 + 60 issues).
- AC5 GET only, writes only to this branch, no search endpoint: pass (`LiveSource` sends GET only, tested; no
  `search/` path in the code; every commit is on `claude/agent-tools-count`; no issue, comment, review, star or fork).
