#!/bin/bash
# layout rederive.py expects (results/dv1, dv3, local) built from the REPORT-2 rows: dv6 + dv7 (Actions), local5 (container)
R=/home/user/fenvix-engine-cli/harness/dep_verdict
B=/tmp/claude-0/s/base2
rm -rf "$B"; mkdir -p "$B/results/dv1" "$B/results/dv3" "$B/results/local"
cp "$R/commits.json" "$B/"
for f in "$R"/results/dv6/*.json.gz "$R"/results/dv7/*.json.gz; do cp "$f" "$B/results/dv3/"; done
for f in "$R"/results/local5/*.json.gz; do cp "$f" "$B/results/local/"; done
