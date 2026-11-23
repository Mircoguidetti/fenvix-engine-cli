DONE

# Agent pull requests and flaky fixes on public code: Counts 1, 2 and 3

Date: 2026-11-23. Branch `claude/agent-pr-scan` (from `origin/claude/flaky-scan` @ 0208987), folder
`harness/agent_pr_scan/`. Read-only: GitHub issue and repository search plus blobless partial git fetches. Nobody
was contacted, nothing from another repository was installed or executed, and nothing in `node/`, `python/`,
`crates/` or `runner/` changed.

Every number from the scan is written as `<number><!--key-->` in the source of this file and is re-derived from the
committed raw rows by `python3 harness/agent_pr_scan/verify_scan.py`, which exits 1 on any mismatch, on an unknown
key, on a decision sentence that does not follow the pre-registered rule, on a flagged pull request without a hand
verdict, or on an unflagged reading set that is not the seeded draw. Labels: **MEASURED** (from raw rows),
**ESTIMATED**, **DECLARED** (a constant from the spec), **UNKNOWN**.

## Plain answers

- **Count 1. Do autonomous coding agents weaken tests in real merged pull requests?** Rarely. Of
  300<!--c1_aut_den--> merged pull requests by Copilot, Devin, Jules and Codex in repositories that had tests,
  3<!--c1_aut_conf--> weaken a test after a hand read: **1.0%<!--c1_aut_rate-->** (Wilson 95% interval
  0.3%<!--c1_aut_lo--> to 2.9%<!--c1_aut_hi-->). **MEASURED.**
  **Decision: **LEAVE**.** The founder's rule (threshold ASSUMED 2%, decided on the point estimate) puts the
  point estimate below 2%, so ideas 1 and 2 leave the list. The interval reaches above 2%, so the data do not
  exclude a rate at the threshold; the rule decides on the point estimate, as pre-registered.
- **Count 2. Are red checks already red on the base?** **UNKNOWN.** The check-runs API is refused for every
  third-party repository in this session (exact error below). Nothing was estimated.
- **Count 3. Do flaky fixes hold?** Of 150<!--c3_nameable--> merged flaky-fix pull requests with a nameable test,
  28<!--c3_notheld--> did not hold within 90 days: **18.7%<!--c3_rate-->** (Wilson 13.2%<!--c3_lo--> to
  25.7%<!--c3_hi-->). **MEASURED** by the spec's rule on commit history; the events were not hand-read
  (informational count).

## Step 0: preflight

Commands and raw output are in `preflight.txt` (re-run at the end of the scan; the first run at the start gave the
same results). **MEASURED.**

