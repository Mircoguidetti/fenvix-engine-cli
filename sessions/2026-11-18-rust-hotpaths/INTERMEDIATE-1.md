# rust-hotpaths, intermediate 1: where the cold-run overhead goes (base engine)

Engine profiled: `claude/cache-proof-step1` at 24b6d15 (the base of this branch). Labels: MEASURED (numbers from runs
listed here), ESTIMATED (derived), not marked = description.

## Method

* `harness/rust_hotpaths/profile.py` (workflow `.github/workflows/rust-hotpaths.yml`, run `p1`, results in
  `tracks/rust-hotpaths/results/p1/`): for one spec/shard at its HEAD commit, set up exactly as the cache-proof walk
  (same specs, same 12 % home-assistant sample, same pytest arguments), then interleaved, unprofiled:
  plain pytest (`P0`), `--det` (`B`), cold `--det --det-cache=<empty>` (`C`), warm (`W`, same cache again).
  home-assistant: 3 rounds, shards 0 and 10 of 16 (shard 5 had not finished when this was written); click and
  pygments: 5 rounds. Walls below are medians.
* Then one py-spy profile per variant (`--native`, 250 Hz) of the single process detpy execs (the re-exec is
  captured and launched directly), every sample classified into a bucket (`profile.classify`: the innermost detpy
  phase frame, else the innermost detpy hook frame, else "test+pytest").
* Locally (4 CPUs, same specs at the same HEADs): phase timers added to the cache summary (`phase_seconds`), and
  ablations (LINE events off) for click and pygments. py-spy does not sample a sleeping process, so waits are
  measured with timers.

## Walls (MEASURED, GitHub Actions, p1)

| project | tests | plain pytest | --det | cold --det-cache | warm --det-cache | --det / plain | cold / plain | cold / --det | warm / plain |
|---|---|---|---|---|---|---|---|---|---|
| click | 2653 | 8.9s | 9.5s | 16.1s | 9.8s | 1.06x | 1.81x | 1.70x | 1.10x |
| home-assistant 0/16 | 444 | 27.1s | 35.7s | 42.8s | 14.3s | 1.32x | 1.58x | 1.20x | 0.53x |
| home-assistant 10/16 | 624 | 35.1s | 44.4s | 53.0s | 18.3s | 1.26x | 1.51x | 1.19x | 0.52x |
| pygments | 5346 | 18.2s | 20.5s | 26.6s | 6.5s | 1.12x | 1.46x | 1.30x | 0.36x |

On home-assistant the cold run's 1.51-1.58x splits into **`--det` itself 1.26-1.32x** and **capture 1.19-1.20x**
(MEASURED): the 1.1x target cannot be reached by the capture alone.

## Capture overhead (cold - `--det`)

py-spy, samples in capture-only buckets as a share of the sample difference (MEASURED, one profiled run per variant;
the click and pygments differences are small against run-to-run noise):

| bucket | click | home-assistant 0/16 | home-assistant 10/16 | pygments |
|---|---|---|---|---|
| record.loop (per-test assembly, Python) | 181 (9%) | 591 (24%) | 2477 (20%) | 617 (78%) |
| lines (LINE/PY_START callbacks, Rust) | 71 (4%) | 287 (12%) | 2198 (18%) | 90 (11%) |
| record.facts (file facts, AST) | 437 (23%) | 610 (24%) | 947 (8%) | 569 (72%) |
| switch.sockets (/proc/self/fd scan at every context switch) | 151 (8%) | 15 (1%) | 98 (1%) | 512 (65%) |
| startup.identity (runtime identity) | 7 (0%) | 235 (9%) | 329 (3%) | 22 (3%) |
| audit (file-read capture, audit hook) | 13 (1%) | 42 (2%) | 219 (2%) | 15 (2%) |
| env (environment capture) | 90 (5%) | 13 (1%) | 42 (0%) | 26 (3%) |
| record.children (followed children, CPU part) | 108 (6%) |  |  |  |
| other capture (startup, check, follow) | 37 (2%) | 10 (0%) | 42 (0%) | 25 (3%) |
| not attributed (interpreter slowdown under sys.monitoring, noise) | 831 (43%) | 689 (28%) | 5865 (48%) | -1090 (noise) |
| **sample difference** | 1926 | 2492 | 12217 | 786 |

