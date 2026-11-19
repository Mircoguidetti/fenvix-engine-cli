#!/bin/sh
# one library: generate planted-regression cases, then run finder and bisect on them (both resumable)
n=$1
cd /home/user/work
KS=5,7,10,13,16,20,25,30,38,45,55,65,80,95,110,125,140,160,180,200
/home/user/work/eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/mutants.py --repo repos/$n --venv venvs/$n --name $n --ks $KS --out cases/a-$n.jsonl
/home/user/work/eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/run_code_cases.py --cases cases/a-$n.jsonl --repo repos/$n --venv venvs/$n --out results/a-$n.jsonl --keys-dir keys/$n
echo DONE $n
