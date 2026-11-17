# Skip-with-proof study 2: where are the minutes?

Status: **version 1 (2026-11-16 23:45 UTC), partial**. Settings 1 (large repositories) and 4 (time to green,
reruns) have data; setting 2 (coding-agent pull requests), saleor, the remaining reruns and the finer rule
v2 are still running or queued on GitHub Actions. Every number is labelled. Raw data:
`harness/skip_study2/results/<run>/`; summary: `harness/skip_study2/results/summary.json`; tables are
regenerated with `python3 harness/skip_study2/aggregate.py --md`.

## Interim update (2026-11-17 01:10 UTC)

* home-assistant now 30 commits: closure 98% / 87% (unchanged), coverage-only `func` 98% / 90%, strict
  98% / 74%; 1575 verified skips, 0 wrong (MEASURED).
* prometheus now 40 commits: go-cache 50% / 48% (MEASURED), 256 verified hits, 0 wrong.
* saleor, first 10 commits (shard-complete): closure **0% / 9%**, func+guard 0% / 16%, coverage-only
  `func` 32% / 38% (MEASURED, 15% sample); 9 of 10 commits invalidate everything (a data directory listing
  changed 4, a shared Python source changed 4, a config file read 1). Django loads the whole project
  (settings, every app's models) in every test process, so every test reads nearly every module.
* Coding-agent PRs (setting 2), first results (MEASURED, time skipped per push, median / mean, rule
  `closure`; Go also `go-cache`): Copilot on github-mcp-server 15 PRs / 101 pushes: closure 47% / 49%,
  go-cache 68% / 52%, 0 wrong of 287 verified; Copilot on typescript-go 1 PR / 6 pushes: 49% / 55%;
  Copilot on home-assistant 3 PRs / 12 pushes: 100% / 95%; Codex on home-assistant 1 PR / 4 pushes:
  49% / 49%.
* **Two verification mismatches** on the Home Assistant Copilot PRs (MEASURED): a skipped unit whose fresh
  outcome differed from the cached one, reproducibly at the new commit
  (`tests/components/switchbot/test_init.py` in PR 171334, `tests/components/knx/test_number.py` in PR
  163164). In both cases the push changed 1 file unrelated to the integration, and the cached outcome came
  from the base commit, where every unit ran in parallel under strace with HA's `--timeout=9`. Until a
  re-check proves otherwise they count as **wrong hits**. A re-check job (run s1, `recheck.py`) reruns each
  unit at the cached commit and at the new commit, plainly, traced alone and traced under load, to tell
  a missed dependency from an outcome that does not reproduce.
* openai-agents-python Codex PRs (run r6) were invalid: the walker took the merge base with the default
  branch while these PRs target another branch (400+ commits per "PR", installs failed). Fixed (own base
  branch, cap at 25 commits) and relaunched in run s1.
* more-itertools (finer rule): closure 0/11, file+guard 6/14, line+guard 53/38, line+names 53/38,
  coverage-only line 60/55 (strict, median/mean %). With 14 libraries the median of medians / mean of
  means is: strict/closure 0/15, file+guard 0/21, line+guard 0/24, **line+names 0/26**, coverage-only
  line 48/46 (MEASURED).

## 0. Question and answer so far

The first study (`docs/CACHE-SKIP-STUDY.md`, 14 small Python libraries x 50 commits) found that a median
0% / mean 22% of test time per commit could be skipped **with proof**. Where are the skippable minutes?

Answer so far: **in large repositories made of many loosely coupled parts.** On Home Assistant a median
98% of test time per commit is skippable with proof (MEASURED, 12% sample of test files, 20 commits so
far); on Docusaurus 98% (MEASURED, 50 commits). Tightly coupled code skips little even when large:
vue-core 25% median (MEASURED). In Go the toolchain's own test cache, used as a remote cache across
commits, skips a median 43-72% of package test time (MEASURED) and was never wrong on 832 verified hits
(MEASURED).

| setting | time skippable with proof, median / mean per commit | wrong hits (verified skips) | label |
|---|---|---|---|
| first study, 14 small Python libraries (reference) | 0% / 22% | 0 | MEASURED (`docs/CACHE-SKIP-STUDY.md`) |
| home-assistant (Python, 20 commits so far, 12% sample) | **98% / 87%** | 0 (1046) | MEASURED |
| saleor (Python) | not yet (1 of 8 shards has 10 commits) | - | UNKNOWN |
| docusaurus (TypeScript, vitest, 50 commits) | **98% / 81%** | 0 (829) | MEASURED |
| vue-core (TypeScript, vitest, 50 commits) | 25% / 28% | 0 (371) | MEASURED |
| terraform (Go, go test cache as remote cache, 50 commits) | 72% / 61% | 0 (697) | MEASURED |
| prometheus (Go, go test cache, 20 commits so far) | 43% / 43% | 0 (135) | MEASURED |
| coding-agent PR pushes (setting 2) | queued | - | UNKNOWN |
| finer rule `line+names`, 13 of the 14 libraries (setting 3, v1) | 0% / 25% (proof `file+guard` 0% / 21%; coverage-only `line` 47% / 45%) | 0; pygments 7c196150 caught | MEASURED |

## 1. Method (same proof discipline as the first study)

Harness: `walk.py` (Python, TypeScript and Go walks), `strace_deps.py` and `pyhooks/` (dependency
capture), `flaky.py` (reruns), `finer/` (setting 3), `agent_walk.py` (setting 2), `aggregate.py`. All
runs on GitHub Actions `ubuntu-latest` (4 vCPU), workflow `.github/workflows/skip-study2.yml`.

* **Unit** = one test file run in its own process (pytest, vitest) or one Go package.
* **Commits**: consecutive first-parent commits of the default branch (50 transitions per repository
  unless stated). At every commit the walker checks out, reinstalls when a dependency spec changed,
  builds, decides per unit, then really runs every unit it cannot skip.
* **Proof rule `closure`**: a unit reuses its last result only if nothing it read changed: every file it
  opened (strace: sources, node_modules, interpreter, shared libraries), every path it found missing (now
  created?), every path it stat'ed, every directory it listed, every module name it looked up, every
  environment variable it read, new pytest plugin entry points. Python also records imports via hooks.
* **`strict`** = `closure` plus the first study's config rule (any lockfile, config or CI file change
  reruns everything): the rule a cautious product would ship first.
