#!/bin/sh
# fix round 4: one library at a time (lock = mkdir): clone, environment, re-run the round-4 finder on its a2 cases
# (red-side check with key-validity inference; probes CULPRIT_WORKERS at a time, budget CULPRIT_RED_BUDGET)
cd /home/user/work; WD=/home/user/work
export CULPRIT_RED_BUDGET=${CULPRIT_RED_BUDGET:-64} CULPRIT_D_BUDGET=${CULPRIT_D_BUDGET:-64} CULPRIT_WORKERS=${CULPRIT_WORKERS:-4}
export CULPRIT_ROUND=4
E=/home/user/fenvix-engine-cli/harness/culprit
W=$(ls /home/user/work/wheels/detpy-*.whl)
mkdir -p r4/locks-a r4/logs r4/results
for n in jinja attrs toolz marshmallow click cachetools more-itertools sqlparse boltons structlog; do
  mkdir r4/locks-a/$n 2>/dev/null || continue
  url=$(python3 -c "import json;print(json.load(open('$E/round3/a2-repos.json'))['$n'])")
  [ -d repos/$n ] || git clone -q $url repos/$n
  [ -x venvs/$n/bin/python ] || eng/bin/python $E/setup_lib.py $WD/repos/$n $WD/venvs/$n $W >> r4/logs/setup-$n.log 2>&1
  eng/bin/python $E/round3/refind_a2.py --name $n --repo repos/$n --venv venvs/$n --results-dir $E/results \
    --out r4/results/a-$n.jsonl --keys-dir keys4/$n >> r4/logs/a-$n.log 2>&1
  echo DONE $n >> r4/logs/a-$n.log
done
