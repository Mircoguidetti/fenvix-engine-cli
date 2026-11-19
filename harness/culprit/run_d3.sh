#!/bin/sh
# step-4 worker: takes repositories one at a time (lock = mkdir), so several workers never share a checkout
cd /home/user/work
for r in $(python3 -c "import json;print(' '.join(json.load(open('cases/d-victims2.json'))))"); do
  mkdir locks/$r 2>/dev/null || continue
  V=$(python3 -c "import json,sys;print(json.dumps(json.load(open('cases/d-victims2.json'))[sys.argv[1]]))" $r)
  /home/user/work/eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/orderdep.py --repo-name $r --victims "$V" --out results/d.jsonl >> logs/d.log 2>&1
done
echo DONE-D3 >> logs/d.log
