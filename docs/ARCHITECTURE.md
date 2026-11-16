# detpy architecture

```
┌──────────────────────────── pytest process ─────────────────────────────┐
│                                                                          │
│  test code ──calls──▶ time / random / os / glob / pathlib / socket / ssl │
│                         │  (patched by the Python shell)                 │
│                         ▼                                                │
│   python/detpy/  clock.py  seeds.py  fsorder.py  network.py  reexec.py   │
│                  └──────── _state.record(source, op, value) ───────┐     │
│   plugin.py  (pytest hooks: options, order, per-test begin/end)    │     │
│                                                                    ▼     │
│   detpy._core  (Rust, PyO3)                                              │
│     Recorder ── Fingerprinter (BLAKE3 hash chain) ── TraceWriter (JSONL) │
│     Cassette (network record/replay)   shuffle_order / derive_seed       │
│     verify / verify_text (cross-run verifier)                            │
└──────────────────────────────────────────────────────────────────────────┘
          trace_1.jsonl … trace_N.jsonl ──▶ `detpy verify` / harness
```

## Rust core (`crates/detpy-core`, bindings in `crates/detpy-py`)

| module | responsibility |
|---|---|
| `event` | `Event {thread, source, op, site, value}`, `Source` (time, random, fs, net, entropy, outcome, syscall, other) and its canonical, length-prefixed byte encoding (versioned by `ENCODING_VERSION`). |
| `fingerprint` | `Fingerprinter`: hash chain `h_{i+1} = BLAKE3(h_i ‖ enc(e_i))`, terminated by the outcome event. Keeps the first `max_events` events verbatim plus a checkpoint (chain head) every `checkpoint_every` events, so the fingerprint always covers every event while memory stays bounded. The node id is *not* hashed: only behaviour is. |
| `recorder` | Per-test lifecycle (`begin_test` / `record` / `end_test`), streams one JSON line per finished test (crash-safe partial traces). Implements the `EventSink` trait. |
| `trace` | JSONL format: header (format, version, encoding, free-form `meta`, executed `order`), one `test` line per test, footer (count, order digest). |
| `verify` | Loads N traces, compares fingerprints per test, finds the first diverging event (exact index from stored events, or a `[lo, hi)` window from checkpoints) and classifies it: `time`, `random`, `fs`, `net`, `entropy`, `thread`, `outcome-only`, `beyond-trace`, `missing`. |
| `order` | `derive_seed(base, key)` and a hierarchical, reproducible shuffle (module → class → test) built on SplitMix64 + Fisher–Yates, identical on every Python version and platform. |
| `cassette` | Recorded connections per test: ordered `send`/`recv` segments (plaintext above TLS), base64 in JSON. |
| `cache` | Vocabulary for a future result cache: `CacheKey` (node id + code digest + environment digest), `CachePolicy` (only stable tests that touched no live network/entropy/syscall source), `ResultCache` with memory and JSON-file implementations. Not wired into the plugin yet. |
| `backend` | `Backend::PythonHooks` (implemented) and `Backend::Syscall` (reserved) with declared `Capabilities` (what is controlled vs. only observed). |

### Extension points

* **Syscall-level interception (Hermit-style).** A tracer backend (ptrace +
  seccomp-bpf, or running under Meta Hermit) would intercept
  `clock_gettime`, `getrandom`, `getdents64`, `connect`, `sched_*`… below
  the interpreter, including native extensions and subprocesses. It only has
  to push `Event`s into the same `EventSink`; the fingerprint, trace format,
  verifier and harness are unchanged. Divergence reasons the Python backend
  cannot explain today (`outcome-only`, `thread`) are exactly what
  `Capabilities::{sees_native_code, controls_scheduling}` advertise.
  Planned layout: a `detpy-tracer` crate exposing `run_under_tracer(argv) ->
  Trace`, selected by `--det-backend=syscall`.
* **Result cache.** Once `verify` has shown a test stable over ≥ 2 runs and
  its record has no `net`/`entropy` events, `CacheKey::compute(nodeid,
  code_digest, env_digest)` can map to its outcome; the plugin would then skip
  it in `pytest_runtest_protocol` when the key hits. The missing piece is the
  code digest (e.g. hash of the modules imported by the test, collected with
  an import hook).

## Python shell (`python/detpy`)

| file | role |
|---|---|
| `plugin.py` | pytest hooks. `pytest_load_initial_conftests` (earliest hook with parsed options) re-execs if needed and installs the controls before conftest files and test modules are imported. `pytest_collection_modifyitems` (hookwrapper) restores collection order after other plugins and applies the seeded shuffle. `pytest_runtest_protocol` (hookwrapper) brackets each test: reset clock, reseed generators, reset network counters, begin/end fingerprint. |
| `reexec.py` | `os.execve` of `sys.orig_argv` with `PYTHONHASHSEED` fixed and, on Linux, `personality(ADDR_NO_RANDOMIZE)`. Restores pytest's early fd capture before exec. Guarded against loops and nested in-process sessions. |
| `clock.py` | Virtual clock (single nanosecond counter, tick per read). Patches `time.*` module functions and the C types `datetime.datetime`/`datetime.date` *in place* (`now`, `utcnow`, `today`). `threading.Condition.wait` timeouts advance the clock; asyncio's loop keeps real time. |
| `seeds.py` | Per-test reseeding (`derive_seed(seed, nodeid)`), deterministic default seeds for `Random()`/`default_rng()`, observation (or optional control) of OS entropy. |
| `fsorder.py` | Sorted `os.listdir`, `os.scandir` (thus `os.walk`, `shutil`), `glob`, `pathlib` iteration. |
| `network.py` | Connection policy (block / record / replay), DNS guard, socket- and ssl-level recording, socketpair-based replay with a TLS stand-in. |
| `_sites.py` | Call-site resolution (first non-stdlib frame; events from pytest/detpy are dropped) and path normalisation (`<basetemp>`, `<tmp>`, `<site>`, `<stdlib>`, rootdir-relative). |
| `_patch.py` | Reversible patching, including C types; `disguise()` keeps replacements picklable. |
