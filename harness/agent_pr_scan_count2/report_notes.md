Hand-written parts of REPORT.md (report.py inserts each block verbatim at its marker).

<<changes>>
Every change after `PREREG.md` (commit 454d89a) is listed here, with when it was decided and why.

1. **Per-request time limit (`max_minutes`).** Decided before the main run, before any rate was computed. The
   workflow token's actual limit is {{rate_limit}} requests per hour (`X-RateLimit-Limit`), not the 1,000 the spec assumed. At 1 request per second
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
   - **What it touched.** {{own_head_in_base}} PRs read have their head commit in the base listing. The missing reads
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

<<decision>>
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

<<handcheck>>
**Method.** I read each of the {{hand_n}} PRs in the committed raw JSON (`python3 handcheck_dump.py <i>`). I also wrote a
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

<<verified>>
**Verified (re-derived by `verify_count2.py`, exit 0):**
- The draw equals the seeded draw re-built from the pools and repository metadata.
- The {{read}} PRs read, in order, and the repository-cap exclusions equal a simulation of the quota and caps.
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
