#!/bin/bash
# usage: before_after.sh <fix-commit> <test files...>   (runs in $S/rv-fix, venv from $S/rv-b2)
S=/tmp/claude-0/-home-user/50f6213c-868e-5784-89fb-56a198be63cf/scratchpad
C=$1; shift; W=$S/rv-fix; PY=$S/rv-b2/.venv/bin/python
cd $W || exit 1
for phase in before after; do
  git checkout -q -f --detach $C
  [ $phase = before ] && { git checkout -q -f --detach $C^; git checkout -q $C -- "$@"; }
  echo "== $C $phase ($(git rev-parse --short HEAD))"
  PYTHONPATH=$W/python nice -n 10 timeout 600 $PY -m pytest -q -p no:randomly -p no:cacheprovider "$@" 2>&1 | tail -3
  git checkout -q -f HEAD -- . ; git clean -fdq tests
done
