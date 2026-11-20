#!/bin/sh
# fix round 3: one library at a time (lock = mkdir): clone, environment, re-run the fixed finder on its a2 cases
cd /home/user/work; WD=/home/user/work
E=/home/user/fenvix-engine-cli/harness/culprit
W=$(ls /home/user/work/wheels2/detpy-*.whl)
for n in attrs boltons cachetools click jinja marshmallow more-itertools sqlparse structlog toolz; do
  mkdir -p locks3; mkdir locks3/$n 2>/dev/null || continue
  url=$(python3 -c "import json;print(json.load(open('$E/round3/a2-repos.json'))['$n'])")
  [ -d repos/$n ] || git clone -q $url repos/$n
  [ -x venvs/$n/bin/python ] || eng/bin/python $E/setup_lib.py $WD/repos/$n $WD/venvs/$n $W >> logs3/setup-$n.log 2>&1
  eng/bin/python $E/round3/refind_a2.py --name $n --repo repos/$n --venv venvs/$n --results-dir $E/results \
    --out results3/a-$n.jsonl --keys-dir keys3/$n >> logs3/a-$n.log 2>&1
  echo DONE $n >> logs3/a-$n.log
done
