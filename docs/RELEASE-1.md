# Release 1: one engine, four languages

Branch `claude/release-1` of fenvix-engine-cli. One Cargo workspace, one CI workflow
(`.github/workflows/release-1.yml`), one CLI entry (`release/fenvix`), one image install
(`release/install-image.sh`). The integration record (branches, commits, conflicts, CI run ids) is
`sessions/2026-11-20-release-1/REPORT.md`.

Labels: **MEASURED** (Actions run id or local command), **ESTIMATED**, **DECLARED** (stated by the branch's own docs or
report, not re-measured here), **UNKNOWN**.

## What is in

| component | source | crate / path | artifact |
|---|---|---|---|
| engine core (events, fingerprints, traces, verifier, shuffle, proof store, record plan, carried-set rule, parallel schedule, culprit keys) | `claude/parallel-proof-3` lineage | `crates/detpy-core` | linked into every binding |
| Python: pytest plugin, `python -m detpy` runners (unittest, Django, nose2, ward, zope, doctest), xdist under `--det`, `--det-isolate`, `--det-cache`, `--det-cache-keys` | `claude/parallel-proof-3`, `claude/all-runners-2`, `claude/exact-culprit` | `crates/detpy-py`, `python/detpy` | wheel `fenvix-0.1.0-cp312-abi3-manylinux_2_28_x86_64.whl` inside the engine artifact (docs/INSTALL.md) |
| Node/JS/TS: `detjs` for Vitest, Jest, Mocha, node:test, AVA, tap, uvu, Jasmine, Bun, Deno; `--det-cache` | `claude/all-runners-2` (with `claude/node-cache-proof`) | `crates/detpy-node`, `node/` | napi addon `detjs.linux-x64.node` + `node/` |
| Go: `fenvix-go test` (toolchain overlay), `--skip-cache` | `claude/go-l0` | `crates/fenvix-go` (C ABI, static), `go/` | `fenvix-go` (self-contained binary: overlay embedded, core linked) |
| JVM (Java, Kotlin; Gradle, Maven; JUnit 5, JUnit 4): agent, `--deps` capture, skip decider | `claude/jvm-l0` | `crates/fenvix-jvm` (JNI), `crates/fenvix-skip`, `jvm/` | `fenvix-agent.jar` (agent, runtime, JNI library, Gradle init script, Maven extension), `fenvix-skip` |
| dependency verdict | `claude/dep-verdict-abjcfw` | already in `claude/parallel-proof-3` | (in the wheel) |
| exact culprit finder input (`--det-cache-keys`) | `claude/exact-culprit` | `detpy_core::record::record_session_keys`, `_proof.ProofSession._dump_keys`; harness `harness/culprit/` | (in the wheel) |

Versions (DECLARED): every crate `0.1.0` (workspace), detpy wheel `0.1.0`, detjs `0.1.0`, fenvix-agent `0.1.0`;
the release is tagged by the branch commit named in the REPORT.

## Support per language

`--det`: deterministic run (Level 0 controls, trace, fingerprints, verify). Cache: skip with proof (a test is reused
only when every input it depended on is unchanged; failures are never reused). Parallel: whether `--det` / the cache
keep a parallel run.

| language | `--det` | skip with proof | parallel |
|---|---|---|---|
| Python (pytest) | yes; reproducible shuffle `--det-seed`; network cassette | `--det-cache=DIR\|URL` (Python 3.12+: `sys.monitoring`), receipts, `--det-cache-verify`, shared store `--det-cache-shared` | pytest-xdist `-n` under `--det` with a fixed plan (docs/PARALLEL-PROOF-DESIGN.md), carried-set rule across workers; `--det-isolate` (fork per test, Linux) |
| Python (other runners) | `python -m detpy unittest\|django\|nose2\|ward\|zope\|doctest --det` | same session, same options (docs/ALL-RUNNERS.md) | serial |
| Node/TS | `detjs vitest\|jest\|mocha\|node-test\|ava\|tap\|uvu\|jasmine\|bun\|deno --det` | `--det-cache=DIR\|URL` per test file (docs/NODE-CACHE.md) | serial under `--det` (Vitest `fileParallelism: false`, Jest in band: J14); the cache runs each file in its own process |
| Go | `fenvix-go test --det` (overlay: clock, seeds, map order, fs order, network, scheduling with one P) | `fenvix-go test --skip-cache=DIR` (needs strace; per top-level test) | packages one at a time under `--det` (`-p 1`); `t.Parallel` serialised in skip mode (`--det-keep-parallel` restores) |
| JVM | `java -jar fenvix-agent.jar run --det -- <gradle\|mvn ...>` | **capture + decision**: `run --deps` writes the capture, `fenvix-skip decide A B` says which tests of run A are reusable in state B; the build tool still runs every test (the decision is not yet applied to skip execution) | serial under `--det`/`--deps` (one test JVM, Jupiter parallel off: V15) |

