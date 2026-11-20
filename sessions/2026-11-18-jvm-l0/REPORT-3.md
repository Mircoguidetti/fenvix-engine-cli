DONE

# P-022b · JVM track: fixes for review R-022b (verdict FIX 4)

Work session on `claude/jvm-l0`, 2026-11-19. Input: `sessions/2026-11-19-review-jvm/REPORT-2.md` (R-022b, merged from `claude/review-r022b`) and `sessions/2026-11-18-jvm-l0/REPORT-2.md`. Container: 4 CPUs, OpenJDK 21.0.13 only (no JDK 17), Gradle 8.14.3, Maven 3.9, cargo. Labels: MEASURED (command / log), ESTIMATED, DECLARED, UNKNOWN. Logs: `sessions/2026-11-18-jvm-l0/r022b-logs/`.

**Summary.** All four findings are fixed, and each fix is checked by a test that failed before and passes now. `run_review_r022b.py` passes 8 of 8 scenarios (before: 5 of 7 BAD) with `PlainTest` reused in every scenario. `check_r022b_docs.py` passes 6 of 6 (before: 6 of 6 BAD). The decision logic is in Rust (`crates/fenvix-skip`). The shared-state rule is narrowed in four sound ways. Each narrowing has a mutable twin that must still rerun its reader. While building the twins I found and fixed a further wrong-reuse channel the reviewer's `clinit-null-read` attempt had narrowly missed (§2). Cost, MEASURED on the same 50 transitions per repository with the same verifier: **gson** verified reuses 93,089 → **100,064**, median test time skipped 12.1% → **19.9%**, mean 42.4% → 45.6%. **jsoup**: no change beyond noise (39,675 → 39,711; median 5.7% → 4.9%, mean 38.9% → 38.9%). There were **0 wrong reuses and 0 flaky** in all four walks.

## 1. Gates (MEASURED, final agent = HEAD's `jvm/dist`, logs `r022b-logs/*.log`)

| script | result |
|---|---|
| `run_review_r022b.py` (S12–S14) | **8/8 ok**: no wrong reuse, every reader RUN, `PlainTest` reused |
| `check_r022b_docs.py` | **6/6 ok** |
| `run_r022b_narrowing.py` (new, item 4) | **5/5 probes not `mut`, 9/9 scenarios ok** |
| `run_r022b_cost_probe.py` | all 7 `Cost*Test` probes `mut=False` (before: 5 of 7 `mut`) |
| `run_review_r022.py` (S1–S11) | **13/13 ok** |
| `run_review_r022_det.py` (D1–D5) | **7/7 ok** (fingerprints-under-load: 3/3 pairs identical in this run; D5 stays a documented Level 1 limit, §4) |
| `run_w1_verifier.py` | ok |
| `check_report2_numbers.py` | ok |
| `run_review_r022_walk.py` | exit 1, **by construction** (documented in REPORT-2 §5, confirmed by R-022b §1): `reused=14 wrong=[] flaky=[]` |
| `check_review_r022_numbers.py` | exit 1, **by construction**: the two embedded claims (29, 0) vs the data (25, 26) |
| `run_skipkeys.py` | **12/12 ok**. A first attempt hit HTTP 429 from Maven Central (environment), and the rerun passed |
| `run_controls.py` | JUnit 5 Gradle 40/40, Maven 40/40; JUnit 4 Gradle 10/10, Maven 10/10; fingerprints identical; seed checks ok |
| `cargo test -p fenvix-jvm -p detpy-core -p fenvix-skip` | 44 + 2 + **13** passed (3 new decider tests) |
| CI (GitHub Actions run 44524080905, on the first push of this round) | `review-r022` and `skipkeys` ok (`jvm/test/results/ci/`) |

The reviewer's files are unchanged. `git diff origin/claude/review-r022b HEAD` is empty for `run_review_r022b.py`, `check_r022b_docs.py`, `run_r022b_cost_probe.py`, `mut_blame.py`, `jvm/fixtures/review-r022b` and `sessions/2026-11-19-review-jvm`. `git diff 342fea5 HEAD` is empty for the four R-022 scripts and the three R-022 fixtures.

## 2. Per finding: what changed, before → after

