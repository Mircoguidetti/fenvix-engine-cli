FIX 4

# R-022b · Final review of the JVM track after the R-022 fixes (P-022 REPORT-2, branch `claude/jvm-l0`)

Reviewer session, 2026-11-19. Branch `claude/review-r022b` = `claude/jvm-l0` (342fea5) + this review. Input: `sessions/2026-11-18-jvm-l0/REPORT-2.md` (DONE-WITH-OPEN-ITEMS) and the first review `sessions/2026-11-19-review-jvm/REPORT.md` (R-022, FIX 17, from `claude/review-r022`).
Everything below was run in this session's container (4 CPUs, OpenJDK 21.0.13 only, Gradle 8.14.3, Maven 3.9, cargo). Labels: MEASURED / ESTIMATED / DECLARED / UNKNOWN. Logs and JSON: `sessions/2026-11-19-review-jvm/results-2/`.

**Verdict: FIX 4.** All 17 R-022 findings are fixed: the reviewer's scripts and fixtures are byte-identical to `claude/review-r022`, and every check they make passes, except the two that cannot pass by construction. That claim is true, and the replacement scripts test the same intent (§1). The `--det` defects D1–D4 are fixed. D5 is a real Level 1 timing limit and not a hidden defect (§4). But the skip key still reuses results it should not through **three channels R-022 did not test**. Each one is shown by a committed scenario where the reused test **fails** in the fresh run of the same state: JDK-internal caches, JDK global state reached through static methods, and the runner thread's own state (§2). The fourth finding is the user documentation. `docs/JVM.md` was not touched by P-022: it still describes the pre-fix skip rule and does not list the D5 limit or the inputs that are still not keyed. The numbers in REPORT-2 re-derive from the committed data (§5).

## How to reproduce

```bash
jvm/build.sh && pip install blake3
python3 jvm/test/run_review_r022b.py     # new wrong reuses: 5 of 7 scenarios BAD (exit 1)
python3 jvm/test/check_r022b_docs.py     # docs/JVM.md vs REPORT-2 (exit 1)
python3 jvm/test/run_r022b_cost_probe.py # what the shared-state rule calls mutable (measurement, exit 0)
python3 jvm/test/mut_blame.py <deps dir> <out.json>   # mut tests and blamed classes of a capture
```

Fixture `jvm/fixtures/review-r022b` (Gradle, JUnit 5). It has one writer/reader pair per channel, `rv.<X>ATest` and `rv.<X>BTest` in name order, plus `PlainTest` and the `Cost*Test` probes. The protocol is the same as `run_review_r022.py`. Each scenario changes only the writer, so the writer is rerun. The reader is unchanged and must be decided RUN, and `PlainTest` must stay reused.

## 1. R-022 findings: fixed? (MEASURED, JDK 21, agent built from 342fea5)

The reviewer's files are unchanged: `git diff origin/claude/review-r022 HEAD` is empty for all four scripts `jvm/test/run_review_r022*.py` and `check_review_r022_numbers.py`, and for the fixtures `jvm/fixtures/review-r022`, `review-r022-det` and `review-r022-junit4`.

