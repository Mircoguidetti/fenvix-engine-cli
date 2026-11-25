# Cache measurement B: preregistration (PREREG)

Committed before the first B1 replay. Spec: "cache measurement B" rev 3 (founder "manda" 2026-11-25), gate rev 3 notes.
Engine base: `origin/claude/release-1` 6e79a62. A's data: `origin/claude/cache-measure-a` 6c4ee3d
`harness/cache_selection/`. Sets built by `harness/cache_b/prereg.py` into `prereg.json` (every sha listed there);
runner-time estimates by `budget.py` into `budget.json`; disjointness checked by `test_prereg.py`
(`python3 -m pytest -q harness/cache_b/test_prereg.py`: 10 passed).

## Decision line (unchanged from the memo; threshold 30% ASSUMED, kept)

By 19 Dec 2026, on at least 3 measurable pool repositories, the cache saves at least 30% of CI test-job wall time
(median per repository over its replayed commits and PRs, gate saving = 1 - T(cached)/T(plain)) with 0 wrong reuses
over every replay, red-push replay and fault injection of B2. Any wrong reuse, or fewer than 3 repositories at 30% or
more: the cache stays out until fixed. Fewer than 3 measurable repositories: NOT MEASURABLE.

## Set rules (as applied by prereg.py)

- **B2 commits:** the 20 most recent merged-PR landing commits of A's `prs.json` (by landing date); fewer than 20 ->
  filled with the most recent first-parent commits of the specs.json commit not already taken. Replayed in
  first-parent order (oldest first). Commit seed = first parent of the oldest B2 commit.
- **B2 PRs:** 10 code PRs (`klass` code), most recent landing first; fewer -> all (n stated). PR seed = merge-base of
  base and head.
- **K2(a):** per code PR of A's `prs.json`, most recent first, `git rev-list --first-parent --no-merges base..head`
  minus A's `states`, at most 10 per PR and 30 per repository; seed = the PR's merge-base.
- **Harden set (B1):** 10 first-parent commits strictly older than the oldest B2 commit, plus up to 10 intermediate
  states (A's `states` other than the head) of PRs not in the B2 PR set, most recent first. A sha in any B2 list is
  dropped: B2 commits, PR heads, **seeds** (the commit seed and every PR / K2(a) merge-base: stricter than the spec's
  text, so that B1 never stores on a state B2 seeds from) and K2(a) states. The campaign replays the harden states in
  committer-date order (oldest first); its seed is the oldest.
- **Later B2 lists** (K2(b) closed-unmerged heads, red states, fault states) are added to `prereg.json` before the
  first B2 job, never chosen from the harden set; `test_prereg.py` covers them once present (gate note 6).
- Precedence: A's landing commits are used as they are; the specs.json commit pins install instructions only.

| repo | specs.json commit | LAUNCH_SHA | Node | B2 commits | B2 PRs | K2(a) | harden (commits + PR states) | notes |
|---|---|---|---|---|---|---|---|---|
| codex-multi-auth | b9886168aafc | b9886168aafc | 22.23.5 | 20 | 10 | 30 | 20 (10 + 10) | - |
| ironcurtain | abf2b44c2e1b | abf2b44c2e1b | 22.23.5 | 20 | 10 | 8 | 15 (10 + 5) | - |
| yalc | 5686d1f2f526 | 5686d1f2f526 | 22.23.5 | 20 | 10 | 13 | 6 (2 + 4) | B2 commits: 19 landing commits, 1 filled from first-parent history of 5686d1f2f526 |
| nestjs-pino | 82d92198747c | 82d92198747c | 22.23.5 | 20 | 2 | 0 | 10 (10 + 0) | B2 PRs: 2 code PRs available (fewer than 10) |
| agentsys | ce58913304d8 | ce58913304d8 | 22.23.5 | 20 | 10 | 3 | 20 (10 + 10) | - |
| lerna-lite | fec3cb9660ba | fec3cb9660ba | 22.23.5 | 20 | 10 | 0 | 14 (10 + 4) | - |
| drydock | ce562a6a84c9 | fcb46a5ac53c | 24.22.3 | 20 | 10 | 10 | 18 (10 + 8) | B2 commits: 11 landing commits, 9 filled from first-parent history of ce562a6a84c9 |
| agentlang | f02e27199b19 | f02e27199b19 | 22.23.5 | 20 | 10 | 11 | 20 (10 + 10) | - |
| alakajam | af63a7e0993f | af63a7e0993f | 22.23.5 | 20 | 10 | 13 | 20 (10 + 10) | - |

Fixed paths: every repository at `/home/runner/work/pool/<repo>` (drydock runs in `app/`), state switched in place.

## Classification of a mismatch (B1.3, used by B1 and B2)

A mismatch is a file the cache would reuse as passing while the fresh run of the same state fails a test in it. It is
reproduced with 10 plain runs of that test file at that state on the same machine: `instability` only if the 10 runs
include at least one pass and one fail (failing count recorded); every other result (10/10 fail or 10/10 pass) is
`wrong-reuse` (split in B2 as `wrong-reuse (plain fails)` and `wrong-reuse (engine only)`; both count).

## B1 harden campaign

- **Where (B1.4 / gate note 12): the session's container** (4 CPUs, Linux x86_64, Node 22.23.5 for every repository
  except drydock 24.22.3), not GitHub Actions: a mismatch must be reproduced on the same machine (10 plain runs), and
  fix-restart cycles need no artifact chain. The exit pass runs in the URL form (gate note 9): the engine's own cache
  service on loopback, `FENVIX_CACHE_TOKEN`, a fresh `FENVIX_CACHE_LOCAL` per run.
