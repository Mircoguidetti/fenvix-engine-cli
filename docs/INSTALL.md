# Installing fenvix

Two packages, one version (CHANGELOG.md):

| ecosystem | install | gives |
|---|---|---|
| Python | `pip install fenvix` (or `fenvix[xdist]`) | pytest plugin (`pytest --det`), runner shells (`python -m detpy unittest\|django\|nose2\|ward\|zope-testrunner\|doctest`), the `fenvix` command |
| Node | `npm install --save-dev fenvix` | runner shells (`npx fenvix vitest\|jest\|mocha\|node-test\|ava\|tap\|uvu\|jasmine\|bun-test\|deno-test`), commands `fenvix` and `detjs` |

Check an installation with `fenvix --version` (both packages print `fenvix X.Y.Z`) and `fenvix doctor` (Python).

## Supported

| | supported | refused with a message |
|---|---|---|
| OS / CPU | Linux x86_64 and arm64 with glibc 2.28+ (Debian 10+, Ubuntu 20.04+, RHEL/Alma/Rocky 8+, Amazon Linux 2023); macOS 11+ on Apple silicon | musl (Alpine), glibc < 2.28, Windows, macOS on Intel |
| Python | CPython 3.12, 3.13, 3.14 | older CPython (pip: `Requires-Python >=3.12`; at start: exit 4), free-threaded builds (3.13t/3.14t), PyPy |
| pytest | 8.1+ and 9; pytest-xdist 3.7+ for `-n` under `--det` | older pytest (pip), older xdist (usage error) |
| Node | 22, 24, 26 (`engines: >=22`) | older Node is not tested |

Wheels: `cp312-abi3-manylinux_2_28_x86_64`, `cp312-abi3-manylinux_2_28_aarch64`, `cp312-abi3-macosx_11_0_arm64`
(one wheel per platform serves every supported CPython). npm: the native core is the optional dependency of your
platform (`@fenvix/linux-x64-gnu`, `@fenvix/linux-arm64-gnu`, `@fenvix/darwin-arm64`); do not install with
`--omit=optional`.

The Python import package is `detpy`. The unrelated PyPI project `detpy` installs a package with the same import
name: never `pip install detpy`; `fenvix doctor` reports it if it is present.

## In tox, nox, hatch, poetry, uv

The plugin must be installed in the environment that runs pytest: add `fenvix` to that environment's test
dependencies (`deps = fenvix` in tox, `session.install("fenvix")` in nox, a dev dependency in poetry/uv).

## What the machine needs besides the packages

| need | for | without it |
|---|---|---|
| `strace` (Linux) | skip with proof of tests that start processes (`--det-cache`) | those tests run every time ("not cacheable: subprocess") |
| a C compiler (`cc`, `gcc` or `clang`) at run time (Linux) | the child-process clock shim of `--det-cache` | tests that start processes run every time |
| permission to call `personality(ADDR_NO_RANDOMIZE)` (Linux) | ASLR off under `--det` (addresses, `id()` order) | the run continues with "ASLR on" in the header |

macOS: child processes are not followed (no strace), so under `--det-cache` a test that starts a process runs
every time; ASLR cannot be switched off; `--det-isolate` falls back to the carried-set rule (one line in the
summary). The libraries a test loads, the CPU's features, internet sockets opened by C code and live children are
observed on macOS as on Linux.

## Containers and CI images

Docker's default seccomp profile (GitHub Actions `container:` jobs, GitLab Docker executors, Kubernetes
`RuntimeDefault`) denies the ASLR switch: run with `--security-opt seccomp=unconfined` or accept "ASLR on". `strace`
must be installed in the image and ptrace allowed (default Docker allows it; gVisor does not). Mount the cache
directory (`--det-cache=DIR`) on a volume that outlives the container.

## Uninstall

`pip uninstall fenvix`, `npm uninstall fenvix`. What runs leave behind (safe to delete): `.detpy/`, `.detjs/`,
`.fenvix/` in the project; `~/.cache/detpy/` (precompiled bytecode under a fixed hash seed), `~/.cache/fenvix/`;
`node_modules/.detjs/`; the `--det-cache` directory you chose.
