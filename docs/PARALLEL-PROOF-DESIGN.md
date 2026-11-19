# Parallel with proof: `--det` across workers, and a footprint scheduler

Status: design and measurement only. No engine code changed (`crates/` and `python/detpy/` are being moved to Rust
on `claude/rust-hotpaths-2`; the build starts after that). Branch `claude/parallel-proof-design`, based on
`claude/rust-hotpaths-2` at f1c18492.

Labels: **MEASURED** (a run named in this document, raw files in `tracks/parallel-proof/`), **ESTIMATED** (derived
from measured numbers, the derivation is given), **DECLARED** (read from a repository's own configuration at the
pinned commit), **UNKNOWN** (not found; what was checked is said).

Engine measured: a wheel built from `claude/rust-hotpaths-2` at c28a5318 (the round-2 engine), Python 3.12,
pytest-xdist 3.8.0. Machine for every local run: this session's container, 4 vCPU, 15 GB, one run per variant
unless said otherwise, variants run one after another on an otherwise idle machine. Two plain serial runs of the
same esphome selection took 160 s and 180 s: read single local walls as ±12 %.

## 0. Answers in short

* **CI shape (DECLARED, 1.1).** Of the 11 market-test repositories (10 with results; haystack's walk produced no
  units), 8 run pytest-xdist in their unit CI: esphome (`-n auto`, load), pydantic-ai (`-n logical
  --dist=loadgroup`), prefect (`-n auto/logical --maxprocesses 6 --dist worksteal` + pytest-split, 8/18 groups),
  litellm (`-n 4 --dist loadscope` on 34 of 44 shards), mlflow (6 `-n auto --dist loadscope` shards + 4 serial
  shards), moto (`-n 4 --dist loadscope` for a subset, the rest serial), airflow (non-DB tests `-n <cpus>`), and
  community.general through ansible-test (`-n auto`). Serial: haystack, integrations-core. transformers' public CI
  is defined outside the repository (`-n 8`, EXTERNAL), its in-repo CircleCI generator uses `-n 4`.
