#!/bin/sh
# clean timing: 2 planted cases per library (one short, one long distance), finder + bisect, one at a time, idle host
cd /home/user/work
mkdir -p cases/timing
for n in sqlparse toolz more-itertools boltons marshmallow structlog jinja click arrow attrs; do
  python3 - "$n" <<'PY'
import json,sys
n=sys.argv[1]
try: L=[json.loads(l) for l in open(f'cases/a-{n}.jsonl')]
except OSError: L=[]
L.sort(key=lambda c:c['k'])
pick=[L[0],L[-1]] if len(L)>1 else L
open(f'cases/timing/{n}.jsonl','w').writelines(json.dumps(c)+'\n' for c in pick)
PY
  /home/user/work/eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/run_code_cases.py --cases cases/timing/$n.jsonl --repo repos/$n --venv venvs/$n --out results/timing-a.jsonl --keys-dir keys-timing/$n
done
echo TIMINGDONE