Timers and ablations (MEASURED, local, base engine):

| | click | pygments |
|---|---|---|
| cold wall - `--det` wall | 5.5 s | 4.5 s |
| end-of-session recording (`record_seconds`) | 4.4 s | 2.9 s |
| of which: waiting for children's trace logs | **3.0 s** (13 pager children killed before strace wrote a log, each waited for until the timeout) | 0 |
| of which: file facts | 0.6 s | 1.6 s |
| LINE events off (ablation) | -0.45 s | n/a |

Where the overhead goes, in order of size:

1. **End-of-session recording** (`_record_all`): on click mostly *waiting* for strace logs that can never appear
   (3.0 s of 5.5 s); everywhere else the per-test Python loop (copies of the global inputs for every test, a pass
   over every loaded module per test: 20-78 % of the difference) and the file facts (AST of every executed file).
2. **Line capture** on home-assistant (18 % in the callbacks, most of the 48 % not attributed is the interpreter
   running instrumented code): HA runs its own core (under the repository root, so all of it is instrumented). In
   the callback, `LineRecorder::hit` and SipHash (`RandomState::hash_one`) are the top frames.
3. **Context-switch socket scan**: `os.listdir("/proc/self/fd")` (through detpy's sorted `listdir`) and one
   `readlink` per descriptor at every switch (two per test, two per wider fixture): 65 % on pygments.
4. Startup runtime identity on HA (9 % on shard 0: thousands of distributions, memoised after the first run of a
   cache directory, so paid by every cold run).
5. Per-call hooks (audit, env) are small (0-5 %).

## `--det` overhead (`--det` - plain)

| bucket | home-assistant 0/16 | home-assistant 10/16 | pygments |
|---|---|---|---|
| compile (modules compiled from source at every run) | 1785 (54%) | 5032 (65%) | 609 (14%) |
| det.plugin (`_state.record`, call-site resolution, Rust recorder `end_test`) | 260 (8%) | 1552 (20%) | 91 (2%) |
| det.clock (virtual clock in asyncio's selector/condition waits) | 275 (8%) | 906 (12%) | 51 (1%) |
| det.seeds (`end_test`: repr of the random state) | 35 (1%) | 154 (2%) | 294 (7%) |
| det.fsorder, det.network | 37 (1%) | 110 (1%) | 37 (1%) |

The `compile` bucket is `SourceLoader.get_code` of **installed** modules: `reexec.precompile` runs `compileall -x
<venv|.venv|.git|...>` over the library directories too, and a library directory lives inside a virtual environment
(`.../venv/lib/python3.14/site-packages`), so nothing installed is precompiled and, with `PYTHONDONTWRITEBYTECODE=1`,
every installed module is compiled from source at every `--det` run (MEASURED: the pattern matches the walk's venv
and any `.venv`). This is the largest single `--det` cost on home-assistant.

Also seen: `TraceWriter::write_test` deep-copies every test's event list to serialize it.

## Plan (in order of measured gain)

1. Per-test assembly of `_record_all` to Rust (`detpy_core::record`), one plan of plain data in, store entries out;
   equivalence test against the old Python loop kept verbatim. Socket scan to Rust. **Done**, see the report.
2. Child trace logs: do not wait for a log whose strace tracer is gone (a `/proc` scan in Rust), charging the wait
   to the budget so the other children's decisions are unchanged. **Done.**
3. Line recorder: integer hasher for the callback maps (SipHash dominated). **Done.**
4. `--det`: precompile library directories without the project exclusions (a fix, flagged in the report as a
   behaviour change of `--det`: installed modules are then loaded from the deterministic bytecode cache, as
   documented, instead of being compiled from source); trace lines serialized by reference. **Done.**
5. File facts: statement-list walks instead of full-tree traversals (Python; the parse itself is CPython's).
   **Done.**
6. Next candidates: runtime identity on cold runs, call-site resolution and the per-event Python path of Level 0
   events (`_state.record` / `_sites.resolve`), the virtual clock in asyncio waits, and the line-capture strategy.

## Raw tables

`python3 harness/rust_hotpaths/analyze.py tracks/rust-hotpaths/results/p1` (add `-v` for every bucket).
