#!/bin/sh
# round 2, kind c (Python): no-code scenarios -> results2/c-final.jsonl, data edits (random position) -> results2/c-edit.jsonl
cd /home/user/work
export CULPRIT_WHEEL=/home/user/work/wheels/detpy-0.1.0-cp39-abi3-manylinux_2_34_x86_64.whl
E=/home/user/fenvix-engine-cli/harness/culprit
for s in "$@"; do
  case $s in *-data) out=results2/c-edit.jsonl;; *) out=results2/c-final.jsonl;; esac
  for d in none tz dep; do
    eng/bin/python $E/nocode.py --scenario $s --decoy $d --placement random --out $out
  done
done
echo LANE DONE "$@"
