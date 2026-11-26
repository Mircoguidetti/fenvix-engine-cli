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

## A. Own re-measure

(filled in at the end of A)
