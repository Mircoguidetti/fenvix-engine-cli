#!/usr/bin/env bash
# --det entropy across Go toolchains (review R-025b D3b; coordinator: "a test
# that only passes on old Go is not a fix").
#
# For each toolchain: the review's fixture review-r025b-det (go line set to
# that version), N runs of `fenvix-go test --det` (seed 0) through
# GOTOOLCHAIN=<version> (the go command downloads and switches, the path that
# hid fenvix's overlay before the GOROOT fix). Each single-goroutine entropy
# test must have one outcome and one fingerprint across the N runs, and the
# trace must hold every test.
#
#   harness/go/det_entropy_matrix.sh <fenvix-go binary> <runs> go1.22.12 go1.23.12 ...
set -u
bin=$(realpath "$1"); runs=$2; shift 2
here=$(cd "$(dirname "$0")/../.." && pwd)
tests="TestMaphashSeed TestSyncMapRange TestPid TestDevUrandom"
fail=0
for v in "$@"; do
  work=$(mktemp -d)
  cp -r "$here/go/testdata/fixtures/review-r025b-det" "$work/fx"
  short=$(echo "$v" | sed -E 's/^go([0-9]+\.[0-9]+).*/\1/')
  sed -i "s/^go 1\.[0-9.]*/go $short/" "$work/fx/go.mod"
  for r in $(seq 1 "$runs"); do
    (cd "$work/fx" && GOFLAGS= GOTOOLCHAIN=$v "$bin" test --det --det-trace="$work/t$r.jsonl" ./det > "$work/r$r.log" 2>&1)
  done
  python3 - "$v" "$work" "$runs" $tests <<'PY' || fail=1
import json, sys
v, work, runs, tests = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4:]
seen = {t: set() for t in tests}
ok = True
for r in range(1, runs + 1):
    try:
        lines = [json.loads(l) for l in open(f"{work}/t{r}.jsonl")]
    except OSError:
        print(f"{v}: run {r}: no trace"); print(open(f"{work}/r{r}.log").read()[-3000:]); sys.exit(1)
    got = {l["nodeid"].split("::")[-1]: l for l in lines if l.get("type") == "test"}
    head = [l for l in lines if l.get("type") == "header"][0]["meta"]
    for t in tests:
        if t not in got:
            print(f"{v}: run {r}: {t} missing from the trace ({len(got)} tests)"); ok = False
            continue
        seen[t].add((got[t]["outcome"], got[t]["fingerprint"]))
for t in tests:
    status = "ok" if len(seen[t]) == 1 else "VARIES"
    ok &= len(seen[t]) == 1
    print(f"{v} ({head.get('runtime_version')}): {t}: {sorted(o for o, _ in seen[t])} over {runs} runs, {len(seen[t])} (outcome, fingerprint) {status}")
sys.exit(0 if ok else 1)
PY
  grep -h "fenvix-go: --det controls" "$work/r1.log" | cut -c1-120
  rm -rf "$work"
done
exit $fail