Through the single entry: `fenvix python ...`, `fenvix python-runner unittest ...`, `fenvix node vitest ...`,
`fenvix go test ...`, `fenvix jvm run ... -- mvn test`, `fenvix jvm decide ...`, `fenvix verify A B` (every shell
writes the same trace format), `fenvix detect`, `fenvix version`.

## Platforms

| platform | status |
|---|---|
| Linux x86_64 | gated: every job of `release-1.yml`. Run 44710687525: build, Go, JVM ×4 and the four smoke tests green; Python fails 1 test on GitHub runners only (REPORT 0.1) (MEASURED) |
| Linux arm64 | not shipped: the go-live runs on our machines only (Linux x86_64; founder decision 2026-11-20) |
| macOS arm64 | not shipped: the go-live runs on our machines only (Linux x86_64; founder decision 2026-11-20) |
| Windows | UNKNOWN (never built) |

## Known limits (from each branch's limits doc; the full tables are there)

**Python** (docs/LIMITS.md): Level 0 works at the Python API level: C extensions, native libraries and subprocesses
are not controlled (S1, S2); references bound before installation keep real objects (S3); the cache needs Python 3.12+;
inputs the recorder cannot see (section 9: C-level reads; a test reading a file time is refused, R-032b F2) and the
real-clock bound `--det-cache-max-age` (section 8); xdist plan limits (O1). Python 3.11 and older: refused with one message and exit code 4 (CPython 3.12, 3.13, 3.14 only).

**Node** (docs/NODE.md J1-J17, docs/NODE-CACHE.md): native addons, child processes and user worker threads are not
controlled (J1); Vitest `vmThreads`/`vmForks` and browser mode are out of reach (J2); Jest `setupFiles` run before the
runner (J3); custom Jest runners (jest-light-runner) are not traced (J16); Playwright measured only (J11); the cache does
not see native reads below Node (`process.binding`, C `getenv`) and needs the same work paths on every machine that
shares a cache.

**Go** (docs/GO.md): Linux only; examples, benchmarks and fuzz corpora are never skipped; a panic ends the binary
(`interrupted`); packages run one at a time under `--det`; the overlay rebuilds std once per toolchain; goroutine
interleaving beyond the one-P scheduler, real timer delays, poller deadlines, vDSO / raw syscall clock reads and child
processes' clocks are not controlled; skip mode keys the day (a fixture expiring later today passes until the next UTC
day: run the nightly `--skip-real-clock` check); without strace nothing is reused.

**JVM** (docs/JVM.md V1-V20): only call sites in code under test are rewritten (JDK-internal clocks keep real time:
V1); native code and child processes not controlled (V2); thread interleaving not ordered (V3); no network
record/replay (V5); Gradle + JUnit 4 class order not controlled (V7); skip-with-proof inputs not keyed: JUnit extension
stores, `Unsafe`/`VarHandle` static writes, type annotations, some JDK caches (V20). The skip decision is not yet applied
to execution (table above).

## Gates

`claude/release-1` is the engine trunk: engine sessions branch from it and return by pull request. The workflow runs on
every push and on every pull request into it. A commit passes the gate when every blocking Linux x86_64 job is green:

1. `build`: `cargo test --workspace --exclude detpy-py` and every artifact built (wheel, addon, `libfenvix_go.a` +
   `fenvix-go`, `fenvix-agent.jar` + `fenvix-skip`).
