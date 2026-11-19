#!/bin/sh
cd /home/user/work
for ws in "s1d/jinja-0of1 20" "s1d/arrow-0of1 6" "s1d/arrow-0of1 28" "s1d/pylint-0of1 8"; do
  set -- $ws
  /home/user/work/eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/realhist.py --walk $1 --step $2 --out results/b.jsonl >> logs/b.log 2>&1
done
echo DONE-B >> logs/b.log
