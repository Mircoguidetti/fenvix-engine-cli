# Head-to-head: competitor-style skip rules vs the fenvix proof rule

**Status: DRAFT (2026-11-17 19:30 UTC).** Runs h1 (main, env, runtime arms) and h2 (home-root arm) are in; run h3
(re-walk of the Python projects with the per-test-coverage rules Ae / Af) is running. Final tables and the sentence
follow when h3 lands. Raw data: `results/h1`, `results/h2`, `results/h3`. Tables: `python3 h2h_aggregate.py h1 h2 h3`.

Preliminary, MEASURED:

* **Fixed environment (measurement 1):** 0 wrong for every rule so far. The competitor-style rules skip as much as
  fenvix or more, e.g. Home Assistant A 100% / 92% vs C 98% / 82% (median / mean).
* **Environment changed (measurement 2):**
  * `env`, `runtime`: 0 wrong for every rule.
  * `home-root` (HOME=/root, as on a root container runner): docusaurus, A / B / B+ skip 99% and reuse 3 stale
    passes (3 distinct units, 15 unit-transitions, each confirmed at both commits). C skips 0% there, 0 wrong.
