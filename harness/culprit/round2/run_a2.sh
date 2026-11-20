#!/bin/sh
# one library: round-2 cases (placed + reland) from the round-1 mutation sites, then keys, finder and git bisect
n=$1
cd /home/user/work
E=/home/user/fenvix-engine-cli/harness/culprit
eng/bin/python $E/round2/placed.py --cases $E/results/round1/cases/a-$n.jsonl --repo repos/$n --venv venvs/$n --out cases2/a2-$n.jsonl > logs-a2-gen-$n.txt 2>&1
eng/bin/python $E/run_code_cases.py --cases cases2/a2-$n.jsonl --repo repos/$n --venv venvs/$n --out results2/a2-$n.jsonl --keys-dir keys2/$n > logs-a2-run-$n.txt 2>&1
echo DONE $n
