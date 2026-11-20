#!/bin/sh
# fix round 3: round-2 rows move to results/round2/; the round-3 rows of the session machine replace them at the root
W=/home/user/work
R=/home/user/fenvix-engine-cli/harness/culprit/results
mkdir -p $R/round2
for f in $R/a-*.jsonl $R/b-*.jsonl $R/c-final.jsonl $R/c-edit.jsonl $R/summary.json; do
  [ -f $R/round2/$(basename $f) ] || cp $f $R/round2/
done
for f in $W/results3/a-*.jsonl; do cp $f $R/; done                                    # kind a2, re-run
for f in $W/results3/b-*.jsonl; do n=$(basename $f .jsonl | sed 's/^b-//'); [ $n = pytest ] && n=pytest-fx; cp $f $R/b-$n.jsonl; done
cat $W/results3/c-final-*.jsonl $W/results3/c2-*.jsonl > $R/c-final.jsonl              # no-code: head-to-head + added
cat $W/results3/c-edit-*.jsonl > $R/c-edit.jsonl                                       # data-edit commits
cp $W/results/d-r3b.jsonl $R/d.jsonl                                                   # step 4, re-run with red-side check
echo assembled
