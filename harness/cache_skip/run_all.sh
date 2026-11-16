#!/usr/bin/env bash
# Collection + analysis for the cache-skip study, JOBS repositories at a time.
#   WORK=/path/work OUT=harness/cache_skip/results WHEEL=dist/detpy-*.whl JOBS=3 harness/cache_skip/run_all.sh repo1 repo2 ...
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python3}"
WORK="${WORK:?}"; OUT="${OUT:-$HERE/results}"; JOBS="${JOBS:-3}"; COMMITS="${COMMITS:-51}"
mkdir -p "$WORK/logs" "$OUT"
printf '%s\n' "$@" | xargs -P "$JOBS" -I{} sh -c \
  "'$PY' '$HERE/run_repo.py' --repo {} --work '$WORK' --commits $COMMITS ${WHEEL:+--wheel '$WHEEL'} > '$WORK/logs/{}.log' 2>&1; \
   '$PY' '$HERE/analyze.py' --repo {} --work '$WORK' --out '$OUT' > '$WORK/logs/{}.analyze.log' 2>&1; echo done {}"
