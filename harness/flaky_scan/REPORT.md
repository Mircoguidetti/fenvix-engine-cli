# Flaky tests on public code: D21 and D22

Date: 2026-11-22. Branch `claude/flaky-scan`, folder `harness/flaky_scan/`. Read-only: public code search plus
blobless partial clones that fetched only test, config, dependency and CI files. Nothing from another repository was
installed or executed. Nobody was contacted, and the engine was not changed.

Every number tagged in the source of this file (`<!--key-->`) is re-derived from `scan.jsonl` by
`python3 harness/flaky_scan/verify_scan.py`, which exits 1 on a mismatch. Labels used here: **MEASURED** (from
`scan.jsonl`, with the command that produced it), **ESTIMATED**, **DECLARED** (from the spec) and **UNKNOWN**.

## Plain answers

- **D21. How many projects live with flaky tests?** In a neutral sample of public repositories that have a
  test-runner config, 18.6%<!--pct_neutral_lives--> carry a retry or flaky-skip mechanism. That drops to
  11.5%<!--pct_neutral_lives_excl_scaffold--> once you remove repositories whose only signal is Playwright's
  generated default (`retries: process.env.CI ? 2 : 0`). Only 4.8%<!--pct_neutral_stated--> say "flaky" (or a
  similar word) next to the mechanism. When repositories are found by the mechanism alone, a majority of those
  using it, 57.6%<!--pct_mechanism_implied_of_lives-->, give no reason. **MEASURED.**
- **D22. Do skipped flaky tests stay skipped for months?** Yes. Of 656<!--skips_n--> tests skipped with a flaky
  reason, 59.1%<!--pct_skips_over6--> have been skipped for more than 6 months, and
  36.1%<!--pct_skips_b_over12--> for more than 12. Only 2.0%<!--pct_skips_ref_open--> point to an issue that is
  still open, and 88.9%<!--pct_skips_ref_none--> point to no issue at all. **MEASURED** (the ages are lower bounds,
  see D22).

## Sample (DONE criterion 1)

**MEASURED** with `python3 harness/flaky_scan/collect.py` and then `scan_repos.py`.

- **Repositories examined:** 1296<!--examined--> (716<!--examined_js--> JavaScript/TypeScript and
  580<!--examined_py--> Python).
- **Scan coverage:** all 1296<!--scanned_ok--> scanned without a clone, checkout or timeout failure.
- **Collection:** each query was taken once (100 results per page, page 1, or pages 1-2 for `conftest.py`).
  GitHub forks were dropped. Each repository is attributed to the first query that found it.
- **Excluded by hand:** 28<!--vendored_excluded--> repositories carry another project's test suite as a copy
  (esp-idf, cypress, nest, penpot, pandas, …). They stay in the sample with no signals. The reason for each is in
  `build_scan.py` (`VENDORED`).
- **Excluded by rule:** 2029<!--excluded_signals--> raw matches were dropped by the `build_scan.py` rules:
  documentation, examples, blog posts, templates and fixtures; a call that only appears inside a string or
  `expect()`; and a test runner's own repository testing its own retry feature.

| # | frame | query (`gh api -X GET search/code -f q=…`) | repos (first found) | live with flaky | stated |
|---|---|---|---|---|---|
| 1 | neutral | `defineConfig filename:vitest.config.ts` | 100<!--q1_n--> | 15<!--q1_lives--> | 6<!--q1_stated--> |
| 2 | neutral | `module.exports filename:jest.config.js` | 100<!--q2_n--> | 4<!--q2_lives--> | 0<!--q2_stated--> |
| 3 | neutral | `defineConfig filename:playwright.config.ts` | 100<!--q3_n--> | 66<!--q3_lives--> | 6<!--q3_stated--> |
| 4 | neutral | `import pytest filename:conftest.py` | 200<!--q4_n--> | 19<!--q4_lives--> | 11<!--q4_stated--> |
| 5 | neutral | `testpaths filename:pytest.ini` | 98<!--q5_n--> | 7<!--q5_lives--> | 6<!--q5_stated--> |
| 6 | mechanism | `"jest.retryTimes("` | 67<!--q6_n--> | 35<!--q6_lives--> | 15<!--q6_stated--> |
| 7 | mechanism | `"this.retries(" language:JavaScript` | 85<!--q7_n--> | 8<!--q7_lives--> | 1<!--q7_stated--> |
| 8 | mechanism | `retry filename:vitest.config.ts` | 94<!--q8_n--> | 80<!--q8_lives--> | 32<!--q8_stated--> |
| 9 | mechanism | `"--reruns" filename:pytest.ini` | 96<!--q9_n--> | 77<!--q9_lives--> | 13<!--q9_stated--> |
| 10 | mechanism | `"pytest.mark.flaky" language:Python` | 75<!--q10_n--> | 46<!--q10_lives--> | 44<!--q10_stated--> |
| 11 | mechanism | `"--reruns" filename:pyproject.toml` | 27<!--q11_n--> | 23<!--q11_lives--> | 9<!--q11_stated--> |
| 12 | flakyword | `flaky "it.skip(" language:TypeScript` | 80<!--q12_n--> | 66<!--q12_lives--> | 62<!--q12_stated--> |
| 13 | flakyword | `flaky "test.skip(" language:JavaScript` | 90<!--q13_n--> | 73<!--q13_lives--> | 52<!--q13_stated--> |
| 14 | flakyword | `flaky "pytest.mark.skip" language:Python` | 84<!--q14_n--> | 27<!--q14_lives--> | 27<!--q14_stated--> |

