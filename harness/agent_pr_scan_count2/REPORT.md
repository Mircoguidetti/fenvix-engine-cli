DONE

# Count 2: is an agent pull request's red already red on the base?

Spec: `specs/20261124-agent-pr-scan-count2.md` (md5 1de362e09ce9aa6a62a3fb0184fe1e82). Pre-registration:
`PREREG.md` (commit 454d89a, before any result). Routes: `routes.md`. Re-derivation: `python3 harness/agent_pr_scan_count2/verify_count2.py` (exit 0).

## Changes after the pre-registration (each says when it was decided)

Every change after `PREREG.md` (commit 454d89a) is listed here, with when it was decided and why.

1. **Per-request time limit (`max_minutes`).** Decided before the main run, before any rate was computed. The
   workflow token's actual limit is 5000<!--rate_limit--> requests per hour (`X-RateLimit-Limit`), not the 1,000 the spec assumed. At 1 request per second
   the "stop below 20% remaining" rule would never trigger inside the job's 340-minute timeout. Request 1 therefore
   carried `max_minutes: 300`, so results are committed before the timeout. The time limit was not reached: the run
   stopped at the hard cap first (`results/chunks.jsonl`, chunk 1).
2. **Secondary rate denominator.** Decided before any rate was computed, when `stats.py` was written. The share is
   the number of PRs flagged "already red" by the secondary rule, divided by all PRs with a failed check.
3. **The PR's own commits are excluded from the base commit walk.** Decided after the first pooled rate had been
   computed, during the hand check. In sample PR spaja86/AI-IQ-SUPER-PLATFORMA#1018, the newest "base" commit had
   the same statuses at the same second as the head. `commits?sha=<base.ref>` returns the base branch history as it
   is when read (November 2026). For a PR merged later with a merge commit or fast-forward, that history contains
   the PR's own earlier commits, dated before S. Their statuses are not base-side evidence. In
   `pipeline.py`, when the PR's head commit is in that listing, `pulls/{n}/commits?per_page=100` is read and those
   SHAs are skipped in the primary and secondary walks. Test: `test_pr_own_commits_are_not_base_evidence`.
   - **What it touched.** 9<!--own_head_in_base--> PRs read have their head commit in the base listing. The missing reads
     were made by request 2, a supplement chunk that replays every PR against its committed responses and reads live
     only what is missing (requests in `results/chunks.jsonl`; responses in `results/supplement/2.jsonl.gz`; affected
     PRs in `2_changes.jsonl`).
   - **Effect.** No PR verdict changed. One per-check base commit changed: d0uble3L/cybersecurityos#139 moved from
     the PR's own commit to the next real base commit, still failed. That PR's secondary flag became true (pooled secondary count up by one PR).
     The selection replay still reproduces the PRs read.
   - **Limit.** For Tatsh/mutt-oauth2#202 (closed unmerged), `pulls/202/commits` returned HTTP 200 with an empty
     list, so nothing was excluded there. No verdict depends on it: its only non-Actions check has no base result.
   - **Not covered.** The Actions walk was not changed. Its base runs are runs created on the base branch at the
     time, so a later merge does not add runs before S.

## Route

Route 1 works: GitHub Actions in this repository (`.github/workflows/agent-pr-count2.yml`, `GITHUB_TOKEN`, read-only on other repositories), results committed back to this branch by the job and read with `git pull --rebase`. 3<!--chunks--> chunks, 6542<!--requests--> REST requests. Route 2 not attempted (not needed); route 3 blocked by the session proxy (403). Detail: `routes.md`.

## Sample

Draw prepared to 2500<!--draw_eligible--> eligible PRs (4472<!--draw_prepared--> sequence positions; the full interleaved sequence of merged and closed-unmerged pools is longer). PRs read: 1500<!--read--> (the first 5<!--probe_n--> are the route-1 probe). Repository-cap exclusions during the run: 215<!--cap_excluded-->.

Stop: `hard cap 1500`. The quota was not met for every family; rateable PRs reached per family: Copilot 22<!--copilot_n_rateable-->, Devin 12<!--devin_n_rateable-->, Jules 36<!--jules_n_rateable-->, Codex 33<!--codex_n_rateable-->, Claude Code 40<!--claude_code_n_rateable-->.

Outcomes of the PRs read: no failed check on the last head commit 1261<!--no_failed-->; at least one failed check 236<!--with_failed-->; `pulls/{n}` unreadable 0<!--pr_unreadable-->; head checks unreadable 3<!--head_unreadable-->.

## Results