* **Python only**: `func+guard` (a changed `.py` file with unchanged module skeleton forces a rerun only
  if a function whose definition changed was executed: still a proof at the Python level), `~cfg`
  variants (a root config file whose pytest section is unchanged does not count: near-proof), and
  **`func` = coverage-only, NOT a proof**, reported as asked.
* **Go**: `go-cache` = the go command's own test cache (GOCACHE persisted across commits, i.e. a remote
  cache restored into cold CI). Go `closure` = go-cache hit AND no file the test read at runtime (strace)
  changed. A go-cache hit whose runtime reads changed is a *potential* wrong hit and is always verified.
* **Verification**: at every commit a random sample of skippable units (plus every potential Go wrong hit)
  runs anyway. A **wrong hit** is a fresh outcome that differs from the cached one and reproduces on a
  second fresh run (if it does not reproduce it is counted as flaky, not wrong).
* **Shares** per commit: skipped unit time / total unit time (unit time = test durations, or unit wall
  minus the fixed process start-up, whichever is larger: per-file imports and transforms are paid in CI
  too), and skipped tests / total tests. Median and mean over commits.
* **Time to green** (ESTIMATED from MEASURED unit costs): longest-processing-time-first schedule of the
  units on the project's CI worker count, before (all units) and after (units that must run). "After" is
  shown with the MEASURED dependency-capture overhead applied to every unit that runs, and in brackets
  without it (capture only on a sampled share of runs). Unit costs come from one measured run per unit,
  so "before" is constant across commits.
* **Sampling of very large suites**: Home Assistant (12% of test files: 776 units, 11 889 tests) and
  saleor (15%) use a fixed-seed sample of test files; the walk runs as 4 / 8 parallel shards over
  disjoint unit sets. Time to green schedules the sample on the same share of CI workers (same load per
  worker as the full suite).

