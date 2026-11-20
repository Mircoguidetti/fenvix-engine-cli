FIX 17

# R-022 · Review of the JVM track (P-022, branch `claude/jvm-l0`)

Reviewer session, 2026-11-19. Branch `claude/review-r022` = `claude/jvm-l0` (1b9b211) + review input + this review. Input: `review-input/REPORT.md` (P-022, PARTIAL) and `review-input/P-022-jvm-l0.md`.
Everything below was run in this session's container (4 CPUs, OpenJDK 21.0.13, Gradle 8.14.3, Maven, cargo); labels as in the brain (MEASURED / ESTIMATED / DECLARED / UNKNOWN).

**Verdict: FIX 17.** The skip-with-proof key **does** reuse results it should not: 11 independent inputs change a test's outcome without changing its key, each shown by a committed scenario where the reused test **fails** in the fresh run of the same state. The 0 wrong in 5,731,740 verified reuses is reproduced from the committed data, but the walk only exercises the inputs that 50 ordinary commits change; it cannot see these. Under `--det`, 4 engine defects were found (three of them explain 12 of the 25 container "broken by --det" tests, which the report attributed to test order, Level 1 timers and "not classified"). One headline number is wrong (29 → 25) and 26 tests that `--det` silently stopped running appear in no column.

## How to reproduce (all fail on `claude/jvm-l0`)

```bash
jvm/build.sh && pip install blake3
python3 jvm/test/run_review_r022.py        # skip key: 12 scenarios + control "none"      (exit 1)
python3 jvm/test/run_review_r022_walk.py   # skip walk verifier on a 2-commit repository  (exit 1)
python3 jvm/test/run_review_r022_det.py    # --det: isolation, method refs, timers, JUnit 4, load (exit 1)
python3 jvm/test/check_review_r022_numbers.py   # headline numbers vs committed results  (exit 1)
```

Fixtures: `jvm/fixtures/review-r022` (Gradle, JUnit 5; JNI source in `src/native`), `jvm/fixtures/review-r022-det` (Maven and Gradle), `jvm/fixtures/review-r022-junit4` (Maven, Surefire 2.17). Outputs of this session's runs: `sessions/2026-11-19-review-jvm/results/`.

A skip scenario fails when a test is decided REUSE while its fresh outcome in B is not `passed` (a wrong reuse), or an expected test is not decided RUN; for a local change `PlainTest::unchanged()` must still be reused (so "rerun everything" is not accepted as a fix). The base run A passes every test.

## 1. Can the key reuse a result it should not? Yes (MEASURED, JDK 21, Gradle)