| Family | PRs read | with a failed check | ALREADY_RED | NEW_RED | NO_BASE_SIGNAL | UNREADABLE | primary rate | Wilson 95% | NO_BASE+UNREADABLE share | secondary already red (share of failed-check PRs) |
|---|---|---|---|---|---|---|---|---|---|---|
| Copilot | 288<!--copilot_read--> | 38<!--copilot_with_failed--> | 16<!--copilot_already_red--> | 6<!--copilot_new_red--> | 16<!--copilot_no_base--> | 0<!--copilot_unreadable--> | 72.7%<!--copilot_rate--> | 51.8%<!--copilot_lo--> to 86.8%<!--copilot_hi--> | 42.1%<!--copilot_unrated_share--> | 16<!--copilot_sec_already--> (42.1%<!--copilot_sec_rate-->) |
| Devin | 218<!--devin_read--> | 28<!--devin_with_failed--> | 10<!--devin_already_red--> | 2<!--devin_new_red--> | 15<!--devin_no_base--> | 1<!--devin_unreadable--> | 83.3%<!--devin_rate--> | 55.2%<!--devin_lo--> to 95.3%<!--devin_hi--> | 57.1%<!--devin_unrated_share--> | 11<!--devin_sec_already--> (39.3%<!--devin_sec_rate-->) |
| Jules | 326<!--jules_read--> | 62<!--jules_with_failed--> | 25<!--jules_already_red--> | 11<!--jules_new_red--> | 26<!--jules_no_base--> | 0<!--jules_unreadable--> | 69.4%<!--jules_rate--> | 53.1%<!--jules_lo--> to 82.0%<!--jules_hi--> | 41.9%<!--jules_unrated_share--> | 26<!--jules_sec_already--> (41.9%<!--jules_sec_rate-->) |
| Codex | 280<!--codex_read--> | 38<!--codex_with_failed--> | 21<!--codex_already_red--> | 12<!--codex_new_red--> | 5<!--codex_no_base--> | 0<!--codex_unreadable--> | 63.6%<!--codex_rate--> | 46.6%<!--codex_lo--> to 77.8%<!--codex_hi--> | 13.2%<!--codex_unrated_share--> | 26<!--codex_sec_already--> (68.4%<!--codex_sec_rate-->) |
| Claude Code | 388<!--claude_code_read--> | 70<!--claude_code_with_failed--> | 23<!--claude_code_already_red--> | 17<!--claude_code_new_red--> | 30<!--claude_code_no_base--> | 0<!--claude_code_unreadable--> | 57.5%<!--claude_code_rate--> | 42.2%<!--claude_code_lo--> to 71.5%<!--claude_code_hi--> | 42.9%<!--claude_code_unrated_share--> | 29<!--claude_code_sec_already--> (41.4%<!--claude_code_sec_rate-->) |
| **All five (pooled)** | 1500<!--read--> | 236<!--with_failed--> | 95<!--already_red--> | 48<!--new_red--> | 92<!--no_base--> | 1<!--unreadable--> | 66.4%<!--rate--> | 58.4%<!--lo--> to 73.7%<!--hi--> | 39.4%<!--unrated_share--> | 108<!--sec_already--> (45.8%<!--sec_rate-->) |

Split by pull request state (informational):

| State | PRs read | with a failed check | ALREADY_RED | NEW_RED | NO_BASE_SIGNAL | UNREADABLE | primary rate | Wilson 95% | NO_BASE+UNREADABLE share | secondary |
|---|---|---|---|---|---|---|---|---|---|---|
| merged | 742<!--merged_read--> | 73<!--merged_with_failed--> | 36<!--merged_already_red--> | 6<!--merged_new_red--> | 31<!--merged_no_base--> | 0<!--merged_unreadable--> | 85.7%<!--merged_rate--> | 72.2%<!--merged_lo--> to 93.3%<!--merged_hi--> | 42.5%<!--merged_unrated_share--> | 36<!--merged_sec_already--> (49.3%<!--merged_sec_rate-->) |
| closed unmerged | 758<!--closed_unmerged_read--> | 163<!--closed_unmerged_with_failed--> | 59<!--closed_unmerged_already_red--> | 42<!--closed_unmerged_new_red--> | 61<!--closed_unmerged_no_base--> | 1<!--closed_unmerged_unreadable--> | 58.4%<!--closed_unmerged_rate--> | 48.7%<!--closed_unmerged_lo--> to 67.5%<!--closed_unmerged_hi--> | 38.0%<!--closed_unmerged_unrated_share--> | 72<!--closed_unmerged_sec_already--> (44.2%<!--closed_unmerged_sec_rate-->) |

Primary rate (pooled) = ALREADY_RED / (ALREADY_RED + NEW_RED) = 95<!--already_red--> / 143<!--n_rateable--> = 66.4%<!--rate-->, Wilson 95% 58.4%<!--lo--> to 73.7%<!--hi-->. NO_BASE_SIGNAL + UNREADABLE = 92<!--no_base--> + 1<!--unreadable--> of 236<!--with_failed--> PRs with a failed check (39.4%<!--unrated_share-->); the validity ceiling is 50%.