- Per repository: seed at the oldest harden state with measure.py's `serial` command plus `--det-cache=<dir|url>`;
  every later harden state with the same plus `--det-cache-verify`; summary and receipts written outside the tree.
  Each mismatch of `verify_mismatches` (summary JSON, never the printed lines) is classified as above; each
  `wrong-reuse` is an engine defect: root cause, fix with a red-then-green regression test, restart from the seed.
- Exit criterion and stop date: as the spec (one complete pass of all 9 repositories on the final B1 head with 0
  `wrong-reuse`; NOT DONE on 9 Dec 2026 12:00 UTC otherwise).

## B2 runner-time budget (ESTIMATED; cap 8 h per repository)

Model (`budget.py`): every run costs A's median plain wall; a replay state is 4 runs; seeds 1 run (+1 URL-form probe);
red search 1 run per candidate; red and K2 replays 4 runs; cs.py 2 runs per K2 state; a fault job 1 run. Drops in the
spec's order until under the cap; then commits down to a minimum of 5 (`under-sampled`). The estimate is pessimistic
for cached runs (a cached run that reuses costs less than a plain run); the real drops are decided from measured walls
at B2 time and recorded.

| repo | A plain wall (s, median) | full plan (h) | after drops (h) | drops applied | commits / PRs kept | under-sampled | over cap at minimum |
|---|---|---|---|---|---|---|---|
| codex-multi-auth | 345.1 | 42.95 | 15.15 | k2b_replays, k2a_replays, red_search_beyond_5, prs_beyond_5, commits_beyond_10 | 5 / 5 | yes | yes |
| ironcurtain | 233.7 | 20.51 | 7.92 | k2b_replays, k2a_replays, red_search_beyond_5, prs_beyond_5, commits_beyond_10 | 7 / 5 | yes | no |
| yalc | 16.3 | 1.57 | 1.57 | - | 20 / 10 | no | no |
| nestjs-pino | 19.6 | 1.24 | 1.24 | - | 20 / 2 | no | no |
| agentsys | 34.6 | 2.75 | 2.75 | - | 20 / 10 | no | no |
| lerna-lite | 616.6 | 45.9 | 16.79 | k2b_replays, k2a_replays, red_search_beyond_5, prs_beyond_5, commits_beyond_10 | 5 / 5 | yes | yes |
| drydock | 520.4 | 47.41 | 17.06 | k2b_replays, k2a_replays, red_search_beyond_5, prs_beyond_5, commits_beyond_10 | 5 / 5 | yes | yes |
| agentlang | 54.0 | 5.01 | 5.01 | - | 20 / 10 | no | no |
| alakajam | 1.2 | 0.12 | 0.12 | - | 20 / 10 | no | no |

Three repositories (codex-multi-auth, lerna-lite, drydock) stay over the cap at the minimum in this estimate: the
free-tool count of K2 (kept by the spec's drop order) alone costs about 2 plain runs per K2 state. They are listed
`under-sampled` and any MET resting on them prints its n.