## 2. Setting 1: large repositories

Skip shares MEASURED on the stated sample; time to green ESTIMATED (see method).

| project | lang | commits | units (sample) | rule | time skipped median / mean | tests skipped median / mean | time to green before -> after (no capture overhead), median / mean | commits invalidating everything (why) | verified skips (wrong, flaky) |
|---|---|---:|---|---|---:|---:|---|---|---|
| home-assistant | pytest | 20 | 776 (12%) | closure | 98% / 87% | 98% / 88% | 417s -> 35s (16s) / 417s -> 127s (60s) | 0/20 | 1046 (0, 0) |
| home-assistant | pytest | 20 | 776 (12%) | func+guard | 98% / 87% | 98% / 88% | 417s -> 35s (16s) / 417s -> 126s (59s) | 0/20 | 1046 (0, 0) |
| home-assistant | pytest | 20 | 776 (12%) | func (coverage-only) | 98% / 87% | 98% / 88% | 417s -> 35s (16s) / 417s -> 126s (59s) | 0/20 | 1046 (0, 0) |
| home-assistant | pytest | 20 | 776 (12%) | strict | 98% / 72% | 98% / 72% | 417s -> 35s (16s) / 417s -> 261s (122s) | 0/20 | 1046 (0, 0) |
| docusaurus | vitest | 50 | 202 (100%) | closure | 98% / 81% | 100% / 81% | 30s -> 3s (2s) / 30s -> 10s (6s) | 7/50 (config read 6, env var 1) | 829 (0, 0) |
| docusaurus | vitest | 50 | 202 (100%) | strict | 97% / 60% | 98% / 61% | 30s -> 4s (2s) / 30s -> 19s (13s) | 7/50 | 829 (0, 0) |
| vue-core | vitest | 50 | 185 (100%) | closure | 25% / 28% | 46% / 39% | 31s -> 37s (24s) / 32s -> 35s (23s) | 15/50 (config read 10, shared source 5) | 371 (0, 0) |
| vue-core | vitest | 50 | 185 (100%) | strict | 25% / 26% | 46% / 37% | 31s -> 37s (24s) / 32s -> 36s (23s) | 15/50 | 371 (0, 0) |
| terraform | go | 50 | 125 pkgs | go-cache | 72% / 61% | 80% / 73% | 95s -> 48s / 95s -> 68s | 0/50 | 697 (0, 0) |
| terraform | go | 50 | 125 pkgs | closure | 35% / 31% | 79% / 72% | 95s -> 95s / 95s -> 95s | 0/50 | 697 (0, 0) |
| prometheus | go | 20 | 90 pkgs | go-cache | 43% / 43% | 64% / 67% | 136s -> 118s / 136s -> 120s | 0/20 | 135 (0, 0) |

Observations:

* **Home Assistant** (MEASURED): 15 of 20 commits let at least 90% of test time be skipped; no commit
  forced everything. The repository is about a thousand integrations, each with tests that load the core
  plus one integration; most commits touch one integration. The coverage-only rule adds nothing over the
  proof (`func` = `closure`): on this shape of code the proof is not the bottleneck. The config rule costs
  15 points of mean (5 of 20 commits touched a strict-config file).
* **Docusaurus** (MEASURED): 39 of 50 commits skip at least 90%; 7 of 50 invalidate everything, 6 because
  a configuration file every test reads changed, 1 because an environment variable every test reads
  changed. 18 of 50 commits touch a strict-config file, hence the 21-point drop of the mean under `strict`.
* **vue-core** (MEASURED): a compact core (`runtime-core`, `shared`, `reactivity`) read by nearly every
  test file; 15 of 50 commits invalidate everything. Time to green does not improve: the capture overhead
  (x1.55, MEASURED) eats the saving, and even without it the longest units dominate (31 s -> 24 s).
