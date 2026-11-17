FIX 1

# R-002 re-check: skip study 2, fix round (fenvix-engine-cli `claude/loving-maxwell-58mv2w` @ dbb3bbe)

I am the reviewer. I worked in a read-only worktree (`<scratch>/rv-skip3`, detached at dbb3bbe) and pushed nothing. My new tests and scripts are in `<scratch>/review-R-002b/`, and my working notes are in `review-R-002b/notes.md`. `<scratch>` = `/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad`.

Labels: **MEASURED** = measured by me. **DECLARED** = taken from the delivery's files.

## Summary

| # | check | result |
|---|---|---|
| E1 | sqlite fixture opened read-write | **Fixed.** My original `test_sqlite_fixture_change_is_a_dependency` passes on dbb3bbe and still fails on 6be49f6 (control). I re-ran my full `walk.py` demo (`review-R-002/demo/spec.json`) with the v3 walker: `tests/test_db.py` now reruns with `closure = read:data` (MEASURED). |
| E2 | environment variable not in the key | **Fixed.** My original `test_environment_variable_is_a_dependency` passes on dbb3bbe and fails on 6be49f6 (MEASURED). |
| E3 | Go: no network guard | **Fixed for direct connections; still open behind a loopback proxy (proven error 1 below).** v3 data for terraform `internal/cloud`: `closure = network` at all 29 go-cache hits, including b3fb138b (i=50). The recorded addresses are 75.2.98.97, 99.83.150.238 and 127.0.0.53:53 (MEASURED from `results/v3/walk/terraform-0o2.json.gz`). |
| N1 | go-cache relabelled "no proof" | **Done** in the aggregator (`RULE_LABEL`) and in REPORT. One leftover: the Go **`strict`** row (see the notes). |
| N2/N9 | method: runtime identity, wall-clock | **Done.** §1 lists the runtime identity in the key. It states that wall-clock is not covered outside `detpy --det`. It also lists the remaining known limits (C-level `getenv`, loopback services, `.git/`). |
| N3 | rules beyond closure | **Done.** v2 rows print `n/a`. v3 compares every extra skip (`xverify`). Home Assistant v3, for example: `func` 4792 (0, 0) and `func+guard` 2494 (0, 0) (MEASURED, `aggregate.py --md v3`). |
| N4 | never reuse a cached failure | **Done.** `decide()` returns `cached-failure` for every rule when the cached code is not 0 or 5. I checked this with `review-R-002b/check_cached_failure.py`, which passes. Go caches only passes, so the rule holds there too. |
| N5 | verdict allow-list | **Done.** `aggregate.FLAKY_VERDICTS` is an explicit set. Any other verdict stays a wrong hit. |
| - | delivery's own tests | 14 of 14 pass (MEASURED; DECLARED: 14 passed). |
| 3 | v3 numbers | **Reproduced.** `aggregate.py --compare r1,r2,r3,r5,r6,r7,r8 v3` gives the headline before/after table cell for cell (MEASURED). My own share code, using the cost definition stated in §1, gives vue-core 25.4% / 30.6% and docusaurus 98.4% / 81.2% (report: 25% / 31% and 98% / 81%). |
| 3 | spot-check (vue-core v3) | **100 of 100 match** (MEASURED). See below. |

**Spot-check, vue-core v3.** Commits were picked at random (seed "R-002b", `spot/pick3.py`) among the 35 commits with at least 50 unverified `closure` skips. At each commit I took 50 random unverified skipped units and re-ran them fresh in one vitest call (Node 22.23.4, `spot/run_vue.sh`).

| commit | unverified skips there | re-run | fresh = reused outcome (pass) | tests passed / failed |
|---|---:|---:|---:|---|
| i=9 f64bfa57 | 75 | 50 | 50 | 1098 / 0 |
| i=17 70599b52 | 83 | 50 | 50 | 1050 / 0 |

- None of the 100 units is in `cached_fail`, so the reused outcome is a pass.
- None of the 100 test files changed between its record commit and the reuse commit (MEASURED, `git diff`).

## Proven error

### 1. The E3 network guard does not fire when the external service is reached through an HTTP(S) proxy on loopback