| # | scenario (`run_review_r022.py`) | change between A and B | test wrongly reused (fresh outcome in B) | why the key misses it |
|---|---|---|---|---|
| S1 | `heap-state` | `Filler.fill` adds 2 items instead of 1 | `HeapBTest::count()` (failed), `PerClassTest::b_count()` (failed) | Only `PUTSTATIC` creates an `after` edge. State mutated *through* a static reference (`Bag.ITEMS.add`, a `GETSTATIC`), or instance state of a JUnit `PER_CLASS` test instance shared by its methods, records no dependency: the writer reruns, the reader is reused. This is the IDoFT OD polluter/victim shape. |
| S2 | `new-writer-test` | a new test class `StateBTest` (runs between A and C) assigns `Shared.value = 2` | `StateCTest::read()` (failed) | `after` edges are taken from A only. A test added (or renamed, or reordered) in B that writes state a reused test reads is never considered. Even the `PUTSTATIC` path is unsound. |
| S3 | `inherited-static` | `Limits.MAX` (interface constant, not compile-time) 3 → 4 | `LimitsTest::b_second()` (failed) | `<clinit>` runs once per JVM, so only the first test that triggers it records `Limits`. Later tests read the field through the inheriting class (`GETSTATIC LimitsTest.MAX`, which javac emits for a simple name) and record only `LimitsTest`. Capture shows `a_first: [LimitsTest, Limits]`, `b_second: [LimitsTest]`. |
| S4 | `annotation-default` | `@Cfg int retries() default 3` → `5` | `AnnoTest::retries()` (failed) | Classes enter the key only when a method runs or a static field is touched. Metadata read reflectively (annotation defaults, and likewise fields or signatures read by reflection-driven frameworks) never does. `Cfg` and `Service` are loaded and digested but are not in the test's key. |
| S5 | `resource-appears` | add `src/test/resources/rv-optional.properties` | `LookupTest::resourceAbsent()` (failed) | The capture records `rv-optional.properties=absent`, but `fenvix_skip.py` skips absent entries (`if loc == "absent" ... continue`). A present resource being shadowed by an earlier class path entry is not checked either. |
| S6 | `class-appears` | add class `rv.ext.Plugin` (looked up with `Class.forName` on a computed name) | `LookupTest::classAbsent()` (failed) | A failed class lookup is recorded nowhere: `Caller.user()` returns null under `loadClass`, and probes only exist for classes that load. |
| S7 | `provider-appears` | add a `Greeter` provider + `META-INF/services/rv.Greeter` | `LookupTest::noProvider()` (failed) | Only `ClassLoader.getResource` is hooked; `getResources` (ServiceLoader, Spring factories, `junit-platform.properties`-style lookups) is not. An empty enumeration leaves no trace. |
| S8 | `csv-source-data` | `sums.csv` row `1,2,3` → `1,2,4` | `CsvTest::sum(int, int, int)[1]` (failed) | `@CsvFileSource` data is read by JUnit, which is infrastructure. `Caller.user()` returns null for infra frames, so neither the resource lookup nor the file read is recorded. Arguments of parameterized tests from files are outside the key (also `@CsvFileSource(files=...)` and other infra-side readers). |
| S9 | `child-process-input`, `native-code-input` | `data/proc.txt` read by `cat` in a child process; `data/native.txt` read by JNI `fopen` | `ProcTest::childReadsFile()` (failed), `NativeTest::nativeReadsFile()` (failed) | `ProcessBuilder.start` and native code are invisible to the capture, and the test is not marked not-reusable (unlike the external network). Docs V2 lists them as uncontrolled for `--det` only. For the key they are silent holes. |
| S10 | `junit-config-parameter` | the build adds `systemProperty 'junit.jupiter.execution.timeout.default', '1ns'` | **every test** (18/18 reused, 18/18 failed in B) | JUnit configuration parameters supplied as system properties (Gradle `systemProperty`, Surefire `systemPropertyVariables`/`argLine -D`) are read by JUnit (infra, not recorded), excluded from `jvm:args` (user `-D` "count where read"), and excluded from `fenvix.config`. The same goes for Surefire `<configurationParameters>`, which the Maven extension does not put in `fenvix.config`. |
| S11 | `infra-package-code` | `org.codehaus.plexus.rvutil.Words.join` changes its separator | `WordsTest::join()` (failed) | `Infra.PREFIXES` decides by package name: classes under `org/apache/maven/`, `org/codehaus/plexus/`, `org/gradle/`, `org/junit/platform/`, `org/testng/`, `org/jacoco/`, ... are never instrumented. A repository whose own code lives there (every Apache Maven plugin, plexus-utils, Gradle, JUnit, TestNG, JaCoCo) has no code in its keys, so any code change is reused. |

`none` (no change) reuses everything that should be reused. The existing `run_skipkeys.py` passes 12/12 here (MEASURED); it tests only inputs the capture records.

