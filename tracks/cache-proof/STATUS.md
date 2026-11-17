# STATUS: cache-proof (P-013)

Updated 2026-11-17 07:45 UTC.

* Local branch `track-cache-proof` (worktree `<scratch>/cp-wt`), based on `origin/claude/gracious-rubin-eyswxd` @ 1573079.
  Patches: `patches/` (apply with `git am patches/*.patch` on that base; `patches/BASE` has the base commit).
* Done: engine feature `pytest --det --det-cache=DIR` (Rust store/check/key + sys.monitoring recorder in `detpy._core`,
  shell `python/detpy/proofcache.py`, `_codefacts.py`); 19 tests in `tests/test_proofcache.py`, full suite 104 passed.
* Done (3rd patch): walk harness `harness/cache_proof/walk.py` + 14 library specs.
* Done (4th patch): per-module import-time read scope, DNS/sendto/C-socket guards (reviewer R-002b), env fix; HA + pylint specs.
* Running: Actions run r2 (r1 cancelled: slow store merge fixed) (`.github/workflows/cache-proof.yml`, `run.json`), results in `results/r2/`.
* Next: aggregate results, REPORT.md. Old line: measurement harness (`harness/cache_proof/`), workflow `.github/workflows/cache-proof.yml` (this branch),
  runs on 14 libraries + home-assistant sample + one large app.
