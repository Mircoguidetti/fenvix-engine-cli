PARTIAL

# P-022 · JVM track: Level 0 and skip with proof for Java and Kotlin — final report

Work session P-022. Engine: fenvix-engine-cli, branch `claude/jvm-l0` (from `origin/claude/node-l0`). Docs: `docs/JVM.md`. Intermediate: `INTERMEDIATE-1.md` (this folder).

**Why PARTIAL:** everything in the prompt is built and tested, and every measurement ran, but the GitHub Actions share is smaller than asked because the account's runners were held for hours by other sessions' long matrices: the IDoFT round has **10 projects measured on GitHub Actions** (prompt: 15-25) plus **28 in this session's container**, and the skip walk has **6 of 7 repositories complete on GitHub Actions** (retrofit still running when this was written; jsoup measured in the container). The GitHub Actions IDoFT round on the final agent (12 projects, run 44424494082) was still queued. All numbers below say where they come from.

## 1. Numbers against the prompt

| item | result | label |
|---|---|---|
| 1. JNI crate `crates/fenvix-jvm` over detpy-core | built (jni-rs 0.21; Panama not used: the projects need Java 8-21); same events, BLAKE3 fingerprints, JSONL trace format, verifier; 2 crate tests + detpy-core tests green on GitHub Actions | MEASURED |
| 2. Shell: `-javaagent` (ASM 9.8, shaded) + JUnit Platform listener + JUnit 4 hooks + Gradle init-script plugin + Maven core extension, `--det` | control tests on **GitHub Actions** (run 44428628118): JDK 21: **40/40** Gradle and Maven (JUnit 5), **10/10** and **10/10** (JUnit 4); JDK 11: 38/38, 38/38, 10/10, 10/10; JDK 8: 37/38 Gradle (one weak control: `nanoTimeDelta` happened to be equal in both runs *without* `--det`), 38/38 Maven, 10/10, 10/10; JDK 17: all jobs green, result file lost by the workflow's copy step (fixed). In every case the two `--det` runs verify with **identical fingerprints for every test**; `--det-seed=5` reproduces its order and differs from seed 0. Same suite in the container on the final agent: 40/40, 40/40, 10/10, 10/10 | MEASURED |
| 3. Skip with proof key per test | built: classes executed or whose statics were accessed (+ class-file digests), static-field dependencies between tests, files read/probed/listed, classpath resources, env vars, system properties, external network, runtime identity, configuration | built |
| 4. Tests for every control and every skip-key input | controls as above; skip keys **12/12 scenarios** on GitHub Actions and in the container | MEASURED |
| 5a. IDoFT round | see §2: GitHub Actions 10 projects; container 28 projects | MEASURED |
| 5b. Skip walk, 50 commits | see §3: **0 wrong reuses in 5,731,740 verified reuses** on GitHub Actions (6 repositories), 0 wrong in 71,952 (jsoup, container, final agent) | MEASURED |
| Threads, Kotlin coroutines (measure only) | §4 | MEASURED |

## 2. IDoFT round (5a)

Protocol (`jvm/harness/jvm_harness.py`), per project, Maven module of the IDoFT row, JDK 8 → 11 → 17 (first that builds): 10 baseline runs with a realistic random order (Surefire `runOrder=random`, Jupiter `MethodOrderer$Random`, a new seed per run), 10 `--det` runs (seed 0), seeds 1-20, 10/10 confirmation of the first failing configuration, 3+3 quiet timing runs. **Reproduced** = fails 10/10 with one fingerprint under one `--det` configuration and passes under another. **Broken by `--det`** = fails in ≥1 seed-0 run, in ≤1 baseline run, and more often than in the baseline (the Python definition). Candidates: 132 IDoFT Maven projects with OD / OD-Vic / OD-Brit / NOD / TD / NDOD / NIO tests (ID = NonDex left out); giants (Hadoop, HBase, ...) excluded.

**Totals** (MEASURED; timings NOISY):

