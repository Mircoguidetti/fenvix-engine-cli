# Skip-with-proof study 2: where are the minutes?

**Status (2026-11-17 02:10 UTC): version 2, partial.** Final: setting 1 for docusaurus, vue-core,
terraform, prometheus (50 commits each) and Home Assistant (50 commits, 12% sample); setting 3 v1 (14
libraries); the verdict on the two verification mismatches (both flaky, 0 wrong hits). Partial: setting 2
(4 agent/repository pairs, 145 pushes; openai-agents-python, vue-core Codex and Home Assistant Claude Code
still running), setting 4 reruns (vue-core 10 runs and docusaurus 8 final; terraform 5 of 10, Home
Assistant 8 of 30 group runs), saleor (10 shard-complete commits), name rule v2 (6 of 14 libraries). Every
number is labelled. Raw data: `harness/skip_study2/results/<run>/`; summary:
`harness/skip_study2/results/summary.json`; tables: `python3 harness/skip_study2/aggregate.py --md`.

## Headline

Rule `closure` (proof: nothing the unit read changed) unless stated. "Verified skips" = skippable units
run anyway and compared with the cached outcome; "wrong" = a different outcome that reproduces and whose
cached outcome also reproduces at its own commit.

| setting | time skipped with proof per commit / push, median / mean | wrong hits (verified skips) | status | label |
|---|---|---|---|---|
| reference: first study, 14 small Python libraries | 0% / 22% | 0 | final | MEASURED |
| 1. home-assistant (pytest, 50 commits, 12% sample) | **98% / 85%** | 0 (2573) | final | MEASURED |
| 1. docusaurus (vitest, 50 commits) | **98% / 81%** | 0 (829) | final | MEASURED |
| 1. vue-core (vitest, 50 commits) | 25% / 28% | 0 (371) | final | MEASURED |
| 1. terraform (Go, go test cache as remote cache, 50 commits) | 72% / 61% (`closure` incl. runtime reads: 35% / 31%) | 0 (697) | final | MEASURED |
| 1. prometheus (Go, go test cache, 50 commits) | 56% / 52% | 0 (313) | final | MEASURED |
| 1. saleor (pytest + Django, 10 commits, 15% sample) | 0% / 9% (`func+guard` 0% / 16%) | 0 (7) | partial | MEASURED |
| 2. coding-agent PR pushes, all 145 pushes pooled | 75% / 54% (Go go-cache: 78% / 56%) | 0 (1097), 2 flaky | partial | MEASURED |
| 2. Copilot on github-mcp-server (15 PRs, 101 pushes) | 47% / 49% (go-cache 68% / 52%) | 0 (287) | partial | MEASURED |
| 2. Copilot on typescript-go (2 PRs, 20 pushes) | 30% / 54% | 0 (145) | partial | MEASURED |
| 2. Copilot on home-assistant (3 PRs, 12 pushes) | 100% / 95% | 0 (407), 2 flaky | partial | MEASURED |
| 2. Codex on home-assistant (3 PRs, 12 pushes) | 49% / 50% | 0 (258) | partial | MEASURED |
| 3. finer rule `line+names`, 14 libraries (strict config rule) | 0% / 25% (proof `file+guard` 0% / 21%; coverage-only `line` 48% / 46%) | 0; pygments 7c196150 caught | v1 final, v2 partial | MEASURED |
| 4. time to green per commit, before -> after, median | home-assistant 417 s -> 35 s; docusaurus 30 s -> 3 s; terraform 95 s -> 48 s; vue-core no gain | - | final | ESTIMATED (schedule of MEASURED unit costs) |
| 4. full CI reruns on one commit, attempts failed by flakiness | 0 of 31 (vue-core 0/10, docusaurus 0/8, terraform 0/5, home-assistant 0/8 group runs) | - | partial | MEASURED |

**Zero wrong hits holds** (MEASURED): 5 887 verified skips across settings 1 and 2, 0 wrong. The two
mismatches on the Home Assistant Copilot PRs are flaky outcomes, not missed dependencies (next section).

## The two verification mismatches: verdict