Why the three frames:

- **neutral:** the query looks only for a test-runner config file. It is the denominator for "how many projects".
- **mechanism:** the query looks for a retry mechanism and never uses the word "flaky". It gives the unbiased
  stated/implied split among projects that use a mechanism.
- **flakyword:** the query contains "flaky", so it finds projects that state it by construction. It is reported
  only for completeness and for the D22 skips it supplies.

When a mechanism-frame repository shows no signal (175<!--mechanism_none--> of them), the hit was commented out (for example
`# addopts = --reruns 3`), set to 0, or inside a copied library. Search ranks by "best match", which favours
larger
repositories, but most of the sample is small: only 149<!--neutral_100_n--> of the 598<!--neutral_n--> neutral
repositories have 100 stars or more.

## D21: living with flaky tests (DONE criterion 2)

**MEASURED** with `python3 harness/flaky_scan/verify_scan.py --print`, which reads `scan.jsonl`.

### What counts as a signal

A repository "lives with flaky tests" when it has at least one of the following:

- **An automatic retry** with a retry count above 0:
  - Vitest `retry:` or `--retry`;
  - Jest `jest.retryTimes(`;
  - Playwright `retries:` or `--retries`;
  - Cypress `retries`;
  - Mocha `this.retries(`, `.mocharc` `retries` or `--retries`;
  - pytest `--reruns` or `reruns=`, `@pytest.mark.flaky`, or the `flaky` plugin;
  - a CI step that re-runs failures (`nick-fields/retry`, `--last-failed`, `--rerun-fails`, …).
- **A skip with a flaky reason.** The skip forms are `it/test/describe.skip`, `skipIf`, `test.fixme`, `xit`,
  `@pytest.mark.skip`/`skipif`/`xfail`, `pytest.skip(`, `@unittest.skip*` and `self.skipTest(`. The reason has to
  be in the skip line, in the comment block directly above it (at most 5 lines, stopping at a blank line or another
  test), or in the next 2 lines. The words that count are flaky/flakiness/flake, intermittent, unstable,
  quarantine, "sometimes fail" and race/racy.
- **A quarantine list or CI quarantine job:** a file named `flaky*` or `quarantine*` (.txt/.json/.yml), or a CI
  file line that mentions quarantine together with test/spec.

A retry is **stated** when one of those words is within ±5 lines of it, and **implied** otherwise. A skip with a
flaky reason is stated by definition. "Strict" drops the matches whose only word is race/racy/races, because a test
that *is about* races is not a flaky test.

### Results

| | neutral (prevalence) | mechanism (unbiased split) | flakyword (biased) |
|---|---|---|---|
| repositories | 598<!--neutral_n--> | 444<!--mechanism_n--> | 254<!--flakyword_n--> |
| live with flaky tests | 111<!--neutral_lives--> (18.6%<!--pct_neutral_lives-->) | 269<!--mechanism_lives--> (60.6%<!--pct_mechanism_lives-->) | 166<!--flakyword_lives--> (65.4%<!--pct_flakyword_lives-->) |
| … stated | 29<!--neutral_stated--> (4.8%<!--pct_neutral_stated-->) | 114<!--mechanism_stated--> (25.7%<!--pct_mechanism_stated-->) | 141<!--flakyword_stated--> (55.5%<!--pct_flakyword_stated-->) |
| … stated, strict | 28<!--neutral_strict_stated--> (4.7%<!--pct_neutral_strict_stated-->) | 111<!--mechanism_strict_stated--> (25.0%<!--pct_mechanism_strict_stated-->) | 135<!--flakyword_strict_stated--> (53.1%<!--pct_flakyword_strict_stated-->) |
| … implied only | 82<!--neutral_implied--> (13.7%<!--pct_neutral_implied-->) | 155<!--mechanism_implied--> (34.9%<!--pct_mechanism_implied-->) | 25<!--flakyword_implied--> (9.8%<!--pct_flakyword_implied-->) |
| stated share of those living with it | 26.1%<!--pct_neutral_stated_of_lives--> | **42.4%<!--pct_mechanism_stated_of_lives-->** | 84.9%<!--pct_flakyword_stated_of_lives--> |
| only signal is the Playwright scaffold default | 42<!--neutral_scaffold_only--> | 6<!--mechanism_scaffold_only--> | 13<!--flakyword_scaffold_only--> |
| live with flaky, excluding scaffold-only | 69<!--neutral_lives_excl_scaffold--> (11.5%<!--pct_neutral_lives_excl_scaffold-->) | 263<!--mechanism_lives_excl_scaffold--> | 153<!--flakyword_lives_excl_scaffold--> |
| carry a skipped flaky test | 14<!--neutral_skip_flaky--> (2.3%<!--pct_neutral_skip_flaky-->) | 37<!--mechanism_skip_flaky--> | 117<!--flakyword_skip_flaky--> |