| set | projects | tests | documented tests reproduced | baseline-unstable reproduced | broken by `--det` | fingerprint coverage | slowdown, median of projects |
|---|---|---|---|---|---|---|---|
| GitHub Actions (run 44385794604, agent 4f04c14) | 10 | 7,678 | **94/469 = 20.0%** | **59/94 = 62.8%** | 22 | 7,777/7,914 = 98.3% | +4.1% |
| session container (agents up to b229d6b) | 28 | 12,226 | **171/542 = 31.5%** | **63/105 = 60.0%** | 35 → **29** after the last fixes | 11,871/12,396 = 95.8% | -3.2% (23 projects with a timing pass) |

How to read it:
* The documented-test share is dominated by categories Level 0 is not meant to reproduce by reordering: **NIO** (non-idempotent outcome: fails when run twice in one JVM; junit-quickcheck alone has 118), **TD/NDOD** on Java-WebSocket (54, real sockets and threads), NOD. On **order-dependent** documented tests the shell does well: Mapper-base **67/70**, ormlite-core **85/87** (container, final agent; 26/87 on GitHub Actions with the older agent 4f04c14), marine-api 12/12 (container, early run), wikidata-toolkit 3/3, seata 2/2, aismessages 2/2.
* Baseline-unstable tests reproduced: 60-63%, concentrated: Mapper-base 37/40, openhtmltopdf 15/15, seata 10/10 (container); Java-WebSocket 0/26 (sockets and threads: Level 1 and real I/O).
* JUnit 4 baselines randomise class order only (JUnit 4 has no method shuffle), so most documented OD tests are stable in the baseline (72 of 542 documented tests unstable there) and reproduced only through the seeded method shuffle.
* ormlite 85/87 vs 26/87 is the effect of the fixes between agent 4f04c14 and the final agent (leaked-thread events out of fingerprints, sleep and timer rules); the GitHub Actions rerun on the final agent (run 44424494082) was still queued.

Per project (container unless marked; documented reproduced / present; baseline-unstable reproduced / unstable; broken before → after the last fixes; fingerprint coverage; slowdown NOISY):

| project | tests | documented | baseline-unstable | broken | coverage | slowdown |
|---|---|---|---|---|---|---|
| Mapper-base | 206 | 67/70 | 37/40 | 0 | 206/206 | +24.4% |
| ormlite-core | 1,220 | 85/87 | 0/0 | 0 | 1,219/1,220 | +7.9% |
| openhtmltopdf-examples | 258 | 3/34 | 15/15 | 1 → 1 | 258/258 | +10.7% |
| incubator-seata common | 552 | 2/2 | 10/10 | 34 → **0** | 551/552 | -32.8% |
| wikidata-toolkit dumpfiles | 50 | 3/3 | 0/0 | 0 | 49/50 | +16.4% |
| aismessages | 44 | 2/2 | 0/0 | 0 | 44/44 | +5.1% |
| junit-quickcheck core | 484 | 3/122 (118 NIO) | 0/0 | 0 | 734/734 | -32.5% |
| json-iterator (java) | 347 | 4/19 | 0/0 | 10 → 10 | 333/333 | -55.3% |
| fastjson | 4,464 | 1/19 | 0/1 | 1 → 1 | 4,453/4,464 | n/a |
| asyncload | 59 | 1/1 | 0/0 | 5 → **1** | 36/59 | -34.2% |
| hutool core | 1,077 | 0/2 | 1/1 | 0 | 1,076/1,077 | -8.7% |
| java-cas-client core | 154 | 0/1 | 0/8 | 2 → **0** | 143/154 | -17.3% |
| mTracker core | 38 | 0/2 (NIO) | 0/0 | 2 → **0** | 38/38 | -39.7% |
| Java-WebSocket | 146 | 0/54 (TD, NDOD) | 0/26 | 5 | 55/146 | n/a |
| http-request lib | 163 | 0/28 | 0/0 | 0 | 121/163 | +9.0% |
| avro ipc-jetty | 35 | 0/20 | 0/0 | 0 | 26/35 | -1.9% |
| spring-ws core | 971 | 0/16 | 0/0 | 0 | 893/971 | -28.0% |
| biojava structure | 355 | 0/16 (NOD) | 0/0 | 1 → 1 | 355/355 | -91.5% |
| wro4j core | 850 | 0/15 | 0/0 | 3 | 838/850 | +3.5% |
| servicecomb generator-core | 50 | 0/15 | 0/0 | 0 | 50/50 | -59.8% |
| c2mon daq-core | 125 | 0/2 | 0/0 | 2 → 2 | 23/125 | +8.6% |
| cat client | 67 | 0/2 | 0/3 | 1 → 1 | 29/67 | +25.0% |
| luwak | 202 | 0/2 | 0/0 | 2 → 2 | 165/202 | -3.2% |
| tyrus non-deployable | 66 | 0/2 | 0/0 | 1 → 1 | 0/0 | n/a |
| easyexcel | 108 | 0/2 | 0/0 | 0 | 107/108 | n/a |
| oci-java-sdk objectstorage-ext | 62 | 0/2 | 0/0 | 0 | 60/62 | -73.3% |
| excelastic | 12 | 0/1 | 0/1 | 1 | 9/12 | +213.5% |
| vertx-completable-future | 61 | 0/1 | 0/0 | 0 | 0/61 | n/a |

