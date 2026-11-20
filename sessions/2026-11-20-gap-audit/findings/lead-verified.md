# Lead re-verification log (claims re-run by the lead on the release-1 wheel, Python 3.13.18, Linux x86_64)

- L-V1 (PY2-001): `--det-cache` makes a passing order-dependent test fail. Project /home/user/audit/work/lead/carry:
  record => `5 passed`; `echo 2 > data.txt`; same command => `reused 4 result(s) with proof, ran 1 ... FAILED
  test_c.py::test_carried_state - assert (0 == 4)`; plain pytest => `5 passed`. CONFIRMED.
- L-V2 (PROC2-024): a module on PYTHONPATH outside the project root changes VALUE 1 -> 22: second cache run =>
  `reused 1 result(s) with proof, ran 0 ... 1 passed`, same runtime digest; plain pytest => `1 failed
  (assert 22 == 1)`. CONFIRMED wrong reuse.
- L-V3: no `--det-threads` / `--det-async` anywhere in release-1 sources (`grep -rnE "det[-_]threads|det[-_]async"
  python crates node/src go jvm` => only the event vocabulary in crates/detpy-core/src/{event,verify}.rs). CONFIRMED.
- L-V4: engine remote default branch is `claude/gracious-rubin-eyswxd`; no `main`; `git ls-remote --tags origin` => 0
  tags. CONFIRMED.

## Platform probe, GitHub Actions run 44703540913 (branch claude/gap-audit @ 28eab34), job `containers` (MEASURED)

Artifacts built on ubuntu-latest exactly as release-1.yml builds them (`maturin build --release --compatibility linux`).
- `objdump -T`: `detjs.linux-x64.node`, `fenvix-skip` and `detpy/_core.abi3.so` all need **GLIBC_2.34**. Wheel file
  name `detpy-0.1.0-cp39-abi3-linux_x86_64.whl` (tag `linux_x86_64`, not `manylinux`).
- python:3.12-alpine (musl): `pip install` succeeds, then `pytest --det` => `Error while loading plugin "pytest11"` ...
  `ImportError: Error loading shared library libgcc_s.so.1: No such file or directory (needed by .../detpy/_core.abi3.so)`.
- python:3.12-slim-bullseye (Debian 11, glibc 2.31): `ImportError: /lib/x86_64-linux-gnu/libc.so.6: version
  'GLIBC_2.33' not found (required by .../detpy/_core.abi3.so)`.
- quay.io/pypa/manylinux2014_x86_64 (glibc 2.17): same `GLIBC_2.33 not found`.
- python:3.12-slim, Docker default seccomp: `pytest --det` => `3 passed`; `strace -f true` rc 0; `--det-cache` x2 =>
  `reused 3 result(s) with proof` (with strace installed, without strace installed, and with `--cap-drop ALL
  --security-opt no-new-privileges`: first run recorded 3; tests had no child process).
- python:3.9-slim: `pytest --det` (no cache) => collection error `AttributeError: 'code' object has no attribute
  'co_qualname'` at `detpy/plugin.py:567` (via `_rewriter_digest`, plugin.py:600); `1 error in 0.13s`. With
  `--det-cache`: `ERROR: --det-cache needs Python 3.12+ (sys.monitoring)`. So Level 0 itself fails on Python 3.9
  although the wheel is tagged cp39 and docs say "3.9+ for --det".
- python:3.14-slim: `pytest --det` => `3 passed`.
- node:22-alpine: `require('/dist/detjs.linux-x64.node')` failed (exit 1); the probe script stopped there (my script
  bug: `set -e`), the remaining Node/fenvix-skip container probes were re-run in a follow-up workflow.
- job `other-os (macos-14)`: cancelled at queue in the same second it was created (the label release-1.yml uses for
  its `other-os` job; same outcome as release-1 runs 44689328374, 44691940543).

## Platform probe, run 44703540913, job `other-os (windows-latest)` (MEASURED; Python 3.13.17, Node 22.23.4, Go 1.26.10, JDK 21)

Step table (rc, last line), from the job log:
- `jvm: jvm/build.sh` rc 101: `error: could not compile 'detpy-core' (lib) due to 2 previous errors` (the Rust core
  does not compile on Windows; every binding depends on it).
