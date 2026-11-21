# The `fenvix` command

`fenvix` is the one command of the product. It is installed as a console script with the Python package
(`pip install detpy-*.whl` puts `fenvix` and `detpy` on the PATH); the runner image's `release/fenvix` hands the same
commands to it (`python -m detpy.fenvix`) and keeps the image-only Go and JVM entries.

```
fenvix pytest [pytest args]                    run pytest deterministically (--det added when absent)
fenvix unittest|django|nose2|ward|zope-testrunner|doctest [args]
fenvix vitest|jest|mocha|node-test|ava|tap|uvu|jasmine|bun|deno|playwright [args]   (detjs, when installed)
fenvix repro TEST [options] [-- runner args]   flaky test -> reproducible defect
fenvix explore --budget MIN [options] [-- runner args]
fenvix replay BUNDLE [--runs N]
fenvix verify TRACE TRACE... [--json] [--show-stable] [--ignore-env NAME]
fenvix detect [DIR]
fenvix version | --version | -V
```

`fenvix python`, `fenvix python-runner RUNNER` and `fenvix node RUNNER` (the release-1 names) still work.
`--no-det` on a runner entry runs the runner without the controls.

## Deterministic runs (`fenvix pytest`, `fenvix <runner>`)

Under `--det` every source below is controlled (C) or observed (O), and recorded in the trace (header `inputs`, or
per-test events):

