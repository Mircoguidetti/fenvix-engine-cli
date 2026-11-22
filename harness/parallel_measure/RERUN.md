# Rerunning every number

Every row of `results.jsonl` carries the exact command (`cmd`) and directory (`cwd`) it was measured with; the steps
below rebuild that state from nothing. Machine of the recorded numbers: this session's container, `nproc` = 4,
Intel(R) Xeon(R) Processor @ 2.10GHz (also recorded per row).

## 1. Engine (trunk)

```bash
git clone https://github.com/mircoguidetti/fenvix-engine-cli && cd fenvix-engine-cli
git checkout bfaf70b4                       # trunk of the final set (each row: engine_commit; earlier sets 5a6463fd)
python3 -m venv /tmp/pm/venv/py && /tmp/pm/venv/py/bin/pip install maturin
(cd node && npm run build)                  # Node addon: node/detjs.linux-x64.node
/tmp/pm/venv/py/bin/maturin build --release -o /tmp/pm/wheels
git checkout claude/parallel-measure -- harness/parallel_measure   # the harness (engine sources stay at the trunk)
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
cd fenvix-engine-cli/harness/parallel_measure
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
