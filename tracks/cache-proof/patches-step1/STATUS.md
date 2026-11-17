# STATUS: cache-proof step 1 (skip on large repositories)

Updated 2026-11-17 16:50 UTC.

* Engine: local branch `track-cache-proof` (worktree `<scratch>/cp-wt`), base in `BASE` (origin/claude/gracious-rubin-eyswxd @ 1573079).
  This folder holds the full series: `git am patches-step1/*.patch` on BASE. 0001-0007 = r5's series, 0008+ = step 1.
* Causes found (MEASURED locally):
  * pylint: every test refused `subprocess` because `pylint/checkers/spelling.py` imports pyenchant at import time; pyenchant calls
    `ctypes.util.find_library("enchant-2")`; libenchant is not in the linker cache, so find_library falls back to `gcc -Wl,-t ... -lenchant*`
    and `ld -t ... -lenchant*` (12 spawns). A spawn at import time of a non-test module refuses every test.
  * structlog: `clock` misses, not refusals. `structlog/stdlib.py` builds a `logging.LogRecord` at import time (reads `time.time_ns`), so every
    test depends on the epoch; `--det-epoch=auto` is the HEAD commit time, which changes on every commit.
  * home-assistant: not reproducible locally (only 7 of 39 shard-0 units collect here, none spawns). Diagnostic run `s1d1` on Actions.
* Done: 0008 every refusal names its cause (program/address, call site, context): `not_cached_where`, summary `not_cached_detail`.
* Next: child following (strace), find_library, wall vs monotonic clock reads, opt-in stable epoch; then the full measurement run.
* Pre-existing: tests/test_clock.py 2 wait-for-child tests fail when stale deterministic temp dirs exist in /tmp (pass with a fresh TMPDIR).
