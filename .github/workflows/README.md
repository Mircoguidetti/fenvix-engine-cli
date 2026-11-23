# Workflows of fenvix-engine-cli

## The gate: `release-1.yml`

`release-1.yml` is the only workflow that gates the trunk `claude/release-1`. It runs the same jobs at two depths
(founder's CI rule of 2026-11-20; header comment of the file):

- **LIGHT** on every `pull_request` into `claude/release-1` and every `push` (merge) into it: build, Python 3.13,
  Node 24, attacks, smoke. Until 2026-12-22 the Python job runs only the test files labelled `shared` in
  `release/python-tests.txt` (they exercise code Node uses); the `python-product` files run on FULL only.
- **FULL** nightly (`schedule`) and by hand (`workflow_dispatch`, depth `full`): Python 3.12/3.13/3.14, Node 22/24/26,
  every Python test file, the install tests, and `publish-engine`, which runs on FULL runs of the trunk only.

Every other workflow below is a measurement, a demo or a helper: none of them runs on the trunk, on a schedule or on a
pull request.

## The other workflows (30)

"In the 22 Dec plan": whether the workflow belongs to the Node-only work planned until 2026-12-22.

| File | What it does | Trigger (as written in the file) | In the 22 Dec plan |
|---|---|---|---|
| `all-runners-node-b.yml` | detjs shells for tap, AVA, Jasmine and uvu: control and wrong-reuse tests, then `--det --det-cache` walks of real repositories. | `workflow_dispatch` | yes |
| `all-runners-node-c.yml` | detjs for Bun (`detjs bun-test`) and Deno (`detjs deno-test`): runner tests and skip-with-proof walks. | `workflow_dispatch` | yes |
| `all-runners-node.yml` | detjs `--det-cache` for `node --test` and Mocha, measured over windows of 31 commits. | `workflow_dispatch` | yes |
| `all-runners-python.yml` | Measures `python -m detpy <runner> --det --det-cache` (unittest, Django, nose2, doctest, zope.testrunner, ward) over consecutive commits. | `workflow_dispatch` | no |
| `block2.yml` | Block 2 measurement: `detpy explore` + repro against pytest-randomly seeds, one job per (repository, tool). | `workflow_dispatch` | no |
| `cache-proof.yml` | Measures `pytest --det --det-cache` (children followed under strace) over consecutive commits. | `workflow_dispatch` | no |
| `dep-verdict-annotations.yml` | Helper of the dependency-update verdict: check-run annotations of upstream CI failures after dependency-only commits. | `workflow_dispatch` | no |
| `dep-verdict.yml` | Validates the dependency-update verdict (harness/dep_verdict/) against the projects' own CI. | `workflow_dispatch` | no |
| `fenvix-demo-hosted.yml` | Rehearsal of `fenvix-demo` on a GitHub-hosted machine, the cache carried between the two jobs as an artifact. | `workflow_dispatch` | no |
| `fenvix-demo-jobs.yml` | Reusable body of the `runs-on: fenvix` demo: two jobs on two commits of a public pytest project, the second reusing with proof and checking every reuse. | `workflow_dispatch`, `workflow_call` (called by `fenvix-demo.yml` and `fenvix-demo-hosted.yml`) | no |
| `fenvix-demo.yml` | The first `runs-on: fenvix` demo on our self-hosted machine: commit N, then N+1 reusing with proof. | `workflow_dispatch` | no |
| `fenvix-shared-cache.yml` | Measures cross-machine reuse through the shared cache service on GitHub-hosted machines (runner/fenvix-run, Python projects). | `workflow_dispatch` | no |
| `go-harness.yml` | Go measurement rounds (P-021 step 5); each job commits its results to harness/go/results/. | `workflow_dispatch` | no |
| `go-nightly-real-clock.yml` | Real-clock check of Go skip mode (review R-025b NC). Despite its name, it has no schedule. | `workflow_dispatch` | no |
| `go-tests.yml` | Engine tests of the Go shell (fenvix-go) and its C ABI crate. | `workflow_dispatch` | no |
| `harness.yml` | The detpy (Python) measurement round as a matrix, one repository per runner. | `workflow_dispatch` | no |
| `jvm-harness.yml` | JVM Level 0 round on IDoFT Maven projects, one job per project. | `workflow_dispatch` | no |
| `jvm-skip-walk.yml` | Skip with proof over 50 commits of Java/Kotlin repositories, sharded. | `workflow_dispatch` | no |
| `jvm-tests.yml` | JVM shell: build (Rust core JNI + agent), engine and control tests on Java 11/17/21, Level 1 measurement. | `workflow_dispatch` | no |
| `node-cache-proof.yml` | detjs `--det-cache` (skip with proof for Vitest / Jest), measured over windows of 51 commits. | `workflow_dispatch` | yes |
| `node-dataset.yml` | Fetches the JavaScript flaky-test dataset (Hashemi et al., ICSME 2022) from Zenodo and commits it to harness/node/dataset/. | `workflow_dispatch` | yes |
| `node-harness.yml` | detjs (Node / TypeScript) measurement round as a matrix, one repository per runner. | `workflow_dispatch` | yes |
| `node-repro.yml` | F-02 Node: `fenvix repro` on every test of the Node Block 1 flaky set, on the engine of the commit. | `workflow_dispatch` | yes |
| `parallel-node.yml` | Parallel with proof for the JavaScript runners (row JS-07), across Node versions. | `workflow_dispatch`, `push` to `claude/parallel-node` (paths filter) -- that branch is already merged into the trunk (5a6463f), so the push trigger no longer fires in practice | yes |
| `parallel-proof.yml` | Parallel with proof P0: `pytest --det -n N` against plain `pytest -n N` and serial `--det` on market-test repositories. | `workflow_dispatch` | no |
| `publish-results.yml` | Commits the results artifact of a harness run to the branch tip when the run's own commit step could not push. | `workflow_dispatch` | no |
| `release.yml` | PyPI publishing of the wheel `fenvix`: DISABLED (the engine ships through `publish-engine` of release-1.yml); kept for the reserved trusted publisher. | `workflow_dispatch` | no |
| `runner-usage.yml` | P-032 step 1: package download statistics of the test runners (npm registry and pypistats.org). | `workflow_dispatch` | no |
| `rust-hotpaths-walk.yml` | Measures `pytest --det --det-cache` over consecutive commits with the rust-hotpaths engine. | `workflow_dispatch` | no |
| `rust-hotpaths.yml` | Overhead profile of `pytest --det --det-cache` (plain, --det, cold/warm cache, py-spy) per engine. | `workflow_dispatch` | no |

Several headers above say "triggered by a push that changes ...": in these files that push trigger is no longer
present; `workflow_dispatch` is what the file declares (verified on the file's `on:` block).
