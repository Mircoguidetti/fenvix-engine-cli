# P2 Phase B: where the engine's parallel time goes

Sources (all raw, all committed or reproducible):

- **Baseline timed traces** (`harness/p2/data/baseline/<repo>/P3w<n>.jsonl`, header `meta.parallel`; the original
  machine, boot ded5bcf2, warm round 3), tabulated by `python3 harness/p2/breakdown.py lanes`.
- **Phase B runs** (`harness/p2/data/phaseB`, branch engine, `fixed_run.py`, `--det-epoch=fixed`, cold engine state
  because fixed_run resets the tree; boot 406fde79 after a container reboot at about 22:10 UTC):
  - a `--cpu-prof` run (`cpuprof-summary.json`);
  - a `DETJS_PHASES=1` run (`phases-summary.json`; segments by `python3 harness/p2/breakdown.py`).
  Phase B times are compared only with each other, never with the baseline numbers (another boot, and a cold plan).
- `ironcurtain` meets both bounds and has no Phase B run. agentlang's parallel request is refused (below).

## 1. The parallel run, round 3 of the baseline (warm plan)

`outside lanes` = par wall - lanes wall (startup, plan, hazard re-run, post-run analysis, deps digest, trace write).
`plan excess` = the plan's makespan - (sum of file seconds / w): lost before the run starts, by the plan.
`runtime excess` = lanes wall - plan makespan: lost while running (worker slots blocked by lane waits, costs that
differ from the recorded ones).

LANES_TABLE

## 2. Phase B runs (branch engine, cold plan)

`pre` = start to first worker ready; `window` = first worker ready to last file end (`ideal` = sum of file walls / w,
`idle` = the rest); `post` = last file end to exit; pass 2 = the hazard wrapper's one-lane re-run
(`src/parallel-rerun.js`), whose files' wall adds to the run.

PHASES_TABLE

CPU profiles (`cpuprof-summary.json`, self time over every profile written; Vitest fork workers are killed by the
pool and write none, so worker-side engine time shows only for Jest repositories and processes that exit):

CPU_TABLE

## 3. Causes, ranked by the seconds they cost on the repositories that miss a bound

The gap is E_best - allowance × PP_best (baseline medians): how many seconds E must lose to meet the first bound.

GAP_TABLE

RANKED
