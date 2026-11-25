# P2 speed: preregistration

Committed before the first measurement row of P2 (acceptance criterion 1; `git log --diff-filter=A -- harness/p2/PREREG.md`
versus the first commit that adds a `harness/p2/data/*/results.jsonl`). Spec: "P2 speed" rev 4 (gate 7/10, founder
"manda" 2026-11-25), its "Gate rev 4 notes" included. Where this file and the spec differ, the spec governs; any later
amendment to this file is appended as a dated section at the end, never edited in place.

## 1. Branch, engine, harness

- Branch `claude/p2-speed` from `origin/claude/release-1` = **6e79a62c79aae391b3e96c25bfca29ead64cc02f** (fetched
  2026-11-25, P1 merged).
- Recording-only harness change (gate note 9), committed and pushed before the baseline worktree took the branch's
  harness: **4c93a55** `harness/parallel_measure/measure.py`: every row also stores `host` (`/etc/hostname`) and
  `container_boot` (`/proc/sys/kernel/random/boot_id`). No timed command, environment or protocol change.
- Baseline engine: release-1 6e79a62 in the worktree `/home/user/fx-base` (`git worktree add /home/user/fx-base 6e79a62`,
  then `git checkout claude/p2-speed -- harness/parallel_measure`), addon `npm run build`, wheel `maturin build --release`
  installed into `$PM_WORK/venv/engine` (`venv/networkx` is a symlink to it, RERUN.md §4). `engine_commit` of its rows
  reads 6e79a62 (engine sources equal release-1).
  - addon `node/detjs.linux-x64.node` sha256 `2588c2641f074090734fbeb189143227dabb8d62e28105a85e19d47e5a748264`
  - wheel `fenvix-0.1.0-cp312-abi3-manylinux_2_34_x86_64.whl` sha256 `14e02bbc342f0d5fc227d7bd1fdffb479545b7c082faccfbaad99974d5a93cb2`
  - Fix heads and the final head are built the same way in their own checkout; each built commit and its addon/wheel
    sha256 are recorded in `FIXES.md` / `REPORT-P2.md`. The `verify` rows use the wheel installed in
    `$PM_WORK/venv/engine` at that time: it is reinstalled from the checkout under test before each phase or fix
    re-measure (the wheel's sha256 is recorded with it).
- `PM_WORK=/root/pm` (outside the checkout, not under `/tmp`). Setup commands: `harness/p2/RERUN.md`.

## 2. Machine (Phase A)

`nproc` 4; `Intel(R) Xeon(R) Processor @ 2.10GHz`; kernel 6.18.44-fc-v880; 15 GiB RAM; `node --version` v22.23.5
(drydock: `/opt/node24/bin/node` v24.22.3 through its spec `env.PATH`); Python 3.12 venv for `fenvix verify`.
`host` = `vm`, `container_boot` = `ded5bcf2-08d9-4d47-8920-45c4b494f711` at the time of this commit (every row records
its own; a different `container_boot` is a different container).

## 3. The pool (9 repositories; `harness/parallel_measure/specs.json`, unchanged)

| repo (spec name) | url | commit |
|---|---|---|
| nestjs-pino | https://github.com/iamolegga/nestjs-pino | 82d92198747c64e87057dfb50c6215a936a1a052 |
| agentsys | https://github.com/agent-sh/agentsys | ce58913304d88a1d1a0513e1837ae43c33f5f6f5 |
| alakajam | https://github.com/alakajam-team/alakajam | af63a7e0993f2f7de2ec8dff53a941ccfe855572 |
| agentlang | https://github.com/agentlang-ai/agentlang | f02e27199b193096c19985b7877ad1644974507a |
| yalc | https://github.com/Othmane-Khadri/YALC-the-GTM-operating-system | 5686d1f2f526346133f78eef3349fc5a655757b4 |
| ironcurtain | https://github.com/provos/ironcurtain | abf2b44c2e1b6138ede2d0b46337c684258088d0 |
| codex-multi-auth | https://github.com/ndycode/codex-multi-auth | b9886168aafcebd8581d4e344daf7abd19b510ce |
| drydock | https://github.com/CodesWhat/drydock | ce562a6a84c91b7e101398766d7de560cd18e35f |
| lerna-lite | https://github.com/lerna-lite/lerna-lite | fec3cb9660bac71efe5d5e5749f615a3802c1cc1 |

Phase A / D order: nestjs-pino, agentsys, alakajam, agentlang, yalc, ironcurtain, codex-multi-auth, drydock, lerna-lite.
Flags carried from earlier measurements (reported, not used to exclude): alakajam's own parallel mode fails 8-9 of 27
files (`REPORT-lane-a.md:82`), agentlang's own parallel mode exits 1 in some rounds (lane-a).

## 4. Protocol (plan "Measurement protocol", unchanged)

Per repository, one at a time, nothing else running, one measure.py process per round:

```
python3 <checkout>/harness/parallel_measure/measure.py --spec harness/parallel_measure/specs.json --name <repo> \
  --reps 1 --first-rep <k> --workers 2,4 --timeout 7200 --out harness/p2/data/<phase>      # k = 1, 2, 3; no --skip
```

Round 1 cold, rounds 2-3 warm (measure.py engine state per kind and worker count). Per configuration the median of the
3 rounds; plain parallel and engine each take the best of their w2 and w4 medians. Every table also prints the round-1
(cold) value. A round cut by a container restart discards that repository for the phase; it re-runs from round 1.
Out dirs: `harness/p2/data/baseline`, `harness/p2/data/fix-<n>` (gate note 5), `harness/p2/data/final`,
`harness/p2/data/phaseB/<repo>`; after a container change the "before" rows are re-run into a new dir with a suffix
(`baseline-c2`, ...).

After each round `harness/p2/post.py <out> <repo>` writes the committed evidence (per-test extracts, gzipped verify
reports and runs.log).

## 5. Definitions (copied from the spec; PREREG readings marked)

- **E** of a round at w workers = `par` wall (its one-lane re-runs included) + `verify` wall of that round and w.
  **PREREG reading:** "engine with proof" includes the proof check. `REPORT-P2.md` also prints `meets` on `par` alone.
- **PS** = median of the 3 `plain` walls; **PP(w)** = median of the 3 `plain_par` walls at w; **PP_best** = min over w.
  **E_best** = min over w of the median of E(w). speedup = PS / PP_best; allowance = min(1.3, speedup / 2).
- **Bounds:** `E_best <= allowance x PP_best` and `PS / E_best >= 2`, both from the same phase's rows of the same
  container. `meets` is printed on the medians and on the cold round (round 1 values throughout).
- **Correctness of a speed change** (`harness/p2/correctness.py`, on every targeted repository, w2 and w4):
  1. *Per-test verdict class*: class of a verify entry = `identical` (status `stable`), `not-proven:<reason>`,
     `diverged`, or `missing`; a test's class per w = the set over the 3 rounds. Baseline sets with more than one
     member = `VARIABLE-CLASS`, excluded. Every other test whose set changes is listed in `FIXES.md` with a one-line
     explanation from the fix's mechanism; an unexplained change in either direction is a defect.
  2. *Fixed-epoch fingerprints*: `harness/p2/fixed_run.py` (command = measure.py `serial()` with the checkout-under-test
     `detjs.js`, `--det-epoch=fixed`, trace `<out>/<repo>/F-<label>.jsonl`, measure.py's environment, tree reset,
     `/tmp/pm-<repo>` emptied). 3 runs at the baseline engine after the timed rounds, 1 per fix head, 1 at the final
     head. For each test with one fingerprint over the 3 baseline runs: equal at the fix head = pass; different = the
     fix-head run is repeated once; still different = the test's events at the fix head are compared with baseline
     run 1 after removing only the event kinds (`o`) the fix declared in `FIXES.md` before its re-measure (and approved
     by the coordinator, gate note 1); allowed only if the remaining event lists are equal and the outcome is equal.
  3. *Outcomes*: every test's outcome (passed/failed/skipped) and each run's exit code equal the baseline's, except
     tests whose outcome varied over the 3 baseline rounds of plain or engine runs (`VARIABLE`, listed in
     `BASELINE.md`). Counts may move only within the baseline spread (max - min over 3 rounds, per count and w).
- **Same machine**: `table.py` refuses to compare rows whose `cpu_model`, `host` or `container_boot` differ, and refuses
  a row whose repository's `runs.log` shows phases output (gate note 4).
- **Cold/warm**: every saving is also shown on the cold round; a saving visible only warm is labelled `warm-only`; a
  saving smaller than the baseline's round spread is labelled `within noise`.
- **Engine identity**: rows are keyed by `engine_commit`; fixed runs by `engine_commit` + addon sha256.

## 6. Phase B timing (`DETJS_PHASES=1`, opt-in, off by default)

Timer names (one JSON line each in `<trace>.phases.jsonl`, written through the real `fs` functions captured before
any patching, never into the trace): `start`, `deps_hash`, `plan`, `workers_spawn`, `worker_ready` (per worker),
`tests` (per worker: wall and summed per-file wall), `rerun_one_lane` (count and wall), `trace_write`, `exit`.
Counters per worker: `io_release` (count and total held ms; `node/src/ioorder.js` `releaseAll(true)`, line 250, record
at 259), `stack_captures` (count; `node/src/sites.js` `resolveDepth` 123-138 and the runner lookup at 82-93, plus
`ioorder.js` `nodeInternal()` 152), `uncontrolled_io` (count of `uncontrolled.io` events recorded).

Files on release-1 (confirmed): main process `node/src/session.js` (`prepare`/`finish`), `node/src/parallel.js`
(plan, lanes), `node/src/parallel-rerun.js` (one-lane re-run), `node/src/loaded.js` (deps digest); runner workers
`node/src/vitest/runner.mjs` (+ `node/src/vitest/shell.js`, which it loads) and `node/src/jest/worker.js`.
`node/src/worker-preload.js` exists but is the preload of `worker_threads` started *by a test* (it writes no trace
part); it gets no phase timer, only the counters through the shared modules.

**Normalisation for the flag-on/flag-off trace comparison (B.1).** MEASURED here on a 4-file Vitest fixture with the
baseline engine, `--det-epoch=fixed`, cold state, two flag-off runs: all test lines byte-identical; the header differs
only in `meta.parallel.timing` (all of its fields: `lanes_wall_seconds`, `test_file_seconds`,
`estimated_lanes_seconds`), `meta.parallel.placement.spans` and `meta.parallel.placement.waited_seconds`. These three
are removed before comparing, nothing else. If the B.1 test finds another field differing between two flag-off runs,
it is appended here (dated) before the flag-on comparison is used.

Phase B runs go through `fixed_run.py` (gate note 3): the `DETJS_PHASES=1` run with `--env DETJS_PHASES=1`, the branch
engine, trace `phases-<repo>.jsonl`, out `harness/p2/data/phaseB/<repo>`; the CPU-profile run with
`--node-options "--cpu-prof --cpu-prof-dir=<out>/<repo>/cpuprof"`. `DETJS_PHASES` is never exported in a shell.

## 7. #9 site tests (spec C.3; `grep -l site node/test/*.test.js` on release-1)

`node/test/cache-p041.test.js`, `node/test/p1-c-pid-boundaries.test.js`, `node/test/parallel-p041.test.js`,
`node/test/regressions.test.js`, `node/test/time-p041.test.js`.

## 8. Suites (Phase D)

As the spec D.3: `cargo test -p detpy-core -p detpy-node`; `node/`: `npm ci`, `node --test --test-concurrency=1
test/*.test.js`; Python shared shards 1-4 exactly as `.github/workflows/release-1.yml:141-147` with the empty-shard
guard; `python3 tests/attacks.py`; on the branch head and on 6e79a62, same machine, one at a time.