(mercury platform-core excluded: two local loops ran it at the same time into one output folder.) GitHub Actions rows (agent 4f04c14): Mapper-base 58/70 & 58/70, ormlite 26/87, fastjson 3/19, java 4/19, junit-quickcheck 3/122, Java-WebSocket 0/54, biojava 0/16 (broken 8), openhtmltopdf 0/34, avro 0/20, http-request 0/28; files `jvm/harness/results/idoft/`.

**Tests broken by `--det`, causes after the fixes** (29 in the container set; MEASURED by a recheck of 10 `--det` runs on the final agent against the recorded baseline, `--mode recheck`):
* **order (not Level 0)**: json-iterator 10 — they also fail with no agent at all in plain alphabetical class order (63 failures there; order-only ablation: the same 41 failures as full `--det`). Order-dependent tests exposed by the fixed order.
* **time of day at the fixed epoch**: fastjson `Bug_for_cnhans.test_iso_format` (ISO date round trip in Asia/Shanghai fails at 2025-01-01T00:00Z): a real time-of-day dependency, always hit at the fixed epoch.
* **closed network**: biojava `testStructureWithBranchedEntities` (fetches PDB files) — as designed (allow-host).
* **threads / real-time timers (Level 1, limit V4)**: c2mon `AliveTimerTest`, `DiffMovingAverageTest` (NDOD), luwak `TestCachePurging` (2), cat `CatFilterTest`, asyncload `testSingleton` (1 of 5 left), Java-WebSocket 5 (socket timing), excelastic 1, wro4j 3 (not classified).
* **other**: tyrus "Test mechanism" (a JVM-level error under `--det`, not classified), openhtmltopdf FreeMarker (already 1/10 in the baseline).

