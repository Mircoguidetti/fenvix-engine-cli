DONE: capture overhead median +172% -> +10% (MEASURED, 3 libraries); equivalence over 50 transitions x 3 libraries: identical skip sets, 0 skipped tests failing on the full rerun (MEASURED).

# Capture overhead: per-test ingredient capture for skip-with-proof

Branch `capture-overhead` (local only, not pushed), worktree
`/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad/co-wt`, head `7a73e4a`.
All work in `harness/cache_skip/`. Not touched: `harness/skip_study2`, `idle_study`, `diff_study`, the main
checkout.

## Result

Overhead of the capture run over the plain serial run (wall time, same machine, interleaved runs, one at a time,
`PYTHONHASHSEED=0`, Python 3.13.18). Medians of 5 interleaved runs per variant (MEASURED); the median of the first
3 runs is in brackets (MEASURED).

| library | normal (plain) s | before: coverage.py + contexts | after: sys.monitoring + C recorder | after, no C compiler (Python callbacks) |
|---|---:|---:|---:|---:|
| marshmallow (1192 tests) | 1.00 | +172% (+169%) | **+10%** (+4%) | +21% (+19%) |
| click (2653 tests) | 4.04 | +109% (+109%) | **+10%** (+17%) | +17% (+26%) |
| more-itertools (770 tests) | 8.52 | +349% (+351%) | **+3%** (+5%) | +4% (+6%) |
| **median of the 3** | | **+172%** | **+10%** (+5%) | +17% (+19%) |

Target (under +15% median, same libraries): met (MEASURED). The study measured +107% median over 18 repositories
with coverage.py; on these 3 the old capture costs +109% to +349% here.

Noise: the container is shared; the same variant moves by up to about 10 points between batches (an earlier
3-run batch of the same code gave marshmallow +22%, click +14%, more-itertools +3%; median +14%) (MEASURED).
During the equivalence collection (51 commits per library, one run per variant per commit) the per-commit
sys.monitoring overhead had medians of marshmallow +8%, click +9%, more-itertools +2% (coverage.py: +138%, +99%, +366%) over 51 commits each (MEASURED, single runs, noisier).

more-itertools: `tests/test_more.py::TestConcurrentTee::test_concurrent_consumers` (100 threads, 10^5 items, one
lock) is left out of every variant of the benchmark and of the equivalence collection (`--deselect`, both
captures alike). Its duration is a thread-scheduling lottery even without any capture: 0.9 s to 31 s in the plain
run (MEASURED, same commit, 3 runs).

