# Installing the fenvix engine

The go-live runs on our machines only. The engine ships as **one versioned artifact** for them, built and tested by
the trunk CI (`.github/workflows/release-1.yml`) on every merge into `claude/release-1` and published as a GitHub
pre-release with a stable URL:

    https://github.com/Mircoguidetti/fenvix-engine-cli/releases/download/engine-<version>-r<run>.<sha7>/fenvix-engine-<version>-r<run>.<sha7>-linux-x86_64.tar.gz
    ... and the same URL + .sha256

The runner image pins the file name (version + build) and its sha256. The tarball is reproducible (fixed order,
owner, mtimes; gzip without name or time): the same commit gives the same sha256.

## Contents

| path | what |
|---|---|
| `wheels/fenvix-<v>-cp312-abi3-manylinux_2_28_x86_64.whl` | pytest plugin (`pytest --det`), runners (`python -m detpy unittest\|django\|nose2\|ward\|zope-testrunner\|doctest`), the `fenvix` command |
| `node/` | Node shells (`fenvix node vitest\|jest\|mocha\|node-test\|ava\|tap\|uvu\|jasmine\|bun-test\|deno-test`) and the native core `detjs.linux-x64.node` |
| `bin/fenvix` | the `fenvix` command for the image (runs the wheel's `detpy.fenvix_cli` with the image's Python) |
| `install.sh` | the installer |
| `VERSION`, `VERSION.json` | version, build, commit, supported versions, sha256 of every file |

## Install

```bash
sha256sum -c fenvix-engine-<...>-linux-x86_64.tar.gz.sha256
tar xzf fenvix-engine-<...>-linux-x86_64.tar.gz
PYTHON=python3 ./fenvix-engine-<...>-linux-x86_64/install.sh /opt/fenvix   # PREFIX, default $FENVIX_HOME or /opt/fenvix
fenvix --version && fenvix doctor
```

`install.sh` installs the wheel into `$PYTHON`'s environment (its one dependency, pytest>=8.1, from the index unless
already there) and the Node shells into `PREFIX/node` (no npm install: no runtime dependencies). A job that makes
its own environment (tox, nox, uv, poetry, another setup-python) installs the wheel from `wheels/` into it the same
way (`pip install wheels/fenvix-*.whl`).

## Supported

| | supported | otherwise |
|---|---|---|
| machine | Linux x86_64, glibc 2.28+ (tested: AlmaLinux 8 / manylinux_2_28, Debian 12, Debian 13, Ubuntu 24.04) | `install.sh` and the Node loader stop with one sentence (macOS, arm64, musl/Alpine, older glibc) |
| Python | CPython 3.12, 3.13, 3.14 | `install.sh` exits 4 with one sentence; a copy forced into an older interpreter refuses `pytest --det` and `python -m detpy` (exit 4); free-threaded builds and PyPy likewise |
| pytest | 8.1+ and 9; pytest-xdist 3.7+ for `-n` under `--det` | older xdist: a usage error naming the version |
| Node | 22, 24, 26 | other versions: a warning at install, not tested |

The Python import package is `detpy`. The unrelated PyPI project `detpy` installs a package with the same import
name: never install it next to the engine; `fenvix doctor` reports it.

## What the machine needs besides the artifact

| need | for | without it |
|---|---|---|
| `strace` | skip with proof of tests that start processes (`--det-cache`) | those tests run every time ("not cacheable: subprocess") |
| a C compiler (`cc`, `gcc` or `clang`) at run time | the child-process clock shim of `--det-cache` | tests that start processes run every time |
| permission for `personality(ADDR_NO_RANDOMIZE)` | ASLR off under `--det` | the run continues with "ASLR on" in the header |
| `git` | nothing in the engine; the projects' own steps | |
| `libatomic1` (Debian/Ubuntu slim images) | Node 26 itself (its binary links `libatomic.so.1`) | `node` does not start: `error while loading shared libraries: libatomic.so.1` (MEASURED on `python:3.14-slim`) |

Containers: Docker's default seccomp profile denies the ASLR switch (`--security-opt seccomp=unconfined`, or accept
"ASLR on"); ptrace must be allowed for strace (default Docker allows it; gVisor does not). Keep the `--det-cache`
directory on a volume that outlives the container.

## Uninstall

`pip uninstall fenvix`; remove `PREFIX`. Runs leave (safe to delete): `.detpy/`, `.detjs/`, `.fenvix/` in the
project, `~/.cache/detpy/`, `~/.cache/fenvix/`, `node_modules/.detjs/`, and the `--det-cache` directory chosen.
