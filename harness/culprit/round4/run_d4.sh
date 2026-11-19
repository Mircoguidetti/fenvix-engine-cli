#!/bin/sh
# fix round 4: step-4 cases re-run with the round-4 red-side check (budget CULPRIT_D_BUDGET, CULPRIT_WORKERS at a
# time); one repository at a time per worker (lock = mkdir). The git bisect baseline is not re-run (--attempts 0):
# it does not depend on the finder, and the round-3 row keeps it.
cd /home/user/work
export CULPRIT_RED_BUDGET=${CULPRIT_RED_BUDGET:-64} CULPRIT_D_BUDGET=${CULPRIT_D_BUDGET:-64} CULPRIT_WORKERS=${CULPRIT_WORKERS:-4}
export CULPRIT_WORK=/home/user/work
export CULPRIT_WHEEL=$(ls /home/user/work/wheels/detpy-*.whl)
mkdir -p r4/locks-d r4/logs r4/results
for r in $(python3 -c "import json;print(' '.join(json.load(open('d-victims4.json'))))"); do
  mkdir r4/locks-d/$r 2>/dev/null || continue
  V=$(python3 -c "import json,sys;print(json.dumps(json.load(open('d-victims4.json'))[sys.argv[1]]))" $r)
  eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/orderdep.py --repo-name $r --victims "$V" \
    --out r4/results/d-r4.jsonl --attempts 0 >> r4/logs/d4-$r.log 2>&1
  echo DONE $r >> r4/logs/d4-$r.log
done