Both were a skipped unit whose cached outcome was a **failure** recorded at the PR's base commit and whose
fresh run at a later push passed. Re-check (local, 4 vCPU, Python 3.14.6, HA's `--timeout=9`; evidence in
`results/s1/recheck/*-local.json`; the GitHub Actions re-check job `recheck.py`, run s1, is still queued):

| unit (PR) | failing test | base commit, plain runs failed | PR commit, plain runs failed | traced (strace) runs failed | verdict |
|---|---|---|---|---|---|
| `tests/components/switchbot/test_init.py` (171334) | `test_exception_handling_for_device_initialization[...wrong model]`, error at teardown | 2 / 20 | 2 / 30 | not needed | **flaky test** (MEASURED) |
| `tests/components/knx/test_number.py` (163164) | `test_number_ui_load`: "No Telegram found. Expected: GroupValueRead - 2/0/0" | 0 / 20 | 0 / 20 | base 6 / 8 alone, 15 / 20 four at once; PR commit 6 / 8 alone, 6 / 12 four at once; import hooks without strace 0 / 8 | **failure caused by the capture** (MEASURED) |

* switchbot: the test passes, then the `hass` fixture teardown re-raises an exception from a background
  task the integration left running (PySwitchbot's lock update tries to connect to the mock BLE device,
  bleak's BlueZ backend raises `KeyError: 'path'`). Same error, same rate, at both commits. The push
  changed only `homeassistant/components/hassio/const.py`.
* knx: the test asserts that xknx's StateUpdater already sent its initial read when the telegram queue
  drains. Plainly it always has; under strace (syscalls slowed) it often has not. Same at both commits;
  the push changed only `homeassistant/components/zwave_js/cover.py`.
* **No dependency was missed; the proof rule does not change.** Two harness/product rules change:
  1. **A cached failure is never reused**: a unit whose last outcome was a failure always reruns (Bazel
     does the same). Both mismatches disappear; cost on these PRs: 1 to 3 failing units of 189 to 216.
  2. **A failure observed under dependency capture is confirmed by a plain rerun before it is recorded.**
     strace changes timing enough to flip a race (knx: 0% -> 75% failure). Product consequence: capture
     must be cheap enough not to perturb tests (in-process audit hooks, eBPF or fanotify instead of
     ptrace), or the recorded outcome must come from a plain run.
* The aggregator now applies re-check verdicts: a mismatch whose cached outcome does not reproduce at
  its own commit counts as flaky, not wrong.

## 0. Question and answer

The first study (`docs/CACHE-SKIP-STUDY.md`, 14 small Python libraries x 50 commits) found that a median
0% / mean 22% of test time per commit could be skipped **with proof**. Where are the skippable minutes?

Answer: **in large repositories made of many loosely coupled parts, and in the pushes of coding agents.**
Home Assistant 98% median (MEASURED), Docusaurus 98% (MEASURED). Tightly coupled code skips little even
when large: vue-core 25%, saleor 0% (Django loads every app in every test process) (MEASURED). In Go the
toolchain's own test cache, used as a remote cache across commits, skips 56-72% median and was never
wrong on 1 010 verified hits (MEASURED). Coding-agent PRs: a median 75% / mean 54% of test time per push
(MEASURED, 145 pushes, partial).

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

Skip shares MEASURED on the stated sample; time to green ESTIMATED (see method). Go `strict` = go cache plus
the config rule (it is not a subset of Go `closure`, which adds runtime reads).

| project | lang | transitions | units (sample) | rule | time skipped median / mean | tests skipped median / mean | time to green before -> after (after without capture overhead), median / mean | invalidate all (why) | verified skips (wrong, flaky) |
|---|---|---:|---|---|---:|---:|---|---|---|
| docusaurus | vitest | 50 | 202 (100%) | closure | 98% / 81% | 100% / 81% | 30s -> 3s (2s) / 30s -> 10s (6s) | 7/50 (read:config 6, read:env 1) | 829 (0, 0) |
| docusaurus | vitest | 50 | 202 (100%) | strict | 97% / 60% | 98% / 61% | 30s -> 4s (2s) / 30s -> 19s (13s) | 7/50 (read:config 6, read:env 1) | 829 (0, 0) |
| home-assistant | pytest | 50 | 776 (12%) | closure | 98% / 85% | 98% / 85% | 417s -> 35s (16s) / 417s -> 142s (67s) | 0/50 (-) | 2573 (0, 0) |
| home-assistant | pytest | 50 | 776 (12%) | func+guard | 98% / 85% | 98% / 85% | 417s -> 35s (16s) / 417s -> 142s (66s) | 0/50 (-) | 2573 (0, 0) |
| home-assistant | pytest | 50 | 776 (12%) | func | 98% / 89% | 98% / 90% | 417s -> 35s (16s) / 417s -> 106s (50s) | 0/50 (-) | 2573 (0, 0) |
| home-assistant | pytest | 50 | 776 (12%) | strict | 97% / 67% | 97% / 67% | 417s -> 35s (16s) / 417s -> 299s (140s) | 0/50 (-) | 2573 (0, 0) |
| prometheus | go | 50 | 90 (100%) | go-cache | 56% / 52% | 84% / 73% | 135s -> 118s (118s) / 135s -> 118s (118s) | 0/50 (-) | 313 (0, 0) |
| prometheus | go | 50 | 90 (100%) | closure | 56% / 52% | 84% / 73% | 135s -> 118s (118s) / 135s -> 118s (118s) | 0/50 (-) | 313 (0, 0) |
| prometheus | go | 50 | 90 (100%) | strict | 52% / 48% | 82% / 67% | 135s -> 118s (118s) / 135s -> 119s (119s) | 0/50 (-) | 313 (0, 0) |
| saleor | pytest | 10 | 112 (15%) | closure | 0% / 9% | 0% / 8% | 289s -> 819s (289s) / 289s -> 746s (263s) | 9/10 (listing:data 4, py-source:source 4, read:config 1) | 7 (0, 0) |
| saleor | pytest | 10 | 112 (15%) | func+guard | 0% / 16% | 0% / 16% | 289s -> 819s (289s) / 289s -> 687s (243s) | 9/10 (listing:data 4, py-source:source 4, read:config 1) | 7 (0, 0) |
| saleor | pytest | 10 | 112 (15%) | func | 32% / 38% | 37% / 40% | 289s -> 559s (197s) / 289s -> 506s (179s) | 9/10 (listing:data 4, py-source:source 4, read:config 1) | 7 (0, 0) |
| saleor | pytest | 10 | 112 (15%) | strict | 0% / 9% | 0% / 8% | 289s -> 819s (289s) / 289s -> 746s (263s) | 9/10 (listing:data 4, py-source:source 4, read:config 1) | 7 (0, 0) |
| terraform | go | 50 | 125 (100%) | go-cache | 72% / 61% | 80% / 73% | 95s -> 48s (48s) / 95s -> 68s (68s) | 0/50 (-) | 697 (0, 0) |
| terraform | go | 50 | 125 (100%) | closure | 35% / 31% | 79% / 72% | 95s -> 95s (95s) / 95s -> 95s (95s) | 0/50 (-) | 697 (0, 0) |
| terraform | go | 50 | 125 (100%) | strict | 66% / 57% | 78% / 69% | 95s -> 48s (48s) / 95s -> 70s (70s) | 0/50 (-) | 697 (0, 0) |
| vue-core | vitest | 50 | 185 (100%) | closure | 25% / 28% | 46% / 39% | 31s -> 37s (24s) / 32s -> 35s (23s) | 15/50 (read:config 10, read:source 5) | 371 (0, 0) |
| vue-core | vitest | 50 | 185 (100%) | strict | 25% / 26% | 46% / 37% | 31s -> 37s (24s) / 32s -> 36s (23s) | 15/50 (read:config 10, read:source 5) | 371 (0, 0) |

Observations:

* **Home Assistant** (MEASURED, 50 commits): 35 of 50 commits let at least 90% of test time be skipped;
  no commit forced everything. The repository is about a thousand integrations, each with tests that load
  the core plus one integration; most commits touch one integration. The coverage-only rule adds 4 points
  of mean over the proof (`func` 89% vs `closure` 85%): on this shape of code the proof is not the
  bottleneck. The config rule costs 18 points of mean (14 of 50 commits touched a strict-config file).
* **Docusaurus** (MEASURED): 39 of 50 commits skip at least 90%; 7 of 50 invalidate everything, 6 because
  a configuration file every test reads changed, 1 because an environment variable every test reads
  changed. 18 of 50 commits touch a strict-config file, hence the 21-point drop of the mean under `strict`.
* **vue-core** (MEASURED): a compact core (`runtime-core`, `shared`, `reactivity`) read by nearly every
  test file; 15 of 50 commits invalidate everything. Time to green does not improve: the capture overhead
  (x1.55, MEASURED) eats the saving, and even without it the longest units dominate (31 s -> 24 s).
* **Go** (MEASURED): the go test cache persisted across commits hits a median 72% (terraform) / 56%
  (prometheus, 50 commits) of package test time. **Ever wrong? No**: 697 + 313 verified hits, 0 wrong. On terraform
  222 of the verified hits were *potential* wrong hits (strace saw a file the test read change, and the go
  cache key did not include it); all 222 reproduced the cached outcome. Terraform's time to green is set by
  one long package that most commits invalidate, so `closure` (35%) gives no wall-time gain while
  `go-cache` halves the median.
* **saleor** (MEASURED, 10 commits reached by every finished shard, 15% sample; partial): 9 of 10 commits
  invalidate everything (a data directory listing changed 4, a shared Python source changed 4, a config
  file read 1). Django loads the whole project (settings, every app's models) in every test process, so
  every test reads nearly every module. Even coverage-only `func` skips only 32% / 38%. The capture
  overhead is x2.8 (MEASURED), so with capture on every run the time to green gets worse. Shards 0-5 have
  10-30 commits, shards 6-7 started at 01:45 UTC; the walk ends about 07:30 UTC.

## 3. Setting 2: commits inside pull requests opened by coding agents

Each push of an agent PR is a transition from the previous push; the PR's base commit runs every unit
first (MEASURED; Home Assistant on its 12% sample; Go packages in full):

| repository : agent | PRs | pushes | rule | time skipped per push median / mean | verified (wrong, flaky) |
|---|---:|---:|---|---:|---|
| github-mcp-server:copilot | 15 | 101 | go-cache | 68% / 52% | 287 (0, 0) |
| github-mcp-server:copilot | 15 | 101 | closure | 47% / 49% | 287 (0, 0) |
| github-mcp-server:copilot | 15 | 101 | strict | 14% / 43% | 287 (0, 0) |
| home-assistant:codex | 3 | 12 | closure | 49% / 50% | 258 (0, 0) |
| home-assistant:codex | 3 | 12 | strict | 0% / 41% | 258 (0, 0) |
| home-assistant:copilot | 3 | 12 | closure | 100% / 95% | 407 (0, 2) |
| home-assistant:copilot | 3 | 12 | strict | 100% / 95% | 407 (0, 2) |
| typescript-go:copilot | 2 | 20 | go-cache | 30% / 54% | 145 (0, 0) |
| typescript-go:copilot | 2 | 20 | closure | 30% / 54% | 145 (0, 0) |
| typescript-go:copilot | 2 | 20 | strict | 30% / 54% | 145 (0, 0) |

* Pooled over the 145 pushes: `closure` median 75% / mean 54%; with the go cache for the Go repositories
  78% / 56% (MEASURED). The distribution is two-humped (github-mcp-server p25 4%, p75 87%): a push either
  touches something every test reads or almost nothing.
* Home Assistant Copilot PRs are small, single-integration fixes: a median push skips 100%. Codex PRs on
  Home Assistant touch shared code more often: 49%.
* The 2 flaky verifications are the two mismatches above.
* Still running (partial): Codex on openai-agents-python (relaunched in run s1 after a walker fix: these
  PRs target a non-default branch), Codex on vue-core, more Copilot on typescript-go, Claude Code on Home
  Assistant (run r9).

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
  bindings) is running (run r7). On the 6 libraries finished so far (arrow, attrs, boltons, click, flask,
  jinja) v2 gives the same `strict/line+names` medians/means as v1 except attrs (28% -> 24% mean: v2 is more
  conservative there) (MEASURED); the table above stays v1 until v2 finishes on all 14.
* toolz: 94% of its test time (MEASURED) is in tests absent from the first study's determinism table
  (`harness/results/mixed/toolz.csv`), which every variant must rerun; by count `line` skips a median 64%.
  This rerun therefore under-states toolz for every rule alike (first study: `line` 59% / 48%); the
  comparison between rules on the same library is unaffected.

## 5. Setting 4: time to green and reruns

**Time to green per commit** (ESTIMATED: longest-first schedule of MEASURED unit costs on the project's CI
workers; "after" with the MEASURED capture overhead on every unit that runs, in brackets without it):

| project | rule | before | after, median | after, mean |
|---|---|---:|---:|---:|
| home-assistant (12% sample on 12% of the workers) | closure | 417 s | 35 s (16 s) | 142 s (67 s) |
| docusaurus | closure | 30 s | 3 s (2 s) | 10 s (6 s) |
| vue-core | closure | 31 s | 37 s (24 s) | 35 s (23 s) |
| terraform | go-cache | 95 s | 48 s | 68 s |
| prometheus | go-cache | 135 s | 118 s | 118 s |
| saleor (15% sample) | closure | 289 s | 819 s (289 s) | 746 s (263 s) |

Where most units are skipped (Home Assistant, docusaurus) time to green falls 10x at the median. Where
one long unit is usually invalidated (prometheus, terraform's longest package) or nothing is skippable
(saleor), it barely moves, and the capture overhead (x1.55 vitest, x2.8 saleor, MEASURED) makes it worse
unless capture runs only on a sample of runs.

**Reruns**: the project's own CI test step, the same commit, repeated on fresh GitHub runners. An attempt
"fails from flakiness" when it fails a test that does not fail in every attempt of that group (MEASURED):

| suite (commit) | CI groups rerun (of) | tests per group run | attempts (min per group) | attempts failed by flakiness | tests failing in every attempt | flaky full-run rate | mean job min | flaky tests |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| docusaurus (4c4ec4aa) | 1 (1) | 3254 | 8 (8) | 0 | 0 | 0% | 1.5 | - |
| terraform (b3fb138b) | 1 (1) | 12462 | 5 (5) | 0 | 14 | 0% | 5.6 | - |
| vue-core (cbd95955) | 1 (1) | 4152 | 10 (10) | 0 | 0 | 0% | 0.7 | - |
| home-assistant (cdf3f923) | 3 (10) | 11026 | 8 (2) | 0 | 0 | 0% | 8.4 | - |

* **0 flaky failures in 31 valid attempts so far** (MEASURED): vue-core 10 full runs, docusaurus 8 full
  runs, terraform 5 full runs, Home Assistant 8 runs of 3 of its 10 CI groups (11 026 tests each).
* terraform fails the **same 14 tests in every run** (MEASURED): environment defects (a lockfile test run
  as root, gzip output), deterministic and replayable, not flaky. Test wall time of that one commit spans
  246 s - 370 s across runners (MEASURED): a 50% spread with no code change.
* Partial: terraform repetitions 5-9 (run s2), Home Assistant 22 more group runs (to 10 per group),
  docusaurus 2 more. Prometheus and saleor reruns were cancelled (run r2) to free runners for the
  mismatch re-check; saleor full-suite reruns cost hours each.
* What the reruns say so far: on these suites, at these commits, flakiness is rarer than 1 in 31 attempts
  (UNKNOWN beyond that). The flaky outcomes this study did see came from the study's own runs: a
  teardown race in switchbot (10% of plain runs, MEASURED) and a timing race in knx that only strace
  triggers.

## 6. Caveats

* Home Assistant and saleor use a 12% / 15% fixed sample of test files; shares are per sample.
* Unit costs are from one run each; time to green is a schedule simulation, not a measured CI wall.
* Docusaurus and vue-core suites are short (about 30 s of test time per commit on 4 workers): the skip
  share is high on docusaurus but the absolute minutes are small. The minutes are on suites shaped like
  Home Assistant.
* Go `closure` is stricter than the go cache (runtime reads included). The go cache was never wrong in
  this sample: 1 010 verified hits on 2 projects.
* The mismatch re-check ran locally (4 vCPU container), not on GitHub runners; the same re-check on
  GitHub Actions (run s1, `recheck.py`) is queued behind the account's concurrency limit.
* Agent PRs: 145 pushes, 101 of them from one repository (github-mcp-server); pooled numbers lean on it.