- `gh auth status` → exit 1, "The token in GH_TOKEN is invalid." API calls still go through the session's proxy.
- `gh api rate_limit` → core limit 15000<!--pf_core_limit--> per hour (above the spec's 5,000).
- `gh api -X GET search/issues -f q='is:pr is:merged author:app/copilot-swe-agent' -f per_page=1` → exit 0,
  total_count 1541356<!--pf_search_total-->. Search works.
- Not BLOCKED by the spec's Step 0 rule. But every REST call to a third-party repository, and GraphQL, is refused:
  2<!--pf_http_403--> such calls in `preflight.txt` return HTTP 403 with "GitHub access to this repository is not
  enabled for this session". Git fetches of public repositories work. The scan was therefore rebuilt on search plus
  git (see Deviations); the API-only parts are UNKNOWN.

## Deviations from the spec (each decided before the Count 1 rate was computed)

1. **No API for third-party repositories.** `base.sha`, pull request files and check runs come only from the API.
   A pull request is rebuilt from a blobless fetch (`gitpr.py`): the commit that landed it is found on a branch by
   committer date within 180 s of `merged_at` and either "Merge pull request #N" (merge commit) or a subject ending
   "(#N)" (squash). The base is that commit's first parent and the diff is base..landing (`git diff -M`). If no
   such commit exists, the fallback diff is merge-base(`refs/pull/N/head`, default branch)..head. Methods used,
   autonomous: 271<!--c1_aut_method_merge_commit--> merge commit, 107<!--c1_aut_method_squash--> squash,
   24<!--c1_aut_method_pr_head_merge_base--> fallback. The fallback can include commits that are not the pull
   request's own (two hand-read cases below show this); every flagged fallback row was read with that in mind.
2. **`template_repository` exclusion not applied (UNKNOWN).** Repository search does not expose it. Forks, archived
   repositories and the 30-day age rule were applied from `search/repositories` (`repo_meta.jsonl`).
3. **Search pages capped.** Reading 1,000 results per window in parallel tripped GitHub's secondary rate limit
   (its message warns about scraping). Each window was then read to its first 300 (Count 1) or 200 (Count 3)
   results, one process at a time. Pools stayed far larger than the draws. Decided before any pull request was read.
4. **One Copilot window missing.** A resume bug in the collector skipped Copilot 2026-05-29..31 (at most 300
   results). Found after the Count 1 draw had started on that pool; adding it would have reshuffled Copilot's
   seeded order mid-draw, so the pool stays at 32<!--s1_windows_copilot--> of 33 windows. The bug was fixed and
   Count 3's windows were filled before its draw.
5. **One Count 3 search file damaged and recovered.** The "flaky" rows file was cut mid-write by a process time
   limit; every complete window was recovered and the one damaged week was collected again. Checked complete.
6. **Family rules.** Codex: `head:codex/` plus the body marker `chatgpt.com/codex` (the Codex Cloud footer
   "------ [Codex Task](https://chatgpt.com/codex/cloud/tasks/task_e_...)"). Claude Code: the body contains
   "Generated with Claude Code" literally (the phrase search alone matches loosely). Both fixed before any data
   was read. Body excerpts were kept at 1,200 characters for the hand check.
7. **Excluded owners**: mircoguidetti, github, anthropics, openai, and microsoft (vendor owner seen in the Copilot
   rules check). `githubnext` (a GitHub organisation) was not seen in the rules check, so it was not excluded; one
   sampled pull request is there (githubnext/gh-cao#11282, WEAK flag, not confirmed).
8. **Classifier approximations** (fixed before the sample was read): "an assertion removed with no assertion added
   in the same test" uses the diff hunk as the unit; a test function is "deleted" when its definition line is
   removed and the name does not reappear anywhere in the pull request. Skip markers are the complete list in
   `classify.py` (`SKIP_MARKERS`); none was added after reading the sample.
9. **Count 3 "mentions flaky"** is read from commit messages (squash commits carry the pull request's title and
   body); pull request metadata is API-only.

## Count 1: agent pull requests that weaken tests (decides ideas 1 and 2)

### Rules check (20 per family, by hand; `rules_check.jsonl`)

| Family | Checked | Agent-made | Wrong | Kept |
|---|---|---|---|---|
| Copilot | 20<!--rc_n_copilot--> | 20<!--rc_yes_copilot--> | 0<!--rc_no_copilot--> | yes |
| Devin | 20<!--rc_n_devin--> | 20<!--rc_yes_devin--> | 0<!--rc_no_devin--> | yes |
| Jules | 20<!--rc_n_jules--> | 20<!--rc_yes_jules--> | 0<!--rc_no_jules--> | yes |
| Codex | 20<!--rc_n_codex--> | 20<!--rc_yes_codex--> | 0<!--rc_no_codex--> | yes |
| Claude Code | 20<!--rc_n_claude_code--> | 19<!--rc_yes_claude_code--> | 1<!--rc_no_claude_code--> | yes |

The Claude Code miss (otus-foss/mail#136) only quotes the phrase while describing a hook that strips attribution
lines. The app families are authored by the app's bot account; every Codex pull request carries the Codex Cloud
task footer.

### Search and sample (MEASURED)

Search per month 2026-05..2026-11-15, months over 1,000 results split by week.

| Family | Search total (sum of month totals) | Rows read | Pool after rule | Drawn and read | Excluded before reading | Unreadable | With tests at base |
|---|---|---|---|---|---|---|---|
| Copilot | 363014<!--s1_total_copilot--> | 9526<!--s1_rows_copilot--> | 9526<!--s1_pool_copilot--> | 111<!--c1_read_copilot--> | 129<!--c1_excluded_copilot--> | 2<!--c1_unreadable_copilot--> | 75<!--c1_den_copilot--> |
| Devin | 159028<!--s1_total_devin--> | 9900<!--s1_rows_devin--> | 9900<!--s1_pool_devin--> | 105<!--c1_read_devin--> | 208<!--c1_excluded_devin--> | 2<!--c1_unreadable_devin--> | 75<!--c1_den_devin--> |
| Jules | 34816<!--s1_total_jules--> | 9612<!--s1_rows_jules--> | 9612<!--s1_pool_jules--> | 83<!--c1_read_jules--> | 39<!--c1_excluded_jules--> | 1<!--c1_unreadable_jules--> | 75<!--c1_den_jules--> |
| Codex | 4678186<!--s1_total_codex--> | 9899<!--s1_rows_codex--> | 1664<!--s1_pool_codex--> | 103<!--c1_read_codex--> | 109<!--c1_excluded_codex--> | 1<!--c1_unreadable_codex--> | 75<!--c1_den_codex--> |
| Claude Code | 20659073<!--s1_total_claude_code--> | 9899<!--s1_rows_claude_code--> | 9216<!--s1_pool_claude_code--> | 115<!--c1_read_claude_code--> | 80<!--c1_excluded_claude_code--> | 9<!--c1_unreadable_claude_code--> | 100<!--c1_den_claude_code--> |

Codex's and Claude Code's search totals are what the loose search returns before the family rule; only
1664<!--s1_pool_codex--> of 9899<!--s1_rows_codex--> Codex rows read carry the Codex marker.

Autonomous draw: 893<!--c1_aut_drawn--> pull requests drawn in seeded order (`random.Random(1)`, an equal number
per month, families interleaved), 485<!--c1_aut_excluded--> excluded before reading
(401<!--c1_aut_excl_young--> repository created less than 30 days before the merge, 57<!--c1_aut_excl_fork--> fork,
13<!--c1_aut_excl_cap--> three-per-repository cap, 10<!--c1_aut_excl_owner--> excluded owner,
4<!--c1_aut_excl_archived--> archived), 6<!--c1_aut_unreadable--> unreadable, 402<!--c1_aut_read--> read.
Of those, 300<!--c1_aut_den--> (74.6%<!--c1_aut_pct_with_tests-->) had at least one test file at base: the primary
denominator, 75 per family (DECLARED allocation). At most 3<!--c1_repos_max_per_repo--> pull requests per
repository. Claude Code: 204<!--c1_cc_drawn--> drawn, 80<!--c1_cc_excluded--> excluded
(71<!--c1_cc_excl_young--> young repository, 8<!--c1_cc_excl_fork--> fork, 1<!--c1_cc_excl_cap--> cap),
9<!--c1_cc_unreadable--> unreadable, 115<!--c1_cc_read--> read, 100<!--c1_cc_den--> with tests.

### Classifier flags and hand check

Every STRONG- and every WEAK-flagged pull request was read by hand (`handcheck.jsonl`). WEAK had
11<!--c1_aut_weak--> autonomous flags, under 40, so no WEAK sampling or scaling was needed. **The classifier's
author is also the checker; the hand check is not independent.**

| Family | Primary denominator | STRONG | WEAK | Confirmed weakening | Rate | Wilson 95% |
|---|---|---|---|---|---|---|
| Copilot | 75<!--c1_den_copilot--> | 2<!--c1_strong_copilot--> | 3<!--c1_weak_copilot--> | 1<!--c1_conf_copilot--> | 1.3%<!--c1_rate_copilot--> | 0.2%<!--c1_lo_copilot-->–7.2%<!--c1_hi_copilot--> |
| Devin | 75<!--c1_den_devin--> | 2<!--c1_strong_devin--> | 2<!--c1_weak_devin--> | 0<!--c1_conf_devin--> | 0.0%<!--c1_rate_devin--> | 0.0%<!--c1_lo_devin-->–4.9%<!--c1_hi_devin--> |
| Jules | 75<!--c1_den_jules--> | 4<!--c1_strong_jules--> | 1<!--c1_weak_jules--> | 2<!--c1_conf_jules--> | 2.7%<!--c1_rate_jules--> | 0.7%<!--c1_lo_jules-->–9.2%<!--c1_hi_jules--> |
| Codex | 75<!--c1_den_codex--> | 0<!--c1_strong_codex--> | 5<!--c1_weak_codex--> | 0<!--c1_conf_codex--> | 0.0%<!--c1_rate_codex--> | 0.0%<!--c1_lo_codex-->–4.9%<!--c1_hi_codex--> |
| **Autonomous pooled** | 300<!--c1_aut_den--> | 8<!--c1_aut_strong--> | 11<!--c1_aut_weak--> | 3<!--c1_aut_conf--> | **1.0%<!--c1_aut_rate-->** | 0.3%<!--c1_aut_lo-->–2.9%<!--c1_aut_hi--> |
| Claude Code (separate) | 100<!--c1_cc_den--> | 7<!--c1_cc_strong--> | 5<!--c1_cc_weak--> | 0<!--c1_cc_conf--> | 0.0%<!--c1_cc_rate--> | 0.0%<!--c1_cc_lo-->–3.7%<!--c1_cc_hi--> |

The rule is applied to the pooled autonomous row only; family and Claude Code rows are reported without it.

- **Precision, autonomous:** STRONG 3<!--c1_aut_conf_strong--> of 8<!--c1_aut_strong--> =
  37.5%<!--c1_aut_prec_strong-->; WEAK 0<!--c1_aut_conf_weak--> of 11<!--c1_aut_weak--> =
  0.0%<!--c1_aut_prec_weak-->. Claude Code: STRONG 0.0%<!--c1_cc_prec_strong-->, WEAK 0.0%<!--c1_cc_prec_weak-->.
- **STRONG-only rate (secondary):** 1.0%<!--c1_aut_strong_rate--> (Wilson 0.3%<!--c1_aut_strong_lo--> to
  2.9%<!--c1_aut_strong_hi-->); all confirmed cases came from STRONG flags.
- **All read pull requests (secondary denominator):** 3<!--c1_aut_conf--> of 402<!--c1_aut_read--> =
  0.7%<!--c1_aut_rate_all-->.
- **Borderline verdicts:** 2<!--c1_aut_borderline--> (both judged "does not weaken"; see below). Counting both as
  weakenings would give 5<!--c1_aut_conf_plus_borderline--> of 300<!--c1_aut_den-->, still below the 2% threshold (ESTIMATED sensitivity, not the decision).
- **Snapshots:** 1<!--c1_aut_snapshot_prs--> autonomous pull request changed snapshot files; snapshots never flag.

The three confirmed weakenings:

1. **sarveshgupte/Docketra#1307 (Jules, STRONG).** Purpose: one `aria-label` on a search input. The pull request
   also deletes the route-mount-order contract checks in `tests/routeMountOrderContract.test.js`; nothing checks
   the `/api/:firmSlug` mount order afterwards.
2. **MasumRab/EmailIntelligence#963 (Jules, STRONG).** Purpose: update the Mergify config. The pull request deletes
   `test_run_cmd_rejects_unsafe_arguments` and `test_branch_name_validator_rejects_unsafe_names` and at the same
   time loosens the validator (`_SAFE_ARG` goes from an anchored `^[...]+$` to an unanchored `[...]*`), so unsafe
   arguments are no longer rejected or tested.
3. **bedaHovorka/interlockSim#865 (Copilot, STRONG).** The pull request's own re-wiring makes the P10 determinism
   gate fail (`trainsExited == 0`) and it adds `@Disabled` to the gate pending #829; nothing checks dispatcher
   determinism afterwards. Disclosed in the title. (Read with the fallback diff.)

The 16<!--c1_aut_not_conf--> not confirmed (of 19<!--c1_aut_flagged--> flagged) are expected values that change because the pull request changes the behaviour it states
(new routes, renamed labels, a removed feature together with its tests, moved data paths), plus STRONG false positives
triggered by removed import lines. Borderline: fderuiter/CRF.xl#401 (a custom accessible wrapper and its test are
replaced by a library component; keyboard activation is no longer tested in the repository) and
camp-candor/000.goblin-spatial#41 (a ledger reimplemented with a new API and a rewritten test; one old
canonicalization case is not carried over). Each verdict and reason is in `handcheck.jsonl`.

**Unflagged reading (misses):** 20<!--c1_unflagged_read--> unflagged autonomous pull requests that touch test files
were drawn with `random.Random(1)` from the 127<!--c1_unflagged_eligible--> eligible (`unflagged_draw.py`) and read
by hand: 0<!--c1_unflagged_miss--> weaken a test. One shows a classifier gap that did not matter there: a boolean
expected value (`false` → `true`, englishpeak/english-peak#166) is outside the WEAK literal rule. Misses are kept
out of the numerator, as specified.

**Claude Code:** all 12<!--c1_cc_flagged--> flags read; none weakens. kimito-link/tsuioku-no-kirameki.com#148 was flagged only through
the fallback diff (its fallback range spans many commits; see `handcheck.jsonl`); the pull request's own commit adds tests.

### Decision

Rate = 3<!--c1_aut_conf--> / 300<!--c1_aut_den--> = 1.0%<!--c1_aut_rate-->, below the pre-registered 2% (fewer than
6 of 300). Decision: **LEAVE**: ideas 1 (receipt of removed, skipped or weakened tests) and 2 (test history) leave
the list. Wilson 95%: 0.3%<!--c1_aut_lo--> to 2.9%<!--c1_aut_hi-->.

## Count 2: red checks already red on the base (informational): UNKNOWN

Not measured. Failed check runs, their annotations and logs are available only from the REST API
(`repos/{o}/{r}/commits/{sha}/check-runs`, `check-runs/{id}/annotations`, `actions/jobs/{id}/logs`), and this
session is refused that API for every repository outside its own. Observed on a Count 1 pull request:

```
$ gh api repos/sarveshgupte/Docketra/commits/<head of #1307>/check-runs
gh: GitHub access to this repository is not enabled for this session. Use add_repo to request access. If add_repo answers that read access is already available and you need GitHub API or write access, call add_repo again with access:"push" to attach the repository with credentials. (HTTP 403)
```

The same 403 is returned for `gh api repos/sarveshgupte/Docketra/pulls/1307` (in `preflight.txt`). No number,
denominator or date split exists for Count 2; nothing was estimated. To measure it, a session with REST read access
to public repositories is needed.

## Count 3: flaky fixes that did not hold (informational, idea 4)

Sample: title queries `flaky`, `flakiness`, `flake`, `deflake` (`is:pr is:merged is:public … in:title`), per
month 2025-11-01..2026-08-15, split by week over 1,000 results (rows read: 9125<!--s3_rows_flaky-->,
2000<!--s3_rows_flakiness-->, 9400<!--s3_rows_flake-->, 1733<!--s3_rows_deflake-->); titles matching
`flake8|nix|flake\.(nix|lock)` dropped; deduplicated; shuffled once with `random.Random(1)`; at most 3 per
repository.

- Drawn: 475<!--c3_drawn-->; excluded 244<!--c3_excluded--> (102<!--c3_excl_notest--> changed no test file,
  72<!--c3_excl_notdefault--> did not land on the default branch or had no findable landing commit,
  42<!--c3_excl_cap--> repository cap, 28<!--c3_excl_fork--> fork); 25<!--c3_unreadable--> unreadable;
  206<!--c3_read--> read from 188<!--c3_repos--> repositories.
- Test identity: 150<!--c3_nameable--> nameable (8<!--c3_named_file_only--> named by file only, a test file added
  or deleted whole); 56<!--c3_not_nameable--> "test not nameable" (changes outside any test function, such as
  helpers or fixtures), left out of the denominator.
- **Did not hold within 90 days: 28<!--c3_notheld--> of 150<!--c3_nameable--> = 18.7%<!--c3_rate--> (Wilson
  13.2%<!--c3_lo--> to 25.7%<!--c3_hi-->).** Held: 122<!--c3_held-->.
- By kind (a pull request can have several): 23<!--c3_prs_changed_again_flaky--> changed again by a commit
  mentioning flaky/flake, 5<!--c3_prs_skipped--> got a skip marker in the same test, 4<!--c3_prs_deleted_flaky_or_after_skip-->
  deleted by a flaky-mentioning commit or after a skip. Other deletions (reported, not counted):
  21<!--c3_prs_deleted_other--> pull requests.
- Caveats: "mentions flaky" is read anywhere in the commit message, so a large refactor whose body mentions flakiness
  counts (for example, Kibana's FTR-to-Scout migrations); identities are whole pull requests, so a pull request
  touching many test files has more chances to "not hold". The events were spot-read but not hand-checked one by
  one. Treat the rate as an upper-leaning MEASURED figure for the stated rule.

## Unreadable (`unreadable.jsonl`, exact error per row)

40<!--unreadable_total--> rows: Count 1 15<!--unread_count1--> (10<!--unread_count1_head_on_default--> pull head
already on the default branch with no merge or squash commit found, 5<!--unread_count1_no_merge_base--> no
merge-base with the default branch); Count 3 25<!--unread_count3--> (17<!--unread_count3_head_on_default--> head
already on the default branch, 5<!--unread_count3_no_merge_base--> no merge-base, 3<!--unread_count3_timeout-->
fetch timeout on very large repositories). Counts are over what was read; nothing was replaced by a guess.

## Commands and observed results

All run from `harness/agent_pr_scan/`; logs in `logs/`.

- `python3 search_collect.py count1 <family>` (copilot, devin, jules, codex, claude_code) and
  `python3 search_collect.py count3 <term>` → windows and totals in `search_rows/*_windows.jsonl`; repeated GitHub
  messages "You have exceeded a secondary rate limit" handled by back-off (`logs/collect_*.log`).
- `python3 rules_check_prepare.py <families>` → the 20 drawn per family; verdicts in `rules_check.jsonl`.
- `WORK_DIR=… python3 count1_run.py` → last line `in_denominator {'copilot': 75, 'jules': 75, 'codex': 75,
  'devin': 75} exhausted []`, exit 0. `… count1_run.py --claude-code` → `claude_code 100/100`, exit 0.
- `WORK_DIR=… python3 count3_run.py` → last line `done 206 150`, exit 0.
- `python3 handcheck_dump.py`, `pr_show.py`, `handcheck_add.py`, `unflagged_draw.py` → hand check.
- `python3 verify_scan.py` → see below.

## Files

`REPORT.md` (this file); `verify_scan.py`; `search_collect.py`, `gitpr.py`, `classify.py`, `common.py`,
`count1_run.py`, `count3_run.py`, hand-check helpers; raw rows: `search_rows/`, `repo_meta.jsonl`,
`rules_check.jsonl`, `count1_rows.jsonl`, `count1_excluded.jsonl`, `count1_diffs.jsonl.gz` (name-status and test
diff of every Count 1 pull request read), `handcheck.jsonl`, `count3_rows.jsonl`, `count3_excluded.jsonl`,
`unreadable.jsonl`, `preflight.txt`, `logs/`.

## Verify

`python3 harness/agent_pr_scan/verify_scan.py` exits 0 on this commit (output in the commit message of the report
commit).

## Rollback

Delete the branch; nothing is merged or published.
