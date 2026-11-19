DONE-WITH-OPEN-ITEMS

# P-022 · JVM track — fixes for review R-022 (verdict FIX 17)

Work session on `claude/jvm-l0`, 2026-11-19. Input: `sessions/2026-11-19-review-jvm/REPORT.md` (R-022, merged from `claude/review-r022`), `review-input/REPORT.md` (P-022). Container: 4 CPUs, OpenJDK 21.0.13 (default), 8/11/17 installed from Ubuntu packages for the IDoFT rechecks, Gradle 8.14.3, Maven 3.9. Labels: MEASURED (command / run), ESTIMATED, DECLARED (source), UNKNOWN.

**Summary.** All 17 findings are addressed in code with a test that failed before and passes now: the 11 skip-key holes (S1–S11), the walk verifier (W1), the four `--det` defects (D1–D4) and the numbers (N1). The skip decider is now Rust (`crates/fenvix-skip`); `jvm/skip/fenvix_skip.py` is only its Python interface. D5 (fingerprints under load) is half fixed: one transient was found and removed, a second one (real-time fallback of the virtual scheduler under heavy load) is reproduced, documented and left open (Level 1).

**The price of soundness is large and MEASURED:** the shared-state rule that closes S1/S2 (a test that reads mutable static state depends on every test before it in its JVM) keeps **0 wrong reuses** in both re-run walks, but on code-change commits it reuses almost nothing in jsoup and gson, because nearly every test there reads mutable static state (§4). Median test time skipped: jsoup **77% → 5%**, gson **84% → 12%**. Commits without a code change are as good as or better than before (gson 99.9%; jsoup's blocked-network and property reruns no longer cascade).

**IDoFT recheck (28 container projects, MEASURED):** broken by `--det` **25 → 14**; tests that ran in the baseline but never under `--det` **13 → 0**; json-iterator 10 → 0 (D1), luwak `testBackgroundPurges` fixed (D3), tyrus traced again (D4).

**Two of the reviewer's four scripts cannot exit 0 after the fixes, by construction** (details §5): `run_review_r022_walk.py` needs a wrong reuse to classify, and S2's fix removes it (VictimTest is now decided RUN, `after-new: rv.PolluterTest::pollute()`); `check_review_r022_numbers.py` embeds the P-022 claims (29 and 0) and checks them against the data, which say 25 and 26. I did not edit either (instruction). Their intent is covered by `jvm/test/run_w1_verifier.py` (W1, exit 0) and `jvm/test/check_report2_numbers.py` (exit 0). The other two, `run_review_r022.py` and `run_review_r022_det.py`, exit 0.

## 1. Test status (MEASURED, this container, agent d248b5b unless said)

| suite | before (P-022 agent, R-022 logs) | now |
|---|---|---|
| `jvm/test/run_review_r022.py` | `none` ok, 12 scenarios BAD | **13/13 ok**, `PlainTest::unchanged()` reused in every local scenario |
| `jvm/test/run_review_r022_det.py` | 5 BAD (iso-maven, method-ref-clock, method-ref-random, sleep-past-timer, junit4-surefire-2.17) | **7/7 ok** (fingerprints-under-load 3/3 pairs identical) |
| `jvm/test/run_review_r022_walk.py` | BAD (wrong reuse labelled flaky) | **exit 1, see §5**: no wrong reuse left to classify (`reused=14 wrong=[] flaky=[]`, VictimTest RUN) |
| `jvm/test/check_review_r022_numbers.py` | 2 BAD | **exit 1 by construction, see §5** (claims 29/0 embedded; data 25/26) |
| `jvm/test/run_w1_verifier.py` (new) | — | **ok**: 5/5 classifier cases; walk with an adversarial "reuse everything" decider labels VictimTest **wrong** (`reruns=[passed, passed]`, `suite_rerun=failed`); walk with the real decider: no wrong reuse |
| `jvm/test/check_report2_numbers.py` (new) | — | **ok** (25; 13 + 13 not run; R-022 rechecks, §3) |
| `jvm/test/run_controls.py` (JDK 21) | 40/40, 40/40, 10/10, 10/10 | **40/40, 40/40, 10/10, 10/10, fingerprints identical** (`sessions/2026-11-18-jvm-l0/r022-logs/controls.log`) |
| `jvm/test/run_skipkeys.py` | 12/12 | **12/12** |
| `cargo test -p fenvix-jvm -p detpy-core -p fenvix-skip` | 44 + 2 | **44 + 2 + 10** |
| `jvm/test/run_d5_load.py` (new, 5 pairs under 2×CPU burners + a neighbour Gradle build) | P-022 agent: 5/5 pairs identical | 4/5 (one `fixedRateTicksWithoutWaiting` extra timer), §2 D5 |

Logs: `sessions/2026-11-18-jvm-l0/r022-logs/`; JSON: `jvm/test/results/`.

## 2. Per finding: what changed, proving test, before → after

Skip with proof (scenario names of `run_review_r022.py`; "before" = R-022's run on 1b9b211, "after" = `jvm/test/results/review-r022.json`):

| # | change | before → after |
|---|---|---|
| S1 heap / PER_CLASS | Capture: every GETSTATIC is classified after it executes: a read is **mutable** unless the field is final and holds a primitive, an immutable JDK type, `null`, an empty array, or an object whose runtime class has only final fields of such types (JDK enum constants included). Scopes record `mut` (and `mut_classes`, why), `swrite` (any static write, `Field.set*` and `System.setProperty` included). Containers record `shared` (Jupiter `@TestInstance(PER_CLASS)` on the class, a supertype or an enclosing class, or the PER_CLASS default; any engine other than Jupiter/Vintage). Decider (`order_reason`): a `mut` reader is reused only if every test before it in its JVM in B is reused or, rerun/new, touched no shared state in B, and the state-touching tests before it are the same, in the same order, as in A; tests of a shared-instance class chain to every earlier test of the class. | `heap-state`: HeapBTest, PerClassTest::b_count reused & failed → both RUN (`after`) |
| S2 writers from A only | The rule above uses B's order and B's captures of rerun/new tests (the decision for a test is taken at its position: the tests before it have run). | `new-writer-test`: StateCTest reused & failed → RUN (`after-new: StateBTest`) |
| S3 inherited static / clinit | Static sites are resolved at first execution like JVM field resolution (declared → superinterfaces → superclass) over the class structure the agent registers; owner **and** declaring class enter the key. `<clinit>` runs inside a frame: what it depends on (classes, files, resources, properties…) is added to every later scope that touches the class. | `inherited-static`: b_second reused & failed → RUN (`code: rv/Limits`) |
| S4 reflective metadata | JDK hooks on `Class.getAnnotation*/getDeclared*/getMethods/…/getGeneric*/getRecordComponents`, `MethodHandles.Lookup.find*`, `Field.get*/set*`; annotation types parsed for a class (`AnnotationParser.parseAnnotations`, JDK 8 and 9+ signatures) are tied to it. | `annotation-default`: AnnoTest reused & failed → RUN (`code: rv/Cfg`) |
| S5 absent resources | `getResource` records `name=absent`; the decider checks "still absent" and compares the **first** location on B's class path (shadowing); lookups through a loader other than the class path's record `?` (never reused). Surefire's manifest-only booter jar is expanded into the recorded class path. The decider never skips an entry. | `resource-appears`: reused & failed → RUN (`resource`) |
| S6 class lookups | Hooks on `Class.forName` (both) and `ClassLoader.loadClass(String)`: every name looked up from a test is recorded `present`/`absent`; the decider checks it on B. | `class-appears`: → RUN (`class-lookup: rv/ext/Plugin`) |
| S7 getResources | Hook on `ClassLoader.getResources`: every location in order (`all:loc@state|…`), compared with B's class path. | `provider-appears`: → RUN (`resource`) |
| S8 infra-read inputs | File reads, probes, listings and resource lookups made by the infrastructure **inside a test or class scope** are recorded (they are on behalf of the test); its writes and its session-scope activity are not. | `csv-source-data`: → RUN (`file`) |
| S9 processes / native | `ProcessBuilder.start` → `proc`; `Runtime.load0/loadLibrary0` from non-JDK code and every call of a project native method (renamed with `setNativeMethodPrefix`, called through a wrapper) → `native`. Both: never reused. | `child-process-input`, `native-code-input`: → RUN (`process`, `native`) |
| S10 JUnit configuration | Configuration key adds `junit.*`/`testng.*` system properties and the plan's configuration parameters (`TestPlan.getConfigurationParameters`, Platform ≥ 1.9; Surefire `configurationParameters` included); the Maven extension also puts `configurationParameters`, `properties`, `reuseForks`, … in `fenvix.config`. | `junit-config-parameter`: 18/18 reused & failed → 0/18 reused (`config`) |
| S11 infra by package | Infrastructure is decided by **code source** (`Infra.decide`: fenvix, the build tool's distribution, runner jars by file name: junit-platform/jupiter/vintage, junit-4.x, surefire, testng, jacoco, IDE runners). Classes from a directory are code under test whatever their package; the package list is only a fallback for classes without a code source. | `infra-package-code`: WordsTest reused & failed → RUN (`code`) |
| W1 walk verifier | `skip_walk.classify`: fails alone and passes alone → flaky; never passes alone → wrong; passes alone but failed in the suite → **wrong** unless one rerun of the whole suite (cached per transition) passes it. | `run_w1_verifier.py` ok (above) |

Further soundness changes found while fixing (MEASURED on the walks, same tests): a test that failed in A but whose key is unchanged is rerun but "clean" for the tests after it (deterministic); a network attempt **blocked by `--det`** is recorded `:blocked` (deterministic: refused at the shell), so the test is never reused but clean; system properties written by tests (`System.setProperty`, `clearProperty`, `setProperties`, `getProperties`) are shared state, other property reads compare against the value at JVM start (`props_start`) instead of the end-of-JVM value.

`--det` (`run_review_r022_det.py`):

| # | change | before → after |
|---|---|---|
| D1 | Maven extension: `forkCount=1` (serial) but `reuseForks` left to the project (`forkMode=always/pertest` → `reuseForks=false`); execution-level config inherits the plugin-level value. Gradle init script no longer forces `forkEvery=0`. | `iso-maven`: IsoBTest failed 2/2 → passed 2/2; `iso-gradle` ok → ok |
| D2 | `invokedynamic` with LambdaMetafactory: a method-reference implementation handle to a rewritten JDK method (static table, `now()` of java.time, `Date/Random/SplittableRandom::new`, virtual rules) is replaced by a synthetic static bridge that calls the runtime with the call site. | `method-ref-clock` failed 2/2 → passed; `method-ref-random` 2 different values → same value |
| D3 | A virtual `Thread.sleep`/`TimeUnit.sleep` first runs every virtual scheduled task due before its end, in due order, at its own virtual time (bounded by the fast-firing budget and, in real time, by the sleep length). | `sleep-past-timer` failed 2/2 → passed; luwak `testBackgroundPurges` 10F/10 → 0F/10 (§3) |
| D4 | JUnit 4 listener tolerates `null` descriptions/failures (Surefire 2.17 `testRunStarted(null)`). | "Test mechanism", 0 tests in trace → 2/2 tests, 2 in trace; tyrus §3 |
| D5 | Investigated, reproduced (§1 controls run next to a JDK install: `busyWaitOnTheClockEnds` read 1002994 vs 1001000). Cause: the quiet check sampled the runner thread (JUnit, no code under test on the stack) RUNNABLE on its way to parking. Fix: a RUNNABLE/BLOCKED thread with no code-under-test frame, inside the runner or pool machinery, is not working for the test. **Residual, open:** `SchedControlTest::fixedRateTicksWithoutWaiting` got a 6th timer in 1 of 5 loaded pairs (`run_d5_load.py`; P-022 agent 0/5 in the same conditions, so not distinguishable at this sample size): when the test thread does not progress for the remaining virtual delay in real time, the scheduler's real-time fallback fires. That is real-time thread progress (Level 1, V4/V6), not fixable at Level 0; documented with the test, which exits 1 when it happens. | §1 |

## 3. Numbers (N1) and the IDoFT recheck after the fixes

Corrections to P-022 (`check_report2_numbers.py`, from the committed data):

* Container, broken by `--det` after the P-022 fixes: **25**, not 29 (Java-WebSocket's recheck says 5 → 1; the report kept 5).
* **26 tests ran in the baseline and never under `--det`** (13 in GitHub Actions run 44385794604, 13 in the container), all json-iterator, all documented IDoFT tests. They belong in their own column ("not run under --det"); cause D1.
* Reclassification of the container's "broken by `--det`" (25, P-022 agent): **engine defects 12** (json-iterator 10 = D1, luwak `testBackgroundPurges` 1 = D3, tyrus 1 = D4; P-022 said "order", "Level 1 timers", "not classified"); closed network by design 1 (biojava); time-of-day at the fixed epoch 1 (fastjson, debatable); threads / timing 6 (c2mon 2, cat 1, asyncload 1, Java-WebSocket 1, luwak `testConcurrentPurges` 1); already unstable in the baseline 1 (openhtmltopdf); not classified 4 (wro4j 3, excelastic 1). GitHub Actions run 44385794604 (22): engine defects 10 (json-iterator, D1), closed network 8 (biojava), Java-WebSocket 2, fastjson 1, openhtmltopdf 1.
* json-iterator "order-only ablation: same 41 failures" is consistent with D1 (the ablation kept the Maven extension, hence `reuseForks=true`), not with order. Its "4/19 documented reproduced" is depressed by D1 (13 of 19 never ran).
* Fingerprint coverage "95.8%" (11,871/12,396) divides by fingerprinted ids; counting tyrus (66) and vertx-completable-future (61), which ran without a trace, as not covered gives 11,871/12,523 = **94.8%** (ESTIMATED: junit-quickcheck has 734 fingerprinted ids for 484 tests; the exact share over tests that ran is UNKNOWN until the ids are unified).

**Recheck after the R-022 fixes** (MEASURED, container, agent d248b5b, `python3 jvm/harness/recheck_all.py --agent-rev d248b5b` (+ a second stream with `--only`); per project: prepare at the recorded JDK, 10 `--det` seed-0 runs against the recorded baseline; output `<project>/recheck-r022.json`):

| project | broken, P-022 round | broken, P-022 recheck | **broken now** | not run under --det, P-022 | **not run now** | broken now (failures / 10 --det runs) |
|---|---|---|---|---|---|---|
| Java-WebSocket | 5 | 1 | **2** | 0 | **0** | runReconnectBlockingScenario6 4F/10 (base 1F/9P), runReconnectScenario9 3F/10 (base 1F/9P) |
| Mapper-base | 0 | 0 | **0** | 0 | **0** |  |
| aismessages | 0 | 0 | **0** | 0 | **0** |  |
| asyncload | 5 | 1 | **1** | 0 | **0** | testSingleton 1F/10 (base 0F/10P) |
| avro-ipc-jetty | 0 | 0 | **0** | 0 | **0** |  |
| biojava-biojava-structure | 1 | 1 | **1** | 0 | **0** | testStructureWithBranchedEntities 10F/10 (base 0F/10P) |
| c2mon-c2mon-daq-core | 2 | 2 | **0** | 0 | **0** |  |
| cat-cat-client | 1 | 1 | **2** | 0 | **0** | testMode0 3F/10 (base 1F/9P), testMode1 2F/10 (base 0F/10P) |
| easyexcel | 0 | 0 | **0** | 0 | **0** |  |
| excelastic | 1 | 1 | **1** | 0 | **0** | shouldWriteToElasticPort 10F/10 (base 1F/9P) |
| fastjson | 1 | 1 | **1** | 0 | **0** | test_iso_format 10F/10 (base 0F/10P) |
| http-request-lib | 0 | 0 | **0** | 0 | **0** |  |
| hutool-hutool-core | 0 | 0 | **0** | 0 | **0** |  |
| incubator-seata-common | 0 | 0 | **0** | 0 | **0** |  |
| java-cas-client-cas-client-core | 2 | 0 | **0** | 0 | **0** |  |
| java | 10 | 10 | **0** | 13 | **0** |  |
| junit-quickcheck-core | 0 | 0 | **0** | 0 | **0** |  |
| luwak-luwak | 2 | 2 | **1** | 0 | **0** | testConcurrentPurges 2F/10 (base 0F/10P) |
| mTracker-core | 0 | 0 | **0** | 0 | **0** |  |
| oci-java-sdk-bmc-objectstorage-extensions | 0 | 0 | **1** | 0 | **0** | abortAll 1F/10 (base 0F/10P) |
| openhtmltopdf-openhtmltopdf-examples | 1 | 1 | **1** | 0 | **0** | testFreeMarkerGenerator 10F/10 (base 1F/9P) |
| ormlite-core | 0 | 0 | **0** | 0 | **0** |  |
| servicecomb-java-chassis-generator-core | 0 | 0 | **0** | 0 | **0** |  |
| spring-ws-spring-ws-core | 0 | 0 | **0** | 0 | **0** |  |
| tyrus-non-deployable | 1 | 1 | **0** | 0 | **0** |  |
| vertx-completable-future | 0 | 0 | **0** | 0 | **0** |  |
| wikidata-toolkit-wdtk-dumpfiles | 0 | 0 | **0** | 0 | **0** |  |
| wro4j-wro4j-core | 3 | 3 | **3** | 0 | **0** | shouldCheckOnlyAfterTimeout 10F/10 (base 0F/10P), testFromFolder 10F/10 (base 0F/10P), testFromFolder 10F/10 (base 0F/10P) |
| **total (28 rechecked)** | | 25 | **14** | 13 | **0** | |

Reading: broken by `--det` **25 → 14**; tests that ran in the baseline and never under `--det` **13 → 0** (json-iterator: D1). Engine defects named by R-022 are gone: json-iterator 10 → 0 (D1), luwak `testBackgroundPurges` 10F/10 → 0 (D3; `testConcurrentPurges` 2F/10 remains, threads), tyrus 1 → 0 and its tests now in the trace (D4). Also c2mon 2 → 0. Left: by design / real dependencies: biojava (closed network), fastjson (time of day at the fixed epoch); already failing in the baseline: excelastic, openhtmltopdf (10F/10 under `--det` vs 1F/9P); wro4j 3 (10F/10, not classified, UNKNOWN cause); thread / timing, 1–4 failures in 10: Java-WebSocket 2, cat 2, asyncload 1, luwak 1, oci 1 (oci `abortAll` 1F/10 and cat `testMode1` are new in this recheck). The rechecks ran two to three projects at a time on 4 CPUs, so the thread/timing rows are NOISY; the 10F/10 rows are not. GitHub Actions run 44385794604's 22 and its 13 not-run tests were not re-run (UNKNOWN for the new agent; same json-iterator project as the container row).

## 4. Skip walks re-run (MEASURED, container, agent d248b5b, same commits as P-022)

`python3 jvm/harness/skip_walk.py --repo {jsoup,gson} --shas-from jvm/harness/results/skip-local/{repo}/shard0.json --out jvm/harness/results/skip-local-r022` (JDK 17). Every reuse checked against the fresh outcome; W1 rule active.

| repository | transitions | test time skipped, median / mean | tests skipped, median | verified reuses | wrong | flaky | top rerun reasons |
|---|---|---|---|---|---|---|---|
| jsoup, P-022 agent (`results/skip-local`) | 50 | 77% / 57% | 91% | 71,952 | 0 | 0 | code, config, runtime, prop |
| **jsoup, now** | 50 | **5% / 23%** | **8%** | **17,572** | **0** | **0** | after 44,388, code 19,936, after-new 11,201, config, runtime, order 1,604 |
| gson, P-022 agent | 50 | 84% / 65% | 91% | 171,571 | 0 | 0 | code, runtime, config |
| **gson, now** | 50 | **12% / 42%** | **2%** | **93,219** | **0** | **0** | after 73,918, code 27,830, runtime, config, after-new 4,091 |

By kind of transition (median test time skipped, P-022 → now): gson without code change (19) 99.9% → 99.9%, with a code change (21) 54% → 0.5%; jsoup without code change (18) 80% → 55% (new tests, `after-new`), with a code change (28) 64% → 1.5%; global changes (plugins, dependencies) 0% → 0% in both.

Why: `mut` is set for 4,570 of 4,612 gson tests (one capture, `mut_classes`): Guava testlib `CollectionSize`, Truth, gson's `Excluder`, `TypeAdapters`, `GsonBuilder` singletons, switch-map arrays. Any rerun test that touched them in B invalidates every later reader in its JVM. That is what the rule must do to be sound against S1/S2 (a test can change a shared registry or cache that a later test reads); a lower reuse rate is the accepted cost. Tightening the immutability check (runtime class with only final immutable fields, final fields of immutable user types; commit 7bab9bd, not used for the walks) does not change this for gson (4,570/4,612 still `mut`).

P-022's GitHub Actions walks (5.7 M verified, 0 wrong) used the old rule and the old verifier; they were not re-run (container time; see §6). Their "0 wrong" stands as measured with the old verifier, which could not see polluter-caused wrong reuses (W1).

## 5. Reviewer scripts that cannot exit 0

* `run_review_r022_walk.py` asserts that the walk labels `rv.VictimTest::flagIsOff()` wrong. It can only do so if the decider reuses VictimTest after the new PolluterTest — exactly S2's wrong reuse, which `run_review_r022.py` (`new-writer-test`) requires to be gone. With S2 fixed the walk decides VictimTest RUN (`after-new: rv.PolluterTest::pollute()`), `wrong=[]`, and the script exits 1. `run_w1_verifier.py` tests W1 on the same two-commit repository with an adversarial decider and passes.
* `check_review_r022_numbers.py` embeds P-022's claims (29 after the fixes; 0 tests not run) and recomputes the committed data (25; 26). The data are right and the claims are now corrected in this report; the script reports BAD for those two lines until its two constants are changed, which I did not do. `check_report2_numbers.py` runs the same computations against REPORT-2's claims (exit 0).

## 6. What is left open

* **Reuse rate under the shared-state rule** (§4). Ways forward, none implemented: per-class shared-state keys with an aliasing analysis (which statics can reach the same objects), or a digest of the static state a test reads, taken at its start in A and compared at its position in B (online decider). Both must stay sound; neither is small.
* **D5 residual**: virtual scheduler real-time fallback under heavy load (Level 1).
* **Not keyed, residual risks I know of** (not in R-022, not fixed): JDK global state other than system properties (`Locale.setDefault`, `TimeZone.setDefault`, `System.setOut`, security providers, URL handler factories); objects shared through JUnit extension stores; `Unsafe` and VarHandle writes to statics; type annotations (`TypeAnnotationParser`); JDK enum constants are assumed immutable.
* The decider is measurement-mode (it reads B's capture). An online decider in the runner (decide at each test's position) is required for production use; the rule is written for it.
* GitHub Actions: the IDoFT round and the six walks were not re-run on Actions after the fixes; the GHA-side "not run under `--det`" (13, json-iterator) is UNKNOWN for the new agent (the container recheck of json-iterator covers the same project, §3).
* JDK 8/11/17: the `--deps` capture changes were exercised on JDK 17 (walks) and 21 (tests); JDK 8/11 under `--det` by the rechecks and by GitHub Actions run 44489391620 (code f98a21f: control jobs on JDK 8, 11, 17, 21 all succeeded; its commit step did not refresh the committed result files, so the numbers are the job conclusions only). JDK hooks on `java.lang.Class`, `ClassLoader`, `System`, `Field`, `MethodHandles.Lookup`, `AnnotationParser` with `--deps` on JDK 8/11: UNKNOWN.
* The full IDoFT round protocol (baselines, seeds, confirmation, timing) was not re-run; only the "broken by `--det`" recheck and the new "not run" column.

## 7. Where things are

* Decider: `crates/fenvix-skip/src/lib.rs` (+ `main.rs`, binary `target/release/fenvix-skip`, built by `jvm/build.sh`); Python interface `jvm/skip/fenvix_skip.py`.
* Capture: `jvm/rt/.../Deps.java`, `Caller.java`, `Infra.java`, `Det.java`, `Lifecycle.java`; agent `CallSiteRewriter.java`, `JdkHooks.java`, `Installer.java`; JUnit `FenvixListener.java`, `Junit4Hook.java`; `VirtualScheduler.java`; Maven extension; Gradle init script.
* Harness: `skip_walk.py` (W1, `--shas-from`, `FENVIX_AGENT`), `jvm_harness.py` (recheck: not-run column, `--recheck-name`, `--agent-rev`), `recheck_all.py`.
* Tests: `jvm/test/run_w1_verifier.py`, `run_d5_load.py`, `check_report2_numbers.py`; results `jvm/test/results/`; walks `jvm/harness/results/skip-local-r022/`; rechecks `jvm/harness/results/idoft-local/*/recheck-r022.json`.
