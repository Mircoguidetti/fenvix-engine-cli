# fenvix-jvm — Level 0 and skip with proof for Java and Kotlin (JUnit 5, JUnit 4; Gradle, Maven)

The JVM counterpart of `detpy` (pytest) and `detjs` (Vitest, Jest): the same Rust
core (`crates/detpy-core`) through JNI (`crates/fenvix-jvm`), a Java agent that
rewrites bytecode, a JUnit Platform listener (and a JUnit 4 run-listener hook),
a Gradle init-script plugin and a Maven core extension. Traces have the same
format: `fenvix-jvm verify`, `detpy verify` and `detjs verify` read each other's.

```bash
jvm/build.sh                                   # cargo build -p fenvix-jvm + mvn package -> jvm/dist/fenvix-agent.jar
java -jar fenvix-agent.jar run --det -- ./gradlew test         # Gradle (init script)
java -jar fenvix-agent.jar run --det-seed=7 -- mvn test        # Maven (core extension), reproducible shuffle
java -jar fenvix-agent.jar run --det --deps -- ./gradlew test  # + skip-with-proof capture (.fenvix/deps/*.jsonl)
java -jar fenvix-agent.jar verify .fenvix/run1.jsonl .fenvix/trace.jsonl
python3 jvm/skip/fenvix_skip.py decide A/deps B/deps --root-b .  # which tests of run A are reusable now
```

Options: `--det`, `--det-seed=N` (implies `--det`; 0 = fixed order), `--deps`,
`--det-disable=random,time,fs,net,sched`, `--det-allow-host=h`, `--out=DIR`.
Without the wrapper: `-javaagent:fenvix-agent.jar=det=1,seed=N,out=DIR,root=DIR`
on the test JVM (system properties `fenvix.*` win over agent options).

## Layout

```
crates/fenvix-jvm        JNI bindings: recorder (packed events, as detjs), verify/verifyText (JSON or text),
                         deriveSeed, shuffleIndices, orderDigest, digest, digestFile (streamed BLAKE3), mergeTraces
jvm/rt                   runtime, on the bootstrap class path of the test JVM (no dependencies, Java 8 bytecode)
  Det                    controls: virtual clock, sleeps and timed waits, seeds, fs order, closed network, env/props
  VirtualScheduler       ScheduledExecutorService on virtual time
  JdkRandoms             reseeds the JDK's hidden generators (Math.random, Collections.shuffle, TLR, SplittableRandom)
  Deps, Lifecycle        skip-with-proof capture, runtime identity, configuration, trace header
jvm/agent                -javaagent (ASM 9.8, shaded), JUnit listener/orderers, JUnit 4 hooks, CLI
  CallSiteRewriter       rewrites call sites in code under test (+ per-class coverage probes for --deps)
  JdkHooks               method-body hooks in a few JDK classes (retransformed at start-up)
  RunnerHooks            JUnit 4: RunNotifier (brackets), ParentRunner (seeded children order)
jvm/gradle/fenvix.init.gradle   Gradle wiring (an init-script Plugin<Gradle>)
jvm/maven-ext            Maven core extension (rewrites the Surefire configuration)
crates/fenvix-skip       proof rule (Rust): decides reuse from a capture and the current state
jvm/skip/fenvix_skip.py  its Python interface
jvm/test                 control tests, skip-key tests, Level 1 measurement
jvm/harness              IDoFT round, skip walk (GitHub Actions)
```

## How a `--det` run works

1. The CLI adds the wiring: Gradle `--init-script fenvix.init.gradle -Dfenvix.*`, Maven
   `-Dmaven.ext.class.path=fenvix-maven-ext.jar -Dfenvix.*`. The wiring adds `-javaagent` to every
   test JVM and makes the run serial: Gradle `maxParallelForks = 1`, `forkEvery = 0`, test tasks never
   up to date or from the build cache; Maven `forkCount=1`, `reuseForks=true`, no `parallel`,
   `runOrder=alphabetical` (seed 0) or `random` with `runOrderRandomSeed` (seed N, JUnit 4 class order).
   JUnit Jupiter parallel execution is switched off. Recorded in `meta.isolation`, `meta.serial`.