How the neutral prevalence changes with the sample:

| neutral subset | repositories | live with flaky tests | stated |
|---|---|---|---|
| JavaScript/TypeScript | 300<!--neutral_js_n--> | 85<!--neutral_js_lives--> (28.3%<!--pct_neutral_js_lives-->) | |
| Python | 298<!--neutral_py_n--> | 26<!--neutral_py_lives--> (8.7%<!--pct_neutral_py_lives-->) | |
| Without the Playwright-config query | 498<!--neutral_nopw_n--> | 45<!--neutral_nopw_lives--> (9.0%<!--pct_neutral_nopw_lives-->) | 23<!--neutral_nopw_stated--> (4.6%<!--pct_neutral_nopw_stated-->) |
| 100 stars or more | 149<!--neutral_100_n--> | 30<!--neutral_100_lives--> (20.1%<!--pct_neutral_100_lives-->) | 11<!--neutral_100_stated--> (7.4%<!--pct_neutral_100_stated-->) |

The Playwright config query inflates the neutral figure. `npm init playwright` writes
`retries: process.env.CI ? 2 : 0` into the config, so finding a repository by its Playwright config almost
guarantees a retry: 66<!--q3_lives--> of 100<!--q3_n-->. That retry is a default nobody chose. This is why the
11.5%<!--pct_neutral_lives_excl_scaffold--> (or 9.0%<!--pct_neutral_nopw_lives--> without that query) is the
honest prevalence figure, not 18.6%<!--pct_neutral_lives-->.

Across all frames, 475<!--retry_repos--> repositories use an automatic retry. 323<!--retry_repos_unstated--> of
them (68.0%<!--pct_retry_repos_unstated-->) say nothing about why near any of their retry lines.

### By mechanism (repositories with the mechanism; one repository can have several)

| mechanism | all frames | neutral frame | with a stated reason |
|---|---|---|---|
| Playwright `retries` | 194<!--mech_playwright_retries--> | 82<!--mech_playwright_retries_neutral--> | 31<!--mech_playwright_retries_stated--> |
| pytest `--reruns` / `reruns=` | 160<!--mech_pytest_reruns--> | 9<!--mech_pytest_reruns_neutral--> | 62<!--mech_pytest_reruns_stated--> |
| skip with a flaky reason | 168<!--mech_skip_flaky--> | 14<!--mech_skip_flaky_neutral--> | 168<!--mech_skip_flaky_stated--> |
| Vitest `retry` | 93<!--mech_vitest_retry--> | 4<!--mech_vitest_retry_neutral--> | 36<!--mech_vitest_retry_stated--> |
| `@pytest.mark.flaky` | 54<!--mech_pytest_mark_flaky--> | 4<!--mech_pytest_mark_flaky_neutral--> | 54<!--mech_pytest_mark_flaky_stated--> |
| CI re-run of failed tests | 41<!--mech_ci_rerun--> | 2<!--mech_ci_rerun_neutral--> | 5<!--mech_ci_rerun_stated--> |
| Jest `jest.retryTimes` | 26<!--mech_jest_retryTimes--> | 0<!--mech_jest_retryTimes_neutral--> | 5<!--mech_jest_retryTimes_stated--> |
| Cypress `retries` | 19<!--mech_cypress_retries--> | 1<!--mech_cypress_retries_neutral--> | 0<!--mech_cypress_retries_stated--> |
| quarantine list file | 15<!--mech_quarantine_list--> | 3<!--mech_quarantine_list_neutral--> | 15<!--mech_quarantine_list_stated--> |
| Mocha `retries` | 14<!--mech_mocha_retries--> | 0<!--mech_mocha_retries_neutral--> | 3<!--mech_mocha_retries_stated--> |
| `flaky` plugin (`@flaky`) | 11<!--mech_flaky_plugin--> | 2<!--mech_flaky_plugin_neutral--> | 11<!--mech_flaky_plugin_stated--> |
| CI quarantine job / script | 11<!--mech_quarantine_ci--> | 0<!--mech_quarantine_ci_neutral--> | 11<!--mech_quarantine_ci_stated--> |
| pytest-retry `--retries` | 0<!--mech_pytest_retry--> | 0<!--mech_pytest_retry_neutral--> | 0<!--mech_pytest_retry_stated--> |