| # | change | before → after (MEASURED) |
|---|---|---|
| **S12** JDK caches | `JdkHooks` kind `MEMO`: `ResourceBundle.getBundleImpl` (JDK 9+ module form; JDK 8 form declared), the four `Introspector.getBeanInfo` overloads and `ObjectStreamClass.lookup(Class, boolean)` run inside a frame, like a `<clinit>`. A catch-all handler is added after the method's own handlers, so the frame is popped on exceptions too (`MissingResourceException`). What the filling call depended on (resources, class lookups, reflected classes, locale) is stored per key and merged into every later caller, hit or miss. Keys are coarser than the JDK's: a bundle key leaves out the locale and the caller module, because entries share parent bundles. A coarser key can only add inputs. | `resource-bundle-cache`: MsgBTest reused & failed → RUN (`file`). `introspector-cache`: BeanBTest reused & failed → RUN (`code: rv/Bean`) |
| **S13** JDK global state | Per-channel reads and writes (`Deps.gr/gw`, scope fields `gread`/`gwrite`). A **write** is a setter that changes the value. `Locale`, `TimeZone`, the context class loader, the thread name and `System.setOut/Err/In` compare the new value with the current one. Thread state set on a thread that has not started does not count: nothing can have seen it, and a pool thread created by a test is reached only through state the shared-state rule already covers. A **read** is a getter called inside a test or class scope by any code, the JDK and the runner included. The exceptions are the runner's own JUL level checks and thread names, which only shape its output. Channels: `locale`, `timezone`, `tccl`, `thread.name`, `uncaught-handler`, `jul`, `stdio` (reads: `GETSTATIC System.out/err/in` in code under test), `security` (`Providers.getProviderList` is read by every `getInstance`), `url-handlers`, `net-defaults`, `jdbc`. Writes LogManager makes while applying its own configuration (lazy start-up, global handlers, a new logger getting its configured level) are not counted. They are the same whichever test triggers them, and they first showed up as a false JUL write in BeanATest. **Decider** (Rust, `order_reason`): per channel the reader reads, every test before it in B that wrote the channel must be reused, and the writers before it must be the same, in the same order, as in A. A rerun or new test that wrote it in B reruns the reader. A write by code under test outside every scope (session) reruns every reader of the channel. | `jul-root-level`: JulBTest reused & failed → RUN (`after`). `locale-default`: LocaleBTest reused & failed → RUN (`after`); MsgATest/MsgBTest also rerun, correctly: `getBundle` reads the default locale. PlainTest is reused in every scenario |
| **S14** runner-thread state | The same mechanism for the context class loader, thread name and uncaught-exception handler. A test that ends with the runner thread **interrupted** is a writer of `interrupt`, which every test reads: each later blocking call would throw. | `context-class-loader`: TcclBTest reused & failed → RUN (`after`) |
| **DOC** | `docs/JVM.md`: the "Skip with proof" section is rewritten to the current rule (Rust decider, every key input, JDK caches, the shared-state rule with the exact immutability test, the per-channel rule). New limits: **V19** (D5, the real-time fallback under load, Level 1) and **V20** (inputs still not keyed). Layout and Tests sections are updated. | `check_r022b_docs.py` 6/6 BAD → 6/6 ok |

Two more defects were found and fixed while doing the above:

* **Wrong reuse, `<clinit>` reading its own final static as `null` (MEASURED).** `Deps.staticRefRead` decided "constant" once per site from the first value. When the first execution of a read site is inside the class's own `<clinit>`, before the field is assigned, it sees `null` and caches the site as constant for the rest of the JVM. The reviewer's `Reg` held only because javac compiled `ITEMS == null ? 0 : ITEMS.size()` to **two** sites. With one site (`List l = ITEMS; return l == null ? 0 : l.size();`, `jvm/fixtures/narrowing`), the agent before this fix decided the reader **reused, and it failed** (`r022b-logs/r022b-narrowing-agent-before-fix.json`, scenario `clinit-null-single-site`). Fix: a `null` read of a final static is not cached and does not mark the site's epoch. Now the reader is RUN.
* **Lost test records under concurrent recording (MEASURED).** `Deps.write` serialised a scope's sets without the lock while other threads could still add to them. The new `gread` recording, which runs on `Thread.getName` and `Locale.getDefault`, made this visible. In one `run_review_r022.py` run, HeapBTest's record was dropped (`ConcurrentModificationException` in `endTest`, trace outcome `interrupted`) and the decider then reused a test B had not recorded. Scope records are now serialised under the capture lock. The rerun of all gates is clean (§1).