2. In the test JVM the agent extracts the runtime jar and the native library (content-addressed
   directory), appends the runtime to the bootstrap class path, loads the Rust core, opens
   `java.lang`, `java.util`, `java.util.concurrent` to the runtime (Java 9+), installs the
   transformers and retransforms the hooked JDK classes.
3. JUnit Platform (Jupiter, Vintage, other engines): a `TestExecutionListener` (ServiceLoader, agent
   jar) opens one trace part per test plan, brackets each test (`executionStarted`/`Finished`):
   reseed, wall clock reset, fingerprint, outcome. JUnit 4 runs (Surefire's junit4 provider,
   Gradle `useJUnit()`): a `RunListener` attached by a hook in `RunNotifier` at its first event.
4. The CLI merges the parts (Rust `merge_traces`) into `<out>/trace.jsonl`, in start order.

Test ids: `<class>::<method>(<parameter types>)`, `[n]` for template/dynamic invocations,
`::Inner::` for `@Nested` classes, JUnit 4 `<class>::<method>`; a module (Gradle project path,
Maven artifactId) prefixes the id when the build has several. Events follow the shared vocabulary:
`op` = the Java API name (`System.currentTimeMillis`, `Instant.now`, `Thread.sleep`,
`UUID.randomUUID`, `File.list`, `connect`, `dns`, `sched.timer`), `site` = the source file relative
to the repository root and line, known at rewrite time (no stack walk), header `meta` with
`runtime=jvm`, `runtime_version`, `runner` (`junit-jupiter`, `junit-vintage`, `junit4`, ...), `seed`,
`controls`. `event.rs` and the encoding are unchanged.

## Controls

"Code under test" = every class not loaded by the bootstrap/platform loader and not test
infrastructure (JUnit, Gradle worker and the Gradle distribution's bundled libraries, Surefire,
JaCoCo, fenvix). Infrastructure keeps real time (JUnit's `@Timeout` and `assertTimeoutPreemptively`
stay real), as pytest plugins and runner frames do in Python and Node.

