# Native extensions audited by measurement

Founder decision, 2026-11-21 (route 1): *"the commonly used compiled extensions are audited one by one by
MEASURING what they actually ask the system for, and only those are listed, with the evidence. An unaudited
compiled extension is NOT PROVEN. A hand audit is our promise, not a proof; only a syscall-level sensor makes
it a proof."*

A compiled extension's own reads are invisible to every in-process sensor, so the general rule refuses any test
whose run loads one (`crates/detpy-core/src/provable.rs`, the declared residual). This file is the evidence for
each extension that is nevertheless listed as audited, and the limit of each audit.

Every audit here is a **measurement with `strace`** of the extension doing its job in isolation, with the
syscalls counted between two markers so that the runtime's own start-up is not credited to it. The command and
the numbers are given so the measurement can be repeated.

## Node

### `@unrs/resolver-binding-*` (`unrs-resolver` 1.13.0), the module resolver of jest 30 and vitest

Why it matters: `jest-resolve` depends on it, so a **jest 30 run loads it before the first test**. Without this
audit no test of any jest 30 suite can ever be proven, cached, or spread across cores — MEASURED on a 4-file
jest project: `covered by Level 0: 0  not proven: 12`, every test refused with
`native:.../@unrs/resolver-binding-linux-x64-gnu/resolver.linux-x64-gnu.node`.

Measurement (2026-11-22, this container, linux-x64-gnu, node 22.23.5): five specifiers resolved
(`./src/state.js`, `./src/state`, `jest-resolve`, `vitest`, `./helpers`), `strace -f` over
`openat, newfstatat, stat, lstat, statx, getdents64, getrandom, clock_gettime, gettimeofday, socket, connect,
readlink, uname, getpid, read, write`, counted between a `MARK-START` and a `MARK-END` write:

```
statx 20   openat 7   read 6
```

and nothing else. In particular **no `getdents64`** (it never enumerates a directory, so no listing order can
reach a test), no `getrandom`, no clock read, no `socket`/`connect`, no `getpid`, no `uname`, no `readlink`.
Every path it touched was named, not discovered: the `package.json` of each directory on the resolution path
and the candidate module files themselves.

The argument: what this extension carries into a run is the PATH a specifier resolves to, and the content at
that path. Both are already run inputs the engine records and the verifier compares (the imported project
source and the installed packages, P-062 step 1). So its reads add no channel the engine does not already
observe through another one.

Limits of this audit, written down rather than implied:

* it covers resolution through `package.json` fields and file extensions, which is what the two runners do. A
  resolution that crosses a symlink (pnpm's store) would add a `readlink` of a named path — the same argument
  covers it, but it was not measured here;
* it covers version 1.13.0 on `linux-x64-gnu`. A different version or platform binding is a different binary;
* it is a measurement of the syscalls this extension makes while resolving, not a proof about its code.

### `node:wasi` (not an addon, but the same question)

`node:wasi` is a builtin, so it is the accounting table's business and not this file's, but the judgement is of
the same kind and belongs next to these. The engine replaces `random_get` and `clock_time_get` on every WASI
instance's import object and records both (`node/src/wasi.js`). What it does NOT observe is a filesystem given
to the instance through `preopens`: those imports go straight to the real one. So the class answers
`Controlled` and each filesystem import marks the running test `uncontrolled.io` at its own call -- per thing,
not per feature: a module that only draws entropy and reads the clock is provable, one that opens a file is
not.

### The engine's own addon (`detjs.<platform>-<arch>.node`, `libdetpy_node.so`)

It is the engine. It was exempt only because it is loaded before the sensor starts, which is timing and not a
reason, so it is named in the list: an engine loaded later, or re-loaded in a worker, is exempt for a reason.

## Python

The Python side's list is `CONTROLLED_NATIVE` in `crates/detpy-core/src/provable.rs`: the engine's own
extension and the standard library's accelerators. No third-party extension is listed, so a suite that imports
numpy, pydantic-core, lxml or psycopg comes out NOT PROVEN. That is the honest consequence of the residual.

### `_time_machine` (the `time-machine` pytest plugin's extension) — the engine's own integration

Why it matters: **merely having `time-machine` installed made every test of every suite NOT PROVEN** — MEASURED
on this branch, a one-test project in a venv with time-machine: `unaccounted = ["native:_time_machine"]`. And
the import is the ENGINE's, not the test's: `python/detpy/clock.py` reads an active travel through
`clock_time_machine_ns` so that `time_machine.travel` is honoured under `--det` instead of being silently
ignored, and while a travel is active the virtual clock returns its destination (a ticking travel advances with
the VIRTUAL counter). So the load is the engine's own act, which Rule E puts outside what the test observed,
and what the extension answers is pinned by the engine's control --
`tests/test_clock.py::test_time_machine_travel_is_honoured` asserts exactly that.

The measurement, and what it does NOT prove: travelling and reading `time`, `monotonic` and `localtime` inside
the travel, then `time` after leaving it, made **zero syscalls** under `strace`. That is not evidence that the
extension never reads the real clock, because a clock read goes through the vDSO and never appears in a trace.
The entry rests on the engine's control over what it returns, not on that measurement, and this paragraph is
here so that nobody later mistakes the one for the other.

### numpy 2.5.5 — MEASURED, NOT cleared

Measured the same way (2026-11-22, this container, CPython 3.13.18, numpy 2.5.5): `strace -f` between two
markers while numpy did ordinary work — `arange`, a multiply and a `sum`, `reshape`, `linalg.norm`, `sort`, and
a SEEDED `default_rng(7).random(5)`:

```
stat 52   openat 23   read 30   mmap 43   getdents64 2   getrandom 2
```

The file reads are the lazy import of `numpy.random` (its `.so` and `.pyc` files), which the engine already
records as run inputs, and the two `getdents64` are the import machinery listing `numpy/random/__pycache__`.

**The two `getrandom` calls are the problem.** The generator was seeded, so nothing in that script should ask
the kernel for entropy, and I could not attribute them inside the time of this block (the most likely source
is an OpenSSL initialisation pulled in by the same import — `/etc/ssl/openssl.cnf` is among the paths — but
"most likely" is not an attribution). A C-level `getrandom` is invisible to the engine's Python-level entropy
control, so clearing numpy on this evidence would be a green on a doubt.

numpy therefore stays unlisted, and a test that imports it is NOT PROVEN, naming it. What the engine's own
suite asserts about numpy is the seeding (`tests/test_f01_gaps.py::test_numpy_imported_lazily_and_unseeded_generators`:
the printed values are equal in both runs, the refusal names numpy, and the test that does not touch numpy stays
covered by Level 0). To finish this audit someone has to attribute those two calls, with `ltrace` or a
breakpoint on `getrandom`, and then re-measure on 3.12 and 3.14 as well.
