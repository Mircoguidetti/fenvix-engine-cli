#!/bin/sh
# fix round 4: round-3 rows move to results/round3/; the round-4 rows of the session machine replace them at the root
W=/home/user/work/r4/results
R=/home/user/fenvix-engine-cli/harness/culprit/results
mkdir -p $R/round3
for f in $R/a-*.jsonl $R/b-*.jsonl $R/c-final.jsonl $R/c-edit.jsonl $R/d.jsonl $R/summary.json; do
  [ -f $R/round3/$(basename $f) ] || cp $f $R/round3/
done
for f in $W/a-*.jsonl; do cp $f $R/; done
for f in $W/b-*.jsonl; do n=$(basename $f .jsonl | sed 's/^b-//'); [ $n = pytest ] && n=pytest-fx; cp $f $R/b-$n.jsonl; done
cat $W/c-final-*.jsonl $W/c2-*.jsonl > $R/c-final.jsonl
cat $W/c-edit-*.jsonl > $R/c-edit.jsonl
cp $W/d-r4.jsonl $R/d.jsonl
echo assembled