* **Go** (MEASURED): the go test cache persisted across commits hits a median 72% (terraform) / 43%
  (prometheus) of package test time. **Ever wrong? No**: 697 + 135 verified hits, 0 wrong. On terraform
  222 of the verified hits were *potential* wrong hits (strace saw a file the test read change, and the go
  cache key did not include it); all 222 reproduced the cached outcome. Terraform's time to green is set by
  one long package that most commits invalidate, so `closure` (35%) gives no wall-time gain while
  `go-cache` halves the median.
* **saleor**: the Django test database makes every unit slow; 1 of 8 shards has reached 10 commits, the
  others their first commit. UNKNOWN until the walk ends (budget ends about 04:00 UTC).

## 3. Setting 2: commits inside pull requests opened by coding agents

Running or queued on GitHub Actions (runs r6 and r9): Codex PRs on openai-agents-python and vue-core,
Copilot coding agent PRs on github-mcp-server and typescript-go, Claude Code and other agent PRs on Home
Assistant. Each push of a PR is a transition from the previous push (first push: from the merge base).
UNKNOWN until the runs finish.

## 4. Setting 3: finer proof rule (module-level names actually read)

Rule `line+names` (`finer/names.py`): a module-level change no longer reruns every test that loaded the
module; the change is reduced to the names whose value changed, propagated through module-level code, and
a test reruns only if code it executed refers to one of those names (side-effecting module-level changes
stay "hard" and rerun every loader). Same 50 commits per library as the first study, same capture.

Time skipped per commit, median / mean in percent (MEASURED; 13 of 14 libraries, more-itertools still
running; "config (strict)" = commits touching a strict-config file):

| library | transitions | config (strict) | strict/closure | relaxed/closure | strict/file+guard | strict/line+guard | strict/line+names | strict/line (coverage-only) | relaxed/line+guard | relaxed/line+names | relaxed/line (coverage-only) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| arrow | 50 | 19 | 0/10 | 0/36 | 0/11 | 0/12 | 0/12 | 49/52 | 0/42 | 0/42 | 100/82 |
| attrs | 50 | 25 | 0/25 | 95/68 | 0/26 | 0/28 | 0/28 | 0/41 | 95/72 | 95/72 | 95/85 |
| boltons | 50 | 4 | 0/6 | 0/11 | 74/43 | 74/43 | 78/50 | 80/71 | 78/47 | 79/54 | 80/76 |
| click | 50 | 11 | 0/10 | 0/19 | 0/15 | 0/17 | 0/17 | 64/47 | 0/26 | 0/26 | 66/59 |
| flask | 46 | 13 | 0/27 | 0/44 | 0/31 | 0/31 | 0/33 | 96/64 | 89/52 | 95/54 | 97/88 |
| isort | 50 | 8 | 0/8 | 0/19 | 11/17 | 19/26 | 19/26 | 32/31 | 37/38 | 37/38 | 46/42 |
| jinja | 50 | 34 | 0/22 | 98/67 | 0/22 | 0/22 | 0/22 | 0/30 | 98/69 | 98/69 | 98/82 |
| marshmallow | 50 | 28 | 0/28 | 100/80 | 0/29 | 0/34 | 0/32 | 0/39 | 100/86 | 100/84 | 100/93 |
| pygments | 50 | 0 | 0/12 | 0/12 | 0/21 | 0/23 | 0/21 | 86/88 **1 wrong** | 0/23 | 0/21 | 86/88 **1 wrong** |
| sqlparse | 50 | 7 | 0/22 | 0/26 | 0/27 | 0/32 | 49/47 | 87/57 | 0/36 | 74/51 | 88/63 |
| structlog | 50 | 20 | 0/24 | 58/50 | 0/26 | 0/26 | 0/26 | 47/34 | 58/52 | 58/52 | 58/60 |
| toolz | 44 | 21 | 0/4 | 3/7 | 0/5 | 0/5 | 0/5 | 3/10 | 4/8 | 4/8 | 4/14 |
| werkzeug | 50 | 11 | 0/1 | 0/3 | 0/1 | 0/1 | 0/1 | 30/22 | 0/4 | 0/4 | 31/28 |
| **median of medians / mean of means** | | | 0/15 | 0/34 | 0/21 | 0/23 | **0/25** | 47/45 | 37/43 | 58/44 | 86/66 |

