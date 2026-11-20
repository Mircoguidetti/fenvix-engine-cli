PARTIAL

# Release 1: one branch, one engine, four languages — report

Session 2026-11-20, branch `claude/release-1` of fenvix-engine-cli (release candidate head: see section 4).
Labels: **MEASURED** (Actions run id, or local command with the machine named), **ESTIMATED**, **DECLARED** (taken from
a branch's own report or docs, not re-measured here), **UNKNOWN**. The brain repository was not written from this
session: this report lives on the engine branch.

## 0. Answer

* **PARTIAL.** Every launch language is on one branch (`claude/release-1`, head 64a9e5c7 + this report), built from
  one Cargo workspace and tested by one workflow (`.github/workflows/release-1.yml`). One CLI entry (`release/fenvix`)
  and one image install (`release/install-image.sh`) exist. On run 44710687525 (64a9e5c7), all of these are green:
  build, Go, JVM (JDK 8/11/17/21), Linux arm64, and the four smoke tests (Python, Node, Go, JVM), each driven through
  the installed image. What keeps this from DONE:
  1. **Python gate: 1 of 954 tests fails on GitHub runners only.**
     `test_proofcache_follow.py::test_child_own_temporary_files_are_not_inputs`, runs 44700422692 and 44705350906, on
     3.12 and 3.13. The engine's reason (printed since 5e1a531d): *"sh (subprocess.Popen) at test_m.py:5 [reads the real
     clock (the time of a file it wrote: statx /tmp/tmp.…/f)]"*. On the runner image, `cat` stats the file its process
     tree just wrote with `statx`, and the follower rule (`crates/detpy-py/src/follow.rs:694`) refuses that as a
     real-clock read. Here coreutils 9.4's `cat` uses `fstat`, and the test passes (as root and as `nobody`, MEASURED).
     The engine errs on the safe side: a lost reuse, not a wrong one. The rule belongs to the parallel-proof lineage.
     The test is neither skipped nor changed in substance; only its assertion message now names the reason. Decision
     for that lane: whether a statx on a path the tree itself wrote should key the time instead of refusing (round 4
     moved user mtime reads that way, `7778dbb9`).
  2. **parallel-proof-3 round 4 (bcd6d9c4, 7 commits) is not merged.** It changes the F2 design in the shared capture
     (a user mtime/ctime read is keyed, `y:`), and its Python half lands in `proofcache.py`, which all-runners-2 moved
     to `_proof.py`. all-runners-2 has ported every earlier F2 round itself (89971a3/0f45362 → 13d402fa); a third port
     here would make a second implementation of one concern. The merge was attempted, conflicted in 4 files, and was
     aborted. Merge it after all-runners-2's port.
  3. **Inherited open gates (DECLARED):** parallel-proof review R-032b FAIL with round 4 landing; all-runners-2 REPORT-2
     PARTIAL (walks); go-l0 REPORT-3 PARTIAL (its D3 CI fix is merged here and green: run 44710687525). No moving
     branch has reported final, so step 5 is open.
  4. **JVM skip with proof is a decision, not a skip.** `fenvix-skip decide` says what is reusable; no build-tool
     integration skips execution yet (DECLARED, docs/JVM.md).
  5. **macOS: UNKNOWN.** `macos-14` never got a runner in any run (cancelled at queue).
* **No soundness traded.** Every conflict was resolved toward the stricter rule (section 3), and each port carries its
  branch's tests. The tests found four integration defects, all fixed (section 3.4).

### Scope decision (coordinator, 09:55 UTC)

`claude/release-1` is now the engine trunk. Engine sessions branch from it and return by pull request, which the
coordinator merges, so this session merges no further moving tips (parallel-proof-3 round 4 included: it comes as a
PR). Commit 644a455b makes `release-1.yml` run on every pull request into the trunk, with Python 3.12/3.13/3.14 and
Node 22/24/26 (Python 3.14, Node 24 and Node 26 are not measured yet: UNKNOWN until the first run). The Go and JVM jobs
and their smoke legs are not blocking: they stay in the tree but are out of go-live scope.

## 1. Branches, merge bases, unique content

All four lines share history with `claude/parallel-proof-3`. They looked unrelated only because the session's
clone was shallow; `git fetch --unshallow` restored the merge bases (MEASURED).

