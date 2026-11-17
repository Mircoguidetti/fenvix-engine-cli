PARTIAL (intermediate: round r1 measured; round r2 with the fixes found by r1 is queued on Actions)

# Report · track l1-threads (P-012) · Level 1 for threads (`--det-threads`)

Intermediate. Numbers below are from Actions round r1 (run 44042691111, code 4d88a2f); the final
report replaces them with round r2 (run 44049131964, code c2596b0). Raw: `results/r1/`,
aggregate: `r1-aggregate/`.

* easypy 10 Block 2 thread tests, `--det --det-threads --det-urandom`: **10/10 one fingerprint**
  over 10 quiet + 5 CPU-loaded runs (MEASURED). Level 0 alone: 0/10; Level 0 + `--det-urandom`: 8/10;
  `--det-threads` without `--det-urandom`: 0/10 (easypy draws `uuid4()` per thread).
* class a (31): 18 are one marshmallow test whose id contains the wall-clock time (not a thread
  problem, no stable id); 13 measured. Plain reruns: 0 failures in 15 runs each. Exploration
  (20 thread seeds) found failing interleavings for 9/13; r1 had a bug (instant deadlock with
  only I/O waiters) that distorts them: r2 is the number to read.
* Popular pool (22/25 suites in r1): tests broken by `--det-threads` (calm): 3 in 2 projects; boltons 2
  fixed after r1 (I/O in flight, event-loop clock), jinja 1 not caused by threads (Level 0 cross-run mtime).
* Slowdown vs `--det`, 5 most thread-heavy suites: more-itertools +20.6%, networkx 0.0%, structlog
  +7.2%, flask 0.0%, click −1.3% (MEASURED, one runner per project, NOISY).
