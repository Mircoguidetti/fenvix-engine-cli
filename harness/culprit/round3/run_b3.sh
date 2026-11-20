#!/bin/sh
# fix round 3: kind b re-run with the fixed finder, one project at a time (lock = mkdir)
cd /home/user/work; WD=/home/user/work
export CULPRIT_WHEEL=$(ls /home/user/work/wheels2/detpy-*.whl)
E=/home/user/fenvix-engine-cli/harness/culprit
mkdir -p locks3b results3 logs3
for n in pytest pyparsing filelock attrs click faker markdown jsonschema; do
  mkdir locks3b/$n 2>/dev/null || continue
  url=$(python3 -c "import json;print(json.load(open('$E/round3/b-repos.json'))['$n'])")
  [ -d reposb/$n ] || git clone -q $url reposb/$n
  git -C reposb/$n checkout -q -f $(git -C reposb/$n rev-parse origin/HEAD)
  [ -x venvsb/$n/bin/python ] || eng/bin/python $E/setup_lib.py $WD/reposb/$n $WD/venvsb/$n $CULPRIT_WHEEL >> logs3/setupb-$n.log 2>&1
  eng/bin/python $E/round3/refind_b.py --project $n --repo reposb/$n --venv venvsb/$n --period periodv3 \
    --results-dir $E/results --out results3/b-$n.jsonl --keys-dir keys3b/$n >> logs3/b-$n.log 2>&1
  echo DONE $n >> logs3/b-$n.log
done
