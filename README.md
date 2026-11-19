# detpy — deterministic execution of Python tests (Level 0)

`detpy` makes a pytest run reproducible at the Python level and *proves* it:
every test gets an execution **fingerprint** (a hash chain over the
non-deterministic sources it touched, plus its outcome). Two runs with
different fingerprints mean the test is **not covered by Level 0**, and the
verifier shows the exact event where the runs diverge.

* Core in **Rust** (`crates/`), exposed to Python with **PyO3** (built by maturin):
  fingerprints, cross-run verifier, trace and cassette formats, reproducible
  shuffle. Designed for a future syscall-level backend (Hermit-style) and a
  result cache — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
* Thin **pytest plugin** (`python/detpy`), enabled with `--det`.
* **Harness** (`harness/`) that measures cost and benefit on real projects.
* Known limits: [docs/LIMITS.md](docs/LIMITS.md). Harness results:
  [harness/results/](harness/results/).

## Install

```bash
pip install maturin
maturin develop --release        # or: maturin build --release && pip install target/wheels/*.whl
```

## Use

```bash
pytest --det                          # Level 0, fixed order, trace in .detpy/trace.jsonl
pytest --det --det-seed=42            # reproducible shuffle (nightly multi-seed runs)
pytest --det --det-trace=run2.jsonl --det-compare=.detpy/trace.jsonl   # report not-covered tests
detpy verify run1.jsonl run2.jsonl run3.jsonl                          # same, offline
pytest --det --det-record             # allow the network once and record responses
pytest --det                          # later runs replay them from .detpy/cassette.json
```

What `--det` controls:

| # | control | how |
|---|---|---|
| 1 | test order | collection order, re-imposed after other plugins (pytest-randomly & co. are switched off); `--det-seed=N` shuffles modules → classes → tests reproducibly (Rust SplitMix64). The executed order and its digest are written in the trace. |
| 2 | seeds | `random` reseeded per test with `derive_seed(seed, nodeid)`; unseeded `Random()` and `numpy.random.default_rng()` get derived seeds; numpy's global state reseeded; `PYTHONHASHSEED` fixed by re-executing the interpreter (Linux: ASLR disabled in the same exec); bytecode precompiled under the fixed hash seed so set literals iterate identically in every run. |
| 3 | virtual clock | `time.time/time_ns/monotonic/perf_counter(_ns)/clock_gettime/localtime/gmtime/ctime/strftime`, `datetime.now/utcnow/today`, `date.today` read a virtual clock: wall time starts at `--det-epoch` (2025-01-01Z) for every test, every read advances `--det-tick` ns (doubling after `--det-tick-adapt` consecutive reads with no other event, so time-calibrated loops such as pytest-benchmark terminate), `time.sleep` advances without waiting; timed-out `Condition/Event/Queue` waits advance it by their timeout. |
| 4 | filesystem order | `os.listdir`, `os.scandir` (so `os.walk`, `shutil`), `glob.glob/iglob`, `Path.iterdir/glob/rglob` return sorted results. |
| 5 | closed network | connections/DNS/UDP to non-local hosts raise `detpy.NetworkBlockedError` (or `socket.gaierror` for DNS) with an explicit message; loopback and `AF_UNIX` allowed; local HTTP proxies count as external. `--det-record` records per-test byte streams (plaintext above TLS) and later runs replay them. |
| 6 | fingerprint | every interaction above (plus OS entropy reads, which are observed but not controlled) becomes an event `(thread, source, op, call site, value)`; the Rust core chains them with BLAKE3 and stores the trace. |

Other options: `--det-disable=time,fs,bytecode,...`, `--det-sleep=real`, `--det-urandom`
(make `os.urandom`/`uuid4` deterministic — beyond Level 0), `--det-tick-adapt=N`,
`--det-allow-host=H`, `--det-max-events=N`, `--det-keep-aslr`, `--det-no-reexec`,
`--det-outcomes=PATH` (outcome map, also without `--det`). See `pytest --help`.

## Node / TypeScript (detjs)

The same core drives `detjs`, a Level 0 shell for **Vitest** and **Jest**
(napi-rs bindings in `crates/detpy-node`, shell in `node/`). Traces and
cassettes share the Python format, so one verifier reads both.

```bash
cd node && npm run build && npm test     # build the addon; per-control tests on Vitest and Jest
detjs vitest run --det                   # or detjs jest --det; DETJS=1 also enables it
detjs vitest run --det --det-seed=3      # reproducible shuffle of files and tests
detjs verify run1.jsonl .detjs/trace.jsonl
detjs vitest run --det --det-cache=.detjs-cache   # skip test files with proof (receipts in .detjs/receipts.jsonl)
```

Cache with proof for Vitest and Jest (same Rust proof core, receipts and shared cache service as `pytest --det-cache`):
[docs/NODE-CACHE.md](docs/NODE-CACHE.md).

Controls, architecture and limits: [docs/NODE.md](docs/NODE.md). Harness:
`harness/node/` (results in `harness/node/results/`).

## Tests

```bash
cargo test -p detpy-core          # Rust core
maturin develop && pytest tests   # plugin (runs pytest in subprocesses via pytester)
```

## Harness

```bash
python harness/select_flaky.py idoft/py-data.csv                    # flaky pool from IDoFT
python harness/detpy_harness.py --set validate --runs 10            # 5 repositories
python harness/detpy_harness.py --set mixed --per-pool 25 --runs 10 --jobs 2   # 25 IDoFT + 25 popular
```

See [docs/HARNESS.md](docs/HARNESS.md) for what is measured and the CSV columns.
