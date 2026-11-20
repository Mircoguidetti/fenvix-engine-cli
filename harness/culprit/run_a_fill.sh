#!/bin/sh
# fill pass: libraries with fewer than 20 planted cases get extra distances (the old end of the window often cannot
# run in today's environment); then finder and bisect on the new cases
n=$1
cd /home/user/work
KS=6,8,11,14,18,22,27,33,40,48,57,67,75,85,90,9,12,24,35,52
have=$(grep -c . cases/a-$n.jsonl 2>/dev/null || echo 0)
if [ "$have" -lt 20 ]; then
  /home/user/work/eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/mutants.py --repo repos/$n --venv venvs/$n --name $n --ks $KS --out cases/a-$n.jsonl --max-cases 20 --tag f
fi
/home/user/work/eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/run_code_cases.py --cases cases/a-$n.jsonl --repo repos/$n --venv venvs/$n --out results/a-$n.jsonl --keys-dir keys/$n
echo FILLDONE $n
