#!/usr/bin/env bash
# One tracked slice (< 2 h) of the B1 harden campaign: runs harden.py for the repositories given, PAR at a time,
# all stopping before BUDGET seconds from the slice start (no new state after it); harden.py resumes where the previous slice stopped (rows per engine commit).
#   campaign.sh <engine-dir> <par> <budget-seconds> repo...
set -u
engine=$1; par=$2; budget=$3; shift 3
here=$(cd "$(dirname "$0")" && pwd)
logdir=/home/runner/work/cacheb/logs; mkdir -p "$logdir"
running=0
deadline=$(( $(date +%s) + budget ))
for repo in "$@"; do
  left=$(( deadline - $(date +%s) )); [ "$left" -lt 600 ] && { echo "$repo: not started (slice budget)"; continue; }
  python3 "$here/harden.py" --repo "$repo" --engine "$engine" --max-seconds "$left" --checkpoint >> "$logdir/$repo.log" 2>&1 &
  running=$((running + 1))
  if [ "$running" -ge "$par" ]; then wait -n; running=$((running - 1)); fi
done
wait
for repo in "$@"; do echo "== $repo"; tail -3 "$logdir/$repo.log"; done
