#!/bin/sh
# copy the round-2 rows of the session machine into harness/culprit/results/ (round 1 stays in results/round1/)
W=/home/user/work
R=/home/user/fenvix-engine-cli/harness/culprit/results
mkdir -p $R/cases $R/scans
for f in $W/results3/a-*.jsonl; do cp $f $R/; done                       # kind a2, finder re-run (refind.py)
for f in $W/cases2/a2-*.jsonl; do cp $f $R/cases/$(basename $f | sed 's/^a2-/a-/'); done
cp $W/results2/c-edit.jsonl $R/c-edit.jsonl                              # data-edit commits (head-to-head)
cat $W/results2/c-final.jsonl $W/ncout/c2-*.jsonl > $R/c-final.jsonl     # no-code: head-to-head + added
for f in $W/rhout/b-*-cases.jsonl; do cp $f $R/cases/rh-$(basename $f | sed 's/^b-//; s/-cases//'); done
for f in $W/rhout/b-*.jsonl; do case $f in *-cases.jsonl) ;; *) cp $f $R/scans/reverts-$(basename $f | sed 's/^b-//');; esac; done
for f in $W/ncout/scan-*.json; do cp $f $R/scans/nocode-$(basename $f | sed 's/^scan-//'); done
for f in $W/results2/b-*.jsonl; do cp $f $R/; done                      # kind b: real history (finder + bisect)
for f in $W/fxout/f-*-cases.jsonl; do cp $f $R/cases/fix-$(basename $f | sed 's/^f-//; s/-cases//'); done
for f in $W/fxout/f-*.jsonl; do case $f in *-cases.jsonl) ;; *) cp $f $R/scans/fixes-$(basename $f | sed 's/^f-//');; esac; done
cp $W/timing2.jsonl $R/timing-a2.jsonl
cp $R/round1/d.jsonl $R/d.jsonl                                          # step 4, carried over
echo assembled
