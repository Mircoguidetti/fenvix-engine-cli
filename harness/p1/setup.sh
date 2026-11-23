#!/usr/bin/env bash
# P1 phase 1 setup: build the trunk engine and fetch + install the six measured repositories.
# Run once:  FENVIX=<engine checkout> PM_WORK=/tmp/pm-p1 bash harness/p1/setup.sh
set -eux
export FENVIX="${FENVIX:?set FENVIX to the engine checkout}" PM_WORK="${PM_WORK:-/tmp/pm-p1}"

# Node addon (RERUN.md section 1)
(cd "$FENVIX/node" && npm run build)

# RERUN.md section 4's venv block, verbatim
if [ -e "$PM_WORK/venv" ]; then echo "STOP: $PM_WORK/venv exists; pick another PM_WORK"; else
  python3.12 -m venv "$PM_WORK/venv/engine" &&
  "$PM_WORK/venv/engine/bin/pip" install maturin &&
  (cd "$FENVIX" && "$PM_WORK/venv/engine/bin/maturin" build --release -o "$PM_WORK/wheels") &&
  "$PM_WORK/venv/engine/bin/pip" install --force-reinstall "$PM_WORK"/wheels/fenvix-*.whl &&
  ln -s "$PM_WORK/venv/engine" "$PM_WORK/venv/networkx"   # the fenvix_python name most Node specs use
fi

# Repositories: RERUN.md section 2's fetch function, commit and install line of each specs.json entry
mkdir -p "$PM_WORK/repos" && cd "$PM_WORK/repos"
fetch() { mkdir -p $1 && (cd $1 && git init -q && git fetch -q --depth 1 https://github.com/$2 $3 && git checkout -q FETCH_HEAD); }
fetch agentsys agent-sh/agentsys ce58913304d88a1d1a0513e1837ae43c33f5f6f5
(cd agentsys && npm ci --ignore-scripts --no-audit --no-fund)
fetch codex-multi-auth ndycode/codex-multi-auth b9886168aafcebd8581d4e344daf7abd19b510ce
(cd codex-multi-auth && npm ci --ignore-scripts --no-audit --no-fund)
fetch ironcurtain provos/ironcurtain abf2b44c2e1b6138ede2d0b46337c684258088d0
(cd ironcurtain && npm ci --ignore-scripts --no-audit --no-fund)
fetch nestjs-pino iamolegga/nestjs-pino 82d92198747c64e87057dfb50c6215a936a1a052
(cd nestjs-pino && npm ci --ignore-scripts --no-audit --no-fund)
fetch claudekit carlrannaberg/claudekit f22a4f9030520394bf1a517b46ad7585badf5130
(cd claudekit && npm install --ignore-scripts --no-audit --no-fund)
fetch sqlectron sqlectron/sqlectron b0f5e24015bca7974fbce6ab5e4ada69d51b48b3
(cd sqlectron && npm install --ignore-scripts --no-audit --no-fund)
echo SETUP-DONE

# DEVIATION (run after the measure loop, 2026-11-23): sqlectron's spec install line (--ignore-scripts) leaves sqlite3
# without its native binding, so 3 of its 7 test files fail to load (14 tests instead of the 42 of the earlier
# engine rows). The sqlectron rows under harness/p1/data/before/sqlectron-rebuilt/ were measured after this step;
# the verbatim ones (14 tests) are kept under harness/p1/data/before/sqlectron/.
# (cd "$PM_WORK/repos/sqlectron" && npm rebuild sqlite3)
