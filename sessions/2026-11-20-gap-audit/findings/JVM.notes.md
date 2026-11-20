# JVM audit notes (agent JVM, engine@claude/release-1, 2026-11-20)

Local tools: OpenJDK 21.0.13 (Ubuntu), Maven 3.9.11, Gradle 8.14.3 (Kotlin 2.0.21, Groovy 3.0.24). Artifacts:
`/home/user/audit/build/opt/jvm/fenvix-agent.jar` (classes major version 52 = Java 8; only native lib inside:
`fenvix/libfenvix_jvm.so`, ELF x86-64), `/home/user/audit/build/opt/bin/fenvix-skip`. Scratch: `/home/user/audit/work/JVM/`
(projects `skipdemo`, `detprobe`, `orderdemo`, `reuseprobe`; raw logs in `logs/`). The audit was cut short by a
time limit: everything below "Not covered" was NOT probed.

## Real user surface (read from code)

- `java -jar fenvix-agent.jar run [--det] [--det-seed=N] [--deps] [--det-disable=random,time,fs,net,sched]
  [--det-allow-host=h] [--out=DIR] -- <gradle|gradlew|mvn|mvnw ...>`; `merge DIR`; `verify [--json] TRACE...`; `paths`
  (jvm/agent/src/main/java/dev/fenvix/cli/Main.java:35-60). `fenvix jvm ...` forwards to it; `fenvix jvm decide` to `fenvix-skip`.
- `fenvix-skip decide A_DEPS_DIR B_DEPS_DIR --root-b DIR [--json OUT|-]` (crates/fenvix-skip/src/main.rs).
- Agent options / system properties: `fenvix.agent, det, deps, seed, root, out, disable, allow.hosts, jvmargs, module, tool,
  plugins, config, strict, debug, cache (extraction dir, default java.io.tmpdir/fenvix-jvm), tick.ns, adapt, epoch.ms,
  timer.budget, native`; env fallbacks `FENVIX_AGENT`, `FENVIX_DET`, ... in the init script and the Maven extension
  (fenvix.init.gradle:12-17, FenvixMavenExtension.java:38-44). None of the tuning properties is documented in docs/JVM.md.
- Files written: `<out>/parts/*.jsonl`, `<out>/trace.jsonl` (--det), `<out>/deps/<module>-<pid>.jsonl` (--deps),
  `${java.io.tmpdir}/fenvix-jvm/<hash>/{fenvix-rt.jar,libfenvix_jvm.so,fenvix.init.gradle,fenvix-maven-ext.jar}`.
  Each `run` deletes the previous `parts/` and `deps/` of its out directory (Main.java:160-166).

## (c) Things the lead should know

- The headline gap is larger than "the decision is not applied": `decide` cannot decide before B has been fully run with
  `--deps` (JVM-002), and feeding it A twice after recompiling gives REUSE for changed, failing tests (JVM-003).