| # | control | how |
|---|---|---|
| 1 | order | Jupiter: `junit.jupiter.testclass.order.default` = `DetClassOrderer` (seed 0: class name order; seed N: SplitMix64 shuffle of the Rust core, `shuffle_indices`, key `classes:<module>`), `junit.jupiter.testmethod.order.default` = `DetMethodOrderer` (seed 0: Jupiter's own default order, which also overrides a project-wide random orderer; seed N: shuffle, key = class), `junit.jupiter.execution.order.random.seed` fixed (classes annotated `@TestMethodOrder(Random)`). JUnit 4: `ParentRunner.getFilteredChildren` shuffled with seed N (key = runner description); class order by Surefire `runOrder` (Gradle `useJUnit()`: Gradle's scan order, limit V7). Executed order in the trace. |
| 2 | random | `new Random()` and `new SplittableRandom()` in code under test get a seed from a per-test stream (`derive_seed(seed, test id)`); `Math.random`/`StrictMath.random`, `Collections.shuffle(List)`, `SplittableRandom`'s and `ThreadLocalRandom`'s seed generators and the test thread's `ThreadLocalRandom` state reseeded at every test; `ThreadLocalRandom.current()` in code under test seeds the calling thread's state once per test (pool threads included, key = logical thread number); every `SecureRandom.nextBytes`/`generateSeed` (so `new SecureRandom()`, `getInstance(...)`, `getInstanceStrong()`, `UUID.randomUUID()`) draws from a seeded stream (JDK hook: covers JDK-internal callers too, unlike Python and Node where OS entropy is only observed). |
| 3 | virtual clock | `System.currentTimeMillis`, `System.nanoTime`, `Instant.now`, `Clock.systemUTC/systemDefaultZone/system(zone)` (a `DetClock`), `LocalDate/LocalDateTime/LocalTime/ZonedDateTime/OffsetDateTime/OffsetTime/Year/YearMonth/MonthDay.now()` and `now(zone)`, `new Date()`, `Calendar.getInstance(...)`: one virtual ns counter, 1 µs tick per read, adaptive tick (after 1000 consecutive reads with no other event every read doubles the tick, up to 1 s, as detjs). Wall clock restarts at 2025-01-01Z at every test; `nanoTime` never goes backwards; events record times relative to the test start. |
| 4 | sleeps and timed waits | `Thread.sleep` (all overloads), `TimeUnit.sleep`: the virtual clock moves to (virtual time at the start of the sleep + the requested time), so concurrent sleeps overlap instead of adding up; the thread sleeps for real, in 10 ms slices re-checked, only while another thread of the test may be working (Python's rule), and while any thread sleeps for real the adaptive tick does not accelerate (found on marine-api: a reader thread polling the clock raced ahead while the test slept). "Working" = a thread created after the infrastructure baseline that is RUNNABLE, BLOCKED, sleeping for real, or in a timed wait outside fenvix's wrappers; idle JDK pool threads (only JDK frames), threads waiting in infrastructure (JUnit) and threads in a rewritten timed wait count as idle. Untimed `CountDownLatch.await()`, `Future.get()`, `BlockingQueue.take()`, `Thread.join()` and the timed waits are tracked with what they wait on: a waiter whose condition already holds (latch at zero, future done, queue not empty, thread ended) counts as about to run, not idle. Timed waits (`Object.wait(ms)`, `LockSupport.parkNanos`, `CountDownLatch.await`, `Condition.await/awaitNanos`, `Future.get`, `BlockingQueue.poll`, `ExecutorService.awaitTermination`, `Thread.join(ms)`) wait for real and, when they time out, advance the virtual clock by their timeout, so deadline loops end. |
| 5 | scheduled executors | `Executors.newScheduledThreadPool(...)`, `newSingleThreadScheduledExecutor(...)` in code under test return a `VirtualScheduler`: tasks ordered by (virtual due time, creation), fired one at a time; when every other thread is idle and no pending timed wait would time out first, the clock jumps to the due time and the task fires at once (checked twice 2 ms apart, so that a thread just woken by the previous task can run); otherwise the dispatcher waits for real. 100 000 fast firings per test at most (periodic tasks never cancelled). Each firing is a `sched.timer` event. `new ScheduledThreadPoolExecutor(...)` and `java.util.Timer` are not virtual (limit V4). |
| 3b | file timestamps | `File.lastModified`, `setLastModified` and NIO `lastModifiedTime`/`lastAccessTime`/`creationTime` read or written by code under test are shifted by (virtual wall clock - real wall clock) at the test's start, so "older than N days" logic compares like with like (found on eBay/mTracker: a virtual 2025 clock against real 2026 file times broke 2 tests). |
| 6 | filesystem order | `File.list`/`listFiles` (JDK hook on `File.normalizedList`, or `File.list` on JDK 8-16) and every NIO directory stream of the default file system (`Files.list`, `newDirectoryStream`, `walk`, `find`, `walkFileTree`: hook on `UnixFileSystemProvider.newDirectoryStream`, read eagerly) come in name order. |
| 7 | closed network | `Socket.connect` (so `HttpURLConnection` and every socket client), `SocketChannel.connect` (NIO, `java.net.http.HttpClient`) towards a non-loopback address, and DNS lookups (`InetAddress.getByName/getAllByName`) of non-local names fail (`ConnectException`, `UnknownHostException` naming fenvix). Loopback allowed; `--det-allow-host`; a connection to the configured HTTP(S)/SOCKS proxy (system properties or `*_PROXY`) counts as external. Record/replay is not built for the JVM (limit V5). |
| 8 | fingerprint | each interaction is an event `(source, op, site, value)`, buffered in Java and sent to the Rust core in batches (`recordPacked`), BLAKE3 hash chain per test. |
| 9 | isolation | serial execution, recorded (above). Threads are not ordered (Level 1, measured: `jvm/test/run_l1_measure.py`). |

`--det-disable=random,time,fs,net,sched` turns controls off one by one (ablation).

## Identity hash codes, HashMap/HashSet order (documented, MEASURED locally)

`HashMap`/`HashSet` iteration over keys that use `Object.hashCode()` (identity hash: plain objects,
enums, `Class`, lambdas) depends on identity hash codes. HotSpot's default generator
(`-XX:hashCode=5`) is a thread-local xorshift seeded from a global pseudo-random sequence: the
codes are the same in every run *as long as the same threads are created in the same order and
each thread requests codes in the same order*. Measured (`/tmp`, JDK 21, 5 JVMs per case): a
program printing a `HashSet` of 20 `Object`s and of 12 enum constants gave one iteration order in
5/5 runs; the same program after starting 3 helper threads gave another order, again 5/5. So:
under `--det` (fixed order, serial) such iteration is reproducible in practice; a different seed
(other tests run earlier on the test thread) or a different number of threads started before can
change it. `-XX:hashCode=2` (all codes = 1; experimental flag) makes it independent of history but
turns every identity-keyed map into a list (not enabled). The fingerprint does not include hash
codes. NonDex-style ("ID") flakiness, where the JDK's iteration order itself is randomised, is not
in Level 0's scope.

## Skip with proof (`--deps`)

The capture is `jvm/rt/Deps.java` (+ `JdkHooks`, `CallSiteRewriter`); the decision is Rust,
`crates/fenvix-skip` (binary `fenvix-skip`, built by `jvm/build.sh`); `jvm/skip/fenvix_skip.py` is only
its Python interface. A test of run A is reused in the current state B when **all** of the following
hold (the decider's doc comment, `crates/fenvix-skip/src/lib.rs`, is the reference):

* it **passed** in A, wrote no file it could read back, made no external network attempt;
* **child processes and native code**: a test that started a child process (`ProcessBuilder.start`),
  loaded a native library from non-JDK code or called a native method of the project is not reusable
  (their inputs are invisible to the capture);
* **code**: every class one of whose methods ran, whose static fields it read or wrote (owner and
  declaring class, resolved like the JVM does), whose static initialiser it depended on (what a
  `<clinit>` read is added to every later scope that touches the class) or whose reflective metadata
  it read (`getAnnotation*`, `getDeclared*`, `MethodHandles.Lookup.find*`, annotation types parsed for
  it) has the same class-file digest (BLAKE3) in B; also those of its class container (`@BeforeAll`);
* **class lookups** by name (`Class.forName`, `ClassLoader.loadClass`): still found, or still absent;
* **classpath resources**: every `getResource` resolves to the same first location and content (or is
  still absent), every `getResources` (ServiceLoader, factories) returns the same locations in the
  same order; lookups through another class loader are not keyable (never reused);
* **files** read (content digest), probed (existence/type), listed (names); reads made by the test
  infrastructure inside a test (`@CsvFileSource`, ...) count;
* **environment variables and system properties** read: same value (properties no test writes are
  compared at JVM start; properties tests write are shared state, below);
* **JDK caches**: a call of `ResourceBundle.getBundle`, `Introspector.getBeanInfo` or
  `ObjectStreamClass.lookup` runs inside a frame; what the call that filled the cache entry depended
  on (the bundle's resources and class lookups, the bean's reflected classes) is added to every test
  that makes the call later, cache hit or miss;
* **runtime identity and configuration** of its JVM are the same (JDK, flags, build tool, plugins,
  JUnit configuration parameters, class path order);
* **shared state** (the order rule). A test that read *mutable static state* (`mut`: a non-final static
  field, or a final one whose value is not deeply immutable) or a system property some test writes,
  is reused only if every test before it in its JVM in B is reused or, rerun or new, touched no shared
  static state when it ran in B, and the state-touching tests before it are the same, in the same
  order, as in A. The decision is taken at the test's position in B. Tests of a class with one shared
  instance (Jupiter `PER_CLASS`, TestNG, other engines) depend on every earlier test of the class.
  A final static counts as immutable when its value is: a primitive wrapper, `String` and other
  immutable JDK value types, an empty array, a JDK enum constant, `List/Set/Map.of` and `Optional` of
  immutable elements, or an object of a user class whose instance fields are all final and again hold
  immutable values (checked on the value, so a non-final class, a record or a non-capturing lambda
  qualifies); an enum's `values()` reads its private synthetic `$VALUES` and returns a copy, so it is
  immutable when the constants are; any other JDK object (`ThreadLocal`, atomics, collections) is mutable;
* **JDK global and runner-thread state** (the same order rule, per channel). JVM-global state that tests
  reach only through JDK methods is keyed by channel: `locale` (`Locale.setDefault`/`getDefault`),
  `timezone`, `tccl` (`Thread.set/getContextClassLoader`), `thread.name`, `uncaught-handler`, `jul`
  (`Logger`/`Handler`/`LogManager` levels, handlers, configuration), `stdio` (`System.setOut/setErr/setIn`;
  reads are `System.out/err/in` in code under test), `security` (providers and security properties;
  every `getInstance` reads the provider list), `url-handlers`, `net-defaults` (`Authenticator`,
  `ProxySelector`, `CookieHandler`, `ResponseCache`, `SSLContext`, redirects, HTTPS defaults), `jdbc`
  (`DriverManager` drivers), and `interrupt` (a test that leaves the runner thread interrupted; every
  test reads it). A setter that changes the value is a write; a getter called inside a test or class
  scope, by any code (the JDK and the runner included, except the runner's own JUL level checks and
  thread names), is a read. A reader of a channel is reused only if the tests before it that wrote the
  channel are reused and the same, in the same order, as in A, and no rerun or new test before it wrote
  it in B. Writes by code under test outside every test (a static initialiser at discovery) make every
  reader of the channel rerun.

The decider runs in measurement mode: it reads B's capture of the tests rerun before a test, which an
online decider in the runner has at that test's position (not built yet).

## Known limits

Found by the tests (**T**), by the harness (**H**) or by design (**D**).

| # | limit | found |
|---|---|---|
| V1 | Only call sites in code under test are rewritten: JDK code that reads the clock itself (`java.util.logging` timestamps, `Timer`, `ScheduledThreadPoolExecutor` internals, `CompletableFuture.orTimeout`) keeps real time. Randomness is wider (JDK hooks). | D |
| V2 | Native code, child processes (`ProcessBuilder`) and other JVMs are not controlled. | D |
| V3 | Threads are not ordered (Level 1): a test racing threads can still differ; Level 0 makes each thread's own clock reads, randomness and listings deterministic but not their interleaving. Kotlin coroutines on `Dispatchers.Default/IO` are threads; `runTest` has its own virtual time and is unaffected. | D |
| V4 | Virtual timers only for executors created through `Executors.newScheduledThreadPool`/`newSingleThreadScheduledExecutor` in code under test; `new ScheduledThreadPoolExecutor`, `java.util.Timer`, Netty/Reactor schedulers keep real time (their sleeps and parks are still rewritten where they are in library code). | D |
| V5 | No network record/replay (Python and Node have cassettes): the network is closed or allowed per host. | D |
| V6 | The "quiet" decision (fast sleep and timers) samples thread states: a thread woken but not yet scheduled can look idle; the scheduler looks twice 2 ms apart, sleeps once. | T |
| V7 | Gradle with JUnit 4 (`useJUnit()`): class order is Gradle's scan order (computed in the Gradle daemon), not controlled; methods are. | D |
| V11 | JUnit 4 seeded shuffle: `ParentRunner.getFilteredChildren` is called many times; the reordering is cached per children collection (found on marine-api: 5x slower seed runs before the cache). | H |
| V12 | Events of threads born in an earlier test (leaked readers, shared pools created outside tests) are not part of the current test's fingerprint (they stay controlled; counted, not hashed). Found on marine-api: a reader thread leaked by one test made 63 later tests' fingerprints unstable. A pool thread first used by an earlier test therefore contributes no events to later tests. | H |
| V13 | JDK classes loaded by the application loader (JDK 8 `tools.jar`, the attach API) are never rewritten (found on incubator-seata: the attach retry loop ran on virtual time and Mockito's inline mock maker failed, 34 tests). | H |
| V14 | Maven: when JaCoCo is declared, `@{argLine}` is kept and an empty `argLine` property is defined if the project has none (found on junit-quickcheck: Surefire 2.x passed a literal `@{argLine}` and the test JVM did not start). | H |
| V15 | Jupiter parallel execution is forced off under `--det` and `--deps` by a hook on `isParallelExecutionEnabled()` (found on jsoup: parallelism enabled through Surefire `configurationParameters` interleaved the per-test scopes of the capture). | H |
| V16 | A loop polling the clock while another thread works (a busy deadline loop) gets a clock that follows real time instead of the adaptive acceleration (found on commons-lang `MultiBackgroundInitializerSupplierTest`: the 3 s deadline passed before the background threads started, under load). Its clock values are then timing-dependent (Level 1). | H |
| V17 | A JDK timer thread (`java.util.Timer`, a scheduled pool worker) waiting for its next task counts as working, so `Thread.sleep` waits for real while a timer is pending (found on java-cas-client: a 250 ms `Timer` and `Thread.sleep(500)`; the infrastructure's own schedulers are excluded). | H |
| V18 | A sleep is fast only if no other thread's timed wait would expire before it ends (found on alibaba/asyncload: a worker's 1 s sleep ended before the test's 300 ms `Future.get` timeout). | H |
| V8 | Fingerprints of timer-driven tests depend on the per-test virtual clock; a background thread left running by an earlier test that reads the clock during a later test changes that test's clock values (found by the control tests: a preemptive-timeout thread that kept sleeping). | T |
| V9 | `SecureRandom` subclasses that override `nextBytes` without calling `SecureRandom.nextBytes` (third-party providers) are not seeded. | D |
| V10 | Identity hash codes are not controlled (see above). | D,T |
| V19 | **D5, Level 1**: the virtual scheduler fires a timer whose virtual due time has not come only when the pool is idle and the run is quiet; otherwise it waits in real-time slices and then fires (real-time fallback, needed for busy-wait code, V16). Under heavy load a test thread descheduled for that real time lets an extra periodic tick fire, so the fingerprint of a fixed-rate timer test can differ between two runs (`SchedControlTest::fixedRateTicksWithoutWaiting`: 1 of 5 loaded pairs, `jvm/test/run_d5_load.py`). Not fixable at Level 0. | T |
| V20 | **Skip with proof, inputs not keyed** (a test reading only these can be reused wrongly): objects shared through JUnit extension stores; writes to static fields through `Unsafe` or `VarHandle`; type annotations (`TypeAnnotationParser`); JDK caches other than resource bundles, bean infos and serialization descriptors (`MethodType`, `ClassValue` inside the JDK, locale service providers, `FileSystems` providers, `PropertyEditorManager`, the JUL configuration file read once at `LogManager` start-up); JDK code reading `System.out/err` (prints, which do not change outcomes); thread priority and daemon flag, `ThreadLocal` values left on the runner thread by JDK code; `ClassLoader` assertion status, the security manager, `Charset` providers; system properties read by JDK code (not through code under test); a static initialiser racing another thread's first use of a class (the epoch fast path); state written asynchronously by a thread an earlier test left running (attributed to whichever test is current). JDK global state in this list but changed and not restored is still seen at the end of the JVM by the runtime identity (`locale`, `tz`), which reruns every test (sound, costly). | D |

## Tests

* `python3 jvm/test/run_controls.py`: fixtures `jvm/fixtures/controls` (JUnit 5, 38 tests) and
  `jvm/fixtures/controls-junit4` (10 tests), each through Gradle and Maven: every control test
  fails in at least one of two runs without `--det` and passes in both runs with it; deterministic
  tests pass everywhere; the two `--det` traces verify with identical fingerprints; `--det-seed=5`
  gives the same order twice and a different order from seed 0.
* `python3 jvm/test/run_skipkeys.py`: fixture `jvm/fixtures/skipkeys`, one change per key input;
  the tests that read it must run again, the others must be reused.
* Reviews: `run_review_r022.py` (fixture `review-r022`, S1–S11), `run_review_r022_det.py` (D1–D5),
  `run_review_r022b.py` (fixture `review-r022b`: JDK caches, JDK global state, runner-thread state;
  `PlainTest` must stay reused), `run_r022b_narrowing.py` (each immutability refinement: a probe that
  reads only immutable state is not `mut`, and its mutating twin still reruns its reader),
  `run_w1_verifier.py`, `check_report2_numbers.py`, `check_r022b_docs.py`.
* `cargo test -p fenvix-skip` (decider rules, including the per-channel global-state rule).
* `python3 jvm/test/run_l1_measure.py`: thread races and Kotlin coroutines, measured.
* `cargo test -p fenvix-jvm`.
* CI: `.github/workflows/jvm-tests.yml` (JDK 8, 11, 17, 21).
