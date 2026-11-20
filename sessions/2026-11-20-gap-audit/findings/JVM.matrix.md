# JVM matrix (agent JVM, branch claude/release-1, audited 2026-11-20)

Cell = status + pointer. `done` only where I ran it (R) or a release-1 CI test covers exactly that runner + feature
(C = `jvm/test/run_controls.py`, fixtures `controls` (JUnit 5) and `controls-junit4`, each through Gradle and Maven,
`.github/workflows/jvm-tests.yml`). `nc` = not checked in this audit (time budget; see JVM.notes.md "Not covered").
Gap ids refer to JVM.gaps.jsonl. Local tool versions: JDK 21.0.13, Maven 3.9.11, Gradle 8.14.3.

Columns: 1 clock, 2 randomness, 3 hash seeds / map+set order, 4 test ordering, 5 network closed + record/replay,
6 fs order, 7 env vars, 8 locale, 9 timezone, 10 scheduling, 11 shuffle + seed, 12 replay command, 13 fingerprints +
verifier first divergent event, 14 repro, 15 nightly exploration, 16 exact culprit, 17 dependency-update verdict,
18 skip with proof, 19 shared cache, 20 parallel under det, 21 det-isolate, 22 receipts, 23 overhead measured.

| runner | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Gradle + JUnit 5 (Java) | partial C; JVM-026..038 | partial C; JVM-048..050 | missing JVM-023, 051 | done C (seed 0 class-name order) | partial: closed C, no replay JVM-044..047 | done C | missing JVM-041 | missing JVM-040 | missing JVM-039 | missing JVM-052..054 | partial C (seeded shuffle; manual seed loop JVM-058) | missing JVM-057 | partial JVM-025, 059, 060 | missing JVM-058 | missing JVM-061 | missing JVM-062 | missing JVM-063, 100 | missing: decision only R (skipdemo) JVM-001, 002, 004 | missing JVM-010 | missing JVM-064, 066 | missing JVM-067 | missing JVM-008 | missing JVM-098 |
| Gradle + JUnit 4 | partial C; same gaps | partial C | missing JVM-023 | partial: class order not controlled JVM-068 | partial C; JVM-044 | done C | missing JVM-041 | missing JVM-040 | missing JVM-039 | missing JVM-052 | partial: methods only JVM-068 | missing JVM-057 | partial JVM-025 | missing JVM-058 | missing JVM-061 | missing JVM-062 | missing JVM-063 | missing JVM-001, 004 | missing JVM-010 | missing JVM-064 | missing JVM-067 | missing JVM-008 | missing JVM-098 |
| Gradle + Kotlin (JUnit 5) | nc (same agent; no Kotlin control fixture) | nc | nc | nc | nc | nc | missing JVM-041 | missing JVM-040 | missing JVM-039 | missing JVM-052 (coroutines on Dispatchers.Default are threads, V3) | nc | missing JVM-057 | nc | missing JVM-058 | missing JVM-061 | missing JVM-062 | missing JVM-063 | missing JVM-001 | missing JVM-010 | missing JVM-064 | missing JVM-067 | missing JVM-008 | missing JVM-098 |
| Gradle + Kotest | nc JVM-080 | nc | nc | nc | nc | nc | missing | missing | missing | missing | missing: Kotest seed not wired JVM-080 | missing | nc | missing | missing | missing | missing | missing JVM-001 | missing | missing | missing | missing | missing |
| Gradle + Spock | nc JVM-079 | nc | nc | nc | nc | nc | missing | missing | missing | missing | nc | missing | nc | missing | missing | missing | missing | missing JVM-001 | missing | missing | missing | missing | missing |
| Gradle + TestNG | missing JVM-078 (no listener: no per-test brackets) | missing JVM-078 | missing | missing | nc | nc | missing | missing | missing | missing | missing | missing | missing JVM-078 | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing |
| Maven Surefire + JUnit 5 | partial R (detprobe) + C; JVM-026..038 | partial R + C; JVM-048..050 | missing R JVM-023, 024 | done R + C | partial R: TCP/DNS closed, UDP/async open, no replay JVM-044..047 | done R (File.list, Files.list/walk, newDirectoryStream sorted) | missing R JVM-041 | missing JVM-040 | missing R JVM-039 | missing R JVM-052..054 | partial R (orderdemo seeds 0-4) JVM-058 | missing R JVM-057 | partial R: false 'identical' JVM-025; outcome-only JVM-059, 060 | missing JVM-058 | missing JVM-061 | missing JVM-062 | missing R JVM-100 | missing: decision only R; wrong reuses JVM-013, 017..022, 099 | missing JVM-010 | missing JVM-065, 066 | missing JVM-067 | missing JVM-008 | missing JVM-098 |
| Maven Surefire + JUnit 4 | partial C | partial C | missing JVM-023 | done C (runOrder alphabetical) | partial C | done C | missing | missing | missing | missing | partial C (runOrder random + seed) | missing JVM-057 | partial JVM-025 | missing | missing | missing | missing | missing JVM-001, 005 | missing | missing JVM-065 | missing | missing | missing |
| Maven + TestNG | missing JVM-078 | missing | missing | missing | nc | nc | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing |
| Maven Failsafe (integration tests) | missing JVM-070 (no agent) | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing JVM-006 | missing | missing | missing | missing | missing |
| Spring Boot tests | nc JVM-081 | nc | nc | nc | nc | nc | missing | missing | missing | missing | nc | missing | nc | missing | missing | missing | missing | missing JVM-001 | missing | missing | missing | missing | missing |
| Android unit tests (Robolectric) | nc JVM-082 | nc | nc | nc | nc | nc | missing | missing | missing | missing | nc | missing | nc | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing |
| Bazel java_test | missing JVM-074 | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing |
| sbt / ScalaTest | missing JVM-075 | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing |

No cell is `excluded`: I did not find a JVM exclusion recorded in brain `DECISIONS.md` (not searched exhaustively: see notes).

## Levels for the JVM

| level | promised | exists on release-1 |
|---|---|---|
| L0 hermetic (order, seeds, virtual clock, fs order, closed network with record/replay) | brain ARCHITECTURE.md; engine docs/JVM.md "Level 0 ... for Java and Kotlin" | partial: order, seeded randomness, virtual clock at rewritten call sites, sorted listings, TCP/DNS closed (ran: detprobe). Missing: record/replay (JVM-044), timezone/locale/env (JVM-039..041), Set.of / reflection order (JVM-023, 024), several clock and timer APIs (JVM-026..038), UDP / async sockets (JVM-045, 046) |
| L1 runtime (thread switches, async event order) | brain ARCHITECTURE.md | missing: threads not ordered (docs/JVM.md V3; ran: JVM-052..054); only a measurement script `jvm/test/run_l1_measure.py` |
| L2 deterministic VM ("for native threads, Go and Java", brain ARCHITECTURE.md:9 "designed") | designed | missing: no code (JVM-069) |
| Verifier naming the first divergent event | promise 1 | partial: compares fingerprints of controlled events; order/race failures give "outcome-only", no event (JVM-059, 060); reports identical when uncontrolled values differ (JVM-025) |