Fixes made during the round, each found on a real project and each covered by a fixture or a recheck: JDK 8 support; `@{argLine}` with skipped JaCoCo (junit-quickcheck: test JVM did not start); JDK `tools.jar` never rewritten (seata: Mockito's self-attach, **34 → 0**); file timestamps on the virtual clock (mTracker, **2 → 0**); concurrent sleeps overlap on the clock and a thread sleeping for real counts as working (marine-api); leaked threads' events out of later fingerprints (marine-api: 63 unstable fingerprints); JUnit 4 seeded order cached (marine-api: seed runs 5x slower); pending JDK timers count as work and a sleep never outlasts another thread's earlier timeout (java-cas-client **2 → 0**, asyncload **5 → 1**).

## 3. Skip with proof over 50 commits (5b)

Protocol (`jvm/harness/skip_walk.py`): for each commit (first-parent history before 2026-11-15), the whole suite runs with `--det --deps`; for each transition the proof rule (`jvm/skip/fenvix_skip.py`) decides from the previous capture which tests could have been reused, and **every reuse is checked against that commit's fresh outcome**; a reused test that does not pass is rerun twice alone (pass + fail = flaky, otherwise wrong).

**GitHub Actions** (run 44366300378, agent b33874c; 5 shards per repository):

| repository | tool | transitions | tests | test time skipped with proof, median / mean | tests skipped, median | verified reuses | wrong | flaky | not verifiable | top rerun reasons |
|---|---|---|---|---|---|---|---|---|---|---|
| commons-lang | Maven | 50 | 107,583 | **98% / 91%** | 99% | 5,133,250 | **0** | 37 | 0 | code, prop, after |
| commons-io | Maven | 50 | 2,102 | **100% / 88%** | 99% | 98,563 | **0** | 0 | 0 | config, runtime, code |
| jackson-databind | Maven | 48 | 7,803 | **93% / 66%** | 98% | 276,259 | **0** | 0 | 0 | code, runtime |
| gson | Maven | 50 | 4,641 | **76% / 63%** | 89% | 163,138 | **0** | 0 | 0 | runtime, code, config |
| mockito | Gradle | 50 | 2,660 | **34% / 27%** | 6% | 7,863 | **0** | 0 | 21 | config, code |
| moshi (Kotlin) | Gradle | 50 | 1,521 | **19% / 14%** | 96% | 52,667 | **0** | 0 | 1 | runtime, config, code |
| **all** | | 298 | | | | **5,731,740** | **0** | 37 | 22 | |

Container, final agent: **jsoup** (Maven) 50 transitions, **77% / 57%**, 71,952 verified, **0 wrong**, 0 not verifiable; gson again 84% / 65%, 171,571 verified, 0 wrong.

How to read it:
* **0 wrong** in 5.7 M verified reuses on GitHub Actions and 0 in the final-agent container walks. The 37 flaky are all commons-lang `MultiBackgroundInitializer*Test` (a busy-wait on `System.currentTimeMillis` while background threads start: the adaptive tick ran past their 3 s deadline under load); fixed afterwards (limit V16) and those tests pass 5/5 under `--det` with the machine loaded. The local commons-lang walk on an older agent had 4 of them counted wrong (reruns also failed); same cause.
* **Not verifiable (22)**: reuses whose fresh record had no outcome (the capture lost a test's end event when JUnit parallel execution or event interleaving split a test scope). Fixed in the capture (tests never nest; Jupiter parallelism forced off under `--det/--deps`), never counted as right; jsoup on the final agent: 0.
* **Gradle (mockito, moshi) skips much less**: most reruns have reason `config` (and `runtime` on moshi): the test-task configuration / class-path key changes on most commits. Which entry changes is UNKNOWN (that walk recorded reason counts only; per-entry details were added afterwards; mockito cannot be built in this container: its JDK 25 toolchain download is blocked). Conservative (more reruns), never wrong; next step for the coordinator's list.
* `runtime` reruns on Maven repositories are mostly plugin-version bumps (dependabot): plugin versions are in the key, as the prompt asks.

**Comparisons** (the per-module column of the walk):
* **Gradle build cache for test tasks** (per task, not per test): ESTIMATED model = a module's tests are reused only when every output file of the module and its jar list are unchanged. mockito: model 98% / 76% vs proof rule 34% / 27%; moshi: 56% / 54% vs 19% / 14% — on these Gradle repositories the proof rule currently loses to the coarse model because of the `config` key above. On Maven repositories the model column of the GitHub Actions run is **invalid** (Surefire's class path is a booter jar; fixed afterwards): with the fixed model the per-module cache skips 0% median on gson and jsoup (any code change invalidates the single module) vs 84% / 77% median for the proof rule (container, MEASURED).
* **Develocity Predictive Test Selection**: a machine-learning model trained on historical builds that predicts which tests are relevant; it always selects recently flaky tests (DECLARED, Develocity docs via search excerpts, docs.gradle.com 2026.2; the page itself is not reachable from this container). It is a prediction, not a proof: Meta's original paper states the selection is approximate and can miss tests that would detect regressions (DECLARED, arXiv 1810.05286). fenvix's rule reuses only with an unchanged key and verified 5.7 M reuses with 0 wrong.

## 4. Level 1, measured only (threads, Kotlin coroutines)

GitHub Actions, 10 runs each (MEASURED): unsynchronized counter race fails 7/10 without `--det`, 10/10 with (1 fingerprint: Level 0 does not order threads; the interleaving decides); completion order of a thread pool 10/10 and 10/10; Kotlin `Dispatchers.Default` race 10/10 and 10/10 with 9 distinct fingerprints; `runBlocking`+`delay`, `runTest` virtual time, `withTimeout`: 0 failures either way (1, 1 and 3 fingerprints). Build+test seconds (NOISY): median 8.9 s without, 9.7 s with `--det`. Reading: coroutines on the default dispatcher are threads (Level 1); `runTest` already has its own virtual time.

## 5. What I decided and why

* Bytecode call-site rewriting for clocks and sleeps (code under test only, the runner keeps real time; sites known at rewrite time), JDK method hooks for randomness, filesystem and network (JDK-internal callers covered: `UUID.randomUUID`, `Files.walk`, `HttpClient`). Every `SecureRandom` is seeded under `--det` (Python and Node only observe OS entropy).
* jni-rs, Java 8 bytecode: IDoFT projects are Java 8 era; most rounds ran on JDK 8.
* Gradle: init-script plugin; Maven: core extension rewriting Surefire's configuration in memory (keeps the project's argLine).
* JUnit 4 supported natively (hooks in `RunNotifier` and `ParentRunner`).
* Sleep/timer semantics favour correctness: a timer or sleep is fast only when no other thread works and no other thread's timeout would expire first; JDK timers count as work. Several real projects needed this (§2).
* Dependency or class-path changes are global in the proof rule (configuration key): conservative.
* Runner shortage: instead of waiting, the IDoFT round and two walks also ran in the container (4 CPUs, JDK 8/11/17 from Ubuntu packages); every table says which.