- The decision itself is wrong in 8 probes I ran (JVM-013, 017-022, 099): file size, Files.size, File.exists on JDK 21,
  permission bit, loopback service, framework-read env var, clock, CPU count. Each was confirmed by the real outcome in B
  (`outcome_b` in the decider's own JSON). Probes that were decided correctly: classpath resource, Files.readString,
  env var, env map, system property, Properties object, inlined constant (test and main), superclass method, interface
  default, annotation default, Class.forName, ServiceLoader file, static initialiser reading a file (both tests), dir listing,
  Files.lines, mapped file, Scanner, ZipFile, absolute file outside the root, @TempDir (reusable), dependency bump (all RUN).
- Under Gradle, fenvix today skips less than plain Gradle (JVM-016).
- `verify` said "covered by Level 0: 14, not covered: 0" for two --det runs whose observable values differed in 25 lines
  (JVM-025): the fingerprint only contains controlled events.
- docs/JVM.md:49 says Gradle `forkEvery = 0` is set; jvm/gradle/fenvix.init.gradle:7 says the project's forkEvery is kept
  and the code sets only maxParallelForks (contradiction, JVM-067).
- docs/JVM.md:117-131 lists "files probed (existence/type)" as keyed; on JDK 21 `File.exists()` is not captured (JVM-019).
  Whether CI's skip-key tests run on JDK 21 was not checked.
- docs/RELEASE-1.md:38 states honestly that the decision is not applied; the reports under sessions/2026-11-18-jvm-l0 and
  2026-11-19-review-jvm were NOT read (time).

## (a) Could not check

- macOS / Windows / Linux arm64 behaviour: from code and the jar listing only (JVM-086..088).
- Docker is not available (`docker ps`: cannot connect), so Testcontainers could not be run.
- JDK 8/11/17/25 were downloaded (Temurin tarballs from GitHub releases into `work/JVM/jdks/`: 1.8.0_432, 11.0.25,
  17.0.13, 25) but no run was made with them before the time limit.

## Not covered (brief items NOT probed; another session must finish them)

Versions and build tools:
- Java 8, 11, 17, 25 runs (JDKs are ready in `work/JVM/jdks/`); whether the agent's ASM 9.8 reads Java 25 class files; whether
  `File.exists` capture works on JDK 17 (expected yes) versus 21 (ran: no).
- Kotlin 1.9 / 2.x; Scala; Groovy.
- Gradle 7.x and 9.x (init script API), Kotlin DSL builds, `--configuration-cache`, build cache (`FROM-CACHE`) interaction
  beyond the forced rerun seen in skipdemo, `--parallel`, daemon vs `--no-daemon`, `maxParallelForks`, `forkEvery`,
  Develocity test distribution / Predictive Test Selection, composite builds, multi-project builds, Android Gradle Plugin
  (unit and instrumented tests), Kotlin Multiplatform, Gradle Wrapper.
- Maven 3.6 and 4, Surefire versions other than 3.2.5, `forkCount`, `reuseForks`, `parallel` + `threadCount`, Failsafe
  (read from code only: JVM-006, 070), multi-module reactor, `-T`, `.mvn/extensions.xml`, Maven Wrapper, the argLine
  property loss (read from code only: JVM-071), JaCoCo `@{argLine}` handling (V14).
- Bazel, sbt, Ant: read from code only.

Test frameworks (none probed except JUnit 5 Jupiter basic tests):
- Jupiter: `@Execution`, `@RepeatedTest`, `@ParameterizedTest`, `@TestMethodOrder`, `MethodOrderer.Random`, class order,
  `@Nested`, `@TestFactory`, extensions, `@Timeout` under the virtual clock, whether the user is told parallel is off.
- JUnit 4 (runners, rules, Parameterized, Gradle class order V7), JUnit Platform Suite, TestNG, Spock, Kotest,
  kotlinx-coroutines-test, Spring Boot tests, Mockito / MockK (agent conflicts), JaCoCo together with the fenvix agent,
  Testcontainers, WireMock, Awaitility, AssertJ, Quarkus / Micronaut, Cucumber-JVM, ArchUnit, jqwik, PIT.
  The gap entries for TestNG, Spock, Kotest, Spring Boot, Robolectric, Cucumber, jqwik, Testcontainers (JVM-078..085 range,
  see file) rest on reading the fixtures and the agent's junit package, not on runs.

Controls not probed by a run: `Locale` change (read only), `file.encoding`, classpath scanning order, `ServiceLoader`
order across jars, `Unsafe`/`VarHandle`, JNI/native code, virtual threads beyond one ordering sample (equal in two runs),
coroutines, `Thread.yield`, `Object.hashCode` beyond one sample (equal in two runs), `--det-disable` and `--det-allow-host`.

Features not probed by a run: seeded shuffle with Gradle and with JUnit 4 (CI test exists: run_controls.py), `repro` /
exploration / culprit absence checked from the CLI code only, Gradle `maxParallelForks` and Surefire `forkCount` forcing
(read only), `forkEvery 1` isolation, overhead on a real project (gson / jsoup: not cloned, not measured), jvm/harness
results (not read), IDoFT numbers in docs (not verified).

Wrong-reuse probes not done: Spring `application.yml`, Kotlin inline / top-level function in another file, random-luck
flaky pass, hostname, JUnit extension store (V20), Unsafe/VarHandle static writes (V20), Gradle (all reuse probes were Maven),
JUnit 4, multi-module, the order rule (shared static state) under a changed order.

Packaging not probed: JPMS projects / `--add-opens`, security manager, agent start failure message on another OS (read
only), IDE runs.

Brain files not read: DECISIONS.md, ROADMAP.md, NOW.md, PRODUCT.md, prompts/P-022-jvm-l0.md, both session report folders;
the matrix therefore has no `excluded` cell and DECISIONS.md must be checked for JVM exclusions (Bazel / sbt are marked DECIDE).

## (b) Evidence appendix (trimmed real outputs)

### E-001 (JVM-001, 002, 003, 011) skipdemo, Maven 3.9.11 + Surefire 3.2.5 + JUnit 5.10.2
```
$ java -jar fenvix-agent.jar run --deps --out=A -- mvn -B -o test     # state A
[INFO] Tests run: 7, Failures: 0, Errors: 0, Skipped: 0
$ fenvix-skip decide A/deps EMPTY --root-b .
RUN   ::app.CalcTest::adds()  [no-jvm-record: ]   (7 lines, all RUN)
# Greeter.java changed to "Hi, " + recompiled, no B run:
$ fenvix-skip decide A/deps A/deps --root-b .
REUSE ::app.GreeterTest::hello()
REUSE ::app.GreeterTest::helloEmpty()   (7 lines, all REUSE)
$ java -jar fenvix-agent.jar run --deps --out=B -- mvn -B -o test     # state B: everything executes
[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 1.798 s -- in app.CalcTest
[ERROR] Tests run: 7, Failures: 2, Errors: 0, Skipped: 0
$ fenvix-skip decide A/deps B/deps --root-b . --json decision.json
REUSE ::app.CalcTest::adds()
REUSE ::app.CalcTest::addsNegative()
REUSE ::app.CalcTest::slow()
REUSE ::app.ConstTest::limitIsTen()
REUSE ::app.ConstTest::nameIsAlpha()
RUN   ::app.GreeterTest::hello()  [code: app/Greeter]
RUN   ::app.GreeterTest::helloEmpty()  [code: app/Greeter]
{"id": "app.CalcTest::adds()", "module": "", "ms_b": 149.696754, "outcome_a": "passed", "outcome_b": "passed", "reason": null, "reusable": true}
$ java -jar fenvix-agent.jar run --det-cache -- mvn test
fenvix-jvm: unknown build tool --det-cache (gradle, gradlew, mvn, mvnw)
```

### E-016 (JVM-001, 016) skipdemo, Gradle 8.14.3 (Groovy DSL) + JUnit 5
```
$ java -jar fenvix-agent.jar run --deps --out=GB -- gradle --no-daemon test    # after changing Greeter.java
CalcTest > adds() PASSED / CalcTest > slow() PASSED / ... 7 PASSED lines; BUILD SUCCESSFUL in 43s
$ fenvix jvm decide GA/deps GB/deps --root-b .   => 5 REUSE, 2 RUN [code: app/Greeter]
$ java -jar fenvix-agent.jar run --deps --out=GC -- gradle --no-daemon test    # nothing changed
> Task :testClasses UP-TO-DATE / > Task :test / 7 PASSED lines (test task executed again)
```

### E-017 (JVM-013, 017-022, 099, 100) reuseprobe decide A B (full output)
```
RUN   ::rp.ClinitFirstTest::triggersInit()  [file: root:data/config.txt]
RUN   ::rp.ClinitLaterTest::readsInitialisedValue()  [file: root:data/config.txt]
REUSE ::rp.DepJarTest::libraryBehaviour()
REUSE ::rp.DepJarTest::libraryManifestVersion()
RUN   ::rp.P_p01_classpathResource_Test::p01_classpathResource()  [file: root:target/test-classes/res.txt]
RUN   ::rp.P_p02_filesReadString_Test::p02_filesReadString()  [file: root:data/input.txt]
RUN   ::rp.P_p03_envVar_Test::p03_envVar()  [env: PROBE_ENV]
RUN   ::rp.P_p03b_envMap_Test::p03b_envMap()  [env: PROBE_ENV2]
RUN   ::rp.P_p04_systemProperty_Test::p04_systemProperty()  [prop: probe.prop]
RUN   ::rp.P_p04b_propertiesObject_Test::p04b_propertiesObject()  [prop: *]
RUN   ::rp.P_p06_inlinedConstantInTest_Test::p06_inlinedConstantInTest()  [code: rp/P_p06_inlinedConstantInTest_Test]
RUN   ::rp.P_p06b_inlinedConstantInMain_Test::p06b_inlinedConstantInMain()  [code: rp/Limits]
RUN   ::rp.P_p07_superclassMethod_Test::p07_superclassMethod()  [code: rp/Base]
RUN   ::rp.P_p07b_interfaceDefault_Test::p07b_interfaceDefault()  [code: rp/Named]
RUN   ::rp.P_p07c_annotationDefault_Test::p07c_annotationDefault()  [code: rp/Tag]
RUN   ::rp.P_p10_classForName_Test::p10_classForName()  [code: rp/Plugin]
RUN   ::rp.P_p11_serviceLoader_Test::p11_serviceLoader()  [file: root:target/test-classes/META-INF/services/rp.Svc]
REUSE ::rp.P_p13_fileLength_Test::p13_fileLength()
REUSE ::rp.P_p13b_filesSize_Test::p13b_filesSize()
REUSE ::rp.P_p13c_fileExists_Test::p13c_fileExists()
RUN   ::rp.P_p13d_dirList_Test::p13d_dirList()  [file: root:data/dir/]
REUSE ::rp.P_p13e_execBit_Test::p13e_execBit()
RUN   ::rp.P_p13f_filesLines_Test::p13f_filesLines()  [file: root:data/lines.txt]
RUN   ::rp.P_p13g_mappedFile_Test::p13g_mappedFile()  [file: root:data/mapped.txt]
RUN   ::rp.P_p13h_scanner_Test::p13h_scanner()  [file: root:data/scanner.txt]
RUN   ::rp.P_p13i_zipFile_Test::p13i_zipFile()  [file: root:data/archive.zip]
RUN   ::rp.P_p13j_absFileOutsideRoot_Test::p13j_absFileOutsideRoot()  [file: abs:/home/user/audit/work/JVM/ext/abs.txt]
REUSE ::rp.P_p23_clockWindow_Test::p23_clockWindow()
REUSE ::rp.P_p24_cpuCount_Test::p24_cpuCount()
REUSE ::rp.P_p25_loopbackService_Test::p25_loopbackService()
REUSE ::rp.P_p30_conditionEnv_Test::p30_conditionEnv()
REUSE ::rp.P_p32_tempDir_Test::p32_tempDir(java.nio.file.Path)
REUSE ::rp.P_p99_control_untouched_Test::p99_control_untouched()
--- judge (reusable && outcome changed):
== WRONG REUSE (reusable=true but outcome changed):
  WRONG rp.P_p13_fileLength_Test::p13_fileLength() passed -> failed
  WRONG rp.P_p13b_filesSize_Test::p13b_filesSize() passed -> failed
  WRONG rp.P_p13c_fileExists_Test::p13c_fileExists() passed -> failed
  WRONG rp.P_p13e_execBit_Test::p13e_execBit() passed -> failed
  WRONG rp.P_p23_clockWindow_Test::p23_clockWindow() passed -> failed
  WRONG rp.P_p25_loopbackService_Test::p25_loopbackService() passed -> failed
  WRONG rp.P_p30_conditionEnv_Test::p30_conditionEnv() passed -> skipped
== RUN although outcome same (over-rerun):
--- round C (taskset -c 0) and round D (commons-lang3 3.12.0 -> 3.14.0):
REUSE ::rp.P_p24_cpuCount_Test::p24_cpuCount()
REUSE ::rp.P_p99_control_untouched_Test::p99_control_untouched()
{'id': 'rp.P_p24_cpuCount_Test::p24_cpuCount()', 'module': '', 'ms_b': 11.651767, 'outcome_a': 'passed', 'outcome_b': 'failed', 'reason': None, 'reusable': True}
=== dependency bump 3.12.0 -> 3.14.0 (pre-fetch online, then run)
[ERROR] Tests run: 33, Failures: 28, Errors: 0, Skipped: 1
[INFO] BUILD FAILURE
     33 RUN   ::rp.ClinitFirstTest::triggersInit()  [config: classpath]
RUN   ::rp.DepJarTest::libraryBehaviour()  [config: classpath]
RUN   ::rp.DepJarTest::libraryManifestVersion()  [config: classpath]
RUN   ::rp.P_p99_control_untouched_Test::p99_control_untouched()  [config: classpath]
{'id': 'rp.DepJarTest::libraryBehaviour()', 'module': '', 'ms_b': 17.962139, 'outcome_a': 'passed', 'outcome_b': 'passed', 'reason': ['config', 'classpath'], 'reusable': False}
{'id': 'rp.DepJarTest::libraryManifestVersion()', 'module': '', 'ms_b': 3.037932, 'outcome_a': 'passed', 'outcome_b': 'failed', 'reason': ['config', 'classpath'], 'reusable': False}

[exited with code 0]
```

### E-027 (JVM-023..055) detprobe: diff of two --det runs (same env) and verify
```
$ java -jar fenvix-agent.jar verify D1/trace.jsonl D2/trace.jsonl
order: identical in every run
covered by Level 0: 14  not covered: 0  missing: 0  outcome-unstable: 0
$ diff det1.txt det2.txt
8,13c8,13
< clock.newGregorianCalendar=1795164012771
< clock.InstantSource.system=2026-11-20T08:40:12.803805494Z
< clock.Clock.tickMillis=2026-11-20T08:40:12.804Z
< clock.reflective.currentTimeMillis=1795164012806
< clock.methodhandle.nanoTime=1442727014804
< clock.jul.LogRecord=2026-11-20T08:40:12.807178353Z
---
> clock.newGregorianCalendar=1795164065819
> clock.InstantSource.system=2026-11-20T08:41:05.819466676Z
> clock.Clock.tickMillis=2026-11-20T08:41:05.819Z
> clock.reflective.currentTimeMillis=1795164065841
> clock.methodhandle.nanoTime=1495761881074
> clock.jul.LogRecord=2026-11-20T08:41:05.842061903Z
15,17c15,17
< clock.ProcessHandle.startInstant=2026-11-20T08:40:09.730Z
< clock.RuntimeMXBean.startTime=1795164009956
< clock.Files.lastModified(new file)=2025-01-01T00:00:00.256Z
---
> clock.ProcessHandle.startInstant=2026-11-20T08:41:02.970Z
> clock.RuntimeMXBean.startTime=1795164063216
> clock.Files.lastModified(new file)=2025-01-01T00:00:00.159Z
55c55
< env.pid=24852
---
> env.pid=1308
64c64
< net.ServerSocket(0).port=34919
---
> net.ServerSocket(0).port=43471
72,73c72,73
< hash.Set.of.order=[zeta, eta, epsilon, beta, alpha, delta, gamma]
< hash.Map.of.order=[e, d, c, b, a]
---
> hash.Set.of.order=[eta, epsilon, beta, alpha, delta, gamma, zeta]
> hash.Map.of.order=[c, b, a, e, d]
75c75
< reflect.getDeclaredMethods.order=[mid, b2, e5, c3, alpha, beta, d4, omega, f6, zeta]
---
> reflect.getDeclaredMethods.order=[mid, b2, e5, c3, alpha, beta, zeta, d4, omega, f6]
85,87c85,87
< rnd.RandomGenerator.getDefault=-2304290423473440673
< rnd.RandomGenerator.of(L64X128MixRandom)=5975599330642151215
< rnd.reflective.newRandom=1404995845625683221
---
> rnd.RandomGenerator.getDefault=6544202197699750911
> rnd.RandomGenerator.of(L64X128MixRandom)=5796793642722374428
> rnd.reflective.newRandom=-6637376378399820521
92,96c92,96
< rnd.Files.createTempFile.name=p3154786182411676662.t
< rnd.File.createTempFile.name=ppp6469615838531588537.t
< proc.child.date+RANDOM=1795164045188804632
< thread.executor.interleaving=t0t2t1t3t0t2t1t3t0t2t1t3t4t5t6t7t4t5t6t7t4t5t6t7
< thread.parallelStream.order=[40, 41, 42, 43, 44, 45, 46, 47, 36, 37, 38, 39, 32, 33, 34, 35, 56, 57, 58, 59, 60, 61, 62, 63, 52, 53, 54, 55, 48, 49, 50, 51, 20, 21, 22, 23, 16, 17, 18, 19, 28, 29, 3
---
> rnd.Files.createTempFile.name=p6469615838531588537.t
> rnd.File.createTempFile.name=ppp13585583660810170366.t
> proc.child.date+RANDOM=1795164097810769709
> thread.executor.interleaving=t0t0t1t1t3t3t2t3t2t4t2t4t5t4t5t6t5t6t7t6t7t7t1t0
> thread.parallelStream.order=[40, 41, 42, 43, 44, 45, 46, 47, 36, 37, 38, 39, 32, 33, 34, 35, 56, 57, 58, 59, 60, 61, 62, 63, 52, 53, 54, 55, 48, 49, 50, 51, 20, 21, 22, 23, 16, 17, 18, 19, 28, 29, 3
101c101
< thread.racyCounter(expect 800000)=449031
---
> thread.racyCounter(expect 800000)=509657
--- det1 values (selected)
clock.currentTimeMillis=1735689600000
clock.nanoTime=1000000002000
clock.Instant.now=2025-01-01T00:00:00.000003Z
clock.LocalDateTime.now=2025-01-01T00:00:00.000004
clock.Clock.systemUTC=2025-01-01T00:00:00.000005Z
clock.newDate=1735689600000
clock.Calendar.getInstance=1735689600000
clock.newGregorianCalendar=1795164012771
clock.InstantSource.system=2026-11-20T08:40:12.803805494Z
clock.Clock.tickMillis=2026-11-20T08:40:12.804Z
clock.reflective.currentTimeMillis=1795164012806
clock.methodhandle.nanoTime=1442727014804
clock.jul.LogRecord=2026-11-20T08:40:12.807178353Z
clock.sql.Timestamp.from(Instant.now)=2025-01-01 00:00:00.000008
clock.ProcessHandle.startInstant=2026-11-20T08:40:09.730Z
clock.RuntimeMXBean.startTime=1795164009956
clock.Files.lastModified(new file)=2025-01-01T00:00:00.256Z
clock.System.currentTimeMillis.supplier=1735689600000
sleep.Thread.sleep(1500).realMs=0
sleep.Object.wait(1000).realMs=1000
sleep.Object.wait(1000,5).realMs=1000
sleep.TimeUnit.sleep(1000).realMs=0
sleep.parkUntil(+1000).realMs=0
sleep.Semaphore.tryAcquire(1000).realMs=1000
sleep.Semaphore.tryAcquire(1000).virtualAdvanceMs=0
sleep.Thread.sleep(1000).virtualAdvanceMs=1000
deadline.loop2000ms.Semaphore50ms.iterations=400
deadline.loop2000ms.Semaphore50ms.realMs=20000
tz.TimeZone.getDefault=UTC
tz.user.timezone=UTC
tz.ZoneId.systemDefault=UTC
tz.LocalDateTime.now.hour=0
sched.Executors.newScheduledThreadPool.1500ms.realMs=0
sched.new ScheduledThreadPoolExecutor.1500ms.realMs=1500
sched.java.util.Timer.1500ms.realMs=1500
sched.CompletableFuture.orTimeout.1500ms.realMs=1500
sched.CompletableFuture.delayedExecutor.1500ms.realMs=1500
env.PROBE_VAR=one
env.hostname=vm
env.pid=24852
net.Socket.external=ConnectException: fenvix --det: network closed, connection to 93.184.216.34:80 refused (allow it with -Dfenvix.allow.hosts=93.184.216.34)
net.dns.external=UnknownHostException: example.com (fenvix --det: network closed; allow it with -Dfenvix.allow.hosts=example.com)
net.udp.external.send=sent
net.AsynchronousSocketChannel.external=ExecutionException: java.net.ConnectException: Connection refused
net.ServerSocket(0).port=34919
net.HttpClient.external=ConnectException: fenvix --det: network closed, connection to 93.184.216.34:80 refused (allow it with -Dfenvix.allow.hosts=93.184.216.34)
--- plain (no --det) sleeps/timers
sleep.Thread.sleep(1500).realMs=1500
sleep.Object.wait(1000).realMs=1000
sleep.Object.wait(1000,5).realMs=1000
sleep.TimeUnit.sleep(1000).realMs=1000
sleep.parkUntil(+1000).realMs=1000
sleep.Semaphore.tryAcquire(1000).realMs=1000
sleep.Semaphore.tryAcquire(1000).virtualAdvanceMs=1000
sleep.Thread.sleep(1000).virtualAdvanceMs=1000
deadline.loop2000ms.Semaphore50ms.iterations=40
deadline.loop2000ms.Semaphore50ms.realMs=2000
sched.Executors.newScheduledThreadPool.1500ms.realMs=1500
sched.new ScheduledThreadPoolExecutor.1500ms.realMs=1500
sched.java.util.Timer.1500ms.realMs=1500
sched.CompletableFuture.orTimeout.1500ms.realMs=1500
sched.CompletableFuture.delayedExecutor.1500ms.realMs=1500
--- det3 (TZ=Asia/Tokyo PROBE_VAR=two)
clock.LocalDateTime.now=2025-01-01T09:00:00.000004
tz.TimeZone.getDefault=Asia/Tokyo
tz.user.timezone=Asia/Tokyo
tz.ZoneId.systemDefault=Asia/Tokyo
tz.LocalDateTime.now.hour=9
env.PROBE_VAR=two
```

### E-057 (JVM-057..060) orderdemo (static-state polluter/victim + racy test), Maven
```
seed 0: Tests run: 11, Failures: 1 (od.RacyTest.counterRace); seeds 1-4: Failures: 1 (od.VictimTest.cleanState)
$ grep -i "fenvix\|replay\|repro" order-mvn-seed1.log
[INFO] Tests will run in random order. To reproduce ordering use flag -Dsurefire.runOrder.random.seed=1   (Surefire, not fenvix)
fenvix-jvm: trace .../orderdemo/S1/trace.jsonl {"n_tests":11,"order_digest":"e5c9485e3be902cb98d57682996f1d49","skipped":[]}
$ java -jar fenvix-agent.jar verify S0/trace.jsonl S1/trace.jsonl
order: DIFFERS between runs
covered by Level 0: 9  not covered: 2  missing: 0  outcome-unstable: 2
NOT-COVERED od.RacyTest::counterRace()  [outcome-only] outcomes=failed,passed
NOT-COVERED od.VictimTest::cleanState()  [outcome-only] outcomes=passed,failed
    runs 0 vs 1: identical observed events, different outcome (passed vs failed): the cause is a source Level 0 does not observe
```

### E-086 (JVM-086..088, 091, 093) packaging
```
$ unzip -l fenvix-agent.jar | grep -iE "\.so|\.dylib|\.dll"  =>  1189232  fenvix/libfenvix_jvm.so
$ file fenvix/libfenvix_jvm.so  =>  ELF 64-bit LSB shared object, x86-64
$ javap -v dev/fenvix/agent/Agent | grep major  =>  major version: 52 (also rt Det, maven-ext, cli Main)
$ java -jar fenvix-agent.jar  =>  usage: fenvix-jvm run [--det] [--det-seed=N] [--deps] [--det-disable=a,b] [--det-allow-host=h] [--out=DIR] -- <build command>
                                         fenvix-jvm merge DIR | verify TRACE... | paths
$ fenvix-skip --help  =>  usage: fenvix-skip decide A_DEPS_DIR B_DEPS_DIR --root-b DIR [--json OUT]
```
