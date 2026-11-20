#!/bin/sh
cd /home/user/work
for s in "$@"; do
  for d in none tz dep; do
    /home/user/work/eng/bin/python /home/user/fenvix-engine-cli/harness/culprit/nocode.py --scenario $s --decoy $d --out results/c-final.jsonl
  done
done
