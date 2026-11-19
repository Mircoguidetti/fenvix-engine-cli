#!/bin/sh
# review R-019c: a sample of kind c (head-to-head scenarios, random placement) and step 4 (two repositories) re-run
# with the round-4 finder, own output directory (copies of round4/run_c4.sh and run_d4.sh lanes).
cd /home/user/work
export CULPRIT_RED_BUDGET=64 CULPRIT_D_BUDGET=64 CULPRIT_WORKERS=4 CULPRIT_WORK=/home/user/work CULPRIT_ROUND=4
export CULPRIT_WHEEL=$(ls /home/user/work/wheels/detpy-*.whl)
E=/home/user/fenvix-engine-cli/harness/culprit
mkdir -p r019c/results r019c/logs
for d in none tz dep; do
  eng/bin/python $E/nocode.py --scenario sqlparse-env --decoy $d --placement random --out r019c/results/c-final-sqlparse-env.jsonl >> r019c/logs/c-sqlparse-env.log 2>&1
done
eng/bin/python $E/nocode.py --scenario flask-data --decoy none --placement random --out r019c/results/c-edit-flask-data.jsonl >> r019c/logs/c-flask-data.log 2>&1
for r in ${D_REPOS-idoft-krllint idoft-coinbase-commerce-python}; do
  V=$(python3 -c "import json,sys;print(json.dumps(json.load(open('$E/round4/d-victims4.json'))[sys.argv[1]]))" $r)
  (cd $E/round4 && /home/user/work/eng/bin/python $E/orderdep.py --repo-name $r --victims "$V" \
    --out /home/user/work/r019c/results/d-r019c.jsonl --attempts 0) >> r019c/logs/d-$r.log 2>&1
done
echo DONE >> r019c/logs/cd.log
