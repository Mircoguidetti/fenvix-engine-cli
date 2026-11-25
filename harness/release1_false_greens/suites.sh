#!/usr/bin/env bash
# Suites of the release1-false-greens spec (Phase A step 0 baseline, acceptance 6 final comparison).
# Usage: harness/release1_false_greens/suites.sh <tree> <outdir> [part...]
#   parts: cargo node py0 py1 py2 py3 attacks-py attacks-node (default: all)
# Python shards: the command of .github/workflows/release-1.yml (job `python`, step "Python suites and reviewer test
# files") in FULL mode (every file, not only `shared`), serial inside the shard. The shard-0 extra suites (runners,
# numpy, hypothesis environments) are not run. Node: the command of the `node` job, all files in one run per shard.
set -u
tree=$(cd "$1" && pwd); out=$(mkdir -p "$2" && cd "$2" && pwd); shift 2
parts=${*:-"cargo node py0 py1 py2 py3 attacks-py attacks-node"}
cd "$tree"
echo "tree $tree sha $(git rev-parse HEAD)" > "$out/sha.txt"
for p in $parts; do
  start=$(date +%s)
  case $p in
    cargo)
      cargo test -p detpy-core -p detpy-node > "$out/cargo.log" 2>&1; rc=$?
      grep -E "^test .* FAILED|panicked" "$out/cargo.log" | sort -u > "$out/cargo.failures" ;;
    node)
      rc=0; : > "$out/node.failures"
      for s in 0 1 2 3; do
        files=$(cd node && python3 ../release/shard.py 4 $s . 'test/*.test.js')
        (cd node && node --test --test-concurrency=1 --test-reporter=spec --test-reporter-destination=stdout $files) > "$out/node-s$s.log" 2>&1 || rc=1
        sed -n '/^✖ failing tests:/,$p' "$out/node-s$s.log" | grep -E "^(test at|✖)" | grep -v "failing tests" >> "$out/node.failures"
      done ;;
    py[0-3])
      s=${p#py}
      files=$(python3 release/shard.py 4 $s tests 'test_*.py' '**/test_*.py' '*_test.py' '**/*_test.py')
      python3 -m pytest -q -p no:randomly $files \
        --deselect tests/test_review_r017.py::test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does \
        -rfE > "$out/py-s$s.log" 2>&1; rc=$?
      grep -E "^(FAILED|ERROR) " "$out/py-s$s.log" | sed 's/ - .*//' | sort -u > "$out/py-s$s.failures" ;;
    attacks-py)
      python3 tests/attacks.py --only python > "$out/attacks-py.log" 2>&1; rc=$?
      grep -E "^(FAILED|ERROR) " "$out/attacks-py.log" | sed 's/ - .*//' | sort -u > "$out/attacks-py.failures" ;;
    attacks-node)
      python3 tests/attacks.py --only node > "$out/attacks-node.log" 2>&1; rc=$?
      grep -E "^✖ " "$out/attacks-node.log" | sort -u > "$out/attacks-node.failures" ;;
    *) echo "unknown part $p"; rc=2 ;;
  esac
  echo "$p rc=$rc $(( $(date +%s) - start ))s" | tee -a "$out/summary.txt"
done
