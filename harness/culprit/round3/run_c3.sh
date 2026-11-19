#!/bin/sh
# fix round 3: kind c re-run with the fixed finder. Lanes (lock = mkdir):
#   nocode2 cases from the committed scans (same green/red commits) -> results3/c2-<project>.jsonl
#   nocode.py head-to-head scenarios (no-code and data edit, random placement, seeded) -> results3/c-final-h2h.jsonl, c-edit.jsonl
cd /home/user/work; WD=/home/user/work
export CULPRIT_WORK=/home/user/work
E=/home/user/fenvix-engine-cli/harness/culprit
W=$(ls /home/user/work/wheels2/detpy-*.whl)
mkdir -p locks3c results3 logs3
for lane in anyio flask httpx humanize markupsafe packaging pluggy pytest rich werkzeug \
            flask-dep structlog-dep sqlparse-env boltons-env pygments-env toolz-env click-env \
            flask-data jinja-data werkzeug-data sqlparse-data pygments-data; do
  mkdir locks3c/$lane 2>/dev/null || continue
  case $lane in
    *-*)
      case $lane in *-data) out=results3/c-edit-$lane.jsonl;; *) out=results3/c-final-$lane.jsonl;; esac
      for d in none tz dep; do
        eng/bin/python $E/nocode.py --scenario $lane --decoy $d --placement random --out $out >> logs3/c-$lane.log 2>&1
      done;;
    *)
      url=$(python3 -c "import json;print(json.load(open('$E/round3/c2-repos.json'))['$lane'])")
      scan=$E/results/scans/nocode-$lane.json
      red=$(python3 -c "import json;print(json.load(open('$scan'))['red'])")
      [ -d repos2/$lane ] || git clone -q $url repos2/$lane
      git -C repos2/$lane checkout -q -f $red
      [ -x venvs2/$lane/bin/python ] || eng/bin/python $E/setup_lib.py $WD/repos2/$lane $WD/venvs2/$lane $W >> logs3/setup2-$lane.log 2>&1
      eng/bin/python $E/round2/nocode2.py case --scan $scan --project $lane --repo repos2/$lane --venv venvs2/$lane \
        --out results3/c2-$lane.jsonl >> logs3/c2-$lane.log 2>&1;;
  esac
  echo DONE $lane >> logs3/c-lanes.log
done