**Cause.**
- `strace_deps.external()` / `is_local_address()` treat every connect to 127.0.0.0/8 as local, except port 53.
- With `HTTPS_PROXY=http://127.0.0.1:<port>`, a test that needs an outside host connects only to the proxy. The proxy resolves the name, so the test makes no DNS connect either.
- So `net_ext = 0`, and Go `closure` and pytest/vitest `closure` both reuse the PASS.
- This setup is common: corporate CI runners, sidecar proxies, and this container. It is also exactly where I reproduced R-002 error 3.

**Real-repo evidence (MEASURED).** I traced terraform `internal/cloud` `TestRunEventWarningsAll` at b3fb138b in this container with the v3 capture (`review-R-002b/go-proxy/trace_tf_cloud.py`):
- connect() targets: `127.0.0.1:41047` (the proxy) and `127.0.0.1:38379`;
- `external()`: `[]`.

So the R-002 error-3 package would again be a `closure` skip whenever its last run passed.

**Failing tests:** `review-R-002b/test_r002b_go_proxy.py`. Both fail on dbb3bbe (MEASURED):
- `test_go_external_service_through_loopback_proxy_is_never_skipped`: a 2-commit Go module with a test that needs `https://github.com/`, run through the full `walk.py`. At c1 the go test cache hits (the recorded run passed), `net=1 net_ext=0`, and `closure` is `None` (skip).
- `test_pytest_external_service_through_loopback_proxy_is_never_skipped`: the same with urllib under pytest. Every rule returns `None`.
- Run them with `WT=<worktree> python -m pytest -q test_r002b_go_proxy.py`. They need a loopback HTTPS proxy and skip without one.

**Fix suggestion.** Count a connect to the address of `HTTP(S)_PROXY` / `ALL_PROXY` (from the unit's environment) as external. Alternatively, keep the proxy logs per unit. Then add one of these tests.

**Effect on the numbers.** None for the study: GitHub Actions has no proxy, and the v3 data shows real external addresses. The effect is on the product claim that "the v3 key closes … an external service" (REPORT §6).

## Notes (not counted)

- **Go `strict` is go-cache based but labelled plain "strict".**
  - `aggregate.py` L198-199 builds Go `strict` from `go-cache` plus the config rule. The terraform rows show `strict` 66% / 57% (v2) and 67% / 56% (v3) against `closure` 35% / 25% (MEASURED).
  - §1 defines strict as "`closure` plus the config rule", so a reader takes it for a stricter proof.
  - Relabel the Go row "go test cache + config (no proof)", or build it from `closure`.
- **Home Assistant v3 invalidates everything at 8 of 50 commits; v2 had 0 of 50.**
  - The breakdown is `py-source:source` 4, `exists:installed` 3, `read:installed` 1 (MEASURED, `aggregate.py --md v3`).
  - The median holds at 97%, but REPORT does not mention this. §2's "no commit forced everything" is true only for v2.
- **saleor row is stale.** The headline row shows v2 "10 commits, 0 (7)". The current aggregator prints 20 transitions and 23 (0, 0) verified (MEASURED). REPORT does label saleor as partial, from report v2.
- **Stale baseline test counts.** `transitions[].tests[u]` is the test count from a unit's first run, not from the commit, and 12 of my 100 differ from the fresh passed count. No outcome or share is affected (shares use time; counts are only the "tests skipped" column). The "tests skipped" share is therefore approximate where test files grew.
- **Disk.** The container volume filled up during the spot-check. I deleted only my own R-002 scratch: `review-R-002/fakehome` (2.8 GB of caches) and a Node tarball. Because of that, `test_docusaurus_home_case_reruns_when_home_changes` depends on my scratch (`DOCUSAURUS_SRC`) and could skip in other containers. It still passed here.

## Files
- `review-R-002b/test_r002b_go_proxy.py`: the 2 failing tests (error 1).
- `review-R-002b/go-proxy/trace_tf_cloud.py`: the real terraform trace for error 1.
- `review-R-002b/check_cached_failure.py`: the N4 check (passes).
- `review-R-002b/demo-e1/`: the E1 demo walk on v3 (`walk.log`, `out.json.gz`).
- `review-R-002b/spot/`: `pick3.py`, `run_vue.sh`, `vue-pick.json`, and the vitest JSON outputs `vue-0.json` and `vue-1.json`.
- `review-R-002b/compare.md`, `review-R-002b/v3-md.md`: the aggregator outputs.
- `review-R-002b/notes.md`: working notes.