Benchmark command (work dirs at the study's head commits):

    python harness/cache_skip/bench_capture.py --work <dir> --runs 5 \
      --variants plain,coverage,sysmon,sysmon:python \
      --deselect more-itertools=tests/test_more.py::TestConcurrentTee::test_concurrent_consumers \
      marshmallow click more-itertools

Raw data: `scratchpad/co/bench9.json` (final), `bench8.json`, `bench6-click.json`, `bench3.json` (earlier).

## What changed

1. **New tracer** `harness/cache_skip/sysmon_capture.py` (Python 3.12+, `sys.monitoring`) replaces
   `coverage run` + dynamic contexts. It records exactly what coverage.py records in statement mode: per
   context (`t|nodeid`, `f|...` fixtures, `c|file` collection, `s|session`, `""` startup), the lines executed in
   each file below the root. Same output layout as `run_repo.extract_coverage`, so `analyze.py` is unchanged
   apart from `--tag/--skip-ids`.
   * `LINE` is armed only locally, on code objects below the root (modules seen through the `exec` audit event,
     nested code objects with them; earlier code via `gc` only when a root module is already loaded).
     `PY_START` also on the code objects whose first line `LINE` never reports (one-line functions, lambdas,
     docstring-only bodies, empty modules), as `settrace` does.
   * **Count strategy** (the main change of this session): the first hit of a location in a context is recorded,
     the next 16 hits only count, after that the location is disabled and only its code object is re-armed at
     the next context switch. The previous strategy (DISABLE on first hit + `restart_events()` at each test)
     re-instruments every function entered after the restart, about 90 ns per line of each function (MEASURED,
     microbenchmark: 27 us per call of a 300-line function); on click that cost more than all the callbacks.
   * **C recorder** `harness/cache_skip/_sysmon_rec.c` (about 300 lines, no dependencies): the two callbacks
     and an audit hook filtered in C (the Python audit hooks were called for about 240 000 events per click run,
     mostly `builtins.id` and `object.__getattr__`, MEASURED). Built on first use with the interpreter's own
     compiler settings (`sysconfig`), cached in `~/.cache/detpy/cache_skip/` by interpreter and source hash;
     `run_repo.py` and `bench_capture.py` build it before any timed run (`python sysmon_capture.py --build`).
     Without a compiler, or with `CACHE_SKIP_NATIVE=0`, the same strategy runs as Python closures: identical
     output, slower (last column of the table).
   * Raw data (file ids, context boundaries, one uint64 per recorded location) is written at exit; folding into
     the per-context blobs runs outside the test process (`fold_file`), as coverage.py's data extraction already
     did in the study.
2. `capture_plugin.py`: `CACHE_SKIP_TRACER=auto|coverage|sysmon` (auto = sysmon when `sys.monitoring` exists and
   the process is not under `coverage run`); file/spawn/socket audit hook unchanged in logic, routed through the
   C filter when the native module is loaded.
3. `run_repo.py --tracer auto|coverage|sysmon|both` (both = the two captures at each commit, for equivalence);
   `analyze.py --tag .sm --skip-ids`; `compare_skips.py` (equivalence + blocking-error check);
   `compare_capture.py`; `bench_capture.py`.
4. Knobs for comparisons: `SYSMON_DBG=restart` (old strategy), `SYSMON_DBG=python` (no C), `SYSMON_DBG=off`,
   `SYSMON_HOT=<n>`.

Tried and dropped (MEASURED on click): DISABLE + `restart_events()` +34%; same with targeted re-arm, not
cheaper; count strategy in Python +31% (before the audit filter); hot threshold 1/4/16/64 within noise on
marshmallow (+11% to +15%), 0 clearly worse (+26% on click).

## Equivalence

Same libraries, same 51 commits (50 base/head transitions) and the same head commits as the study
(marshmallow 777ff66, click 08b803c, more-itertools ceafee8). At every commit both captures ran (coverage.py as
in the study, then the new tracer, tracer code frozen at 301959b, `run_repo.py` at 7a73e4a which only adds `--deselect`); `analyze.py` ran on each
capture set with all 14 rule variants (closure, file, line, file+guard, line+guard, file+nameguard,
line+nameguard, each with the strict and the relaxed config rule),
then `compare_skips.py`.

| library | transitions compared | skip decisions (all rules) | tests skipped, coverage.py / new | differences | skipped but failing on full rerun |
|---|---:|---:|---:|---:|---:|
| marshmallow | 50/50 | 829 472 | 490 122 / 490 122 | 0 | 0 |
| click | 50/50 | 1 398 880 | 458 436 / 458 436 | 0 | 0 |
| more-itertools | 50/50 | 524 454 | 121 133 / 121 133 | 0 | 0 |

All MEASURED. The skip sets are identical for every transition and every rule variant; no skipped test changed
outcome or failed on the full rerun at the new commit: nothing blocking. Raw data:
`scratchpad/co/eq2/out/` (`<repo>.json`, `<repo>.sm.json`, `equivalence.sm.json`), summary
`scratchpad/co/eq2/equivalence.txt`; per-commit captures in `scratchpad/co/eq2/<repo>/caps/`.

Before the long run, per-context line sets were compared directly (same commit, same process settings):
coverage.py vs new tracer vs Python fallback vs old restart strategy, identical for every context on click (2674
contexts) and more-itertools (773), and on marshmallow except 4 test ids that embed the current time (the ids
differ between runs, not the lines). One more-itertools test (`CallbackIterTests::test_abort`, a background
thread polling a queue with a timeout) executes 3 lines or not depending on thread timing: the lines differ
between two runs of the same tracer, not between tracers.

## Python versions

* 3.13.18: all measurements and the equivalence run (the study's version).
* 3.12.3: native build and capture checked on a small project (6 tests incl. a thread, loops, lambdas,
  docstring-only method): identical to coverage.py for every context, native, Python fallback and restart.
* 3.14.6: same check; identical to coverage.py with `COVERAGE_CORE=ctrace`. With coverage.py 7.17's default core
  on 3.14 (its own sys.monitoring core) coverage.py **misses lines** in 4 of 7 contexts (for example the `if`
  of a function already run by an earlier test); the new tracer does not. If the study is ever rerun with
  coverage.py on 3.14, force `COVERAGE_CORE=ctrace`.
* 3.11.18 (no `sys.monitoring`): fallback is coverage.py as in the study (`CACHE_SKIP_TRACER=auto` under
  `coverage run`, `run_repo.py --tracer auto` picks it by itself); forcing `sysmon` stops with a clear error.

## Open points for the coordinator

* The C recorder lives in the harness. In the product it belongs in the Rust core (PyO3), same logic, no
  compiler needed on the user's machine (ESTIMATED same cost).
* `docs/CACHE-SKIP-STUDY.md` still says "+107% (MEASURED) ... a cheaper capture is a requirement": the number
  to add is in the table above. Not edited (outside this task's folders).
* Without a C compiler the fallback is +17% median (+21% on marshmallow): just over the target.
