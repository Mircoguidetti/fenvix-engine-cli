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
[ -f $W/results2/b.jsonl ] && cp $W/results2/b.jsonl $R/b-reverts.jsonl
cp $R/round1/d.jsonl $R/d.jsonl                                          # step 4, carried over
echo assembled