2. `python` (3.12, 3.13, 3.14): the wheel installed and its extension also placed in `python/detpy` (some review tests
   import detpy from the source tree); `pytest tests -p no:randomly`, serial (R-019c E9/E10 change site-packages and break
   concurrent tests: they cannot run under `-n`), with the one pre-existing deselection both parent branches gate with
   (`test_review_r017.py::test_h2_…`, a results-file check). Includes the reviewer files R-019c
   (`test_absent_inputs_r019c.py`), R-020/R-020b (`test_review_r020*_dep_verdict.py`, `test_dep_verdict_r020*_fixes.py`),
   R-023/R-023b (`test_review_r023*.py`, `test_parallel_proof_r023_fixes.py`), R-032/R-032b (`review_r032*/`,
   `test_r032b_engine.py`) and the culprit keys (`test_culprit_keys.py`).
3. `node` (Node 22, 24, 26): every `node/test/*.test.js` (reviewer files R-021, R-021b, R-032, R-032b included).
4. `go` (**not blocking**: Go is in the tree, out of go-live scope): `go vet ./...` and `go test ./...` (review R-025 and R-025b tests included).
5. `jvm` (**not blocking**, out of go-live scope): control tests on JDK 8, 11, 17, 21 (Gradle and Maven, JUnit 5 and 4); skip-key tests and review R-022 on
   JDK 21.
6. `smoke` (Go and JVM legs not blocking): one real repository per language, installed with `release/install-image.sh`, driven through
   `release/fenvix`: two `--det` runs whose traces verify identical, two cache runs where the second reuses at least
   one test with proof and no outcome differs (`release/smoke.py`; repositories: pallets/itsdangerous 2.2.0,
   simple-statistics v7.9.3, google/uuid v1.6.0, google/gson 2.11.0).

Not gates (reported): `other-os`, R-001 results checks (`test_review_results.py`), the walks of each branch's harness
(their numbers stay in their own reports; they were measured on the branch engines, not re-run on release-1).

Open gates (state of 2026-11-20, REPORT section 0):
* Python on GitHub runners: `test_child_own_temporary_files_are_not_inputs` is refused because the runner image's
  `cat` calls `statx` on a file its process tree wrote (`follow.rs:694`: a real-clock read). This is a lost reuse, not
  a wrong one. The decision belongs to the parallel-proof lane.
* parallel-proof-3 round 4 (bcd6d9c4) is not merged yet: it waits for all-runners-2's port to `_proof.py`.
* Inherited (DECLARED): Go REPORT-3 PARTIAL, all-runners-2 REPORT-2 PARTIAL, parallel-proof review R-032b FAIL with
  round 4 landing. Release 1 is final only when those branches report final and their last tips are merged here.

## Runner image (packaging plan)

`release/install-image.sh DIST [FENVIX_HOME=/opt/fenvix]`, from the CI artifact `engine-linux-x64`:

| piece | installed as | needs in the image |
|---|---|---|
| `fenvix-*.whl` (engine artifact `wheels/`) | `install.sh` into the job's Python (pytest plugin entry point `detpy`, `python -m detpy`, `fenvix`) | CPython 3.12, 3.13, 3.14; pytest 8.1+; strace |
| detjs (`node/bin`, `node/src`, addon) | `$FENVIX_HOME/node` (no runtime npm dependencies) | Node 22, 24, 26 (suites and install test on each) |
| `fenvix-go` | `$FENVIX_HOME/bin/fenvix-go` | the project's Go toolchain (1.22+; the overlay builds per toolchain), strace |
| `fenvix-agent.jar`, `fenvix-skip` | `$FENVIX_HOME/jvm/`, `$FENVIX_HOME/bin/` | JDK 8+ for the test JVM (agent built with JDK 21), the project's Gradle or Maven |
| `release/fenvix` | `$FENVIX_HOME/bin/fenvix` | Python 3 (stdlib only) |

The GitHub App / runner wrapper (`runner/fenvix-run`) drives pytest today; extending it to the other languages goes
through `fenvix detect` and the per-language commands above (not done in release 1).