* **What breaks today with `--det -n 4` (MEASURED, 1.4).** (0) On pydantic-ai it **does not start**: its
  `filterwarnings = error` turns detpy's own "xdist is not supported" warning into an INTERNALERROR (exit 3);
  prefect declares the same filter (DECLARED; predicted to abort the same way). With that warning silenced, the verdict equals serial `--det` on esphome and
  pydantic-ai, but: (1) the trace is lost (every worker and the controller write the same path;
  the controller's header-only `"collection": "failed"` file is what remains); (2) distribution is dynamic: 33 % of
  esphome's tests ran on another worker in two identical runs; (3) 50 of 14,446 esphome tests (0.35 %) have a
  different fingerprint in parallel than serially, for reasons that have nothing to do with noise (in-process state
  from earlier tests, `tmp_path` counters), 0 outcome flips; on pydantic-ai 455 of the 2,631 serially stable
  tests (17 %, mostly logfire/OpenTelemetry lazy state), 0 outcome flips, and two serial runs already disagree on
  67 % of its tests through uncontrolled `os.urandom`; (4) the cache under `-n`: the controller reports
  "reused 0, ran 0, recorded 0" and the receipts file is empty; each worker decides for the whole suite; tests that
  read the whole environment (3,000 on esphome, 21 %) are never reused because xdist sets a fresh
  `PYTEST_XDIST_TESTRUNUID` in every run; entries recorded under `-n` are never reused serially (and vice versa)
  because the workers' configuration digest contains xdist's `loadgroup` option; on pydantic-ai nothing at all was
  recorded, under `-n 4` and serially alike (a capture problem, 1.4.6); (5) **a wrong reuse**: a test that
  reads a file another worker's test wrote (outside the repository) is cached and later reused with a result the
  serial run contradicts (synthetic reproduction, 1.4.5).
* **Speed (MEASURED, local 4 vCPU).** esphome: `--det -n 4` 80-82 s vs plain `-n 4` 62-67 s (1.26x) and `--det`
  serial 175-177 s; serial `--det` is 2.7x slower than the customer's `-n 4` job here (the "about 4x" estimate
  assumed a 4x xdist speedup; plain xdist reaches 2.6-2.8x on 4 vCPU on esphome). pydantic-ai subset: `--det -n 4`
  139-140 s vs plain `-n 4` 151 s and `--det` serial 410-464 s (2.9x slower than the customer's mode). Today's
  `--det -n 4` is therefore already about as fast as plain xdist: what is missing is determinism of placement, the
  cache and the proof, not speed.
* **Found on the way (1.4.6):** with the capture on (`--det-cache`), 2,769 of 8,072 pydantic-ai tests fail
  (blockbuster: `os.path.abspath` in the asyncio loop thread, from detpy's audit hook); two esphome UDP tests hang
  under `--det` (raw `select` with a virtual timeout).
* **Design A (2):** keep xdist as process manager, replace its scheduling by a fixed plan (atoms from the customer's
  `--dist`, LPT on recorded durations, sticky), per-worker traces merged by the controller, reuse decided once in
  the controller, workers record shards, merged with a cross-worker write rule. 11 session-days with the proof.
* **Design B (3):** our own lanes (no xdist), constraints from footprints (exclusion for shared paths/ports,
  together-edges for data dependencies, polluters and the customer's groups), every parallel fingerprint checked
  against the test's serial fingerprint; a mismatch is resolved by a serial-equivalent rerun and becomes an edge.
* **Recording off the critical path (4):** feasible for the end-of-session recording (deferred or pipelined:
  saves 2.9-4.4 s per cold run on round 1, 0.8-2.9 s on round 2, 27.6 s of 232 s on esphome here), not for the
  in-test capture except by a shadow run.
* **Build plan (5):** 9 steps, 19-20 session-days, each with its tests and its acceptance measurement.

## 1. Measured facts

### 1.1 How the market-test repositories run pytest in CI (DECLARED)

Read at the market-test HEADs (`harness/market_test/specs/*.json` on `claude/market-test`), each repository checked
out at that commit; file and line evidence in `tracks/parallel-proof/CI-FACTS.md`.

| repository @ HEAD | unit-test pytest in CI | `-n` | `--dist` | split / matrix | runner | `xdist_group` | xdist worker id used by tests |
|---|---|---|---|---|---|---|---|
| airflow @ 56bbac12ad | breeze → `pytest ... --maxfail=50 --timeouts-order=moi ... [-n N]` in docker | non-DB: `-n <cpu count>`; DB tests: no xdist, one serial pytest per test type with its own DB container | load (default) | test types x Python 3.11-3.14 x DB backends (count data-dependent, UNKNOWN) | RunsOn self-hosted (8-64 CPU) or `ubuntu-22.04` | 0 | 0 |
| community.general @ 63fe14d2aa | `ansible-test units` (pytest line built by ansible-core, EXTERNAL: `-n auto`, each test forked) | auto (EXTERNAL) | load | ansible-core x Python: 15 Azure jobs | Azure `Standard` | 0 | 0 |
| esphome @ 141789d240 | `pytest -vv --cov-report=xml --tb=native --durations=30 -n auto tests --ignore=tests/integration/` | auto | load | Python 3.12-3.15 x 3 OS = 10 jobs; integration tests: 5 duration buckets (own script), `--dist worksteal` | `ubuntu/macOS/windows-latest` | 0 | 1 (per-worker library cache) |
| haystack @ 050a979cac | `hatch run test:unit` = `pytest --cov -m "not integration" test` | none | — | 3 OS | GitHub-hosted | 0 | 0 |
| integrations-core @ 5bedd04ea3 | `ddev test` → `pytest -vv --benchmark-skip --cov ...` per integration | none | — | one job per integration (221 Linux + 20 Windows on full runs) | `ubuntu-22.04` | 0 | 0 |
| litellm @ 17e6ea8cb7 | `pytest <paths> --maxfail=10 -n W --dist=D --reruns R --timeout=120 ...` | 4 (34 shards), 8 (4), 2 (4), none (2) | loadscope (41), load (2), worksteal (1) | 44 hand-written path shards | `ubuntu-latest` (40), `ubuntu-latest-16-cores` (4) | 20 (inert except under loadgroup) | 60 `PYTEST_XDIST_WORKER` reads (41 skip an `importlib.reload` under xdist) |
| mlflow @ c365f861ff | `pytest --serial=exclude -n auto --dist loadscope --splits=6 --group=G ...` + `pytest --serial=only --splits=4 ...` | auto (parallel shards), none (serial shards) | loadscope | 6 parallel + 4 serial shards (own round-robin split); 20 xdist-unsafe path prefixes listed in `tests/conftest.py` | `ubuntu-24.04` | 0 | 1 |
| moto @ 96f50b1aa9 | `make test-only`: serial `pytest ./tests/ <excludes>` + serial `-m requires_clean_slate` + `pytest -n 4 <PARALLEL_TESTS> --dist loadscope` | 4 (subset only) | loadscope | Python 3.10-3.15 x decorator/server mode = 12 | `ubuntu-latest` | 0 | 0 (54 `requires_clean_slate` markers) |
| prefect @ 5e8ca118fc | `pytest ... --numprocesses auto/logical --maxprocesses 6 --dist worksteal --splits N --group G --splitting-algorithm least_duration` | auto/logical, max 6 | worksteal | pytest-split by duration: 8 SQLite + 18 Postgres groups x 5 Python ≈ 141 jobs | `ubuntu-latest` | 0 | 4 (per-worker SQLite file / Postgres DB, API server on a pre-bound port) |
| pydantic-ai @ 62e7b66c9f | `pytest --durations=100 -n logical --dist=loadgroup --ignore=tests/durable_exec -m "not temporal"` | logical | loadgroup | Python 3.11-3.15 x 5 install shapes (25 on main, 12 on PRs) + module-level duration shards | `vars.CI_LINUX_RUNNER` or `ubuntu-latest` (value UNKNOWN) | 79 (each group shares one local Temporal/DBOS/Prefect server) | 2 |
| transformers @ a2a53c3be2 | public CI EXTERNAL (`huggingface/transformers-ci@main`, `-n 8`); in-repo CircleCI generator: `pytest -n 4 ... --reruns 5 --random-order-bucket=module` | 4 / 8 (EXTERNAL) | load; doc tests loadfile | CircleCI parallelism 2-8 split by timings; EXTERNAL 14 jobs x ≤8 shards | self-hosted `aws-m8i-l-cache` (EXTERNAL) | 0 | 3 |

Common to all 11 (DECLARED): no pytest-randomly in CI (transformers uses pytest-random-order), no `-p no:xdist`.
Global reruns: litellm (`--reruns 0|2`), transformers (`--reruns 5 --only-rerun`); marker-level reruns in airflow,
haystack, mlflow. Customer-maintained parallel-safety: pydantic-ai's 79 `xdist_group`s, mlflow's serial path list,
moto's `requires_clean_slate`, airflow's DB tests outside xdist, prefect's per-worker databases, esphome's
per-worker caches and `flock`. **That is the work a footprint scheduler takes off the customer (3).**

### 1.2 Suite sizes and how evenly they split

From the market-test walks (`harness/market_test/results/{m1,m3,m4,m5,m6,m7}/walk/*.json.gz` on
`claude/market-test`; GitHub Actions 4 vCPU, one pytest process per test file, plain pytest under the walk's
capture). "Full suite" = the market summary's `full_suite_test_s` (sampled per-file cost / sample fraction,
ESTIMATED). "File LPT" = sum of the sampled files' test times / makespan of a longest-first assignment of whole files
to 4 (8) workers (ESTIMATED: the speedup a duration-balanced file split could reach on the sample, ignoring
per-worker startup).

| repository | sample | files in sample | tests in sample | full suite, serial test time (ESTIMATED) | largest file / sample | file LPT, 4 workers | 8 workers |
|---|---|---|---|---|---|---|---|
| airflow | 6 % | 110 | 2,490 | 8,892 s | 16 % | 3.99x | 6.14x |
| community.general | 100 % | 247 | 2,892 | 182 s | 43 % | 2.35x | 2.35x |
| esphome | 50 % | 350 | 7,237 | 221 s | 9 % | 4.00x | 8.00x |
| haystack | 50 % | 0 (the walk produced no units) | 0 | UNKNOWN | — | — | — |
| integrations-core | 100 % | 1,126 | 8,646 | 1,674 s | 15 % | 4.00x | 6.66x |
| litellm | 10 % | 275 | 11,576 | 35,772 s | 28 % | 3.54x | 3.54x |
| mlflow | 10 % | 86 | 2,104 | 16,150 s | 12 % | 3.99x | 7.93x |
| moto | 25 % | 226 | 3,315 | 1,964 s | 22 % | 4.00x | 4.53x |
| prefect | 12 % | 57 | 2,502 | 12,298 s | 11 % | 3.98x | 7.85x |
| pydantic-ai | 30 % | 245 | 8,589 | 3,903 s | 8 % | 4.00x | 7.99x |
| transformers | 5 % | 57 | 10,610 | 26,115 s | 9 % | 3.99x | 7.94x |

Balance at file granularity is not the obstacle for 8 of 10 repositories; community.general and litellm have one
dominant file (a split inside that file, per test or per class, is needed there). On the full suites (10-20x more
files) the balance is better than on these samples.

### 1.3 Speed: plain, xdist, `--det` (MEASURED, local 4 vCPU)

Selections: **esphome** = the CI selection (`tests --ignore=tests/integration`, plus `--ignore=tests/benchmarks`,
`--no-cov`) minus `-k udp` (102 tests; two UDP tests hang under `--det`, 1.4.6): 14,446 tests. **pydantic-ai** =
`tests/models tests/harness/code_mode tests/harness/refine_output tests/harness/detect_loops
tests/providers/test_openai_compatible_http_clients.py -m "not temporal"` (includes `xdist_group` tests):
8,072 tests; `-n 4 --dist=loadgroup` as in its CI (`logical` = 4 here). Both with `-p no:randomly
--timeout=...` (pytest-timeout as a guard).

| | esphome | pydantic-ai |
|---|---|---|
| plain serial | 160 s / 180 s | 461 s |
| plain `-n 4` (customer's mode) | 62 s / 67 s (80 s with the UDP tests) | 151 s |
| xdist speedup, plain | 2.6-2.8x | 3.05x |
| `--det` serial | 177 s / 175 s | 464 s / 410 s |
| `--det -n 4` | 82 s / 80 s | aborts at start (exit 3, 1.4.3); with `-W ignore:detpy:UserWarning`: 139 s / 140 s |
| `--det -n 4` / plain `-n 4` | 1.26x | 0.92x (one plain run; within the noise) |
| **`--det` serial / plain `-n 4` (today's gap)** | **2.7x** | **2.9x** |
| cold `--det-cache` serial / warm | 232 s / 104 s (reused 14,151 = 98 %) | 1,447 s (3.1x plain), 2,748 failures, **0 entries recorded** (1.4.6); warm not run |
| cold `--det-cache -n 4` / warm / warm again | 104 s / 81 s / 75 s (reused 5,787, then 11,156 = 77 %) | 475 s / 458 s, 2,769 failures, 0 entries recorded, 0 reused |

`--det` serial costs about what plain serial costs on both suites (esphome 1.0-1.1x, pydantic-ai 0.9-1.0x): the
round-2 engine's `--det` overhead is small here; the gap to the customer is the missing parallelism, not the
controls. The capture (`--det-cache`) is another matter on pydantic-ai (1.4.6).

**Where a warm run goes** (MEASURED, esphome warm serial run, 99 s, 14,151 reused, 295 ran; py-spy at 100 Hz on
the re-executed process, `tracks/parallel-proof/results/esphome/warm-profile.txt`): plain pytest collection 17.3 s,
reuse decision (`_decide`, all 14,446 checks) 8.6 s, end-of-session recording 7.7 s, synthesised reports for the
14,151 reused tests 4.9 s (0.35 ms per reused test), the 295 tests that ran 11.8 s, other 5.7 s, plus start-up and
precompile before the profiler attached. For Design A this means: reporting every hit from the controller costs
about 5 s per 14,000 hits, single-threaded; the check is 8.6 s whether one process or four do it (today all four
do it); collection is the largest item, and xdist pays it in every worker, while Design B's lanes collect only the
files of the tests that must run (3.2).

### 1.4 What breaks when `--det` and `-n` are combined (MEASURED)

Commands: `harness` scripts in `tracks/parallel-proof/bin/`; per-worker traces were obtained with a harness-only
shim (`xd_pertrace.py`, loaded with `-p`) that suffixes `--det-trace`/`--det-cache-receipts` with the worker id,
because the engine itself does not (1.4.1). Fingerprint comparison: `placement.py` (serial A/B vs parallel A/B).

**1.4.1 Traces are lost.** Every worker and the controller use the same `--det-trace` path (default
`.detpy/trace.jsonl`). The controller collects nothing under xdist, so at session end it writes a header-only trace
(`"meta": {"collection": "failed"}`, `order: []`, 0 tests) over the workers' lines. Synthetic project, `-n 2`: the
final file has 2 lines, header and footer. With the shim, each worker's trace holds the full collection order (all
14,446 ids, xdist workers collect everything) and only the tests it ran.

**1.4.2 Controls are inherited, order is not detpy's.** Workers run with `PYTHONHASHSEED=0`, the
`ADDR_NO_RANDOMIZE` personality (`/proc/<pid>/personality` = 00040000), `PYTHONPYCACHEPREFIX` and
`PYTHONDONTWRITEBYTECODE=1` inherited from the re-executed controller, and `DETPY_REEXEC=1` stops a re-exec in the
worker (which would break execnet's stdin channel). The order inside a worker is the order xdist sends indices,
not detpy's: two identical `--det -n 4` runs put **4,776 of 14,446 tests (33 %) on a different worker**; per-worker
counts 3,897 / 2,029 / 4,535 / 3,985 in one run and 4,077 / 2,029 / 3,286 / 5,054 in the other. detpy prints
`UserWarning: detpy: pytest-xdist is not supported under --det` and goes on.

**1.4.3 Verdicts.** esphome: serial `--det` and `--det -n 4` (both runs) have the same 7 failures (4 tests that
fail without `--det` too because the container runs as root, 3 LIMITS C7 failures: a test stamps an mtime from the
virtual `time.time()`), 0 outcome differences on 14,446 tests. pydantic-ai: `--det -n 4` **does not start**: pydantic-ai sets `filterwarnings = ["error", ...]`, which turns detpy's own `UserWarning: detpy: pytest-xdist is not supported under --det` (raised in `pytest_configure`) into an `INTERNALERROR`, exit 3 after 6 s. prefect declares the same bare `"error"` filter (DECLARED, `pyproject.toml:304-305`), so it is predicted to abort the same way; airflow and mlflow only turn selected warnings into errors. With `-W ignore:detpy:UserWarning` added, serial `--det` and both `--det -n 4` runs have the same 2 failures (below, 1.4.6) and 0 outcome differences on 8,072 tests.

**1.4.4 Fingerprints: serial noise, parallel noise, placement.** For each test, the fingerprints of two serial
`--det` runs (A, B) and two `--det -n 4` runs (A, B):

| | esphome | pydantic-ai |
|---|---|---|
| tests | 14,446 | 8,029 (in all four traces) |
| serial A ≠ serial B (serial noise) | 67 (59 `os.urandom`, observed not controlled; 5 time; 3 fs) | **5,398 (67 %)**: 5,388 `os.urandom`, 6 time, 4 random |
| parallel A ≠ parallel B | 93 | 5,703 |
| differs from serial while the two serial runs agree (**placement**) | **50 (0.35 %)**, 41 of them in both parallel runs | **455** of the 2,631 tests whose serial runs agree (17 %), 164 of them in both parallel runs |
| first diverging event of the placement tests | fs 19, time 18, random 13 | time 448, random 7 (433 of them a clock read inside logfire / OpenTelemetry) |
| of which only the `tmp_path` counter (`<basetemp>/test_x0` vs `test_x1`) | 5 | 0 |
| of which in-process state left by earlier tests (hypothesis' internal state: 20 in `test_stacktrace.py`, 8 in `test_yaml_util.py`; module caches warmed by a predecessor, e.g. a `Path.glob` result cached by `script/helpers.py`) | 45 | 455 |
| placement tests whose outcome changed | **0** | **0** |

So the fingerprint is already almost position-independent: under the per-test reset of clock and seeds, a test's
event sequence changes with its placement only through process state earlier tests left behind (the O4 class) and
through the `tmp_path` counter (a normalisation gap). That is the property Design B's proof rests on.

**1.4.5 The cache under `-n`.**

* The controller builds its own `ProofCachePlugin`, sees no test, and prints `reused 0 result(s) with proof, ran
  0, recorded 0`; the receipts file it writes last is **empty** (esphome: 0 bytes; serial: 14,446 lines). With
  per-worker receipt paths, each worker's receipts are identical and cover the whole collection: **every worker
  decides reuse for every test** (4x the check; 7.3 s serially on esphome).
* Warm `-n 4` reused 5,787 tests, then 11,156 (77 %) on the next run, against 14,151 (98 %) serially. The misses:
  `env: environment variable *` 3,000, `new` 289, `data` 1. A test that enumerates `os.environ` makes the whole
  environment an input, and xdist sets `PYTEST_XDIST_TESTRUNUID` to a fresh `uuid4().hex` in every worker of every
  run (`xdist/workermanage.py:58`, `xdist/remote.py:416`) and `PYTEST_XDIST_WORKER` to the worker: **these 3,000
  tests (21 %) are never reused under xdist.** pydantic-ai: under `-n 4` **nothing was recorded at all**: after the cold run the store is empty (`"tests": {}`), the warm run reran all 8,072 tests (`new: no recorded result` for every test in every worker's receipts), and the cold wall was 475 s against 140 s for `--det -n 4`. The serial cold run recorded nothing either (1.4.6), so this is not caused by xdist; the cause is not visible: pydantic-ai replaces pytest's terminal reporter, which hides detpy's cache summary and warnings (UNKNOWN; P0 must capture them).
* **Serial and parallel entries do not mix.** The workers' configuration digest differs from a serial session's in
  one option, xdist's `loadgroup` flag (`config_identity`, diff of the two identities), which is not in
  `_VOLATILE_OPTIONS` (`numprocesses`, `dist`, `tx` are). A store written by `-n 4` is not reused by a serial run
  ("not reused: config") and vice versa.
* **Wrong reuse across workers** (synthetic, 3 sessions, `tracks/parallel-proof/synth/`): `test_a` writes a file
  outside the repository from `value.txt`, `test_b` (another file, so another worker under `--dist loadfile`) waits
  for it and asserts its content is `x`. Serially, B is never cached ("reads a file another test or fixture
  wrote"). Under `-n 2`: session 1 runs both, session 2 records B (its input digest = the file as A left it), session
  3 after `value.txt` changes to `y`: A reruns (`data: tests/value.txt`), **B is reused as passed**; a fresh serial run
  fails B. The same file inside the repository is caught (the store persists repository-relative written paths
  across sessions, `record.rs`), but only once the writer's worker has saved first, and never for absolute paths
  (`/tmp`, `$HOME`, a shared cache directory).
* The same scenario also shows the concurrency hazard of plain xdist: in session 3 B *passed* by reading the stale
  `x` before A rewrote it; serially it fails. The parallel verdict itself depended on timing.

**1.4.6 Not caused by xdist, found on the way.** Two esphome UDP tests
(`test_espota2.py::test_udp_channel_delivers_in_order`, `test_start_udp_falls_back_when_blocked`) hang under serial
`--det` (more than 180 s, 8.5 s without `--det`): `UdpChannel` waits with a raw `select` timeout computed from a
virtual `time.monotonic()` (LIMITS C4 "raw select" not covered). Three `test_sdkconfig.py` tests fail under `--det`
with or without `-n` (C7, virtual time written into a real mtime). Whole-environment readers also depend on the
shell's `$_` (the path of the last command, exported by bash): two otherwise identical warm runs started from two
different shell lines missed on `env` for all 14,151 entries; started through the same wrapper, both reused 98 %.
A CI step that invokes pytest differently from the previous run (another wrapper, `uv run` vs `python -m`) would
see the same miss: `_` (and xdist's variables, 1.4.5) belong outside the whole-environment digest. pydantic-ai: 2 tests fail under serial `--det` with or without `-n`: `test_a_streamed_run_can_end_pending_and_be_collected_later` (a streamed run ends pending instead of finished) and `test_bedrock_extra_headers_registration_is_serialized_across_threads` (blockbuster flags `lock.acquire` of detpy's wrapped `threading.Lock`, C4). Under `--det-cache` (capture on), **2,769 of 8,072 tests fail** with `blockbuster.BlockingError: Blocking call to os.path.abspath`: the capture's audit hook resolves paths inside the asyncio loop thread, where pydantic-ai's blockbuster fixture forbids blocking calls (same class as LIMITS F2, found then for globbing). Serial and parallel alike: the serial cold run has 2,748 failures with the same error (raised from
`proofcache.py` `_audit` → `Capture.arm` → `_want` on `exec` events), and **neither the serial nor the parallel cold
run recorded a single entry** (store `"tests": {}`; the reason is hidden by pydantic-ai's own terminal reporter,
UNKNOWN). The cold serial run took 1,447 s, 3.1x plain. A capture fix, not an xdist one, but it blocks the cache
on this repository today.

**1.4.7 Repositories not run here.** prefect (its lockfile needs uv ≥ 0.13.4, this container has 0.11.32), litellm,
moto, mlflow, airflow, community.general, transformers, integrations-core, haystack: not run in this session (time).
What the CI facts predict for them under `--det -n` is in 5.1 (P0 runs all of them on Actions).

## 2. Design A: `--det` across xdist workers

Goal: `pytest --det -n N` (and `--det --det-cache -n N`) gives the same verdict, the same per-test fingerprints and
the same cache decisions every time it runs on the same inputs, and every reused result is as safe as in a serial
session. xdist stays the process manager (workers, execnet, reporting, `--dist` options the customer already has);
detpy replaces its *scheduling* and owns the *merge*.

### 2.1 What xdist does today, and what detpy must take over

| xdist today | under `--det` (design) |
|---|---|
| Every worker collects the whole suite; the controller checks that all collections are equal, then hands out test *indices*. | Unchanged (collection equality is xdist's own determinism check). The controller additionally gets the ordered id list (detpy's order: collection order or `--det-seed` shuffle) and computes the plan before the first index is sent. |
| `load`/`worksteal`: a first chunk per worker, then more indices to whichever worker reports progress first (dynamic). `loadscope`/`loadfile`/`loadgroup`: whole scopes/files/groups to whichever worker is free. | A **fixed plan**: each worker gets its whole, ordered list in one message at start (`DetScheduling`), no refill and no stealing. The plan is a pure function of (ordered ids, grouping constraint, costs, N). |
| `-n auto` = number of CPUs (or `logical`). | Resolved once and recorded; part of the plan input. The fingerprints barely depend on N (2.3; 0.35 % placement tests on esphome, 1.4.4), so once the keys are fixed (2.5) a cache written with `-n 4` can serve `-n 8` or a serial run. |
| `testrun_uid` = `uuid4().hex`, `worker_id` = `gw0..gwN-1`. | `testrun_uid` derived from (seed, order digest, plan digest) under `--det` (it is visible to tests through the `testrun_uid` fixture); `worker_id` stays `gwK` and is fixed per test by the plan. |
| Each worker writes its own outcome stream; the controller aggregates reports. | Each worker writes its own trace and cache shard; the controller merges them (2.4, 2.5). |

### 2.2 The fixed plan (`DetScheduling`)

1. **Atoms.** The unit of placement is an *atom*: a set of tests that must run in one worker, in detpy's order.
   The customer's `--dist` mode defines the minimum atom, because it is often a correctness constraint for them
   (pydantic-ai's `xdist_group`s share one local Temporal/DBOS server per group; mlflow and moto keep
   xdist-unsafe paths out of the parallel run; litellm uses `loadscope`):
   `load`/`worksteal` → one test; `loadscope` → module (class for class-scoped tests); `loadfile` → file;
   `loadgroup` → `xdist_group` name, else one test. detpy may *merge* atoms (Design B adds footprint edges), never
   split them.
2. **Costs.** Per test: the median of its last 3 recorded durations (the cache store's entry duration, `dur` in
   `ProofCachePlugin`; without a cache, the durations kept in `.detpy/durations.json` by the previous `--det` run;
   without either, 1 unit per test and the file's line count as a tie-break). An atom's cost is the sum of its
   tests' costs plus, for each wider-scoped fixture it is the first user of in its worker, the fixture's recorded
   setup time (the `f|scope|baseid|name` contexts already exist in the capture).
3. **Hits first.** With `--det-cache`, the controller decides reuse *before* planning (2.5) and only misses are
   placed; reused tests are reported by the controller and cost 0 worker time.
4. **Assignment.** Longest-processing-time-first over atoms, ties broken by the atom's id digest, never by
   timing; then, inside each worker, the atoms are put back in detpy's global order. Result: worker K runs a
   subsequence of the serial order. That keeps every within-worker predecessor relation a serial predecessor
   relation (2.3).
5. **Stickiness.** Costs move a little from run to run, and a plan that reshuffles everything on every run makes
   per-worker inputs (a test reading `PYTEST_XDIST_WORKER` gets another value) and order effects churn. The
   assignment keeps an atom on its previous worker unless that leaves the makespan more than 10 % (configurable)
   above the LPT optimum. The previous plan is an input like the durations.
6. **Recorded.** The plan (worker → ordered ids), its inputs' digest and N go into the trace header (`meta.plan`)
   and the replay bundle. `--det-plan=FILE` replays an earlier plan exactly (the parallel analogue of
   `--det-order`): a failure seen in worker 2 is reproduced by rerunning worker 2's list, serially, in one process.

Balance is not the risk at file or module granularity: on the market-test samples a file-level LPT over 4 workers
is within 1 % of ideal on 8 of the 10 repositories with data (2.35x on community.general, where one file holds 43 %
of the sample's test time, and 3.54x on litellm, 28 %), see 1.2.

### 2.3 Per-worker controls

| control | serial `--det` | per worker |
|---|---|---|
| hash seed, ASLR off, deterministic bytecode | re-exec of the pytest process | **already inherited** (MEASURED: workers run with `PYTHONHASHSEED=0`, `ADDR_NO_RANDOMIZE` personality, `PYTHONPYCACHEPREFIX`, `PYTHONDONTWRITEBYTECODE=1` from the re-executed controller; `DETPY_REEXEC=1` stops a second exec). Must stay that way: a worker re-exec would break the execnet stdin channel. |
| order | detpy's order of the collected items | the plan's sublist (detpy must then *not* re-sort in the worker: xdist runs indices in the order the controller sends them). |
| clock | reset to the epoch at every test start; monotonic relative to the test start | same, per process; no cross-worker state. |
| seeds | `derive_seed(seed, nodeid)` per test | same (depends on the test id only). |
| network policy, cassette | per test counters; one cassette file | per test; the cassette is read-only in replay; in record mode each worker writes `cassette.gwK.json`, merged by the controller (connections are keyed by test, so the merge is a union). |
| trace | one file | `trace.gwK.jsonl` per worker (today all workers and the controller write the *same* path and the controller's empty trace is what remains, MEASURED 1.4.1), merged by the controller (2.4). |
| `tmp_path`, basetemp | `<basetemp>/test_x0` | xdist gives each worker `<basetemp>/popen-gwK`; `_sites` already normalises both to `<basetemp>`, but the per-name counter of `tmp_path` (`test_x0`, `test_x1` for parametrized tests that share a truncated name) depends on how many same-named tests ran *earlier in the same process*: a path that enters a fingerprint must be normalised without the counter (5 of esphome's 50 placement tests, MEASURED 1.4.4). |

**Why fingerprints should not depend on the worker.** Everything Level 0 controls is reset per test and seeded by
the test id, so a test's own events are a function of its code, its inputs and *process state left by earlier
tests in the same process*. In a plan, a test's in-process predecessors are a subsequence of its serial
predecessors. A fingerprint therefore differs between serial and parallel only when a removed predecessor
changed process state the test observes: exactly the order dependencies of LIMITS O4 (polluters/victims,
state-setters/brittle tests). That is what the proof check of Design B measures and acts on; Design A reports it
(new divergence class `placement`, 2.4) and does not try to prevent it.

### 2.4 Traces and fingerprints

* Each worker writes `trace.gwK.jsonl` (header: worker id, its ordered list, the plan digest; one line per test
  as today). The controller opens no trace of its own until the end.
* **Merge** (controller, `pytest_sessionfinish`): one trace whose header carries `meta.plan` and `order` = the
  serial order restricted to the tests that ran; test lines sorted by that order, each with `worker` and
  `worker_index`; footer with the order digest of the serial order and the plan digest. Byte-identical across two
  runs with the same plan (acceptance target of P2).
* `detpy verify A B` keeps comparing per test id. New: when exactly one side has a plan, a differing fingerprint
  whose test has *fewer in-process predecessors* in the plan side gets the class `placement` (with the predecessors
  it lost), so "differs because it ran elsewhere" is separated from time/random/fs/thread divergences.
* Crash safety: a worker that dies leaves its partial trace; the merge marks its unfinished tests `missing`
  (xdist already reports the crash and, with `--max-worker-restart`, starts a replacement: under `--det` the
  replacement gets the rest of the dead worker's list, never a rebalance).

### 2.5 Cache with proof across workers

Today (MEASURED, 1.4.5): each worker builds its own `ProofCachePlugin`, decides reuse for the whole collection on
its own, samples verification with an RNG seeded by its own run id (time + pid, so the 4 workers pick different
tests), records the tests it ran, and merges into the store under the directory lock (`Store::save_merged`,
`proof.rs`). The controller also starts a capture that sees no test. Three problems:

1. **Cross-worker writes are invisible** (reproduced as a wrong reuse, 1.4.5). The rule "never reuse a test that read a file another test of the same
   session wrote" (`Capture.read`: `rw:` flag from `writers`) only sees writers in the *same process*. With
   workers, test B (worker 1) can read a file test A (worker 0) wrote, and B's entry records a digest that depends
   on A having run before it, in another process, by timing. Worse, B can hash a file *while* A rewrites it. A
   later session reuses B although its input was produced by the session itself. This is a wrong-reuse path that
   does not exist serially.
2. **Decisions are made N times** (MEASURED: identical per-worker receipts covering all 14,446 tests; N x the
   check cost). With `--det-cache-verify` the sampled set would differ per worker (the RNG is seeded with time + pid,
   from the code; not run), so neither the verdict nor the receipts would be reproducible.
3. **Receipts and summary are lost** (MEASURED): the controller's empty receipts file is what remains, and its
   summary reports 0 reused, 0 ran, 0 recorded.

Design:

* **Decide in the controller.** The controller has the ordered ids after collection (xdist sends them). It runs
  `changed_code_files` + facts of changed files + `check(nid)` for every id (no test module is imported: checking
  needs ids, file digests and facts only). Verification sampling uses `derive_seed(seed, "verify:" + run id)`
  where the run id is derived from the order digest and the store's revision, so two runs on the same inputs
  verify the same tests. Hits are reported by the controller (synthesised reports, as `_reuse` does in-process
  today, without a teardown call: the controller has no `SetupState`); misses and verified hits go to the plan.
* **Workers only record.** Each worker's capture records the tests it ran into a shard `store.gwK.json` plus its
  `writers` map (path → tests that wrote it) and its read set (path → tests that read it, with digests).
* **Merge with the cross-worker rule.** The controller unions the writer maps of all workers and drops (records as
  not cacheable, reason `rw-cross:<path>`) every entry that read a path written by any *other* test of the
  session, in any worker, then merges the shards into the store once (single writer; the directory lock stays for
  concurrent sessions). Same rule as serial, extended across processes; because it does not depend on which worker
  ran first, the decision is deterministic. Native and subprocess writes stay outside it exactly as serially (a
  test that spawns a process is never cached, S1/S2).
* **Keys: make them equal to serial keys.** Today they are not (MEASURED 1.4.5): the workers' configuration digest
  contains xdist's `loadgroup` option, and whole-environment readers see a fresh `PYTEST_XDIST_TESTRUNUID` in every
  run. Fix: every xdist option (`loadgroup`, `maxprocesses`, `maxschedchunk`, `max_worker_restart`, `testrunuid`,
  `rsyncdir`, `looponfail`, besides the already volatile `numprocesses`, `dist`, `tx`) becomes volatile; under
  `--det` `testrun_uid` is derived (2.1), so `PYTEST_XDIST_TESTRUNUID` is stable; `PYTEST_XDIST_WORKER` and
  `_COUNT` stay inputs (a test that reads them may depend on them: prefect names its database after the worker),
  kept stable by the sticky plan (2.2.5). Then an entry recorded under `-n 4` is offered to a serial run and vice
  versa (`-n` is not an input). That is only sound if the parallel fingerprint equals the serial one, which is the
  proof of Design B; until P5 ships, an entry carries `placement: serial | parallel` and a serial session does not
  reuse a parallel entry whose test has a recorded `placement` divergence.
* **Receipts.** One `receipts.jsonl` record per test, written by the controller, with the worker id for tests that
  ran. Verification (`--det-cache-verify`): the verified hits run in workers; the controller compares.
* **Audit reruns** (`claude/audit-reruns`: a mismatch is wrong when a second fresh run also differs from the cached
  result). Under a plan a mismatch can have a third cause: placement. The controller reruns a mismatching test
  twice at the end of the session, **alone in a fresh worker** (`--det-plan` with a one-test list): if the
  isolated runs equal the cached result and the in-plan run did not, the class is `placement` (recorded on the
  entry, fed to Design B's edges), not wrong and not flaky.
* **Shared cache** (`claude/shared-cache`). Pull and push move to the controller: pull right before the decision
  (one round of lookups, not N), push after the merge. Workers never hold the token (today every worker process
  would run the client in a test process). Lookup keys are unchanged.

### 2.6 Where the changes go

Module names after the Python → Rust move (`claude/rust-hotpaths-2`; the Rust names for code that does not exist
yet are proposals, to be settled with that session's layout):

| change | Python today | after the move |
|---|---|---|
| xdist hooks: `pytest_xdist_make_scheduler` (returns `DetScheduling`), `pytest_configure_node` (plan, run id, seed into `workerinput`), `testrun_uid` override, `pytest_testnodedown` (collect shard paths from `workeroutput`) | new `python/detpy/xdist.py` (thin, stays Python: it is pytest/xdist glue) | same file; it calls the Rust planner |
| plan: atoms, costs, LPT, stickiness, plan digest | — | new `detpy-core/src/schedule.rs` (pure; property tests: same input → same plan; a permutation of the collection never changes the plan of the sorted input) |
| worker detection, per-worker trace path, do not re-sort in a worker, controller does not open a trace until merge | `plugin.py` (`_configure_det`, `_DetSession.pytest_collection_modifyitems`, `pytest_collection_finish`) | `detpy-py/src/level0.rs` (session state) + `plugin.py` hooks |
| trace merge, `meta.plan`, `placement` divergence class | `plugin.py` (`pytest_sessionfinish`) | `detpy-core/src/trace.rs` (`merge_traces`), `verify.rs` (class `placement`) |
| controller-side decision, deterministic verify sampling, synthesised reports for hits | `proofcache.py` (`ProofCachePlugin._decide`, `_reuse`) | `detpy-core/src/proof.rs` (`Checker`, already Rust) + `detpy-py/src/proofcache.rs`; report synthesis stays in the Python plugin |
| worker shards, cross-worker `rw` rule, single merge | `proofcache.py` (`Capture.read/wrote`, `finish`, `_record_all`) | `proof.rs` (`Store::merge_shards(shards, writers_union)`), `record.rs` (writers/readers in the per-test plan) |
| audit reruns in isolation | `proofcache.py` (`compare_verified`) + `claude/audit-reruns` | `proof.rs` (classification) + `xdist.py` (extra one-test plans at session end) |
| shared-cache pull/push in the controller | `remote_cache.py` (`claude/shared-cache`) | unchanged module, called from the controller only |
| `testrun_uid`, cassette per worker | `network.py` (`save_recordings`) | `cassette.rs` (merge) |
| `LIMITS.md` O1 | — | rewritten: what is supported, what is reported as `placement` |

## 3. Design B: parallel with proof, beyond xdist

Design A makes xdist deterministic. Design B uses what only detpy knows (each test's recorded footprint) to decide
*what may run concurrently* and to *prove*, test by test, that splitting the run changed nothing. It runs on N
cores of one machine or on N machines with the shared cache, without xdist.

### 3.1 Footprint (what is already recorded, what must be added)

The cold `--det --det-cache` run records, per test (MEASURED: these are the fields of a store entry and of the
capture, `proofcache.py` / `proof.rs`):

| footprint part | recorded today | used by the scheduler as |
|---|---|---|
| code units executed, skeletons, conftest hook surface | yes | nothing (code is read-only) |
| files read (content digest), listings, missing paths | yes, per test context | readers of a path |
| files written / removed / renamed / created (audit events `open` for write, `os.remove`, `os.rename`, `os.mkdir`, `shutil.*`) | yes (`Capture.writers`), but only to refuse reuse; not stored per test | **writers of a path**: store per test (new) |
| environment variables read | yes | nothing (process-local) |
| clock, randomness | controlled (virtual, seeded) | nothing (process-local under `--det`) |
| network: connects (host:port), listens on loopback, DNS | flags only (`net`, `net-local`); a test that connects is never cached | **ports bound and endpoints connected**: store per test (new); a fixed port bound by two tests is a conflict |
| sqlite connections (path) | yes (data read) | a database file is a written path when the test writes it (sqlite trace callback: `INSERT/UPDATE/DELETE/CREATE`) |
| subprocesses, native code | flag `subprocess` (followed children: their reads) | **opaque**: unknown footprint |
| wider-scoped fixtures used (`f\|scope\|baseid\|name` contexts) | yes | **affinity**: tests sharing an expensive module/session fixture prefer one lane (fixture setup is paid once per lane) |
| test duration | yes (`dur`) | cost |
| in-process state left for later tests (module globals, caches, monkeypatches not undone, imported modules) | **no** (Level 0 does not see Python object mutation) | inferred from history: placement divergences (3.3) |

### 3.2 Constraints and the schedule

Two different hazards, two kinds of edges:

* **Concurrency hazard (different processes at the same time):** two tests in different lanes conflict when they
  touch the same mutable resource outside their own temporary directories: write/write or write/read on a path
  (or a listing of a directory the other writes into), the same fixed port, the same external endpoint with
  writes (a database server without per-worker naming). These get an **exclusion edge**: the two tests never
  overlap in time. Implementation: they go to the same lane (cheapest correct choice), or, when merging would
  unbalance the plan, a barrier orders them (all lanes past test A before B starts). Suites that already name
  resources per worker (prefect: `prefect_{worker_id}.db`, per-worker Postgres databases; esphome: per-worker
  library cache, ports bound to 0) show it in the footprint: the path or port differs per lane, so no edge.
* **Order hazard (same process, earlier tests):** a test whose behaviour depends on process state left by earlier
  tests. Sources of **together edges** (same lane, serial relative order kept):
  1. the customer's own constraints (`xdist_group`, `loadscope`/`loadfile` mode, mlflow-style serial lists, moto's
     `requires_clean_slate`, airflow's `db_test` marker: declared per repository in the config, 1.1);
  2. data dependencies inside the session: B read a path A wrote (already detected as `rw:` today);
  3. known polluter → victim and state-setter → brittle pairs, from history: a test whose fingerprint differed
     between serial and parallel (`placement`, 3.3) gets an edge to the predecessors it lost, narrowed by bisection
     over those predecessors in the background (iDFlakies-style, but driven by fingerprints, not by outcomes, so a
     changed event sequence is found before it flips an outcome);
  4. opaque tests (subprocess, native network clients): one **serial lane** that runs them in serial order, plus
     an exclusion edge to every test that touches a path or port their parent process touched.
* **Schedule:** union-find over together edges → atoms; exclusion edges between atoms → merge (default) or barrier;
  costs = recorded durations; LPT with deterministic tie-breaks and stickiness, as in 2.2; lanes keep the serial
  order. With a cache, hits are removed first. N lanes = cores (one machine) or machines (each machine runs its
  lanes with `--det-plan`, results join through the shared cache and a merged trace).
* **Execution:** one process per lane, `pytest --det --det-plan=lane.K` (a lane is the existing `--det-order`
  plus the plan metadata). Each lane collects **only the files of its tests** (xdist collects the whole suite in
  every worker: N x collection). No execnet; the parent reads each lane's trace and receipts. The same plan runs on
  one machine or many. Collection is not small: esphome collects 14,548 tests in 11.5 s, pydantic-ai 48,518 tests
  in 178 s in one process (MEASURED, `--collect-only`, local).
* **xdist compatibility inside lanes.** Suites name resources after the xdist worker (prefect:
  `prefect_{worker_id}.db` and one Postgres database per worker; esphome: per-worker library cache; litellm, mlflow,
  transformers read `PYTEST_XDIST_WORKER`). Without xdist, `worker_id` is `master` in every lane and those
  resources collide. Each lane therefore sets `PYTEST_XDIST_WORKER=gwK`, `PYTEST_XDIST_WORKER_COUNT=N`,
  `PYTEST_XDIST_TESTRUNUID` (derived) and provides the `worker_id` / `testrun_uid` fixtures with the same values.

### 3.3 The proof: parallel fingerprint = serial fingerprint

For every test that ran in a lane, the merged trace's fingerprint is compared with the test's **serial
fingerprint**: the fingerprint recorded the last time the test ran in a serial `--det` session with the same cache
key (the store entry keeps it, `fingerprint` field). Three cases:

| case | meaning | what happens |
|---|---|---|
| equal | the split changed nothing observable by Level 0 for this test | proven; the result counts and may be stored as reusable |
| no serial fingerprint under this key (new or changed test) | nothing to compare | the result counts; the entry is stored `placement: parallel-unproven`; the next serial audit run (nightly, or a background serial lane on idle runners) provides the serial fingerprint. An unproven entry is reused only by parallel runs with the same plan neighbours, never offered as proof to a serial run |
| different | the test observed something that depends on where it ran | (1) classify with `verify` (first diverging event: time/random/fs/net/thread/outcome-only); a divergence that also occurs between two serial runs of the test (OS entropy, thread interleaving) is noise and is not counted; the serial noise set is kept per test (67 of 14,446 on esphome, 59 of them `os.urandom`, 1.4.4); (2) **the verdict for the test is the serial-equivalent result**: the test is rerun at the end, in one process, after exactly its serial predecessors from the same file/module (the cheap approximation; the full serial prefix is the exact one, used when the cheap one still differs). If the outcome flips, the run reports it as `placement-sensitive` with both outcomes and the lost predecessors; (3) the test and its lost predecessors get a together edge for the next plans; (4) the entry is not stored from the parallel run. |

What the proof covers: everything Level 0 records (clock reads, randomness, fs order, network, entropy, outcome),
so two runs that agree on the fingerprint executed the same event sequence at the Python API level. What it
does not cover: what Level 0 does not see (C extensions, subprocess internals, in-memory state that changes no
recorded event and no outcome). A test that is placement-sensitive only through such state and whose outcome does
not change is equal by definition of the fingerprint: the run is still correct for that test.

What the two measured repositories say about the proof (MEASURED 1.4.4):

* **Entropy is the first obstacle, not placement.** Two serial `--det` runs disagree on 67 of 14,446 esphome tests
  but on **5,398 of 8,029 pydantic-ai tests (67 %)**, nearly all at an `os.urandom` event (message and run ids drawn
  from OS entropy, observed and not controlled, LIMITS R5). A fingerprint that changes every run proves nothing.
  Two ways: the customer runs with `--det-urandom` (deterministic entropy; never for crypto tests), or the proof
  compares entropy events by (operation, call site, length) and not by value. The second keeps the event sequence
  in the proof and is the default proposed here; values stay in the fingerprint for `verify`.
* **Placement is mostly library state.** Among the tests whose serial runs agree, 50 of 14,379 (esphome) and 455 of
  2,631 (pydantic-ai, 17 %) differ when placed elsewhere, with 0 outcome changes in both. On pydantic-ai the first
  differing event is a clock read inside logfire or OpenTelemetry in 433 of the 455 (lazy initialisation done by
  whichever test came first in the process). Because the virtual clock has one tick counter per process, one extra
  library read shifts every later clock value of the test, so the whole fingerprint differs.
* **Two-tier comparison.** Tier 1: the full fingerprint (entropy by shape). Tier 2: the projection on events whose
  call site is in the project or its tests, clock values replaced by their order, plus the outcome. Tier-2 equality
  explains 25 of esphome's 50 and 277 of pydantic-ai's 455 placement differences (ESTIMATED from the stored events:
  `tracks/parallel-proof/bin/projection.py --timeless`). A tier-1 match is a proof; a tier-2 match with the same
  outcome is accepted for the verdict and stored as `parallel-proven (library state)`; a tier-2 mismatch goes to the
  serial-equivalent rerun.
* **Cost of the proof** (ESTIMATED): the comparison is a string compare per test. Reruns cover the tier-2
  mismatches: 25 of 14,446 per run on esphome, 178 of 8,029 on pydantic-ai (at its measured 0.057 s per test
  serially, about 10 s plus same-module predecessors, against a 140 s parallel run); the together edges learnt from
  them shrink that set in later plans. A per-call-site clock (values independent of other sites' reads) would
  remove most library-state differences at the source, but changes every fingerprint and the semantics of a single
  monotonic clock: an engine decision outside this design.

Customer-facing guarantees (the measurements in 5 check them):

* **0 new failures caused by the split**: a failure in a lane whose serial-equivalent rerun passes is reported as
  placement-sensitive, not as a failure of the change.
* **0 hidden failures**: a test whose lane outcome differs from its serial record (the store keeps the outcome
  with the fingerprint) is rerun serially; the serial verdict is the verdict.
* **0 wrong reuses**: entries are stored only from proven (equal) or serial runs; the cross-lane write rule of 2.5
  applies to lanes.

### 3.4 Why no competitor can do this

Splitters (pytest-xdist `load*`, pytest-split, CircleCI `--split-by=timings`, Buildkite/Knapsack test-splitting,
esphome's and pydantic-ai's own duration buckets) balance files by duration and leave correctness to the
customer: per-worker resource names, `xdist_group` markers (79 in pydantic-ai, 20 in litellm), serial lists
(mlflow `_XDIST_SERIAL_PATHS`, moto `requires_clean_slate` 54 uses), separate serial jobs (airflow DB tests).
None of them knows whether two tests touch the same file or port, none checks that a test behaved the same as it
would serially. detpy records both as a by-product of the cache.

## 4. Recording off the critical path

**Question:** can the customer get the verdict at plain speed while recording completes afterwards?
**Answer:** partly. The end-of-session recording can leave the critical path entirely. The in-test capture
(line events, audit hook, environment capture, the interpreter running under `sys.monitoring`) cannot, except by
recording in a second run. `--det` itself (the controls) is the verdict run and stays.

### 4.1 Where the cold-run time goes (round-1 profiles, `tracks/rust-hotpaths/` on `claude/rust-hotpaths`)

Medians of runs `p1` (base engine 24b6d15, round 1) and `p3` (round-2 engine), GitHub Actions 4 vCPU
(MEASURED); `record` = `record_seconds` of the cold run's cache summary (`ProofCachePlugin.finish`: facts,
followed children, per-test assembly, store save).

| project | plain | `--det` | cold `--det-cache` | record (end of session) | in-test capture = cold − record − `--det` |
|---|---|---|---|---|---|
| click, p1 | 8.9 s | 9.5 s | 16.1 s | 4.4 s (3.0 s of it waiting for child logs, fixed in round 1) | 2.2 s |
| pygments, p1 | 18.2 s | 20.5 s | 26.6 s | 2.9 s | 3.2 s |
| home-assistant 0/16, p1 | 27.1 s | 35.7 s | 42.8 s | 3.8 s | 3.3 s |
| home-assistant 5/16, p1 | 49.4 s | 59.1 s | 69.3 s | 3.9 s | 6.3 s |
| home-assistant 10/16, p1 | 35.1 s | 44.4 s | 53.0 s | 4.3 s | 4.3 s |
| click, p3 (round 2) | 7.4 s | 7.8 s | 9.7 s | 0.8 s | 1.1 s |
| pygments, p3 | 14.5 s | 16.1 s | 18.9 s | 1.4 s | 1.4 s |
| home-assistant 0/16, p3 | 38.5 s | 48.2 s | 49.5 s | 2.9 s | −1.6 s (runner noise) |
| home-assistant 5/16, p3 | 54.0 s | 58.1 s | 64.8 s | 1.6 s | 5.1 s |
| home-assistant 10/16, p3 | 25.5 s | 31.8 s | 36.0 s | 1.7 s | 2.5 s |
| esphome, this session (local 4 vCPU, round-2 engine, 14,446 tests, single runs) | 170 s (160/180) | 176 s | 232 s | 27.6 s | 28.4 s |

### 4.2 Three ways, and what each saves (ESTIMATED from 4.1)

1. **Deferred recording (fork after the verdict).** At `pytest_sessionfinish` the outcomes are final. detpy
   forks: the parent prints the summary and exits with the verdict; the child (stdout/stderr closed, own session)
   runs the recording (facts, assembly, store merge, receipts, shared-cache push). Sound: it records exactly what
   the verdict run observed, nothing is re-executed. Needs: (a) the child must finish before the cache directory
   is saved or the job ends: the CI wrapper (`fenvix-run`, the GitHub Action's post step) waits on a lock the
   child holds; (b) a session that starts while a recorder still holds the store waits for it (the existing
   directory lock); (c) under xdist (Design A) the controller defers the merge the same way.
   Saves the `record` column: cold/plain on round 1 goes from 1.81x → 1.31x (click), 1.46x → 1.30x (pygments),
   1.58x → 1.44x, 1.40x → 1.32x, 1.51x → 1.39x (home-assistant 0/5/10); on the round-2 engine 1.31x → 1.20x,
   1.30x → 1.21x, 1.29x → 1.21x, 1.20x → 1.17x, 1.41x → 1.35x. On esphome (this session) the recording is half
   of the capture overhead: cold/plain 1.37x → 1.20x (MEASURED parts, ESTIMATED sum); the warm run's 7.2-8.4 s of
   recording (295 new or failed tests, plus the store save) would leave its critical path the same way.
   Caveat: in CI the *job* finishes only when the post step returns. The customer gets the verdict earlier (the
   test step's status, annotations, a failing step stops the job earlier), but the job's wall time only shrinks
   when other steps follow the test step (build, lint, upload) and overlap the recorder, or when the recorder runs
   on cores the tests left idle (next point).
2. **Pipelined recording (during the session, on idle cores).** A serial `--det` run uses one core of a 4 vCPU
   runner. The record work is per test except the store merge: the facts of a file can be computed as soon as the
   file first executes, the per-test assembly as soon as the test ends (its data, units and flags are final then;
   the cross-test `rw` rule is applied at the end, and is cheap). Moved to a Rust worker thread (no GIL: needs the
   facts parser in Rust, ruff/rustpython parser, today CPython's `ast` holds the GIL) or to a helper process fed per
   test, the end-of-session work shrinks to the merge (the `save` phase, 0.0-0.45 s in p2/p3). Same saving as 1 on
   the verdict and on the job wall, with no post step, but only while cores are idle: once the run itself is
   parallel (Design A/B) the idle cores are gone and 1 is the remaining option.
3. **Shadow capture (record in a second run).** The verdict run is `--det` without capture; the tests that ran
   are then re-executed under `--det --det-cache` off the critical path (spare cores, the post step, or another
   machine), and an entry is stored only when the shadow run's fingerprint equals the verdict run's (the proof of
   3.3 applied to time instead of placement; a mismatch stores nothing and is reported as flaky). Critical path =
   `--det` alone: 1.07x, 1.13x, 1.32x, 1.20x, 1.26x on round 1, 1.05x, 1.11x, 1.25x, 1.08x, 1.25x on round 2
   (click, pygments, home-assistant 0/5/10). Cost: the executed tests run twice (CPU about cold/plain + `--det`/plain
   instead of cold/plain). With a warm cache most tests are reused (warm runs are 0.36-0.53x plain in p1), so the
   second execution only covers the misses.

"Plain speed" in the strict sense (1.0x) needs the verdict from plain pytest, without `--det`, and the `--det`
recording as the shadow run. That gives up the deterministic verdict on the critical path (a difference between the
plain verdict and the `--det` shadow is reported afterwards). Not recommended as the default; possible as a mode
for customers who want fenvix only for the cache.

**Recommendation:** 2 for serial runs (no CI change, no extra CPU), 1 for parallel runs, 3 as an option for
customers whose in-test capture dominates (home-assistant 5/16: 5.1-6.3 s of capture during tests). The in-test
capture itself is the round-3 target of `claude/rust-hotpaths-2` (line capture strategy, clock as Rust builtins).

## 5. Build plan

Starts after `claude/rust-hotpaths-2` finishes the move (module names in 2.6). Each step lands with its tests and is
accepted on its measurement. Sizes in session-days (ESTIMATED, one session working alone, including the review
fixes a step usually needs). Every wall-time measurement is taken on GitHub Actions 4 vCPU runners (the market
test's runners) and repeated on a 4 vCPU Blacksmith runner when we have access (UNKNOWN today), medians of 3,
interleaved with the comparison runs on the same runner.

Reference walls used by every step, per repository (the "xdist set": esphome, pydantic-ai, prefect, litellm one
shard, moto's `-n 4` group, mlflow one parallel shard, all at the market-test HEADs): plain pytest serial, plain
`pytest -n 4` with the customer's own `--dist`, `--det` serial, cold and warm `--det --det-cache` serial.

| step | what | tests | the measurement that says it works | size |
|---|---|---|---|---|
| P0 | `harness/parallel_proof/`: the runner of this report (variants, per-worker trace shim, fingerprint comparison `cmp_traces.py`, outcome comparison) as an Actions workflow over the xdist set; results committed under `tracks/parallel-proof/` | harness unit tests on a 20-test synthetic project (one polluter/victim pair, one file writer/reader pair, one fixed-port pair) | reproduces 1.4 within the runner noise; prints for each repository the serial-noise rate (tests whose fingerprint differs between two serial `--det` runs) | 1 |
| P1 | Per-worker traces, controller merge, worker detection; the controller stops opening its own empty trace; cassette per worker; the "xdist is not supported" `UserWarning` removed (it aborts pydantic-ai and prefect under `filterwarnings = error`, 1.4.3) | pytester `-n 2`: one trace per worker, merged trace has every test once with `worker`; byte-identical merge from the same worker traces; a killed worker leaves `missing` lines | xdist set: merged trace covers 100 % of the tests that ran (today: the controller's header-only file, 0 tests, 1.4.1) | 1 |
| P2 | `DetScheduling` (fixed plan, atoms from `--dist`, LPT on recorded durations, stickiness, `--det-plan` replay, `testrun_uid`) in `schedule.rs` + `xdist.py` | Rust property tests (same input → same plan; collection permutation invariance; atoms never split; makespan ≤ 4/3 OPT + max atom); pytester: `loadgroup` groups stay on one worker, two runs give the same per-worker lists, `--det-plan` replays a worker's list serially, worker crash → replacement runs the rest | xdist set, `--det -n 4` twice: identical per-worker lists; per-test fingerprints identical between the two runs except the serial-noise tests from P0; wall of `--det -n 4` ≤ (wall of plain `-n 4`) x (`--det`/plain serial ratio) x 1.05 (a fixed plan must not cost more than 5 % against xdist's dynamic balance) | 2 |
| P3 | Cache across workers: decision in the controller, worker shards, cross-worker `rw` rule, single merge, deterministic verify sampling, receipts from the controller, isolated audit reruns; keys equal to serial keys (xdist options volatile, derived `testrun_uid`, `_` and xdist's variables outside the whole-environment digest) | pytester: A writes a file in worker 0, B reads it in worker 1 → B not reused next session (fails on today's engine: write it first); serial and `-n 2` sessions take identical reuse decisions; two `-n 2` sessions write identical receipts; a placement mismatch is classified `placement`, not wrong | cache-proof walk (`harness/cache_proof/walk.py`) with `-n 4` on esphome, pydantic-ai, prefect, 50 commits each, every reuse checked by a fresh serial `--det` run: **0 wrong reuses**; reuse share within 1 point of the serial walk on the same commits (esphome today: 77 % under `-n 4` vs 98 % serial, 1.4.5); a store written by `-n 4` serves a serial run and vice versa; warm wall vs plain `-n 4` | 3 |
| P4 | Shared cache from the controller (pull before the decision, push after the merge; workers never hold the token) | `test_shared_cache.py` cases rerun with `-n 2`; a worker process has no token in memory or environment | two-machine run (`fenvix-shared-cache.yml`) with `-n 4`: machine 2 reuses 100 % of what machine 1's own warm run reuses, 0 wrong | 1 |
| P5 | Proof: `tmp_path` counter normalised out of recorded paths (`_sites`), serial fingerprint kept per entry, parallel vs serial comparison per test, `placement` class in `verify`, serial-equivalent rerun of differing tests, entries tagged `serial` / `parallel-proven` / `parallel-unproven` | synthetic polluter/victim split across workers → `placement`, verdict = serial outcome, edge recorded; noise tests (thread divergence also between serial runs) not counted; an unproven entry is not reused by a serial session | xdist set: count of `placement` tests per repository; **0 new failures caused by the split** (every lane failure whose serial rerun passes is reported as placement-sensitive, none as a failure); **0 hidden failures** (every test that fails serially fails or is flagged in the parallel run) | 3 |
| P6 | Design B lanes without xdist: per-test writers and ports in the footprint, atom/edge graph, exclusion by merge or barrier, lane processes with partial collection, merged trace and receipts | pytester: two tests writing one path never overlap; two tests binding one fixed port never overlap; per-worker-named resources (prefect pattern) give no edge; an opaque (subprocess) test runs in the serial lane; lane crash → its tests `missing`, rest of the run unaffected | xdist set, cold and warm: wall vs plain `-n 4` (targets: cold ≤ `--det` serial ratio x plain `-n 4`, i.e. the engine's serial overhead and no more; warm ≤ 0.6x plain `-n 4`); wall vs `--det` serial (target ≥ 2.5x faster on 4 cores); 0 wrong reuses (walk as in P3); 0 new failures caused by the split (as in P5) | 4 |
| P7 | Lanes on several machines (plan shared, results joined through the shared cache, merged trace) | two local "machines" (containers) with one service | 2 x 4 vCPU vs 1 x 4 vCPU on prefect and litellm: wall ≤ 0.6x; identical verdicts and fingerprints | 2 |
| P8 | Recording off the critical path: pipelined recording (serial), deferred recording after the verdict (parallel), shadow capture as an option | the deferred child records exactly the entries the inline recorder would (store equality on the `test_rust_hotpaths` reference project); the post step waits for the child; shadow entries stored only on fingerprint equality | `harness/rust_hotpaths/profile.py` on click, pygments, home-assistant 0/5/10: cold/plain at the verdict vs 4.2's estimates; 0 store differences against the inline recorder | 2-3 |

**Prerequisites outside this plan** (found here, owned by the engine work): the capture's audit hook must not call
blocking functions in an event-loop thread (2,769 pydantic-ai failures under `--det-cache`, 1.4.6) and pydantic-ai's
empty store must be explained; until then pydantic-ai cannot be one of P3's walk repositories (use moto's parallel
group instead). The esphome UDP hang (raw `select` with a virtual timeout) is a Level 0 limit to fix or document.

**Total: 19-20 session-days** (P0-P5, the deterministic xdist path with the cache and the proof: 11; P6-P7, our
own scheduler on one and several machines: 6; P8: 2-3). P8 is independent of P1-P7 and can run in parallel with
them.

Order of value: P1-P3 remove the "several times slower than the customer's `-n auto` job" problem (2.7x on esphome, MEASURED 1.3) for the four repositories
that run xdist (esphome, prefect, pydantic-ai, litellm) and mlflow/moto's parallel groups; P5 is the claim no
competitor can make; P6 is where footprints beat duration-only splitting (fewer serial jobs and markers for the
customer to maintain).

### 5.1 What P0 must check on the repositories not run here (ESTIMATED from the CI facts, 1.1)

| repository | predicted issue under `--det -n` / lanes | where it lands in the plan |
|---|---|---|
| prefect | `worksteal` (atom = one test); per-worker SQLite file / Postgres database named after `worker_id`; an autouse session fixture starts a Prefect API server subprocess that tests reach over loopback: tests that connect are never cached (network), and sleeps wait for real while a child process is alive (C2b) | P2 (atoms), P6 (lanes must set `PYTEST_XDIST_WORKER`), cache share measured in P3 |
| litellm | 41 tests skip an `importlib.reload(litellm)` when `PYTEST_XDIST_WORKER` is set: serial `--det` runs code the customer's CI never runs (and the reverse for lanes that set the variable); `--reruns 2` (pytest-rerunfailures) under `--det`; one file holds 28 % of the sample's time (split inside the file) | P0 (verdict comparison per shard), P2 (atom granularity) |
| mlflow | 20 xdist-unsafe path prefixes run with `--serial=only`; its own `--splits/--group` plugin; conftest-level `flaky` reruns | P2/P6: the serial list becomes a together-edge set (one serial lane) |
| moto | 54 `requires_clean_slate` tests in a separate serial call; server mode shares one MotoServer container across workers (an external endpoint with writes) | P6: marker → serial lane; endpoint → exclusion edge |
| airflow | DB tests deliberately outside xdist (one serial pytest per test type, each with its own DB container); pytest-timeouts with real timers | P6: DB tests are opaque-to-network (DB connections), serial lane per DB |
| community.general | ansible-test forks every test (`ansible_forked`): the test body runs in a child process, so Level 0's events and the cache's capture stay in the child (S2): `--det` fingerprints would cover the fork only | needs `--det` support for forked tests before parallel work matters; out of scope here |
| transformers | pytest-random-order (blocked under `--det`, O2) and `--reruns 5 --only-rerun`; model downloads from the Hub (network) | P0 verdict comparison; network tests never cached |
| integrations-core, haystack | already serial in CI; docker-compose environments on fixed host ports (integrations-core) | parallel lanes would need exclusion edges on those ports (P6) |