## 6. What blocks or is missing

* GitHub Actions share below the prompt (§ top): IDoFT 10 projects on GitHub Actions (+28 container); final-agent IDoFT rerun (run 44424494082, 12 projects) and the retrofit walk shards were still queued/running. `jvm/harness/results/idoft/` and `.../skip/` will fill as they finish (each job commits its results).
* Gradle skip rate: the `config` key changes on most mockito/moshi commits (UNKNOWN entry; to investigate with the per-entry details the walk now records).
* Not built: network record/replay for the JVM (V5); virtual time for `java.util.Timer`, `new ScheduledThreadPoolExecutor`, Netty/Reactor (V4: they keep real time, and now sleeps wait for them); identity-hash control (V10; measured and documented); Gradle + JUnit 4 class order (V7).
* `FileTimeTest` (2 unchanged-type control tests) did not report on JDK 8/11 in CI (38 instead of 40 checks; UNKNOWN why; JDK 21: 40/40).

## 7. Links

* Branch: https://github.com/Mircoguidetti/fenvix-engine-cli/tree/claude/jvm-l0 (no PR opened).
* Code: `crates/fenvix-jvm/`, `jvm/rt/` (runtime), `jvm/agent/` (agent, JUnit, CLI), `jvm/gradle/fenvix.init.gradle`, `jvm/maven-ext/`, `jvm/skip/fenvix_skip.py`, `docs/JVM.md` (controls, skip key, limits V1-V18).
* Tests: `jvm/test/run_controls.py`, `run_skipkeys.py`, `run_l1_measure.py`, fixtures `jvm/fixtures/`; CI results `jvm/test/results/ci/`.
* Rounds: `jvm/harness/jvm_harness.py` (+ `--mode recheck`), `skip_walk.py`, workflows `.github/workflows/jvm-tests.yml`, `jvm-harness.yml`, `jvm-skip-walk.yml`; results `jvm/harness/results/idoft/` (GitHub Actions), `idoft-local/` (container), `skip/` (GitHub Actions), `skip-local/` (container).

## 8. Errors or gaps found in this brain

* ARCHITECTURE.md: header meta `runtime` lists `python` or `node`; the JVM writes `jvm`, and `runner` = `junit-jupiter`, `junit-vintage`, `junit4`. JVM test ids: `docs/JVM.md`.
* Coordination: one GitHub account's runners are shared by all sessions; long matrices (6-hour jobs) starve the others for hours. A per-session `max-parallel` budget, or a queue order agreed in NOW.md, would help.