| source | how | recorded as |
|---|---|---|
| clock | C: virtual clock, every test starts at the epoch (`--det-epoch`, default HEAD commit time) | input `clock`; events `time.*` |
| randomness | C: `random`, unseeded `Random()`, numpy reseeded per test from `--det-seed` | input `seed`; events `random.*` |
| hash seed | C: interpreter re-executed with `PYTHONHASHSEED` fixed | input `hashseed` |
| test order | C: collection order, or a reproducible shuffle (`--det-seed`), or `--det-order FILE` | per test: the tests before it |
| network | C: closed; `--det-record` / cassette replay; `--det-allow-host` | input `network` (mode, allowed hosts, cassette digest); events `net.*` |
| file-system order | C: listings sorted | input `fs`; events `os.listdir` & co. |
| time zone | C: `TZ` pinned (`--det-tz`, default `UTC` whatever the environment sets, Python and Node alike; `keep` = the environment's, recorded and keyed) | input `tz` |
| locale | C: `LC_ALL` and `LANG` pinned, `LANGUAGE` removed (`--det-locale`, default `C.UTF-8`; `keep`) | input `locale` |
| environment | O: every `os.environ` read is an event (`env.get NAME=<digest>`); every variable is an input (`env:NAME`, value digest) | input `env:*`; events `env.*` |
| OS entropy | O (C with `--det-urandom`) | input `urandom`; events `os.urandom` & co. |
| threads, child processes, I/O readiness | O only: not controlled in this release | events `uncontrolled.thread|child|io` |

Values of environment variables never reach the trace: only digests.

A failing test under `--det` ends the run with the command that turns it into a defect:

```
1 test(s) failed under --det (seed 0, fixed order). Turn each into a reproducible defect (cause, seed, order, replay command):
    fenvix repro tests/test_o.py::test_victim
```

## `fenvix verify`

Compares two or more traces of the same suite. A test is **identical** only when:

1. every run had the same inputs (header `inputs`: runtime, runner, seed, hash seed, clock, time zone, locale,
   network, file-system order, entropy control, bytecode, ASLR, and the environment variables it read);
2. it ran after the same tests (serial runs; a parallel run is compared by placement);
3. it used no source this release does not control (threads, child processes, I/O readiness);
4. it observed the same events with the same outcome (same fingerprint).

Otherwise it is **divergent** and the first divergent event is named: the first differing input (`[tz]`, `[locale]`,
`[env]`, `[seed]`, `[hashseed]`, `[time]`, `[net]`, `[fs]`, `[entropy]`, `[runtime]`, `[config]`), the order
(`[order]`), the uncontrolled source (`[thread]`, `[child]`, `[io]`), or the first differing event of the test
(`[time]`, `[random]`, `[fs]`, `[net]`, `[env]`, ...). Two runs where no test ran verify nothing (exit 1).

**Environment (design A).** A test that read an environment variable whose value differs between the runs, and is
otherwise identical, is **input differs** (`INPUT-DIFFERS`, `verdict: INPUT DIFFERS: NAME`), not divergent and not
unstable: the variable is named, with the read's site. Variables no test read are listed as `not compared`. The Node
shell does not record which test read a variable: every test of its runs counts as reading it. CI-volatile variables
are never inputs: under `--det` the run and attempt ids, the job and runner names and the host name are pinned
(`GITHUB_RUN_ID=0`, `GITHUB_RUN_NUMBER=0`, `GITHUB_RUN_ATTEMPT=1`, `GITHUB_JOB=fenvix`, `RUNNER_NAME=fenvix-runner`,
`RUNNER_TRACKING_ID=fenvix`, `HOSTNAME=localhost`; `socket.gethostname()` / `os.hostname()` answer `localhost`; the
CPU count is 2 for `os.cpu_count()`, `os.process_cpu_count()`, `len(os.sched_getaffinity(0))`, `multiprocessing.cpu_count()`,
`os.cpus().length` and `os.availableParallelism()`, while `-n auto` and the engine's own workers use the machine), and
temp and workspace paths, per-step files, CI tokens and session variables (`RUNNER_TEMP`, `GITHUB_WORKSPACE`,
`GITHUB_ENV`, `GITHUB_OUTPUT`, `TMPDIR`, `PWD`, `ACTIONS_RUNTIME_TOKEN`, ...: `VOLATILE_KEPT` in
`python/detpy/_level0.py`, `node/src/volatile.js`) keep their values but are not compared. Add a project's own with
`FENVIX_VOLATILE_ENV=NAME,PREFIX*` (a per-run output path, say).

Exit codes: 0 every test identical; 3 the only differences are environment variables tests read (input differs);
1 a test diverged or is missing, no test ran, or the traces do not record their run inputs; 2 a trace is missing or
unreadable.

```
fenvix verify: 2 runs, 5 tests
verdict: DIVERGENT: 5 of 5 tests are not identical (the first divergent event of each is named below)
run inputs: DIFFER between run 0 and run 1:
    env:MY_FLAG: "590eebb3cc504ed6" vs "af9a03130efbd033"
NOT-COVERED tests/test_x.py::test_env  [env] outcomes=passed,failed
    runs 0 vs 1: event #0: env.get @ tests/test_x.py:3 read the environment differently: MY_FLAG=4ae75b2349db vs MY_FLAG=485216adbab9 (name=value digest) (run inputs that differ: env:MY_FLAG)
```

`--ignore-env NAME` (or `PREFIX*`) leaves out a variable you declare irrelevant; the report lists it. Traces without
`inputs` (older engines, shells that do not record them yet) are reported as `run inputs: NOT RECORDED` and are never
identical: same events give `verdict: NOT PROVEN` (exit 1), since the runs cannot be shown to have had the same inputs.

## Flaky test to reproducible defect

### `fenvix repro TEST`

1. search: the fixed order, then `--det-seed=1..--seeds`; each configuration runs the tests up to TEST;
2. minimise: delta debugging over the tests before TEST (the polluters); if TEST fails alone, the passing
   configuration is minimised to name the tests it needs (state setters);
3. bundle: `.detpy/repro/<slug>/` with `bundle.json`, `order.txt`, the failing and passing traces;
4. proof: the bundle is replayed `--confirm` times (default 10); it must fail every time with one fingerprint.

Output (exit 0 when reproduced):

```
fenvix repro: tests/test_o.py::test_victim
  status: REPRODUCED: failed 10/10 replays with one fingerprint a63bad0ce5fccfced3e227003bc9d3cc
  cause: test order: it fails when run after tests/test_o.py::test_polluter (state left behind by that test)
  seed: none (fixed order)
  order: tests/test_o.py::test_polluter -> tests/test_o.py::test_victim
  error: AssertionError: assert 'x' not in {'x': 1} (tests/test_o.py:5)
  replay: fenvix pytest --det --det-order=.detpy/repro/test_victim-a60269ec/order.txt
  check: fenvix replay .detpy/repro/test_victim-a60269ec  (replays 10x, exit 0 when every run fails with the bundle's fingerprint)
  rerun: pytest --det --det-order=.detpy/repro/test_victim-a60269ec/order.txt
  bundle: .detpy/repro/test_victim-a60269ec (10 runs, 6.5 s)
```

`replay` is the failing run itself: it fails (exit 1) when the defect reproduces and takes runner arguments
(`--det-trace=PATH`, `-x`, ...). `check` replays the bundle N times and exits 0 when every run fails with the bundle's
fingerprint.

Causes: `test order` (polluters, or state setters), `seed` (fails alone under one seed, passes under another), or the
first divergent event against a passing run. A failure that does not replay N/N with one fingerprint is reported
`NOT REPRODUCIBLE under fenvix`, with the uncontrolled source when the test used one, and its cause is `not
established`: the tests and seed it was found with are not named as its cause, since the configuration does not fail
every time.

Options: `--seeds N`, `--seed fixed|N` (skip the search), `--confirm N`, `--max-runs N`, `--timeout S`, `--out DIR`,
`--runner NAME`, `--python PATH`, `--json`; runner arguments after `--`.

### `fenvix explore --budget MINUTES`

Runs the whole suite under seeds 1, 2, ... until the budget or `--max-seeds` is spent, keeps the tests that fail
under one seed and pass under another, and runs `repro` on each (`--no-repro`: exploration only; `--targets FILE`:
bundles only for those ids). Summary in `<out>/explore.json`, bundles in `<out>/bundles/`.

Exit 0 when the suite ran; 2 when it cannot run (collection errors, an unknown runner argument, an interpreter that
does not exist): no test ran under any seed, so nothing was explored, and the runner's error lines are printed.
`fenvix repro` on such a suite reports `not collected: the suite did not collect cleanly` with the same lines.

### `fenvix replay BUNDLE`

Replays the bundle `--runs` times (default 10). Exit 0 when it failed every time with one fingerprint, 1 when it did
not (fixed, or something the bundle does not hold changed). Run it from the project root, the directory `fenvix repro`
ran in (the bundle records it as `project`): from elsewhere, or when the test is no longer collected, it exits 2 and
says the test did not run, never that the defect is fixed. The bundle's `runner` field picks the adapter.

## Runner adapters (how Vitest, Jest and Playwright plug in)

The commands, their options, their output and the bundle layout do not depend on the runner. A runner adapter
(`python/detpy/fenvix.py`, `ADAPTERS`) does the runner-specific part:

| member | contract |
|---|---|
| `name` | the runner (`--runner NAME`; stored in every bundle as `runner`) |
| `available()` | `None` when it can run here, else the sentence shown to the user |
| `owns(test_id)` | whether a test id has this runner's shape (`path::name` for pytest, `*.test.ts` for Vitest/Jest, `*.spec.ts` for Playwright); used when `--runner` is absent, with `detect` to break ties |
| `detect(dir)` | whether the project uses this runner (config files) |
| `repro(ns)` | returns the bundle dict: `test, status, config, kind, order, polluters, setters, replay{runs, fails, fingerprints, identical_fingerprint}, exception, divergence, command, runner` |
| `explore(ns)` | returns the summary dict (seeds, flaky tests, bundles) |
| `replay(bundle, runs, python)` | returns `{test, runs, fails, identical_fingerprint, matches_bundle}` |

The search, minimisation, replay verdict and first divergent event are runner-neutral Rust
(`crates/detpy-core/src/repro.rs`, `Driver` trait): an adapter implements the `Driver` for its runner, i.e.

* `order_of(config)`: the test order a whole-suite run with that configuration uses (`fixed` or a seed);
* `run(config, order, tag)`: run exactly `order` under `config` with `--det`, writing a trace and outcomes;
* `verdict(run, test)`: failed / passed / other;
* `fingerprint(run, test)`.

For detjs this means: `detjs <runner> --det --det-seed=N --det-order=FILE --det-trace=PATH --det-outcomes=PATH`, which
the Vitest and Jest shells already accept for the seed and trace (the `--det-order` and outcomes files are the part to
add). The JavaScript adapters are registered today and answer:

```
fenvix: repro / explore / replay are not available for vitest in this version: the interface is fixed (docs/CLI.md), the vitest adapter is not built yet. `fenvix vitest --det` runs the suite deterministically and `fenvix verify` compares its runs.
```

## `fenvix detect [DIR]`

One line per project found in DIR and its first-level subdirectories: `path<TAB>language<TAB>runner`.
