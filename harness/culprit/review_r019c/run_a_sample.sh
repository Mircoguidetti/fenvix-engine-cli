#!/bin/sh
# review R-019c: re-run a sample of kind-a2 cases (rows selected into /home/user/work/r019c/sel, seed 19) with the
# round-4 finder; copy of round4/run_a4.sh with its own output directory.
cd /home/user/work; WD=/home/user/work
export CULPRIT_RED_BUDGET=${CULPRIT_RED_BUDGET:-64} CULPRIT_D_BUDGET=${CULPRIT_D_BUDGET:-64} CULPRIT_WORKERS=${CULPRIT_WORKERS:-4}
export CULPRIT_ROUND=4
E=/home/user/fenvix-engine-cli/harness/culprit
W=$(ls /home/user/work/wheels/detpy-*.whl)
mkdir -p r019c/logs r019c/results
for n in attrs toolz structlog sqlparse; do
  url=$(python3 -c "import json;print(json.load(open('$E/round3/a2-repos.json'))['$n'])")
  [ -d repos/$n ] || git clone -q $url repos/$n
  [ -x venvs/$n/bin/python ] || eng/bin/python $E/setup_lib.py $WD/repos/$n $WD/venvs/$n $W >> r019c/logs/setup-$n.log 2>&1
  eng/bin/python $E/round3/refind_a2.py --name $n --repo repos/$n --venv venvs/$n --results-dir r019c/sel \
    --out r019c/results/a-$n.jsonl --keys-dir keys019c-a/$n >> r019c/logs/a-$n.log 2>&1
  echo DONE $n >> r019c/logs/a-$n.log
done