| branch | merge base with parallel-proof-3 | unique content (outside sessions/, results) |
|---|---|---|
| `claude/all-runners-2` | 72100d3c (pp3 merged in) | `crates/detpy-node`, `node/` (detjs, all JS runners; node-cache-proof ported), `python/detpy/runners/`, `_proof.py` / `_level0.py` (runner-neutral session), `runner/` |
| `claude/jvm-l0` | 227c1610 (2026-11-16) | `crates/fenvix-jvm`, `crates/fenvix-skip`, `jvm/` (agent, rt, maven-ext, gradle, tests, fixtures, harness). It also carries node-l0 (8e9209bb: `node/`, `crates/detpy-node`, detpy-core event/order/trace/verify), unchanged since |
| `claude/go-l0` | 227c1610 | `crates/fenvix-go`, `go/`, `harness/go`; the same node-l0 copy |
| `claude/exact-culprit` | d470b597 | `record_session_keys` (detpy-core), `CacheSession.record(keys=)`, `--det-cache-keys`, `harness/culprit/`, `tests/test_culprit_keys.py` |
| `claude/dep-verdict-abjcfw` | in parallel-proof-3 already | — |
| `claude/node-cache-proof` | (closed) | already ported into all-runners-2 |

Integration order: all-runners-2 tip (a719d94b at session start) → jvm-l0 → go-l0 → exact-culprit, then the
moving tips repeatedly.

## 2. Commits integrated (final state of this session)

| branch | last commit merged | merge commit on release-1 |
|---|---|---|
| claude/all-runners-2 | b4c921ff | 64a9e5c7 (earlier: a719d94b base, de456ab1 ← a9893338, 13d402fa ← ce34ce02) |
| claude/jvm-l0 | 8317f887 (closed) | b712246e |
| claude/go-l0 | 655f98f5 | 340ee59c (earlier: e6040e51 ← f28d2ad8, 02f68965 ← a658fb0b, cd104375 ← 4b4c3315, 0e342e84 ← 27ec80b1) |
| claude/exact-culprit | abe3ffc2 (closed) | 820a0019 |
| claude/parallel-proof-3 | 50a2238d (tip bcd6d9c4: round 4 not merged, see 0.2) | 377ddb5c (earlier: 271f4d5f ← 41968480, 012135fb ← 19ba7982) |
| claude/dep-verdict-abjcfw | 43d52671 (via parallel-proof-3) | — |

Release-1's own commits: 315a3c41, 1b57b351, 75334097, 498e543e, 9db671ff, acb80e2b, 0b2eeae3, plus this report and
`docs/RELEASE-1.md`.

## 3. Conflicts and how they were resolved

### 3.1 jvm-l0 and go-l0 (shared crates)

* `node/`, `crates/detpy-node`, `crates/detpy-core/src/trace.rs`, `docs/NODE.md`, `README.md`: the jvm-l0/go-l0 side
  was byte-identical to node-l0 8e9209bb (checked per file, MEASURED). all-runners-2 carries the later lineage
  (node-l0 → node-cache-proof → port), so its side was kept. Neither JVM nor Go changed shared core code beyond node-l0;
  only `Cargo.toml` members changed (MEASURED: `git diff 8e9209bb origin/claude/{jvm,go}-l0 -- crates/detpy-core ...`).
* API drift: the engine lineage renamed `trace::merge_traces(parts, out, header)` to `trace::concat_traces`. The name
  `merge_traces` now means the parallel merge. `fenvix-jvm` (JNI `mergeTraces`) and `fenvix-go`
  (`fenvix_merge_traces`) now call `concat_traces`; the C/Java interfaces are unchanged.
* `Cargo.toml` members: the union of all six crates. `.gitignore`: union. `Cargo.lock`: regenerated by cargo.

### 3.2 exact-culprit onto the refactored engine

exact-culprit's diff targeted the pre-refactor layout (options in `plugin.py`, session in `proofcache.py`). It was
ported, not duplicated:
* `detpy_core::record::record_session_keys` and `dump_test` sit inside the engine's record loop, after the carried-set
  rule. The dump therefore holds the test's whole key, carried contexts included, and names them in a new
  `"carried"` field. `out.carried` counts recorded tests only.
* `CacheSession.record(keys=)` / `keys_json` (PyO3). `ProofSession.keys_path` / `_dump_keys` live in the
  runner-neutral `_proof.py`, so the dump works for the pytest plugin and every `python -m detpy` runner. There is one
  file per xdist worker or `--det-isolate` child (`<path>.<gwN>` / `<path>.<pid>`).
* `--det-cache-keys` is in `_level0.OPTIONS` and is volatile, not configuration, in both the engine and the reference
  capture.
* `tests/test_culprit_keys.py`: one assertion encoded the pre-carried-set key ("f is not an input of test_g_fails").
  On the engine, `test_f` runs earlier in the process and reaches the same module, so its context is carried
  (R-020 / round 3). That is sound. The assertion now checks that `f` is in the key via the carried `test_f`, that the
  first test carries nothing, and that `g` is not in `test_f`'s key.

### 3.3 parallel-proof-3 R-032b F2 against all-runners-2's stat capture

