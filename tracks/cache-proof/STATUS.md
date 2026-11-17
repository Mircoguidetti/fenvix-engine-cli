# STATUS: cache-proof (P-013)

Updated 2026-11-17 06:50 UTC.

* Local branch `track-cache-proof` (worktree `<scratch>/cp-wt`), based on `origin/claude/gracious-rubin-eyswxd` @ 1573079.
  Patches: `patches/` (apply with `git am patches/*.patch` on that base; `patches/BASE` has the base commit).
* Done: engine feature `pytest --det --det-cache=DIR` (Rust store/check/key + sys.monitoring recorder in `detpy._core`,
  shell `python/detpy/proofcache.py`, `_codefacts.py`); 19 tests in `tests/test_proofcache.py`, full suite 104 passed.
* Next: measurement harness (`harness/cache_proof/`), workflow `.github/workflows/cache-proof.yml` (this branch),
  runs on 14 libraries + home-assistant sample + one large app.
