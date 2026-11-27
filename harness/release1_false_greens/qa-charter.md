# /review Step 4.7: exploratory QA charter and result (2026-11-26)

Run by the coordinator's instruction (founder decision on the final report, D1 = A, item 2). Tools: gstack
`gstack-qa-deadline` (300 s smoke budget) and `gstack-qa-evidence` (captures, checkpoints, materialized verdict); raw
evidence under `.gstack/tmp/qa-reports/run-20261126T042548Z/` (local, not committed).

## Charter
- **Target:** detpy CLI `python -m pytest --det [--det-cache=DIR]` (functional surface, CLI process contract), venv with
  detpy linked to the tree, head 3b08fa26.
- **Behavior:** the W8 controlled `_random.Random` (2ca21db1) and the cache's reuse decision around it.
- **Risk:** the controlled subclass changes what user code sees (`isinstance`, `issubclass`, copy, pickle, subclassing);
  a seeded generator stops being reusable (false red); an unseeded one is reused (false green).
- **Isolation:** an owned fixture under the report directory; no network, no repository writes.
- **Exit:** 300 s or 12 probes.

## Probes
| capture | command | expected | result |
|---|---|---|---|
| 001 | plain `pytest` (no --det), 4 fixture tests | reference | pass: ISINST True ISSUB True SR True; copy/pickle of a C generator raise TypeError |
| 002 | `pytest --det` | same types as 001 | **fail**: `isinstance(random.Random(0), _random.Random)`, `issubclass(random.Random, _random.Random)`, `isinstance(SystemRandom(), _random.Random)` all False |
| 003 | replay of 002 | same | fail (deterministic) |
| 004, 005 | `--det-cache` cold, warm | nothing NOT PROVEN or failed reused | pass: reused 0 (the failing test, the NOT PROVEN pickle test, and the tests after them in the process by the predecessor rule) |
| 006 | 002's command after the fix | same types as 001 | pass (revalidation; 002/003 superseded) |

Stopped at 5 of 12 probes with 250 s left: the defect found was replayed; fix and revalidation outside the smoke budget.

## Defect and fix
`random.Random` and every generator built before the sensor derive from the ORIGINAL C type, not from the controlled
subclass the sensor binds to `_random.Random`: under --det, `isinstance`/`issubclass` against `_random.Random` turned
False for them (True without --det). Introduced by 2ca21db1. Fix: `provable._ControlledMeta` answers
`isinstance`/`issubclass` against the controlled class as against the C type; a user's own subclass keeps the ordinary
checks. Failing-first test `test_the_controlled_class_keeps_isinstance_and_issubclass_of_the_c_type` (red log
`qa-isinstance-red-on-3b08fa26.log`), green after. Not covered (docs/LIMITS.md section 10): `type(x) is _random.Random` for a
generator built before the sensor started.

Verdicts (gstack-qa-evidence materialize): exploration `fail` (1 defect), revalidation `pass`, no open remainder.
