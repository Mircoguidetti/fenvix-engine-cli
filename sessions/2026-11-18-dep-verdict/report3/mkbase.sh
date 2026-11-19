#!/bin/bash
# layout rederive.py expects (results/dv1, dv3, local) built from the REPORT-3 rows: dv14 (Actions, all 10 repositories)
R="$(cd "$(dirname "$0")/../../.." && pwd)/harness/dep_verdict"
B="${1:-/tmp/claude-0/s/base3}"
rm -rf "$B"; mkdir -p "$B/results/dv1" "$B/results/dv3" "$B/results/local"
cp "$R/commits.json" "$B/"
cp "$R"/results/dv14/*.json.gz "$B/results/dv3/"
echo "$B"
