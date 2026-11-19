#!/bin/sh
# fix round 4: kind c re-run with the round-4 finder. Lanes (lock = mkdir):
#   nocode2 cases from the committed scans (same green/red commits) -> r4/results/c2-<project>.jsonl
#   nocode.py head-to-head scenarios (no-code and data edit, random placement, seeded) -> r4/results/c-final-h2h.jsonl, c-edit.jsonl
cd /home/user/work; WD=/home/user/work
export CULPRIT_RED_BUDGET=${CULPRIT_RED_BUDGET:-64} CULPRIT_D_BUDGET=${CULPRIT_D_BUDGET:-64} CULPRIT_WORKERS=${CULPRIT_WORKERS:-4}
export CULPRIT_WORK=/home/user/work
export CULPRIT_ROUND=4
E=/home/user/fenvix-engine-cli/harness/culprit
W=$(ls /home/user/work/wheels/detpy-*.whl)
mkdir -p r4/locks-c r4/results r4/logs
for lane in anyio flask httpx humanize markupsafe packaging pluggy pytest rich werkzeug \
            flask-dep structlog-dep sqlparse-env boltons-env pygments-env toolz-env click-env \
            flask-data jinja-data werkzeug-data sqlparse-data pygments-data; do
  mkdir r4/locks-c/$lane 2>/dev/null || continue
  case $lane in
    *-*)
      case $lane in *-data) out=r4/results/c-edit-$lane.jsonl;; *) out=r4/results/c-final-$lane.jsonl;; esac
      for d in none tz dep; do
        eng/bin/python $E/nocode.py --scenario $lane --decoy $d --placement random --out $out >> r4/logs/c-$lane.log 2>&1
      done;;
    *)
      url=$(python3 -c "import json;print(json.load(open('$E/round3/c2-repos.json'))['$lane'])")
      scan=$E/results/scans/nocode-$lane.json
      red=$(python3 -c "import json;print(json.load(open('$scan'))['red'])")
      [ -d repos2/$lane ] || git clone -q $url repos2/$lane
      git -C repos2/$lane checkout -q -f $red
      [ -x venvs2/$lane/bin/python ] || eng/bin/python $E/setup_lib.py $WD/repos2/$lane $WD/venvs2/$lane $W >> r4/logs/setup2-$lane.log 2>&1
      eng/bin/python $E/round2/nocode2.py case --scan $scan --project $lane --repo repos2/$lane --venv venvs2/$lane \
        --out r4/results/c2-$lane.jsonl >> r4/logs/c2-$lane.log 2>&1;;
  esac
  echo DONE $lane >> r4/logs/c-lanes.log
done