| suite | result now | |
|---|---|---|
| `run_review_r022.py` (S1–S11) | **13/13 ok**; `PlainTest` reused in every local scenario | fixed |
| `run_review_r022_det.py` (D1–D4) | `iso-maven`, `iso-gradle`, `method-ref-clock`, `method-ref-random` (same value twice), `sleep-past-timer`, `junit4-surefire-2.17` (2/2 in the trace): **ok**. `fingerprints-under-load`: **BAD**, 1 of 3 pairs (`SchedControlTest::fixedRateTicksWithoutWaiting`, one extra `sched.timer`) | D1–D4 fixed; the BAD is the open D5 residual (§4). REPORT-2 §1 says "7/7 ok": that was one run, and this run says 6/7 |
| `run_review_r022_walk.py` (W1) | exit 1: `reused=14 wrong=[] flaky=[]`, VictimTest decided RUN (`after-new: rv.PolluterTest::pollute()`) | cannot pass after S2 is fixed (below) |
| `run_w1_verifier.py` (replacement) | **ok**: 5/5 classifier cases. Adversarial decider: VictimTest `wrong`, `reruns=[passed, passed]`, `suite_rerun=failed`. Real decider: no wrong reuse | W1 fixed |
| `check_review_r022_numbers.py` (N1) | 14 ok; 2 BAD (29 vs 25, 0 vs 26) | cannot pass: it embeds the P-022 claims that N1 showed wrong |
| `check_report2_numbers.py` (replacement) | **5/5 ok** (25; 13 + 13; 28 rechecks, 14 broken, 0 not run) | N1 fixed |
| `run_skipkeys.py` | 12/12 ok. The first attempt stopped on an HTTP 429 from Maven Central; it passed on rerun | |
| `run_controls.py` | JUnit 5 Gradle 40/40, Maven 40/40, JUnit 4 Maven 10/10. JUnit 4 Gradle 6/10 on the first run (the four "unchanged" tests were `missing` in the first run without `--det`), **10/10 on rerun**. Fingerprints identical in every case | environment (like R-022's 429) |
| `cargo test -p fenvix-jvm -p detpy-core -p fenvix-skip` | 44 + 2 + 10 passed | |

**Is "cannot exit 0 by construction" a way around the bar? No.**
* `run_review_r022_walk.py` asserts that the walk labels `rv.VictimTest::flagIsOff()` **wrong**. The walk can only label a test it reused. VictimTest follows the new `PolluterTest`, which does a `PUTSTATIC Flag.on`: the same shape as S2's `new-writer-test`, which `run_review_r022.py` requires to be decided RUN. The two scripts cannot both pass with any sound decider. (Their conflict comes from the review: the walk test was written against the unfixed decider.) The replacement `run_w1_verifier.py` keeps the reviewer's repository and commits: it imports `POLLUTER` and `git` from the reviewer's script. It forces the wrong reuse with an adversarial "reuse everything" decider and checks the reviewer's assertion (wrong, not flaky) plus the suite-rerun evidence. It also unit-tests the classifier: fail-alone → wrong, pass-alone and suite fails → wrong, pass-alone and suite passes → flaky. Same intent, stricter.
* `check_review_r022_numbers.py` hard-codes the claims under test (29, 0). Its two BAD lines say that P-022's claims disagree with the data, which is the finding itself. The fix is to correct the claims, and that makes the script's constants stale, not wrong. `check_report2_numbers.py` reuses the reviewer's `summaries()`, `RES` and project list, and repeats the same two computations against REPORT-2's corrected claims. It does not repeat the reviewer's other 14 checks, which still pass in the original script. It does not check REPORT-2 §4 (walks): I re-derived those separately (§5).

## 2. New wrong reuses (MEASURED, `run_review_r022b.py`, JDK 21, Gradle)

| # | scenario | writer change (writer is rerun: `code`) | reader, reused | fresh outcome of the reader in B | why the key misses it |
|---|---|---|---|---|---|
| **S12** | `resource-bundle-cache` | `rvmsg.properties`: `greeting=hello` → `hi` (MsgATest reads the bundle first: rerun, `file`) | `rv.MsgBTest::read()` | **failed** | `ResourceBundle.getBundle` caches per (name, loader) for the life of the JVM. Only the first test that loads the bundle reads the resource. The reader's capture is `classes=[rv/MsgBTest]`, `resources=[]`, `mut=false`: the bundle is in no part of its key. This is the S3 clinit shape again, inside a JDK cache. |
| **S12** | `introspector-cache` | `Bean` gets a third property (BeanATest introspects it first: rerun, `code`) | `rv.BeanBTest::read()` | **failed** | `java.beans.Introspector` caches `BeanInfo` per class. The reader hits the cache, so no reflective call runs and the S4 hooks see nothing. `Bean.class` as a constant (LDC) is not recorded either. The reader's capture is `classes=[rv/BeanBTest]`. The same applies to any JDK cache filled by an earlier test: `MethodType`/`ClassValue` caches inside the JDK, `ObjectStreamClass`, and the JUL `LogManager` configuration read once. |
| **S13** | `jul-root-level` | `Logger.getLogger("").setLevel(OFF)` | `rv.JulBTest::read()` | **failed** | JDK global state reached through static methods. The test runs no `GETSTATIC` in code under test, so it is not `mut` and the order rule never applies. Not listed in REPORT-2 §6. |
| **S13** | `locale-default` | `Locale.setDefault(de_DE)`; `LocaleCTest`, which runs after the reader, restores `en_US` | `rv.LocaleBTest::read()` | **failed** | Listed in REPORT-2 §6 as not keyed. When the leak lasts to the end of the JVM, the `jvm` record's `runtime.locale` (an end-of-JVM value) changes and **every** test reruns (`runtime`, measured in a first version without `LocaleCTest`): sound but costly, and only in measurement mode. One restoring test later in the JVM makes the end states equal, and the reader is wrongly reused. |
| **S14** | `context-class-loader` | `Thread.currentThread().setContextClassLoader(<empty loader>)` | `rv.TcclBTest::read()` | **failed** | Per-thread state of the runner thread, which runs every test of the JVM. The reader's capture records the resource it found through the context loader in A (`rv-tccl.txt=root:build/...@file:…`) and is reused in B, where the context loader no longer finds it. Frameworks use the context class loader (`ServiceLoader.load(Class)`, JAXB, Spring, logging back ends). The thread name and the runner thread's other state go through the same channel. |

Attempts that held (MEASURED, same script):
* `clinit-null-read` (class initialisation order). The `GETSTATIC` in `Reg.size()` first runs inside `Reg.<clinit>`, before `ITEMS` is assigned, and sees `null`. I expected the site to be cached as "constant" (`Deps.staticRefRead` decides `constant` once per site). The reader was still `mut=true` and decided RUN (`after`). Held.
* `property-via-jdk`: a property written by one test (`System.setProperty`) and read by another through JDK code (`Boolean.getBoolean`). The reader records `props={rv.flag: unset}` and is decided RUN (`after`). Held.
* Checked by reading the code, not run. A `static final ThreadLocal` read by user code is `mut`: the runtime class is JDK and not an enum, so `immutableValue` returns false. Reflective static reads (`Field.get`) and `findStaticGetter`/`findStaticVarHandle` set `mut`. Static state in library jars (Spring's context cache, AssertJ configuration, `ClassValue` held in a static) is instrumented like project code, because infrastructure is decided by jar name (S11). Not attempted: JNI from a dependency (covered by the S9 hook on `Runtime.load0/loadLibrary0` from non-JDK code), and Spring itself (not in this container).

**What would make the claim true** (suggestions):
* S12: hook the JDK caches that hide inputs, and record their inputs on **every** call, hit or miss: `ResourceBundle.getBundle` (name, locale, loader → the bundle's resource or class), `Introspector.getBeanInfo` (the bean class and its supertypes), `ObjectStreamClass.lookup`. Or treat a cache hit like `<clinit>`: store the inputs of the call that filled the entry and add them to every later scope that hits it (`Deps.INIT` already does this for class initialisers).
* S13/S14: a call to a JDK global or runner-thread setter is a shared-state write that **every** later test in the JVM depends on. It is not enough to mark it `swrite`, because a reader that reads the state only through JDK methods is not `mut`. The setters: `Locale.setDefault`, `TimeZone.setDefault`, `Logger.setLevel`/`addHandler`/`LogManager.*`, `System.setOut/setErr/setIn`, `Security.addProvider/insertProviderAt`, `URL.setURLStreamHandlerFactory`, `Thread.setContextClassLoader`/`setName`/`setDefaultUncaughtExceptionHandler`, `Authenticator/ProxySelector/CookieHandler.setDefault`, `HttpURLConnection.setFollowRedirects`. When a test calls one, every later test in its JVM is ordered behind it, as if each were `mut` and the setter test had touched shared state. The rule stays sound and costs nothing in projects that never call these setters.

## 3. The soundness cost: is the shared-state rule broader than needed?

Measured on single captures at the last walk commit of each repository (JDK 21, agent 342fea5; `results-2/mut-*.txt`, `mut-*.json.gz`):

| capture | tests | `mut` | blamed most (tests) |
|---|---|---|---|
| gson 7c6a315 | 4,722 | **4,672 (98.9%)** | Guava testlib `CollectionSize` 3,170; Guava `RegularImmutableList` 1,442; Truth `Truth` 1,436; `Subject$ComparisonResult` 1,229; `Excluder` 950; `SqlTypesSupport` 938; `TypeAdapters`/`ObjectTypeAdapter`/`NumberTypeAdapter` 937; `GsonBuilder` 928; `JsonWriter` 583 |
| jsoup 84ca201 | 2,113 | **1,981 (93.8%)** | `CharacterReader` 1,888; `StringUtil` 1,848; `QueryParser` 1,712; `TokenQueue` 1,708; `HtmlTagOptions`, `Tag`, `SharedConstants`, `Element`, `Entities`, `TagSet` ≈ 1,500–1,650 each |

REPORT-2's "4,570 of 4,612 gson tests `mut`" has no committed capture behind it (UNKNOWN as committed). This capture gives a similar share.

**Over-broad cases.** These can change nothing after initialisation, the capture still calls them mutable, and a sound refinement exists. Probe `run_r022b_cost_probe.py` (MEASURED; `results-2/review-r022b-cost.json`):

| probe (reads only…) | `mut` now | provable how | `mut` with the experiment |
|---|---|---|---|
| `Color.values()` (user enum) | **yes**: `$VALUES` is a non-empty array | javac pattern: a `private static final synthetic` array, read only in `values()` and followed by `clone()`. Verifiable at transform time | no |
| `static final Holder HOLDER`, a non-final class with only final fields whose values are again final-only | **yes**: `refFields` require a *final declared* type | check the **runtime value** deeply over final fields (user classes; empty arrays; the JDK immutable list) | no |
| `static final Function LEN = String::length` (non-capturing lambda) | **yes**: hidden class with no `Info` | same deep runtime check (reflection over the hidden class's final fields) | no |
| `List.of("a","b")`, `Optional.of("x")` | **yes** | JDK value-based immutables. Need a JDK whitelist plus a deep check of the elements | yes (not in the experiment) |
| enum constant, enum `switch` | no | — | no |

**Experiment** (`results-2/cost-experiment.patch`, review only, not on the product branch). (R1) a deep runtime check over final fields for user classes, allowing the field-less JDK bases `AbstractCollection`, `AbstractSet`, `Number`. (R2) `$VALUES` treated as constant. JDK classes are never deep-checked: `ThreadLocal` has only a final `int` field, and passing it would be unsound. Results (MEASURED):
* Soundness: `run_review_r022.py` with the experimental agent: **13/13 ok** (`results-2/exp-run_review_r022.log`).
* gson: `mut` **4,672 → 4,432** (−240 tests, 5.1%): Truth, `RegularImmutableList.EMPTY`, `ComparisonResult`, `JsonToken.$VALUES`, the number adapters. jsoup: **no change** (1,981 → 1,983, another capture).

**What dominates instead.** Static state that is mutable by type, and that the code under test uses read-only or in a way that does not change results:
* gson: Guava testlib `CollectionSize` enum constants, which hold a `LinkedHashSet` (`implied`) that `getImpliedFeatures()` hands out. It is the **only** blocker left for 3,107 of the 4,432. Also `Excluder.DEFAULT` (non-final fields, copy-on-write by convention) and `GsonBuilder.DEFAULT` (a builder).
* jsoup: buffer pools, `SoftPool<char[]>`/`SoftPool<String[]>`/`SoftPool<StringBuilder>` in `CharacterReader` and `StringUtil` (contents rewritten by every user), and the `TagSet.HtmlTagSet` registry. The private read-only `char[]`/`String[]` tables (`QueryParser.Combinators`, `TokenQueue.ElementSelectorChars`, `Entities`) are provable with an intra-class bytecode check: never stored to outside `<clinit>`, never escaping. But every test that uses them also reaches a pool.

**Recommendation for the product.**
1. Do R1 + R2, and add private read-only static arrays (a bytecode check of the declaring class) and JDK value-based immutables with element checks (`List/Set/Map.of`, `Optional`). They are sound and cheap, but worth about 5% on gson and about 0% on jsoup (MEASURED / ESTIMATED as above). They will not change the walks' medians.
2. The lever that matters is dynamic, as REPORT-2 §6 suggests: compare the **state** a reader reads, not whether someone touched it. Take a digest of the object graph reachable from the static fields the test read, at its start in A and at its position in B. That frees `CollectionSize`, `Excluder` and `GsonBuilder`, whose state does not change (ESTIMATED: these graphs are small and contain no buffers). A digest cannot free pools, whose contents do change: they need a **declared, opt-in** list of "result-neutral" state (pools, memo caches), labelled DECLARED and never presented as proof. Measure the online cost before promising it.
3. Do not relax by intersecting per-class `mut_classes` without an aliasing check: two static roots can reach the same object.

## 4. D5 (fingerprints under load)

* Reproduced here: `run_review_r022_det.py` `fingerprints-under-load` BAD in 1 of 3 pairs, on `fixedRateTicksWithoutWaiting` (MEASURED). `run_d5_load.py` in REPORT-2: 4/5 on the new agent, 5/5 on the P-022 agent (committed JSON, re-read). As REPORT-2 says, that is not distinguishable at this sample size.
* Mechanism (`VirtualScheduler.loop`, lines 225–246). A task whose virtual due time has not come is fired early only when the pool is idle and the system is `settled`. Otherwise the scheduler waits in real-time slices up to the virtual remaining delay, then advances the clock and fires. After the 5th tick, the test thread must reach `shutdownNow()` within 1 s of **real** time. A thread descheduled that long under load lets a 6th tick fire. Whether it does depends on the interleaving of two threads in real time. Removing the fallback would deadlock busy-wait code (V16). This is a Level 1 limit (V3/V6 family), **not a hidden defect**.
* **Not documented where users look:** it appears only in REPORT-2 and in the test's docstring. `docs/JVM.md`'s limits table (V1–V18) has no entry for it (§6, finding 4).

## 5. Numbers in REPORT-2 re-derived (MEASURED from committed data)

* §3 recheck table: all 28 rows match `summary.json` / `recheck.json` / `recheck-r022.json` / `tests.json`. Columns: P-022 round, P-022 recheck, broken now, not run before, not run now. Totals 25 → **14**, not run 13 → **0**. `check_report2_numbers.py` agrees.
* §4 walks, from `results/skip-local{,-r022}/*/shard0.json`. jsoup: 50 transitions, median/mean test time skipped 0.0479/0.2260 (**5% / 23%** ✓), median tests skipped 0.0759 (**8%** ✓), verified 17,572, 0 wrong, 0 flaky; rerun reasons `after` 44,388, `code` 19,936, `after-new` 11,201, `order` 1,604 ✓. gson: 0.1210/0.4205 (**12% / 42%** ✓), tests 0.0168 (**2%** ✓), 93,219, 0, 0; `after` 73,918, `code` 27,830, `after-new` 4,091 ✓. P-022 rows: jsoup 0.7660/0.5650, 71,952 ✓; gson 0.8417/0.6468, 171,571 ✓ (median tests skipped 90.50%, printed 91%: rounding).
* §4 "by kind of transition": there is no committed script. Classifying transitions by the P-022 walk's reasons (≥90% `runtime`+`config` = global; else any `code` = code change; else none) reproduces jsoup exactly (18: 80% → 55%; 28: 64% → 1.5%; 4 global). For gson it gives 19 / **24** / 7 (REPORT-2 says 19 / 21 / 10), with code-change medians 52.6% → 0.5% (REPORT-2: 54% → 0.5%). The conclusions hold. Label: the split should name its rule or be marked ESTIMATED.
* §1 numbers: cargo 44 + 2 + 10 ✓; `d5-load.json` 4/5 and `d5-load-p022-agent.json` 5/5 ✓; "fingerprints-under-load 3/3" was 2/3 here (§4, D5 open).
* Statement labels. "Already failing in the baseline: excelastic, openhtmltopdf" means 1F/9P in the baseline and 10F/10 under `--det`. They are counted in the 14, which is correct, but "already failing" reads as "not our problem": `--det` turns an occasional failure into a constant one. Better: "unstable in the baseline, pinned failing by `--det`".

## 6. Findings (FIX list)

Skip with proof: wrong reuse, each a failing scenario in `jvm/test/run_review_r022b.py`.
1. **S12. JDK-internal caches hide inputs from every test after the first.** `ResourceBundle.getBundle` (`resource-bundle-cache`) and `Introspector.getBeanInfo` (`introspector-cache`): the reader is reused and fails in B.
2. **S13. JDK global state reached through static methods is not keyed.** `Logger` level (`jul-root-level`, not in REPORT-2 §6); `Locale.setDefault` restored by a later test (`locale-default`; §6 lists it, but the end-of-JVM `runtime.locale` only catches leaks that last to the end of the JVM). The reader is reused and fails in B.
3. **S14. The runner thread's own state is not keyed.** `setContextClassLoader` (`context-class-loader`): the reader is reused and fails in B.

Documentation (failing check `jvm/test/check_r022b_docs.py`, 6/6 BAD):
4. **DOC.** `docs/JVM.md` is unchanged since before R-022. Its "Skip with proof" section still says `fenvix_skip.py` decides and gives the old rule: only "static fields last written by an earlier test". It does not describe the shared-state rule, class lookups/`getResources`, or processes and native code being not reusable. Its limits table does not list the D5 residual (virtual scheduler real-time fallback under load, Level 1) or the inputs that are still not keyed (REPORT-2 §6, plus S12–S14 above). REPORT-2 says D5 is "documented with the test". It is documented in the report and a docstring, not in the user-facing limits.

Not counted:
* The two reviewer scripts that cannot exit 0 (§1): the claim is true and the replacements test the same intent.
* D5: a Level 1 limit, apart from its documentation, which is finding 4.
* The soundness cost (§3): a product question, with evidence and a recommendation.
* REPORT-2 "7/7" for the `--det` script, "4,570/4,612 `mut`" (no committed capture), and the gson per-kind split: labels (§5).