## 3. Item 4: narrowing the shared-state rule, and what it buys

The reviewer's probe (`run_r022b_cost_probe.py`) and blame (`mut_blame.py`) show that the rule calls state "mutable" when it provably is not. Implemented in `Deps.deepImmutable` and `CallSiteRewriter.enumValuesCopy`:

1. **R1, deep runtime check.** An object of a non-JDK class, whatever its declared finality (the runtime class is known), is immutable when every instance field, its own and its superclasses', is final and again holds an immutable value. The check runs on the value itself, so non-capturing lambdas and records are covered. The only field-less JDK bases allowed are `AbstractCollection`, `AbstractSet` and `Number`. Graphs are bounded at depth 8 and 256 objects; anything larger counts as mutable.
2. **R2, an enum's `values()`.** The read of the private, final, synthetic `$VALUES` in its own class outside `<clinit>` is checked at transform time. Source code cannot name that field, and javac's `values()` returns a clone. The site counts as immutable when every constant is deeply immutable, so an enum with a mutable instance field stays `mut`.
3. **R3, JDK immutable collections.** `ImmutableCollections$*` (`List/Set/Map.of`), `KeyValueHolder` (`Map.entry`) and `Optional` are immutable **when their elements are**. Every other JDK object stays mutable, even one with only final fields (`ThreadLocal`, `AtomicInteger`), because its state lives outside its fields.
4. Not done: private read-only static arrays (the reviewer's third suggestion). Every jsoup test that uses them also reaches a buffer pool (R-022b §3), so they would buy nothing measurable here.

**Soundness proof per narrowing** (`jvm/test/run_r022b_narrowing.py`, fixture `jvm/fixtures/narrowing`, MEASURED). The five immutable probes (deep final fields of a non-final class, a non-capturing lambda, an enum's `values()`, `List.of`, `Optional.of`) are not `mut`. Each refinement has a mutable twin of the same shape, whose writer mutates in B and whose reader must be RUN: a final field holding a mutable list; a declared `Holder` whose runtime class has a mutable field; an enum constant with a mutable field read through `values()`; `List.of(new StringBuilder())`; `Optional.of(new AtomicInteger())`; a lambda capturing a counter; a `ThreadLocal`; the single-site `<clinit>` null read. **9/9 ok, 0 wrong reuses.** With the agent before this round, the probes were all `mut` and `clinit-null-single-site` was a wrong reuse.

**Re-measured reuse** (MEASURED; `python3 jvm/harness/skip_walk.py --repo {jsoup,gson} --shas-from jvm/harness/results/skip-local/{repo}/shard0.json`, the same 50 transitions as P-022 and REPORT-2, JDK 21, every reuse verified against the fresh outcome with the W1 rule). "Before" is this round's agent without R1–R3, with everything else identical (S12–S14, the null fix, the lock fix). "After" is the final agent. Results are in `jvm/harness/results/skip-local-r022b-{before,after}/`, the summary in `r022b-logs/walks-summary.txt`.

| repository | variant | test time skipped, median / mean | tests skipped, median / mean | verified reuses | wrong | flaky | `mut` tests at the last commit |
|---|---|---|---|---|---|---|---|
| jsoup | before | 5.7% / 38.9% | 6.7% / 38.5% | 39,675 | 0 | 0 | 1,987 / 2,117 |
| jsoup | **after** | 4.9% / 38.9% | 6.7% / 38.5% | **39,711** | **0** | **0** | 2,001 / 2,117 |
| gson | before | 12.1% / 42.4% | 1.6% / 40.0% | 93,089 | 0 | 0 | 4,672 / 4,722 |
| gson | **after** | **19.9% / 45.6%** | **8.0% / 43.0%** | **100,064** | **0** | **0** | **4,432** / 4,722 |

Reading:

* **gson**: 240 tests stop being `mut`: the Truth singletons, `Subject$ComparisonResult` and Guava's `RegularImmutableList.EMPTY`. That matches the reviewer's experiment (4,672 → 4,432) exactly. `after` reruns fall from 74,252 to 71,137, and `after-new` disappears (3,860 → 0). Verified reuses rise by 6,975 (+7.5%). The largest remaining blocker is still Guava testlib's `CollectionSize` (3,170 tests), whose enum constants hand out a `LinkedHashSet`. They are mutable by type and stay `mut` under any sound static rule.
* **jsoup**: no measurable change. The narrowing frees one test (`Connection$Method`, an enum's `values()`). The +14 `mut` at the last commit is run-to-run noise, not the narrowing: it is the 15 tests of one class (`AttributesTest`) that happened to be current when Netty's static initialisers ran in that capture (`mut_classes` = Netty internals). jsoup's blockers are buffer pools (`CharacterReader`, `StringUtil`) and registries, whose contents do change. As R-022b §3 says, freeing them needs the dynamic state comparison or a declared, opt-in list, and neither is done here.
* **Compared with REPORT-2's walks** (agent d248b5b, JDK 17): gson "before" reproduces REPORT-2's figures (12% / 42%, 93,219 verified). jsoup "before" has the same median (5.7% vs 5%) but a higher mean (38.9% vs 23%, 39,675 vs 17,572 verified). I have not isolated the cause (UNKNOWN). Candidates are JDK 21 vs 17 and the lost-record fix (a dropped record makes the decider see fewer tests in B). The before/after pair above is like for like.
* **Cost of the new channels** (MEASURED on the last captures). Reads are common: jsoup has `tccl` in 2,117 tests and `locale` in 404; gson has `tccl` in 4,704 and `locale` in 3,934. Writes are rare: jsoup has `locale` 22 and `net-defaults` 3; gson has `timezone` 128 and `locale` 4. Writers must be rerun or reordered to cost anything, and the walks show it: no rerun reason in either walk names a channel. Compared with REPORT-2, jsoup's verified reuses did not fall, and gson's match.

## 4. D5 and the inputs still not keyed

* D5 (`docs/JVM.md` V19) is the virtual scheduler's real-time fallback under heavy load, a Level 1 limit. The mechanism and evidence are in R-022b §4. In this round's run of `run_review_r022_det.py`, 3 of 3 pairs were identical. That is one run and does not show the limit is gone.
* `docs/JVM.md` V20 lists the inputs that are still not keyed: objects in JUnit extension stores; `Unsafe` and `VarHandle` static writes; type annotations; JDK caches other than the three hooked ones (`MethodType`, JDK-internal `ClassValue`, locale service providers, `FileSystems` providers, `PropertyEditorManager`, the JUL configuration file read at start-up); JDK code printing to `System.out/err`; thread priority and daemon flag; `ThreadLocal` values left by JDK code; assertion status, the security manager, `Charset` providers; system properties read by JDK code; the epoch fast path racing another thread's class initialisation; and asynchronous writes by a thread left running. A `locale`/`tz` leak that lasts to the end of the JVM is still caught by the runtime identity, which is sound but reruns everything.

## 5. Open

* The decider still runs in measurement mode: it reads B's captures of the tests rerun before a test. The rule is written for an online decider in the runner, which is not built.
* JDK 8/11/17: the new hooks were exercised on JDK 21 only (this container). The JDK 8 `getBundleImpl` descriptor is DECLARED from the JDK 8 sources, not run. A hook whose descriptor does not match a JDK is simply not installed, so on that JDK the cache is not keyed (UNKNOWN until CI runs the JDK matrix with `--deps`).
* The reviewer's dynamic proposal (a digest of the state a reader reads, plus a DECLARED opt-in list for pools and memo caches) is not implemented. It is the only lever left for jsoup.

## 6. Where things are

* Capture: `jvm/rt/.../Deps.java` (`gr`/`gw` and the channel setters, `memoEnter`/`memoExit`, `deepImmutable`, `elementsImmutable`, the null-read rule, `write` under the lock); `jvm/agent/.../JdkHooks.java` (kinds `ENTRY_INT`, `MEMO`, hook table); `CallSiteRewriter.java` (`System.out/err/in` reads, `enumValuesCopy`).
* Decider: `crates/fenvix-skip/src/lib.rs` (`global_reads`, `global_writes`, the per-channel block in `order_reason`, 3 new tests).
* Tests: `jvm/test/run_r022b_narrowing.py`, fixture `jvm/fixtures/narrowing`; results `jvm/test/results/{review-r022b,r022b-narrowing,review-r022b-cost}.json`.
* Walks: `jvm/harness/results/skip-local-r022b-{before,after}/{jsoup,gson}/shard0.json`; `mut` blame of the last captures: `r022b-logs/mut-*.txt`.
* Docs: `docs/JVM.md` (Skip with proof, V19, V20, Tests).