`@pytest.mark.flaky` and `@flaky` always count as stated, because the decorator itself names the problem. Go was
not sampled (the spec asked for JavaScript/TypeScript and Python).

Examples (verbatim, `file:line`, from `scan.jsonl`):

- `NativeScript/NativeScript` `packages/core/css/parser.spec.ts:375`: `it.skip('our parser is fast (this test is flaky, gc, opts.)', () => {`
- `tradingstrategy-ai/web3-ethereum-defi` `tests/enzyme/test_events.py:307`: `@pytest.mark.skipif(CI, reason="Too flaky on Github")`
- `dask/distributed` `distributed/tests/test_client.py:6519`: `@pytest.mark.skip(reason="known intermittent failure")`
- `eggjs/egg` `package.json:25` (implied): `"test": "vitest run --bail 1 --retry 2 --testTimeout 20000 --hookTimeout 20000",`

## D22: how long flaky skips stay (DONE criterion 3)

**MEASURED** with `python3 harness/flaky_scan/date_skips.py <kept.json>`, `build_scan.py` and then
`verify_scan.py --print`.

**What is counted.** These are the skipped tests with a flaky reason from D21, across all frames. A Python decorator
stack, or consecutive `test.skip(cond, …)` modifiers, counts as one test. That gives 656<!--skips_n--> skipped
tests in 168<!--skips_repos--> repositories: 404<!--skips_unconditional--> unconditional and
252<!--skips_conditional--> conditional (`skipIf(CI)`, `skipif(PR_TESTING)`, …).

**How the age is measured.** Each repository gets a blobless clone with history since 2025-10-01
(`--filter=blob:none --shallow-since=2025-10-01`, no checkout). Each skip line is then dated with
`git blame -w --porcelain -L n,n <commit> -- <file>`, using the committer date. That date is when the line last took
its current form, so it is a **lower bound** on how long the test has been skipped (a later edit of the line resets
it).

**Lines older than the fetched history.** These are attributed to the history's edge. 187<!--skips_over12_lower_bound-->
of the over-12 skips are such lines, so their exact age is UNKNOWN beyond "more than 12 months". A further
6<!--skips_b_lower_bound--> skips sit at an edge that is younger than 12 months. They are recorded as lower bounds
and left out of the four buckets below. Repositories with no commit since 2025-10-01 were fetched at depth 1. Their
`added_date` is the HEAD date, which is also a lower bound.

### Age distribution

| skipped for | all flaky skips | strict (no race-only) | unconditional only |
|---|---|---|---|
| under 1 month | 46<!--skips_b_under1--> (7.0%<!--pct_skips_b_under1-->) | 39<!--skips_strict_b_under1--> (6.3%<!--pct_skips_strict_b_under1-->) | 24<!--skips_uncond_b_under1--> (5.9%<!--pct_skips_uncond_b_under1-->) |
| 1-6 months | 222<!--skips_b_1_6--> (33.8%<!--pct_skips_b_1_6-->) | 202<!--skips_strict_b_1_6--> (32.7%<!--pct_skips_strict_b_1_6-->) | 109<!--skips_uncond_b_1_6--> (27.0%<!--pct_skips_uncond_b_1_6-->) |
| 6-12 months | 145<!--skips_b_6_12--> (22.1%<!--pct_skips_b_6_12-->) | 137<!--skips_strict_b_6_12--> (22.2%<!--pct_skips_strict_b_6_12-->) | 87<!--skips_uncond_b_6_12--> (21.5%<!--pct_skips_uncond_b_6_12-->) |
| over 12 months | 237<!--skips_b_over12--> (36.1%<!--pct_skips_b_over12-->) | 234<!--skips_strict_b_over12--> (37.9%<!--pct_skips_strict_b_over12-->) | 181<!--skips_uncond_b_over12--> (44.8%<!--pct_skips_uncond_b_over12-->) |
| lower bound only | 6<!--skips_b_lower_bound--> | 6<!--skips_strict_b_lower_bound--> | 3<!--skips_uncond_b_lower_bound--> |
| **over 6 months** | **388<!--skips_over6--> (59.1%<!--pct_skips_over6-->)** | 377<!--skips_strict_over6--> (61.0%<!--pct_skips_strict_over6-->) | 271<!--skips_uncond_over6--> (67.1%<!--pct_skips_uncond_over6-->) |
| total | 656<!--skips_n--> | 618<!--skips_strict_n--> | 404<!--skips_uncond_n--> |

