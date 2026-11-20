# Changelog

All notable changes of the packages `fenvix` (PyPI) and `fenvix` / `@fenvix/<platform>` (npm). One version for
every package (release/version.py); a release is the git tag `v<version>` (.github/workflows/release.yml).
The format follows Keep a Changelog; versions follow Semantic Versioning.

## [Unreleased]

## [0.1.0]

First packaged release.

### Added
- PyPI package `fenvix`: the pytest plugin (`pytest --det`), the Python runner shells (`python -m detpy ...`), the
  `fenvix` command (`--version`, `doctor`, `verify`, `python`, `node`). Wheels `cp312-abi3` for Linux x86_64 and
  arm64 (manylinux_2_28) and macOS arm64 (11.0+), plus the sdist.
- npm package `fenvix` (the Node runner shells, commands `fenvix` and `detjs`) with the native core in one optional
  package per platform: `@fenvix/linux-x64-gnu`, `@fenvix/linux-arm64-gnu`, `@fenvix/darwin-arm64`.
- macOS: the engine observes the libraries loaded into the process (dyld), the CPU features (sysctl), internet
  sockets opened in C (/dev/fd + getsockname) and live child processes (proc_listchildpids).

### Changed
- Supported interpreters: CPython 3.12, 3.13, 3.14 (`Requires-Python >=3.12`); older ones, free-threaded builds
  and other implementations are refused with one message and exit code 4, at install and at start.
- Supported Node: 22, 24, 26 (`engines`); unsupported platforms (musl, glibc < 2.28, Windows, macOS Intel) get one
  message naming the supported ones.