* **Gap recovered** (MEASURED, strict config rule, mean of means): proof `file+guard` 21%, coverage-only
  `line` 45%, a 24-point gap; `line+names` reaches 25%: it recovers **4 of 24 points (about 17%)**, 2 of
  them over `line+guard` (23%). Under the relaxed config rule: `line+guard` 43%, `line+names` 44%,
  coverage-only 66%: 1 of 23 points. Medians stay 0% under the strict rule.
* **pygments 7c196150 caught** (MEASURED): coverage-only `line` and `file` skip 2853 tests on that commit
  and get one wrong (`tests/examplefiles/fstar/example.fst`, whose expected output depends on a changed
  module-level table read through `tests/conftest.py`); `line+names` reruns them (0 skipped, 0 wrong). No
  variant with a guard or with the name rule had a wrong outcome on any library.
* **Where the gap is**: mostly not Python-level imprecision. It is (a) config commits (compare the
  strict and relaxed columns on attrs, jinja, marshmallow, structlog), and (b) small libraries where most
  commits edit the module every test reads, so the changed names are really read. A v2 of the name rule
  (signature changes act only on callers, dunders only on users of the class, guarded imports as
  bindings) is queued (run r7); this table will be replaced by its results.
* toolz: 94% of its test time (MEASURED) is in tests absent from the first study's determinism table
  (`harness/results/mixed/toolz.csv`), which every variant must rerun; by count `line` skips a median 64%.
  This rerun therefore under-states toolz for every rule alike (first study: `line` 59% / 48%); the
  comparison between rules on the same library is unaffected.

## 5. Setting 4: time to green and reruns

Time to green per commit: columns of section 2 (ESTIMATED from MEASURED unit costs). Headlines: Home
Assistant (sampled suite on proportional workers) 417 s -> 35 s median / 127 s mean with capture overhead,
16 s / 60 s without; docusaurus 30 s -> 3 s median; vue-core no gain; terraform 95 s -> 48 s median with
the go cache.

Reruns: the project's own CI test step, the same commit, repeated on fresh GitHub runners (MEASURED):

| suite | commit | runs | runs failed | of which flaky (pass on another run) | always failing | mean job min | test wall min - max |
|---|---|---:|---:|---:|---|---:|---|
| vue-core (vitest unit projects) | cbd95955 | 10 | 0 | 0 | - | 0.7 | - |
| terraform (`go test ./...`) | b3fb138b | 3 (7 queued) | 3 | 0 | the same 14 tests every run (environment: a read-only lockfile test run as root, gzip output) | 5.6 | 246 s - 370 s |
| docusaurus | 4c4ec4aa | 10, invalid | - | - | harness bug (reporter flag did not reach vitest); rerun queued (r8) | - | - |
| prometheus, saleor, home-assistant (3 of 10 CI groups) | | queued | | | | | |

No flaky failure in 13 valid runs so far (MEASURED). Terraform's identical 14 failures are environment
defects, not flakiness: deterministic, replayable. Test wall time of the same terraform commit varies from
246 s to 370 s across runners (MEASURED): a 50% spread with no code change.

## 6. Caveats

* Home Assistant and saleor use a 12% / 15% fixed sample of test files; shares are per sample. Home
  Assistant has 20 of 50 commits so far (walk still running).
* Unit costs are from one run each; time to green is a schedule simulation, not a measured CI wall.
* Docusaurus and vue-core suites are short (about 30 s of test time per commit on 4 workers): the skip
  share is high on docusaurus but the absolute minutes are small. The minutes are on suites shaped like
  Home Assistant.
* Go `closure` is stricter than the go cache (runtime reads included). The go cache was never wrong in
  this sample, but the sample is 832 verified hits on 2 projects.
* Pending on GitHub Actions (queue bounded by account concurrency): coding-agent PRs (setting 2), saleor,
  prometheus to 50 commits, the remaining reruns, and the name rule v2.