**What would make the claim true** (suggestions, for the coordinator):
* S1/S2: an `after` edge needs a write. Use a heap-level conservative rule: any test whose scope reads a static field of a class whose reachable state a *previous* test could have mutated depends on every earlier test touching that class. Recompute edges in B's order: a reused test depends on every test that runs before it now, including new ones.
* S3: record the declaring class at field resolution, not the symbolic owner (`GETSTATIC` owner → resolve with `Class.getField` once, at rewrite or first execution), and add the initialised class to every test that reads its statics.
* S4: add "classes whose reflective metadata were read" (hooks on `Class.getAnnotation*`, `getDeclared*`), or put every class loaded during the test in the key (cheap, slightly coarser).
* S5–S7: record misses (`forName`/`loadClass` failing, `getResources` empty) and compare them as "still absent" in the decider. The decider must never `continue` past an entry.
* S8, S10: infra reads of *user* inputs must be recorded. The Caller filter is right for runner internals but wrong for argument sources and configuration. Put the JUnit configuration parameters (system properties `junit.*`, `configurationParameters`) in `config`.
* S9: `ProcessBuilder.start`, `Runtime.exec` and `System.load*` of a project library should make the test not reusable (as the network does), or be declared as a limit with the customer opting in.
* S11: decide infrastructure by **code source** (the runner's jars, the tool distribution), not by package prefix.

**Walk verifier** (`run_review_r022_walk.py`): the walk's own wrong-reuse detector is blind to the commonest wrong reuse. `skip_walk.py` labels a reused test that failed fresh as **flaky** as soon as one rerun of its class *alone* passes. The test (a 2-commit repository, commit 2 adds `PolluterTest`, which sets a static flag; `VictimTest`, reused, expects it off) gives `wrong=[]`, `flaky=[VictimTest::flagIsOff() fresh=failed reruns=[passed, passed]]` on `claude/jvm-l0`: a deterministic wrong reuse counted as flaky. So "0 wrong" excludes by construction every wrong reuse caused by a polluter (S1/S2), which is the IDoFT OD shape. Under `--det` a fail-in-suite/pass-alone test is order-dependent, not flaky; it should count as wrong unless the full suite, rerun, passes. (The first version of this test used `StateCTest`, which also fails alone; the walk then correctly said wrong.) **W1.**

## 2. `--det` determinism and "broken by --det"

Control suite (`jvm/test/run_controls.py`, JDK 21, MEASURED here):
* Quiet machine: JUnit 5 Gradle **40/40**, Maven **40/40**, JUnit 4 Maven **10/10**, fingerprints identical; JUnit 4 Gradle failed its first run on an HTTP 429 from Maven Central (environment), rerun **10/10**, identical.
* **Loaded machine:** the JUnit 5 Gradle rerun ran next to two other builds: 40/40 checks hold, but **fingerprints differ across the two `--det` runs for 2 tests**. `SchedControlTest::fixedRateTicksWithoutWaiting()` got an extra `sched.timer` event, and `SleepControlTest::busyWaitOnTheClockEnds()` read `currentTimeMillis` = 1004105 vs 1001000 at event #1000. The P-022 claim "in every case the two `--det` runs verify with identical fingerprints for every test" holds on a quiet machine only. CI runners are rarely quiet.
* `cargo test -p fenvix-jvm -p detpy-core`: 44 + 2 passed.

Defects (`run_review_r022_det.py`, MEASURED):

| # | check | result on `claude/jvm-l0` | cause |
|---|---|---|---|
| D1 | `iso-maven` | project with Surefire `forkCount=2, reuseForks=false`: passes without `--det`; with `--det` **`IsoBTest` fails 2/2** | `FenvixMavenExtension.configure` forces `forkCount=1, reuseForks=true`, so classes the project isolates in fresh JVMs share one JVM. Serial execution does not need JVM reuse (`forkCount=1, reuseForks=false` is serial). **This is the cause of all 10 json-iterator "broken by --det" tests**, not test order. json-iterator's pom runs its suites with `reuseForks=false, forkCount=4`; under `--det` `StreamingTests.setup` fails with `LinkageError: duplicate class definition for com/jsoniter/IterImpl` (`idoft-local/java/runs.log:2079`), its 13 member tests never run, and the other failures are mode leaks between suites. Gradle (`iso-gradle`, `forkEvery = 1`) is **not** affected (passes). |
| D2 | `method-ref-clock`, `method-ref-random` | under `--det`, `LongSupplier clock = System::currentTimeMillis` and `Instant::now` return **real time** (2/2 failed); `Random::new` gives **different values** in two `--det` runs (4804933043389977091 vs 8229280818536933116) | Only `INVOKESTATIC`/`INVOKESPECIAL` call sites are rewritten. A method reference compiles to `invokedynamic` with a direct method handle, so the clock and seed escape. Injectable clocks (`LongSupplier clock = System::currentTimeMillis`) are a common pattern. Rewrite the bootstrap arguments' `Handle`s (same table as the call sites). |
| D3 | `sleep-past-timer` | `scheduleAtFixedRate(…, 1 s)` then `TimeUnit.SECONDS.sleep(2)`: the task **never ran** (2/2 failed), passes without `--det` | A virtual sleep that passes a `VirtualScheduler` task's due time returns before the task fires. This is exactly luwak `TestCachePurging.testBackgroundPurges`: the purge executor is `Executors.newSingleThreadScheduledExecutor()` (virtual) and the test sleeps 2 s. It is broken **10/10** on the final agent (recheck). P-022 lists it under "threads / real-time timers (Level 1, V4)", but it is neither real-time nor an interleaving: it is deterministic and an engine defect. The sleep must run due virtual timers before returning. |
| D4 | `junit4-surefire-2.17` | a 2-test JUnit 4 project on Surefire 2.17: **`Test mechanism` error, 0 tests in the trace** | Surefire 2.17's JUnit 4 provider calls `fireTestRunStarted(null)`; `Junit4Hook.Listener.collect` dereferences it (NPE at `Junit4Hook.java:130`), so JUnit's SafeNotifier reports "Test mechanism" and removes the listener. This is the tyrus row ("a JVM-level error under `--det`, not classified", fingerprint coverage 0/0). |
| (D5) | `fingerprints-under-load` | **not reproduced by the committed check** (3/3 pairs identical with 4 × CPUs busy loops; 1/1 with 2 ×). Seen **once**, MEASURED: the JUnit 5 Gradle control rerun next to two other Gradle/Maven builds verified with 2 tests not covered (`results/controls-loaded-verify.txt`). Observation only, not counted in FIX: I have no failing test for it. | Two of the controls depend on thread-state sampling (V6, V16): the "quiet" decision and the real-time fallback of a busy clock loop. Under CPU load the sampled answer changes, and so does the fingerprint. |

**The broken-by-`--det` counts, classified** (from the committed `tests.json`, `recheck.json`, run logs):
* GitHub Actions run 44385794604, **22**: json-iterator 10 (**D1, engine**), biojava 8 (closed network: `UnknownHostException ftp.wwpdb.org`, by design), fastjson 1 (ISO round trip at the fixed epoch 2025-01-01T00:00Z, a real time-of-day dependency, debatable), Java-WebSocket 2 (1/10 and 5/10, socket timing; one was already 1/10 in the baseline), openhtmltopdf 1 (`testMaliciousSvgInsecureMode`, bare `AssertionError`, UNKNOWN). Real engine defects: **10 of 22**, plus the 13 tests D1 stops from running.
* Container, final agent: **25**, not 29 (§3). json-iterator 10 (**D1**), tyrus 1 (**D4**), luwak 2 (`testBackgroundPurges` 10/10 = **D3**; `testConcurrentPurges` 2/10), wro4j 3 and excelastic 1 (not classified), c2mon 2, cat 1, asyncload 1, Java-WebSocket 1 (threads/timing, 1-2/10), biojava 1 (network, by design), fastjson 1 (epoch), openhtmltopdf 1 (already 1/10 in the baseline). Real engine defects: **at least 12 of 25** (D1 10, D3 1, D4 1).
* The final-agent GitHub Actions round (run 44424494082) has 7 projects committed after the report was written: broken seata 1 and hutool 1 (both closed network), mTracker 2 (already 1/10 in the baseline; the container said 2 → 0), cat 2, c2mon 1. wikidata reproduced 2/3 (container 3/3).

## 3. Headline numbers re-derived (`check_review_r022_numbers.py`)

| claim | committed data | |
|---|---|---|
| GitHub Actions run 44385794604: 10 projects, documented **94/469**, baseline-unstable **59/94**, broken **22**, fingerprints **7,777/7,914** | identical | ok |
| container: 28 projects, 12,226 tests, documented **171/542**, unstable **63/105**, broken 35 before the fixes, slowdown median **-3.2%** (23 projects) | identical | ok |
| container: broken by `--det` **35 → 29** after the last fixes | committed rechecks give **25**: Java-WebSocket's `recheck.json` says 5 → 1, but the report keeps 5 (table row and causes list) | **wrong** |
| no test lost under `--det` (implicit: no column) | **26** test rows (13 GitHub Actions + 13 container, all json-iterator, all *documented* IDoFT tests, e.g. `IterImplForStreamingTest::testLoadMore`) ran 10/10 in the baseline and **0 times** under `--det` | **missing** |
| skip walk on GitHub Actions: **5,731,740** verified reuses, **0** wrong, 37 flaky, 22 not verifiable, 6 repositories; per-repository medians/means | identical (`results/skip/summary.json`, shards) | ok |
| container walks: jsoup 71,952 / 0 wrong, gson 171,571 / 0 wrong | identical (`results/skip-local`) | ok |

Labels:
* "Fingerprint coverage 95.8%" divides by tests that *have* a fingerprint. Tyrus (66 tests, D4) and vertx-completable-future (61) have no trace and drop out of both terms, and junit-quickcheck has 734 fingerprinted ids for 484 tests (another id vocabulary). Over the tests that ran, the share is lower than printed, and the gap is UNKNOWN until the ids are unified.
* The json-iterator "order-only ablation: the same 41 failures as full `--det`" is consistent with D1, not with order: the ablation keeps the Maven extension, hence `reuseForks=true`.
* "Reproduced" for json-iterator (4/19 documented) is depressed by D1: 13 of its 19 documented tests never ran under `--det`.
* The 37 commons-lang "flaky" (36 failed fresh and then passed twice alone): the walk's rule cannot tell them from a polluter-caused wrong reuse (W1). The V16 explanation (busy clock loop under load) is plausible and consistent with the class, and P-022 reports them passing 5/5 after the fix. But "0 wrong" over 5.7 M rests on that classification, not on the rule.

## 4. What I ran (MEASURED, this container)

| suite | result |
|---|---|
| `jvm/build.sh` | ok (27 s) |
| `cargo test -p fenvix-jvm -p detpy-core` | 44 + 2 passed |
| `jvm/test/run_controls.py` (JDK 21) | 40/40 + 40/40 + 10/10 Maven; JUnit 4 Gradle 10/10 on rerun (first run: HTTP 429). Fingerprints identical when quiet, **not identical under load** (D5) |
| `jvm/test/run_skipkeys.py` | 12/12 ok |
| `jvm/test/run_review_r022.py` | `none` ok; 12 scenarios BAD (S1–S11; S9 has two) |
| `jvm/test/run_review_r022_det.py` | `iso-gradle` ok; `iso-maven`, `method-ref-clock`, `method-ref-random`, `sleep-past-timer`, `junit4-surefire-2.17` BAD; `fingerprints-under-load` ok (3/3 pairs identical; observation from a run next to other builds in §2) |
| `jvm/test/run_review_r022_walk.py` | BAD: `VictimTest` wrong reuse labelled flaky |
| `jvm/test/check_review_r022_numbers.py` | 2 BAD (29 vs 25; 26 tests not run), 14 ok |

Not run: JDK 8/11/17 (only JDK 21 is installed here), the IDoFT round and the skip walks themselves (hours; re-derived from the committed results instead), `run_l1_measure.py`.

## 5. Findings (FIX list)

Skip with proof (wrong reuse; each a failing scenario in `run_review_r022.py`):
1. **S1** heap and `PER_CLASS` instance state mutated without `PUTSTATIC`: no `after` edge (`heap-state`).
2. **S2** `after` edges from run A only: a test added in B that writes state is ignored (`new-writer-test`).
3. **S3** static initialiser recorded only in the first test; inherited static reads miss the declaring class (`inherited-static`).
4. **S4** reflective class metadata (annotation defaults) not in the key (`annotation-default`).
5. **S5** absent classpath resources skipped by the decider (`resource-appears`).
6. **S6** failed `Class.forName` lookups not recorded (`class-appears`).
7. **S7** `ClassLoader.getResources` / ServiceLoader not hooked (`provider-appears`).
8. **S8** user inputs read by JUnit (infrastructure), e.g. `@CsvFileSource`, not recorded (`csv-source-data`).
9. **S9** child processes and JNI code read inputs invisibly and the test stays reusable (`child-process-input`, `native-code-input`).
10. **S10** JUnit configuration parameters set by the build are not in the key: every test reused (`junit-config-parameter`).
11. **S11** project code in infrastructure-prefixed packages is never instrumented (`infra-package-code`).
12. **W1** the skip walk counts a polluter-caused wrong reuse as flaky (`run_review_r022_walk.py`).

`--det` (`run_review_r022_det.py`):

13. **D1** Maven extension forces `reuseForks=true`, breaking per-class JVM isolation (`iso-maven`; json-iterator's 10 broken and 13 tests not run).
14. **D2** method references (`System::currentTimeMillis`, `Instant::now`, `Random::new`) escape the clock and the seeds (`method-ref-clock`, `method-ref-random`).
15. **D3** a virtual sleep past a virtual timer's due time does not fire the timer (`sleep-past-timer`; luwak 10/10).
16. **D4** NPE in `Junit4Hook` on `testRunStarted(null)` (Surefire 2.17): listener removed, no trace (`junit4-surefire-2.17`; tyrus).

Numbers (`check_review_r022_numbers.py`):

17. **N1** "broken by `--det`" after the fixes is 25 by the committed rechecks, not 29; 26 documented tests that ran in the baseline never ran under `--det` (D1) and are in no column. Labels to correct: the json-iterator cause ("order") and the fingerprint-coverage denominator (§3).

Observation, not counted: control fingerprints not identical in one run next to other builds (§2, D5).

