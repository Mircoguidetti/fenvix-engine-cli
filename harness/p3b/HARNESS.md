# P3b harness: provenance and every command

Spec: P3b rev 3 + gate rev 3 notes (engine-only cases on alakajam, drydock, agentlang). Work dir
`PM_WORK=$HOME/pm-p3b` (`/root/pm-p3b`); every shell call starts with `export PM_WORK=$HOME/pm-p3b;`.

## 0. Base, engine build, harness copy (2026-11-26)

- Branch `claude/p3b-engine-only` cut from `origin/claude/release-1` at
  **ece09e1f502a1d7354e563226ec890046d196fc7** (Merge claude/release1-false-greens, 2026-11-26 08:25 UTC).
  This is newer than the spec's 24962a94. The engine differs between the two:
  `git diff --stat 24962a94..ece09e1f -- crates python node/src node/bin Cargo.toml Cargo.lock pyproject.toml runner`
  = 13 files, +708 −82 (crates/detpy-node/src/lib.rs, node/src/{cache/runtime-id,controls,isolate-meta,isolate,
  parallel,provable,session}.js, python/detpy/{_proof,envobs,osstate,provable}.py, runner/fenvix-run). So the
  Current State table (measured on 24962a94) is not the same engine; A re-measures on ece09e1f.
- Commit identity: `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT` both start
  `Mirco Guidetti <` with the founder's address (checked before the first commit).

Engine build (RERUN.md section 1), each exit 0:

| Command | Result |
|---|---|
| `python3 -m venv $PM_WORK/venv/py && $PM_WORK/venv/py/bin/pip install maturin` | exit 0 |
| `(cd node && npm ci && npm run build)` | exit 0, `detjs: native core -> detjs.linux-x64.node` (cargo release, 35.9 s) |
| `$PM_WORK/venv/py/bin/maturin build --release -o $PM_WORK/wheels` | exit 0, `fenvix-0.1.0-cp312-abi3-manylinux_2_34_x86_64.whl` |
| `node node/bin/detjs.js --version` | `fenvix 0.1.0`, exit 0 |

`venv/engine` (RERUN.md section 4) not set up: `pins.py find` does not use `fenvix_python`.

### P3 harness pin

Pin **80d13bbb973f3e3379852ce3d5aa82ec72b1e742** on `origin/claude/p3-flips` (newer than 7f96338e; 7f96338e is its
ancestor, so amended D2 is in). 7f96338e..80d13bbb changes only `ladder.py` (resume cache: a `--det` run of the same
tag, command and engine commit is reused) and `run_b.sh` (preflight: stop before any run when the engine does not
load). Copied with `git show 80d13bbb:harness/p3_flips/<file> > harness/p3b/<file>`; no data files.

| File | sha256 | diff against the pin |
|---|---|---|
| cases.py | a7d3af25d0a5b9febf8e708608c61849c4d74215cbbf1f89c57b47ba7022d82d | empty |
| classify.py | a6b3a452ac511179d122c2a2fe926019bb6e0eeda4c0539b61d6112015ee3980 | empty |
| test_classify.py | 95c693f9856dbce87fbf963aa068b3bb61c9c21e22a2726f23136a0c2172d2df | empty |
| ladder.py | 0dae583ddf68bda5c4d6b093824b3dfa20bf687f540f7dbd0e0621f3183d53c5 | empty |
| run_b.sh | 6248ecd5b3adbacbdb1248869bd7b354a372e40e4c5ebe629bff4d10ba539f4e | empty |
| sequencer.mjs | 8f9e2fd7183231c46a077aaf7cab350ca2f5e6d9410137a75f71b64a3dddc518 | empty |
| setup_extra.sh | 0d44a7233fe8a5b16e809f62b9013933e2577620452983793e96cb85144a43f1 | empty |
| count_extra.py | 3b45778bd81de9c1f03cfc9b6412639537eda4bba8b809ef8653d14678a5c953 | empty |

The copies keep P3's docstrings (`harness/p3_flips/...`, `/tmp/pm-p3`) and P3's render title; the commands below
are the ones run. The copies import `harness/det_pins` and `harness/parallel_measure` relative to `__file__`, i.e.
release-1's versions. The only difference from p3-flips there is `measure.py`'s `FENVIX_ENGINE` override (not used
here: the engine measured is this checkout).

`python3 -m pytest -q harness/p3b/test_classify.py` → `20 passed in 0.08s`.

## A. Own re-measure (2026-11-26, engine ece09e1f on every run)

