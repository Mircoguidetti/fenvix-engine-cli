#!/bin/sh
# step-4 re-run (review R-019b M6): the 63 carried-over rows, round-2 checkout (fresh stamps), red-side check; no baseline bisect
cd /home/user/work; mkdir -p locks-b
export CULPRIT_WORK=/home/user/work
for r in $(python3 -c "import json;print(' '.join(json.load(open('cases/d-victims-r3.json'))))"); do
  mkdir locks-b/$r 2>/dev/null || continue
  V=$(python3 -c "import json,sys;print(json.dumps(json.load(open('cases/d-victims-r3.json'))[sys.argv[1]]))" $r)
  /home/user/work/eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/orderdep.py --repo-name $r --victims "$V" --attempts 0 --out results/d-r3b.jsonl >> logs/db-$r.log 2>&1
done
echo DONE >> logs/d-worker.log
