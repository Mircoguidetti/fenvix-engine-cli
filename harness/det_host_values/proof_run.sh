#!/usr/bin/env bash
# Step 3 proof: one repository, trunk engine then branch engine, back to back on this machine.
#   PM_WORK=/tmp/pm-hv bash harness/det_host_values/proof_run.sh <repo> <out dir>
# The trunk checkout (TRUNK, default /tmp/fenvix-trunk, f67be4a3 built there) carries this branch's
# harness/parallel_measure (RERUN.md section 1, "+modified": measure.py runs the engine of the checkout it lives in).
set -u
repo=$1; out=$2; TRUNK=${TRUNK:-/tmp/fenvix-trunk}; BRANCH=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "$out"
for e in trunk branch; do
  root=$TRUNK; [ $e = branch ] && root=$BRANCH
  echo "== $repo $e $(git -C $root rev-parse HEAD) $(date -u +%FT%TZ)" >> "$out/proof_run.log"
  ( cd $root && python3 harness/parallel_measure/measure.py --spec harness/parallel_measure/specs.json --name "$repo" \
      --reps 1 --workers "$(nproc)" --skip bare,plain_par --out "$out/$e" ) >> "$out/proof_run.log" 2>&1
  echo "exit $? $(date -u +%FT%TZ)" >> "$out/proof_run.log"
done