A1, checked once: `/opt/node24/bin/node --version` → `v24.22.3` (present, no install); system `node` v22.23.5;
`command -v unshare ip` → `/usr/bin/unshare` only (no `ip`); `id -u` → 0.
`export PM_WORK=$HOME/pm-p3b; mkdir -p $PM_WORK; set -o pipefail; bash harness/p3b/setup_extra.sh 2>&1 | tee $PM_WORK/setup.log`
→ exit 0, log ends `EXTRA-SETUP-DONE`, drydock part prints `v24.22.3`.

A2-A3 per repository R (alakajam, agentlang, drydock), each command exit 0:

```
export PM_WORK=$HOME/pm-p3b; python3 harness/det_pins/pins.py find --repo R --out $PM_WORK/find
export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/count_extra.py run --repo R --find $PM_WORK/find
export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/count_extra.py count --repo R --find $PM_WORK/find
export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/cases.py $PM_WORK/find/R <checkout>
```

Checkouts: `$PM_WORK/repos/alakajam`, `$PM_WORK/repos/agentlang`, `$PM_WORK/fr/CodesWhat_drydock/app`.
Each run's command, exit and wall are in `data/R/find/runs.jsonl` (all `engine_commit` = ece09e1f, not `+modified`).

| R | plain 1 / 2 (exit 0) | --det w1 1 / 2 (exit 1) | --det w4 1 / 2 (exit 1) |
|---|---|---|---|
| alakajam | 33.34 / 31.65 s | 72.21 / 85.75 s | 86.81 / 91.04 s |
| agentlang | 79.20 / 80.36 s | 90.73 / 89.55 s | 102.35 / 95.29 s |
| drydock | 535.27 / 549.47 s | 515.78 / 500.25 s | 229.64 / 233.15 s |

Copied to `data/R/find/` as P3 does (outcome, ids and runner files gzipped with `gzip -n`; `flips.json`,
`count_extra.json`, `runs.jsonl`, `cases.json` as is). The `det*`/`par*` traces and `runs.log` stay in
`$PM_WORK/find/R/` (B4 reads the w4 traces).

## B. Classify every serial case (2026-11-26, engine ece09e1f)

B1, per R, exit 0, all `accepted: true` (alakajam Vitest 5.0.5, agentlang 4.0.18, drydock 4.1.12):
`export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/seqcheck.py --repo R --find $PM_WORK/find` → `data/R/seqcheck.json`.

B2, per R, exit 0, all `neutral: true` (alakajam 0 differ; agentlang 0; drydock 48 differ, 0 outside plain-variable):
`export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/ladder.py neutral --repo R --find $PM_WORK/find` → `data/R/neutral.json`.

B3, the ladder per file (`run_b.sh <repo> [budget_s]`, default budget 6600 s), each exit 0, every file `exit 0`,
none stopped by the budget, logs in `$PM_WORK/logs/b-R.log`:

```
export PM_WORK=$HOME/pm-p3b; bash harness/p3b/run_b.sh alakajam      # 9 files
export PM_WORK=$HOME/pm-p3b; bash harness/p3b/run_b.sh agentlang 1500 # 2 files
export PM_WORK=$HOME/pm-p3b; bash harness/p3b/run_b.sh drydock 5400   # 19 files, one slice
```

B4: `export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/parallel_only.py --find $PM_WORK/find` → `PARALLEL-ONLY.md`
(new P3b script; reads `count_extra.json`'s `parallel_only` and the w4 trace headers).

B5, in the spec's order:

| Step | Command | Result |
|---|---|---|
| 1 | `python3 harness/p3b/classify.py rows` | 198 rows, exit 0 |
| 2 | `timeouts.py measure` | not run: no row has reason "cause wrapper (wrapper)", so no input |
| 3 | `python3 harness/p3b/timeouts.py annotate` | `{"rows": 198, "with_overhead": 0, "timeout_theirs_env_different_line": 0}` |
| 4 | `python3 harness/p3b/classify.py render` | `CLASSIFY.md` |

Then, each exit 0:

- `export PM_WORK=$HOME/pm-p3b; python3 harness/p3b/report.py excluded --repo R --find $PM_WORK/find` per R;
- `python3 harness/p3b/report.py render`;
- `python3 harness/p3b/causes.py`. This compared P3 rows at origin/claude/p3-flips e32e11eb, the branch head at run time, newer than the harness pin 80d13bbb. Only rows.jsonl is read from it.

`python3 -m pytest -q harness/p3b/test_classify.py harness/p3b/test_p3b.py` → `33 passed`.