- `python: python -m detpy ...` rc 1: `No module named detpy` (no wheel was built); `--det`, `--det-seed`,
  `--det-cache`, `-n 2 --det`, `--det-isolate` all rc 4 (pytest usage error: unknown option).
- `node: build addon` rc 1; `node: load addon` rc 1; node/test controls, cache, jsdom, runner-mocha, runner-node-test,
  projects: all rc 1.
- `go: build fenvix-go (cgo, static core)` rc 1: `collect2.exe: error: ld returned 1 exit status`; plain `go test`
  rc 0; go shell suite `FAIL`.
- `cli: release/fenvix version` rc 0 but reports every component absent; `release/install-image.sh` rc 1.
Result: no component of the engine builds or runs on Windows.

## Run 44705292795 (gap-audit-containers) and run 44703690223 (macOS 15 arm64), MEASURED

- Node addon loads on glibc 2.36 under Node 16, 18, 20, 22, 24 (36 exports); fails on node:22-alpine
  (`ld-linux-x86-64.so.2` missing) and node:22-bullseye-slim (`GLIBC_2.33 not found`).
- fenvix-skip: works on Ubuntu 22.04; `GLIBC_2.34 not found` on Debian 11 and Ubuntu 20.04; `not found` on Alpine.
- Python `--det`: 3.10 (python:3.10-slim and Ubuntu 22.04 python3) => co_qualname collection error; 3.11 => 2 passed;
  Amazon Linux 2023 python3.12 => 2 passed; free-threaded 3.14t => `unrecognized arguments: --det`; PyPy 3.11 => no
  output captured (UNKNOWN).
- macOS 15 arm64: Rust crates build; wheel `detpy-0.1.0-cp39-abi3-macosx_11_0_arm64.whl` builds and all Python user
  probes pass (verify shows the same fs NOT-COVERED as Linux, LEAD-016); engine cache subset has 1 failure; detjs addon
  builds, Mocha and node:test runner suites fail; `fenvix-go: only linux is supported (GOOS=darwin)`; jvm/build.sh
  fails on the hard-coded `.so`; install-image.sh fails on the hard-coded linux addon.

## Run 44705292795 (gap-audit-containers) and run 44703690223 (macOS 15 arm64), MEASURED

- Node addon loads on glibc 2.36 under Node 16, 18, 20, 22, 24 (36 exports); fails on node:22-alpine
  (`ld-linux-x86-64.so.2` missing) and node:22-bullseye-slim (`GLIBC_2.33 not found`).
- fenvix-skip: works on Ubuntu 22.04; `GLIBC_2.34 not found` on Debian 11 and Ubuntu 20.04; `not found` on Alpine.
- Python `--det`: 3.10 (python:3.10-slim and Ubuntu 22.04 python3) => co_qualname collection error; 3.11 => 2 passed;
  Amazon Linux 2023 python3.12 => 2 passed; free-threaded 3.14t => `unrecognized arguments: --det`; PyPy 3.11 => no
  output captured (UNKNOWN).
- macOS 15 arm64: Rust crates build; wheel `detpy-0.1.0-cp39-abi3-macosx_11_0_arm64.whl` builds and all Python user
  probes pass (verify shows the same fs NOT-COVERED as Linux, LEAD-016); engine cache subset has 1 failure; detjs addon
  builds, Mocha and node:test runner suites fail; `fenvix-go: only linux is supported (GOOS=darwin)`; jvm/build.sh
  fails on the hard-coded `.so`; install-image.sh fails on the hard-coded linux addon.

## Run 44703540913, job other-os (ubuntu-24.04-arm), MEASURED

Linux arm64: wheel, addon (`detjs.linux-arm64.node`), fenvix-go and the agent jar all build; Python user probes and
both engine Python subsets pass; node/test controls, cache, jsdom, runner-mocha, runner-node-test, projects pass;
`fenvix-go test --det` works; `--skip-cache` reused 0 of 4 on both runs (strace was not installed by the probe, so this
is the documented no-strace behaviour, not an arm64 finding); go/ suite FAIL; install-image.sh fails on the hard-coded
x64 addon. The JVM control-test step failed in the probe script itself (it expects JAVA_HOME_<v>_X64 variables), not
counted as a finding. Job other-os (macos-15-intel) was still running at the report cut-off: UNKNOWN.
