#!/bin/sh
# fix round 5: round-4 rows move to results/round4/; round-5 rows (a2, b, c) replace them at the root. Step 4 (d.jsonl)
# stays: orderdep.py does not use key validity and is unchanged since round 4.
W=/home/user/work/r5/results
R=/home/user/fenvix-engine-cli/harness/culprit/results
mkdir -p $R/round4
for f in $R/a-*.jsonl $R/b-*.jsonl $R/c-final.jsonl $R/c-edit.jsonl $R/d.jsonl $R/summary.json $R/summary4.json; do
  [ -f $R/round4/$(basename $f) ] || cp $f $R/round4/
done
for f in $W/a-*.jsonl; do cp $f $R/; done
for f in $W/b-*.jsonl; do n=$(basename $f .jsonl | sed 's/^b-//'); [ $n = pytest ] && n=pytest-fx; cp $f $R/b-$n.jsonl; done
cat $W/c-final-*.jsonl $W/c2-*.jsonl > $R/c-final.jsonl
cat $W/c-edit-*.jsonl > $R/c-edit.jsonl
echo assembled
