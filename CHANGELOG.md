# Changelog

All notable changes of the fenvix engine. One version for every component (`release/version.py`: Cargo.toml,
`detpy/_version.py`, `node/package.json`). The engine ships as one artifact per trunk build,
`fenvix-engine-<version>-r<run>.<sha7>-linux-x86_64.tar.gz`, published by `.github/workflows/release-1.yml`
(docs/INSTALL.md). The format follows Keep a Changelog; versions follow Semantic Versioning.

## [Unreleased]

### Changed
- Node `--det` uses the machine's values by default (spec 2026-11-23), so it stops failing tests that pass without
  it; each old default stays one flag away:
  - clock: the epoch is the machine's time when the run starts (rounded down to the second), picked once and shared
    by every process and session of the run (parallel lanes, the one-lane re-run, `--det-isolate`, the repro
    driver); `--det-cache` keeps the virtual day; `--det-compare`/`--det-plan=TRACE` take that trace's epoch; the
    trace header has `meta.epoch` (ISO) beside `meta.epoch_ns`. Opt-out: `--det-epoch=fixed` (2025-01-01).
    Certificates a test makes now validate (`certificate has expired` before).
  - time zone and locale: kept from the machine and recorded. Opt-out: `--det-tz=UTC --det-locale=C.UTF-8`.
  - network: new `--det-net=open|closed`, default `open`: external hosts are reached live, recorded as `allowed`
    events with their bytes in the fingerprint, never reused by the cache, `*_PROXY` variables are run inputs.
    Opt-out: `--det-net=closed`. `--det-record` and an existing cassette keep recording / replaying.
    A name sent to the live resolver (`dns.lookup`, `resolve*`, `reverse`) is an `allowed` event too and keeps the
    test out of the cache. Bun's and Deno's native `fetch` / `Bun.connect` / `Deno.connect` follow the same default.
  - `--det-isolate` without `--det` (it implies `--det`): one epoch for all its per-test sessions.
  - `fenvix repro` / `explore` bundles record the failing run's `epoch`; the bundle's command and `fenvix replay` use it.
  - timers: unchanged (virtual; the runner timeouts stay virtual, G-0144). `--det-timers=real` as before.
  - `selfcert.generate(commonName, { notBefore, notAfter })` takes an optional validity.

## [0.1.0]

First versioned engine artifact.

### Added
- The engine artifact for our machines: Linux x86_64 with glibc 2.28+ (manylinux_2_28, built with zig), one
  reproducible tarball with its sha256, a manifest of every file (`VERSION.json`) and an installer (`install.sh`);
  built, install-tested in clean containers (AlmaLinux 8 / glibc 2.28, Debian 12, Debian 13) and published as a
  GitHub pre-release on every merge into the trunk.
- The wheel `fenvix` (`cp312-abi3-manylinux_2_28_x86_64`): pytest plugin, `python -m detpy` runners and the single
  `fenvix` command (`--version`, `version`, `doctor`, `python`, `python-runner`, `node`, `verify`, `detect`).
- `fenvix` / `detjs` Node commands answer `--version` and `--help`, name an unknown runner, and print a user error
  without a JavaScript stack.
- `detpy_core::host`: the loaded images, CPU features and live children of the process, from `/proc` on Linux (and
  from the OS's own interfaces on macOS, which the engine does not ship for).

### Changed
- Supported interpreters: CPython 3.12, 3.13, 3.14 (`Requires-Python >=3.12`, stable ABI 3.12); older ones,
  free-threaded builds and other implementations are refused with one message and exit code 4 by the installer,
  `pytest --det`, `python -m detpy` and the commands, never with a traceback.
- pytest 8.1+ is required (8.0 broke `--det-isolate` on unittest classes); pytest-xdist older than 3.7 under
  `--det -n` is a usage error naming the version.
- Unsupported platforms (macOS, arm64, musl, glibc < 2.28, Windows) get one message naming the supported one.