A few repositories carry many skips: the three largest hold 32.2%<!--skips_top3_share--> of them. Counted per
repository instead, by the oldest flaky skip each of the 168<!--repos_dated--> repositories carries:

| oldest flaky skip in the repository | repositories |
|---|---|
| under 1 month | 17<!--repos_oldest_under1--> (10.1%<!--pct_repos_oldest_under1-->) |
| 1-6 months | 44<!--repos_oldest_1_6--> (26.2%<!--pct_repos_oldest_1_6-->) |
| 6-12 months | 28<!--repos_oldest_6_12--> (16.7%<!--pct_repos_oldest_6_12-->) |
| over 12 months | 79<!--repos_oldest_over12--> (47.0%<!--pct_repos_oldest_over12-->) |
| over 6 months | 107<!--repos_oldest_over6--> (63.7%<!--pct_repos_oldest_over6-->) |

### Referenced issues

**How references are found.** An issue reference has to be next to the skip, in the same window as its reason. It
can be a `github.com/<repo>/issues|pull/<n>` URL, a `#<n>`, `issue <n>`, or a tracker key such as `ABC-123`.

**How states are checked.** Each reference's state was read with
`gh api -X GET search/issues -f q='repo:<repo> is:issue <n> in:number'`, then `is:pull-request` if that returned
nothing. Tracker keys and references the search did not return are UNKNOWN. 38<!--issue_refs_checked--> of the
94<!--issue_refs_total--> references resolved to a state.

| skipped flaky tests | count | share |
|---|---|---|
| reference any issue / PR / ticket | 73<!--skips_ref_any--> | 11.1%<!--pct_skips_ref_any--> |
| … at least one referenced issue still **open** | 13<!--skips_ref_open--> | **2.0%<!--pct_skips_ref_open-->** |
| … all references closed (issue or PR) | 19<!--skips_ref_closed--> | 2.9%<!--pct_skips_ref_closed--> |
| … state UNKNOWN (tracker key, or not found by search) | 41<!--skips_ref_unknown--> | 6.2%<!--pct_skips_ref_unknown--> |
| reference nothing | 583<!--skips_ref_none--> | 88.9%<!--pct_skips_ref_none--> |

The 13<!--skips_ref_open--> skips with an open issue sit in 7<!--repos_with_open_issue_ref--> repositories. Even
if every UNKNOWN reference were open, the share with an open issue would still be below 9% (ESTIMATED as the sum of
the open and UNKNOWN rows).

## Limits

- **Matching is lexical.** A flaky reason more than 5 lines from its skip is missed. A word like "race" can describe
  a test *about* races; the "strict" columns remove those, and they change little. A retry set in a shared preset
  outside the repository, or only in CI-provider settings, is invisible here.
- **The sample is what public code search ranks first.** It is many small repositories, and the default branch
  only. The neutral frame measures "public repositories with a runner config", not companies or paying teams.
- **Ages are lower bounds** (see D22). An over-12 skip cannot become younger if dated more precisely, but a
  1-6-month skip could be older if its line was edited.
- **The by-hand exclusion of 28<!--vendored_excluded--> vendoring repositories is a judgement.** It is written out
  in `build_scan.py`.

## Files

- **`collect.py`:** the 14 queries; writes `candidates.jsonl`.
- **`meta.py`:** stars and language via `search/repositories`; writes `meta.jsonl`. Stars are known for
  1296<!--stars_known--> repositories.
- **`scan_repos.py`:** the per-repository partial fetch and regexes; writes `raw_scan.jsonl`.
- **`date_skips.py`:** the D22 blame and issue states; writes `skip_dates.jsonl`.
- **`build_scan.py`:** the filters and merge; writes `scan.jsonl`, one line per repository. Each line holds the
  repository, commit, stars, language, frame and query, the signals with file:line and the verbatim line, stated or
  implied, and the skipped flaky tests with `added_date`, `age_bucket` and `issue_ref`.
- **`verify_scan.py`:** re-derives every tagged number above from `scan.jsonl`.
