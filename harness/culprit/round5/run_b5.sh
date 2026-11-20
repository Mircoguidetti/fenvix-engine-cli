#!/bin/sh
# fix round 5 (R-019c diff rule): kind b re-run with the round-4 finder, one project at a time (lock = mkdir)
cd /home/user/work; WD=/home/user/work
export CULPRIT_RED_BUDGET=${CULPRIT_RED_BUDGET:-64} CULPRIT_D_BUDGET=${CULPRIT_D_BUDGET:-64} CULPRIT_WORKERS=${CULPRIT_WORKERS:-4}
export CULPRIT_ROUND=5
export CULPRIT_WHEEL=$(ls /home/user/work/wheels/detpy-*.whl)
E=/home/user/fenvix-engine-cli/harness/culprit
mkdir -p r5/locks-b r5/results r5/logs
for n in pytest pyparsing filelock attrs click faker markdown jsonschema; do
  mkdir r5/locks-b/$n 2>/dev/null || continue
  url=$(python3 -c "import json;print(json.load(open('$E/round3/b-repos.json'))['$n'])")
  [ -d reposb/$n ] || git clone -q $url reposb/$n
  git -C reposb/$n checkout -q -f $(git -C reposb/$n rev-parse origin/HEAD)
  [ -x venvsb/$n/bin/python ] || eng/bin/python $E/setup_lib.py $WD/reposb/$n $WD/venvsb/$n $CULPRIT_WHEEL >> r5/logs/setupb-$n.log 2>&1
  eng/bin/python $E/round3/refind_b.py --project $n --repo reposb/$n --venv venvsb/$n --period periodv3 \
    --results-dir $E/results --out r5/results/b-$n.jsonl --keys-dir keys5b/$n >> r5/logs/b-$n.log 2>&1
  echo DONE $n >> r5/logs/b-$n.log
done
