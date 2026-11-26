#!/usr/bin/env bash
# P3 step B driver: run ladder.py file for every case file of a repository, skipping files whose B record exists.
# Resumable; stops cleanly when the deadline (seconds from start, default 6600) leaves less than MIN_LEFT seconds.
#   PM_WORK=/tmp/pm-p3 bash harness/p3_flips/run_b.sh <repo> [budget_s]
# Reusable from any checkout: paths come from PM_WORK (work tree: repos/, find/, logs/) and this script's directory
# (records go to <script dir>/data/<repo>/b/). The repo must have a `pins.py find` directory under $PM_WORK/find.
set -u
repo=$1
budget=${2:-6600}
min_left=${MIN_LEFT:-900}
here=$(cd "$(dirname "$0")" && pwd)
start=$(date +%s)
work=${PM_WORK:?set PM_WORK}
mkdir -p "$work/logs"
log=$work/logs/b-$repo.log
python3 "$here/ladder.py" files --repo "$repo" --find "$work/find" | while read -r f; do
  slug=$(python3 -c "import hashlib,sys;print(hashlib.sha1(f'$repo:{sys.argv[1]}'.encode()).hexdigest()[:10])" "$f")
  rec="$here/data/$repo/b/$slug.json"
  if [ -f "$rec" ] && python3 -c "import json,sys;sys.exit(0 if json.load(open(sys.argv[1])).get('complete') else 1)" "$rec"; then
    echo "skip $f"; continue
  fi
  left=$(( budget - ($(date +%s) - start) ))
  if [ "$left" -lt "$min_left" ]; then echo "STOP budget ($left s left) before $f"; break; fi
  echo "== $f $(date -u +%T)"
  timeout "$((left - 60))" python3 "$here/ladder.py" file --repo "$repo" --find "$work/find" --file "$f" >> "$log" 2>&1 < /dev/null
  rc=$?
  echo "   exit $rc $(date -u +%T)"
  if [ "$rc" -ne 0 ]; then
    echo "   (record incomplete; a rerun resumes this file)"
    pkill -9 -f 'vitest/dist/workers' 2>/dev/null  # orphans of a killed run would load the next one
  fi
done
