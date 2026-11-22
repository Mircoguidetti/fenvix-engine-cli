# claudekit: tests whose outcome changes without the engine (THEIRS)

Repository https://github.com/carlrannaberg/claudekit at f22a4f9030520394bf1a517b46ad7585badf5130; engine verdicts from trunk ['5a6463fd']. Rule: classify.py (outcome differs between plain runs, no engine). Nothing here was published.

0 test(s).


## Outside the classification: order-dependent tests the engine verdict called stable

Found by `repro.py` (plain runner, no engine), not in the not-identical set (engine status `stable` in every verify),
so classify.py gives them no box. MEASURED, engine trunk 5a6463fd:

* `tests/unit/codebase-map.test.ts::CodebaseMapHook::execute::should handle large output buffers`
* `tests/unit/codebase-map.test.ts::CodebaseMapHook::execute::should skip silently if codebase-map is not installed`

Both failed in plain shuffle-2 and passed in plain serial 1-3, par4-1, par4-2 and shuffle-1 (failed in 1 of 7 plain
runs); every engine run (S1-S3, P w2/w4 x3) passed them. Reproduce:
`cd <checkout> && npx --no-install vitest run --no-file-parallelism --sequence.shuffle --sequence.seed=2`
(reproduces: 1 of 1 runs with seed 2; not re-run separately). Nothing published.
