# Rerunning every number

Every row of `results.jsonl` carries the exact command (`cmd`) and directory (`cwd`) it was measured with; the steps
below rebuild that state from nothing. Machine of the recorded numbers: this session's container, `nproc` = 4,
Intel(R) Xeon(R) Processor @ 2.10GHz (also recorded per row).

## 1. Engine (trunk)

```bash
git clone https://github.com/mircoguidetti/fenvix-engine-cli && cd fenvix-engine-cli && export FENVIX=$PWD
git checkout claude/harness-trunk   # the single harness copy (claude/release-1 once that branch is merged)
# measure.py runs the engine of the checkout it lives in (node/bin/detjs.js and its addon, the installed wheel) and
# records engine_commit from that checkout. To rerun rows whose engine_commit is not this checkout's engine (`git diff
# <engine_commit> -- crates python node/src node/bin Cargo.toml Cargo.lock pyproject.toml` not empty): check out
# <engine_commit>, then `git checkout origin/claude/release-1 -- harness/parallel_measure` (before the merge:
# `origin/claude/harness-trunk`), and build there; such rows record `<engine_commit>+modified` (measure.py compares with
# origin/claude/release-1). The 5a6463fd
# sets (data/earlier/) were taken with earlier harnesses and cannot be reproduced exactly with this measure.py.
python3 -m venv /tmp/pm/venv/py && /tmp/pm/venv/py/bin/pip install maturin
(cd node && npm run build)                  # Node addon: node/detjs.linux-x64.node
/tmp/pm/venv/py/bin/maturin build --release -o /tmp/pm/wheels
# results.jsonl (committed in 2cd4ea00 on claude/parallel-measure): the ironcurtain and codex-multi-auth rows were
# measured with this measure.py (D18 temp dir). The 50
# nestjs-pino and agentsys rows were measured before D18 (18c5da5d) and have neither tmpdir_reset nor hardcoded_tmp:
# no per-repository TMPDIR was set for them, so REPORT.md's "fresh empty TMPDIR" does not apply to them and this
# measure.py does not reproduce their exact conditions (their tmpdir-related divergences may differ under D18).
export PM_WORK=/tmp/pm
```

`measure.py` records `engine_commit` = `origin/claude/release-1` only when `crates/ python/ node/src node/bin Cargo.*
pyproject.toml` equal it, otherwise `HEAD+modified`.

## 2. Repositories (pinned commit, install)

Python repositories get their own venv (Python 3.12) with the engine wheel; Node repositories are installed with
their own lockfile and `--ignore-scripts`. Commit and install line per repository: `specs.json` (`commit`,
`install`).

```bash
mkdir -p $PM_WORK/repos && cd $PM_WORK/repos
fetch() { mkdir -p $1 && (cd $1 && git init -q && git fetch -q --depth 1 https://github.com/$2 $3 && git checkout -q FETCH_HEAD); }
fetch nestjs-pino iamolegga/nestjs-pino 82d92198747c64e87057dfb50c6215a936a1a052
fetch codex-multi-auth ndycode/codex-multi-auth b9886168aafcebd8581d4e344daf7abd19b510ce
fetch agentsys agent-sh/agentsys ce58913304d88a1d1a0513e1837ae43c33f5f6f5
fetch ironcurtain provos/ironcurtain abf2b44c2e1b6138ede2d0b46337c684258088d0
for d in nestjs-pino codex-multi-auth agentsys ironcurtain; do (cd $d && npm ci --ignore-scripts --no-audit --no-fund); done
# outside the plan's verdict (their CI runs in parallel, or not a serial-scan candidate)
fetch yaml eemeli/yaml 528ef30d6ded4bd9f2c3521b670eb2b29d503c5c && (cd yaml && git submodule update --init --depth 50 tests/yaml-test-suite tests/json-test-suite && npm ci --ignore-scripts --no-audit --no-fund)
fetch networkx networkx/networkx 6c1a31d1613ad04cf2b2e3d63090b94979521981
python3.12 -m venv $PM_WORK/venv/networkx && $PM_WORK/venv/networkx/bin/pip install $PM_WORK/wheels/*.whl pytest pytest-xdist numpy scipy matplotlib pandas && $PM_WORK/venv/networkx/bin/pip install --no-deps -e networkx
fetch attrs python-attrs/attrs f830e60f9c6485aa7037a52f03fdd28428dfbfc4
python3.12 -m venv $PM_WORK/venv/attrs && $PM_WORK/venv/attrs/bin/pip install $PM_WORK/wheels/*.whl cloudpickle hypothesis pympler "pytest>9" "pytest-xdist[psutil]" && $PM_WORK/venv/attrs/bin/pip install --no-deps -e attrs
```

(`$PM_WORK/venv/networkx/bin/python` is also the interpreter `fenvix verify` runs with for the Node rows:
`fenvix_python` in `specs.json`.)

## 3. Measure

One repository at a time, nothing else running (a round of codex-multi-auth takes about 45 min: run rounds in
separate processes with `--reps 1 --first-rep N` to stay under a 2 h job limit):

```bash
cd "$FENVIX/harness/parallel_measure"
for r in nestjs-pino agentsys ironcurtain codex-multi-auth; do
  python3 measure.py --spec specs.json --name $r --reps 3 --workers 2,4 --out $PM_WORK/final
  python3 repro.py   --spec specs.json --name $r --out $PM_WORK/final --runs 2 --seeds 1,2   # plain runs for classify.py
  python3 classify.py --out $PM_WORK/final --name $r --bugs bugs                             # THEIRS / OURS / UNDECIDED / ENV
done
python3 table.py $PM_WORK/final/results.jsonl specs.json      # the rows of TABLE.md
```

Before every run: `git checkout -- . && git clean -fdx -e node_modules` in the checkout (and its submodules), the
optional `build` of the spec, and an empty `TMPDIR=/tmp/pm-<repo>` (also TMP, TEMP).
Per round `measure.py` runs: (Python, round 1 only) bare pytest with `-p no:detpy`; plain serial (pytest with
`--det-outcomes`; Node: `npx --no-install vitest run --no-file-parallelism` / `npx --no-install jest --runInBand` with
the JSON reporter); the runner's own parallel mode with N workers, no engine (`-n N` / `--maxWorkers=N`), for every repository; `--det` serial
(`detjs ... --det --det-workers=1`); `--det` parallel at 2 and 4 workers; `fenvix verify S_i P_i --json` per worker
count; in round 2 `fenvix verify S_1 S_2` (serial noise). Engine state: per (kind, workers), round 1 cold, later
rounds start from what the previous run of the same kind left.

## 4. Lane A (agentic-qe, lerna-lite, step 3 candidates) — branch `claude/harness-trunk`

Status: complete (2026-11-23); results in `data/lane-a/`, the TABLE.md "Lane A rows" and `REPORT-lane-a.md`.

Harness: this directory on `claude/harness-trunk`; the exact harness commit of the Lane A rows is recorded in
`REPORT-lane-a.md` (measure.py / repro.py / classify.py / table.py byte-identical to `claude/parallel-measure` 20f7752d
throughout). Engine: trunk `claude/release-1` bfaf70b4 (`engine_commit` bfaf70b4 or 0071cbb9, same engine sources; the 9 plain-only sqlectron re-screen rows record
f67be4a3), built as in section 1 into a
Python 3.12 venv of its own. Use a work directory of its own, not section 2's (its `venv/networkx` is the networkx test
interpreter):

```bash
export PM_WORK=/tmp/pm-lane-a            # not /tmp/pm of sections 1-3
if [ -e "$PM_WORK/venv" ]; then echo "STOP: $PM_WORK/venv exists; pick another PM_WORK"; else
  python3.12 -m venv "$PM_WORK/venv/engine" &&
  "$PM_WORK/venv/engine/bin/pip" install maturin &&
  (cd "$FENVIX" && "$PM_WORK/venv/engine/bin/maturin" build --release -o "$PM_WORK/wheels") &&
  "$PM_WORK/venv/engine/bin/pip" install --force-reinstall "$PM_WORK"/wheels/fenvix-*.whl &&
  ln -s "$PM_WORK/venv/engine" "$PM_WORK/venv/networkx"   # the fenvix_python name most Node specs use
fi
```

(The recorded Lane A rows were taken with `PM_WORK=/tmp/pm`, the paths in their `cmd`/`cwd` fields; that /tmp/pm held
no section 2 venv, so `venv/networkx` there was the engine venv.)
Repositories fetched at the `commit` of their spec and installed with its `install`
line (agentic-qe: `npm ci --ignore-scripts --no-audit --no-fund && npm rebuild better-sqlite3 hnswlib-node argon2
sharp`; lerna-lite: `npx -y pnpm@11.28.5 install --frozen-lockfile --ignore-scripts && npx -y pnpm@11.28.5 build`).

```bash
cd "$FENVIX/harness/parallel_measure"
for r in agentic-qe lerna-lite; do
  for n in 1 2 3; do   # one round per process
    python3 measure.py --spec specs.json --name $r --reps 1 --first-rep $n --workers 2,4 --timeout 14400 --out $PM_WORK/lane-a
  done
  python3 repro.py --spec specs.json --name $r --out $PM_WORK/lane-a --runs 2 --seeds 1,2 --timeout 14400
  python3 classify_memo.py --out $PM_WORK/lane-a --name $r --bugs bugs   # classify.py with trace_tests cached (same output)
done
# step 3, per candidate: plain only first, then (admitted) the loop above
python3 measure.py --spec specs.json --name <r> --reps 3 --workers 2,4 --skip serial,par --out $PM_WORK/lane-a-screen
python3 table.py data/lane-a/results.jsonl specs.json     # the "Lane A rows" of TABLE.md
```

`--timeout 14400` (default 3600): the first agentic-qe `--det` serial run was killed by the 3600 s timeout (exit 124,
no trace; kept in `data/lane-a/interrupted/`); the completed one took 4145.98 s. Rounds interrupted by a container
restart were moved to `data/lane-a/interrupted/` (rows and that round's output files) and re-run from their start.
Results go to `$PM_WORK/lane-a/results.jsonl` (and `repro.jsonl`, `<repo>/classification.json`); they are copied to
`data/lane-a/` (same layout, which `table.py` reads) when complete. Step 3 screening rows
(`$PM_WORK/lane-a-screen/results.jsonl`) are copied to `data/lane-a/screen/results.jsonl`; an admitted candidate's
3 plain rounds in `data/lane-a/results.jsonl` come from its full run, not from the screening.