The two lineages had two designs for the same concern: all-runners-2 keys a user `stat` with a metadata probe
(`q`/`Q`: kind, mode, size, mtime, link target); parallel-proof-3 (coordinator's correction) refuses a test that reads a
time field. Both apply on release-1. The probe keys mtime, but neither design keys atime or ctime, so the time-field
refusal is needed for soundness. Write invalidation clears `z`, `q` and `Q`. The final resolution is all-runners-2's own
port of pp3 89971a3/0f45362 (merge 13d402fa), which superseded release-1's interim port. pp3 9b20f6a (site-packages and
stdlib known at capture start) was applied in `_proof.start_capture` (377ddb5c). `Capture` moved to `_proof.py` on
all-runners-2.

### 3.4 Defects found by the tests while integrating (fixed)

1. The interim F2 port lacked pp3 97e61ac's "user code only" condition, so pytest's assertion rewriting (source
   mtimes) would have refused every test. Fixed in 498e543e (then superseded by all-runners-2's port).
2. `test_capture_sessions_match_reference` failed: the reference capture's volatile-option list lacked
   `det_cache_keys`, so the config digests differed. Fixed in 9db671ff.
3. CI: R-008/R-008b start interpreters that import `detpy` from `python/`, which had no compiled `_core` (the parent
   gates run after `maturin develop`). The CI now puts the wheel's extension there too (529c1609).
4. The Python suite under `pytest -n 4` broke other tests: R-019c E9/E10 add a `.pth` file and an entry point to
   site-packages. The same failures occur on the all-runners-2 baseline (MEASURED, local venv). The gate runs serially,
   as both parent branches gate.

### 3.5 One implementation per concern: what remains

* **Skip deciders.** `crates/fenvix-skip` (JVM: class-file digests, class lookups, classpath resources, static state)
  and `crates/fenvix-go/src/skip.rs` (Go: test binary, strace inputs, clock rule) are runtime-specific rules, both
  Rust. Their file-value helpers (content digest, metadata value) overlap with `detpy_core::proof` (`probe_now`,
  digests). Folding those helpers into detpy-core is open. It changes keys, so each lane's key tests must re-gate.
  Python and Node share `detpy_core::proof`.

## 4. CI (Linux x86_64 gated; other platforms reported)

Workflow `release-1.yml`. Runs on this branch: 44686929297, 44688434841, 44688631508, 44688802910 and 44689296016
were cancelled or superseded while queued (pushes). Results:

| job | run 44689328374 (498e543e) | run 44691940543 (acb80e2b) | run 44700422692 (529c1609, final engine code) |
|---|---|---|---|
| build: cargo workspace tests + wheel + addon + libfenvix_go.a/fenvix-go + agent/fenvix-skip | success | success | **success** |
| python 3.12 / 3.13 (serial, every reviewer file) | cancelled mid-run | 3.13: 5 failed (R-008/R-008b ×4: the source tree had no `_core`, fixed in 529c1609; the 5th not shown, the step filtered its output); 3.12: cancelled | **1 failed, 952 passed, 73 skipped** (3.13; 3.12 the same single failure): `test_proofcache_follow.py::test_child_own_temporary_files_are_not_inputs` (section 4.1) |
| node (all node/test, R-021/R-021b/R-032/R-032b) | cancelled mid-run | failure (no output: the step filtered it; the run predates 13d402fa) | **success** |
| go (vet + test, R-025/R-025b) | failure: `TestR025b_D3_UncontrolledEntropy` only | same | same (pre-existing on go-l0, run 44660485039) |
| jvm 8 / 11 / 17 / 21 (controls Gradle+Maven, JUnit 5+4; skip keys + R-022 on 21) | success ×4 | success ×4 | **success ×4** |
| smoke python | check bug (outcomes read flat) | same (old smoke) | **success** |
| smoke node | wrong tag | (old smoke) | **success** |
| smoke go | success | success | **success** |
| smoke jvm | success | success | **success** |
| other-os ubuntu-24.04-arm (Rust core + decider, wheel, Python subset) | success | success | **success** |
| other-os macos-14 | cancelled (no runner) | cancelled (no runner) | cancelled (no runner): UNKNOWN |

Run 44705350906 (5e1a531d, the same engine code; the failing test's message now prints the reason): Python
3.12/3.13 the same single failure, with the reason quoted in 0.1; Go still D3.

**Run 44710687525 (64a9e5c7: + go-l0 655f98f5 with the D3 CI fix, + all-runners-2 b4c921ff):** build success, **go
success**, jvm ×4 success, smoke python/node/go/jvm success, arm64 success, macOS cancelled (no runner). Python and
Node were still running when this report was written. The Python engine code is identical to run 44705350906 (the
merges changed only Go code and results files, MEASURED: `git diff --stat 5e1a531d 64a9e5c7 -- crates python node`
is empty), so its expected result is that single failure; this is not measured on this run.

Local gates on the candidate tree (MEASURED, this container: 4 CPUs, Linux 6.18, Python 3.13.18, Go 1.24.7,
Node 22, JDK 21):
* `cargo test --workspace --exclude detpy-py`: detpy-core 137, fenvix-go 19, fenvix-skip 13, fenvix-jvm 2 passed, 0 failed.
* Python, serial, `pytest tests -p no:randomly` with the parent branches' one deselection (0e342e84): **954 passed,
  68 skipped, 1 xfailed, 4 failed**. After the extension was placed in `python/detpy` (529c1609), R-008/R-008b pass
  12/12 (5 skipped) locally. The 4 were `test_review_r008.py::test_hole_module_on_an_import_path_outside_site_and_root`,
  `::test_hole_cpu_count_visible_to_the_process` and `test_review_r008b.py::test_hole_symlinked_package_directory_on_an_import_path`,
  `::test_hole_sourceless_module_on_an_import_path`. They fail the same way on the all-runners-2 baseline wheel in the
  same kind of venv (MEASURED) and passed in all-runners-2's own gate (DECLARED: run after `maturin develop`). Cause
  (MEASURED): they start interpreters that import `detpy` from the source tree, which needs the compiled extension
  there. The skip count is higher than
  all-runners-2's 55 because this venv lacks some optional runner packages (UNKNOWN which; CI is the reference).
* Node: `node --test test/*.test.js` with a fresh addon (529c1609): **622 tests, 621 pass, 1 skipped, 0 fail**.
* Go: `go vet ./... && go test ./...` on Go 1.24.7 (after the go-l0 merge): exit 0, D3 included.
* JVM: `jvm/build.sh` builds `fenvix-agent.jar` (751,891 bytes) and `fenvix-skip`.

## 5. Smoke tests (one real repository per language, GitHub Actions, through the installed image)

`release/install-image.sh` installs the CI artifact into `/opt/fenvix`; `release/smoke.py` drives everything through
`release/fenvix`. Pass: two `--det` runs whose traces `detpy verify` finds identical; two skip-with-proof runs where
the second reuses at least one test and no outcome differs.

| language | repository | --det (verify) | skip with proof | run |
|---|---|---|---|---|
| Python | pallets/itsdangerous 2.2.0 | 297 covered, 0 not covered, 0 outcome-unstable | 297 of 297 reused with proof in run 2; 297/297 outcomes equal | 44700422692 |
| Node/TS | simple-statistics v7.9.3 (node:test) | 277 covered, 0 not covered, 0 outcome-unstable | 277 tests in 76 files reused with proof in run 2 (ran 0 files); the outcome comparison covered only the 76 entries in run 1's receipts (0 differing): a weaker check than the other three | 44700422692 |
| Go | google/uuid v1.6.0 | 40 covered, 0 not covered | 39 of 40 reused; 43/43 outcomes equal | 44691940543, 44700422692 (also 44689328374) |
| JVM | google/gson 2.11.0 (Maven, `-pl gson`) | traces identical | decision: 1324 of 1371 tests reusable; 0 reusable tests whose fresh outcome differs | 44689328374, 44691940543, 44700422692 |

## 6. Single CLI entry and packaging

* `release/fenvix` (Python stdlib, interface only) dispatches `python`, `python-runner`, `node`, `go`, `jvm run`,
  `jvm decide`, `verify`, `detect` and `version` to the installed shells. No engine logic.
* `release/install-image.sh DIST [FENVIX_HOME]`: wheel into the job's Python; detjs (no runtime npm deps) and its addon;
  `fenvix-go` (self-contained, built in CI); `fenvix-agent.jar`, `fenvix-skip`. Versions: everything `0.1.0`
  (DECLARED). Toolchains are the image's. Full table: docs/RELEASE-1.md.
* Not done: `runner/fenvix-run` (the GitHub App's wrapper) still drives pytest only; extending it to `fenvix detect` and
  the other languages is open.

## 7. What is missing

1. The parallel-proof lane's decision on the `statx`-of-a-file-it-wrote refusal (0.1), then a green Python job on
   GitHub runners.
2. Merging parallel-proof-3 round 4 once all-runners-2 has ported it (0.2), and every moving branch's final tip, then a
   fully green candidate run.
3. JVM: applying the skip decision to execution (Gradle/Maven integration).
4. macOS arm64 measurement (no runner obtained); Windows never built.
5. One shared implementation of the file-value helpers used by the three skip deciders (section 3.5).
6. The runner wrapper / GitHub App for non-Python languages (`runner/fenvix-run` drives pytest only).
7. Node smoke: the outcome comparison covers only the first run's 76 receipt entries; compare per test from the
   runner's own output.
