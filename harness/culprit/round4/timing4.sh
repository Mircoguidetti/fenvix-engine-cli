#!/bin/sh
# fix round 4: clean timing pass (nothing else on the machine): kind b re-run with 4 parallel workers, then 1
cd /home/user/work; E=/home/user/fenvix-engine-cli/harness/culprit
export CULPRIT_ROUND=4 CULPRIT_RED_BUDGET=64 CULPRIT_WHEEL=$(ls /home/user/work/wheels/detpy-*.whl)
mkdir -p r4/timing
for w in 4 1; do
  for n in pytest pyparsing filelock attrs click faker markdown jsonschema; do
    CULPRIT_WORKERS=$w eng/bin/python $E/round3/refind_b.py --project $n --repo reposb/$n --venv venvsb/$n --period periodv3 \
      --results-dir $E/results --out r4/timing/b-w$w-$n.jsonl --keys-dir keys4t/$n >> r4/timing/log-w$w.txt 2>&1
  done
done
echo TIMING-DONE >> r4/timing/log-w1.txt