## Decision (pre-registered rule, threshold ASSUMED)

Idea 3 moves forward: the primary rate is at least 20%.

Reading of the result:

- **Which numbers.** The decision uses only the pooled primary rate and its validity share, as pre-registered. The
  rate and its whole Wilson interval (above) are far above the assumed threshold. The share of failed-check PRs
  without a usable base result (above) is below the validity ceiling.
- **Quota.** The 40-rateable quota was met only for Claude Code. Copilot, Devin, Jules and Codex stopped below 40
  because the 1,500 hard cap was reached first. Per-family rates have wide intervals (Devin has the fewest rateable PRs);
  they are descriptive, not inputs to the rule.
- **Merged vs closed-unmerged.** The rate is higher for merged PRs than for closed-unmerged ones (table above).
  This split is informational only.
- **Caveats on the rule's own terms.** Identity is matched exactly. A head job with a different matrix suffix
  than the base job (hand-check PR benwbrum/fromthepage#5797) counts as NO_BASE_SIGNAL, never NEW_RED. Base runs
  include any same-repository run listed for the base branch name, including `pull_request` events from a branch
  of that name. Neither was changed after the results.

## Hand check

`random.Random(2).sample(sorted(urls_with_failed_check), 20)` (the set is fixed by the PRs read; the hand reading was done after the first pooled rate had been computed, see the changes above): 20<!--hand_n--> PRs, automatic verdict agreed with the hand verdict on first reading for 20<!--hand_agree-->, disagreed for 0<!--hand_disagree-->. Rows: `handcheck.jsonl` (automatic verdict, hand verdict, four confirmed fields with notes).

**Method.** I read each of the 20<!--hand_n--> PRs in the committed raw JSON (`python3 handcheck_dump.py <i>`). I also wrote a
separate script that re-walks each Actions identity over the committed listing and `/jobs` responses (pipeline code
not used). Its verdicts agreed with the automatic per-check verdict for every Actions check in the sample, and found
no newer usable base run that the automatic walk skipped. Non-Actions checks were read by eye against the base
commit listing and each commit's checks and statuses.

**Result.** The automatic PR verdict on first reading agreed with the hand verdict for every sampled PR (counts above). One reading (PR
#1018 above) exposed a possible flaw: the PR's own commits could serve as base evidence. That was fixed in code
(change 3). Re-running with the fix changed no verdict in the sample or elsewhere.

**Notes kept in `handcheck.jsonl`.**
- Matrix-name mismatch counts as NO_BASE_SIGNAL (#5797).
- `pull_request`-event base runs on a same-named branch are counted (Bigdaddy1990/jackery_solarvault#207,
  Dyltom/iamdylanhenderson.com#23, aeternity/ae_mdw#2182).
- A base branch deleted since gives UNREADABLE for status checks (#207, base `testM`).
- A Copilot agent's own workflow run is counted as a failed check (undone0603/authichain-unified#1055).

## What was verified, reused, and not checked

**Verified (re-derived by `verify_count2.py`, exit 0):**
- The draw equals the seeded draw re-built from the pools and repository metadata.
- The 1500<!--read--> PRs read, in order, and the repository-cap exclusions equal a simulation of the quota and caps.
- Every PR verdict, per-check verdict and secondary flag re-derive from the committed raw JSON (raw plus
  supplement).
- The hand-check set is `random.Random(2).sample(...)`, with all fields present, and every hand verdict equals the
  re-derived verdict.
- Every marked number in this report matches the re-computed value, and the decision sentence is the one the rule
  gives.

**Tests.** `python3 -m pytest harness/agent_pr_scan_count2/test_count2.py`. Each test has a card. They cover:
- the primary rule;
- identity matching;
- which states count as failed;
- the secondary rule;
- own-commit exclusion;
- verify passing on the committed data and failing on an altered number, verdict or sentence.

**Reused, not re-checked here:**
- `checks()` from the first scan's `ci_status`;
- the search collection helpers (`harness/agent_pr_scan/search_collect.py`);
- `common.seeded_order`;
- the merged pools (`count1_*`) and the first scan's repository metadata cache.

**Not checked:**
- Job logs (out of scope). A failure is taken as reported, whatever its cause (flaky test, infrastructure).
- Whether a base result came from the same failing test as the head result: only job-name identity is compared.
- Whether the PR's own commits could reach the Actions base listing (argued not to in change 3, not measured).
- PRs with more than 100 commits (only one page of `pulls/{n}/commits` is read).
- The 20% threshold itself is ASSUMED and may be changed by the founder before 22 Dec.
