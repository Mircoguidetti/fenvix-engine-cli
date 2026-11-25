#!/usr/bin/env bash
# B1 exit criterion: the engine's suites on a tree, as release-1.yml runs them (LIGHT: Python 3.13 `shared` files,
# Node full suite, attacks, cargo go-live crates), serially, on this container. Run once on release-1 6e79a62 and
# once on the B1 head; the failing-test lists of the two logs (node: "✖ failing tests", python: FAILED/ERROR lines,
# attacks: its summary) are compared by hand in data/suites/*.txt.
#   suites.sh <tree> <out-dir> <part: cargo|node|python|attacks>
set -u
tree=$1; out=$2; part=$3
mkdir -p "$out"
venv=/home/runner/work/venv-detpy
export PATH="/opt/node24/bin:$PATH"   # CI's LIGHT Node version
cd "$tree"
case "$part" in
  cargo)
    cargo test -p detpy-core -p detpy-node > "$out/cargo.log" 2>&1; echo "cargo rc=$?" | tee "$out/cargo.rc" ;;
  node)
    (cd node && node --test --test-concurrency=1 --test-reporter=spec --test-reporter-destination=stdout \
      --test-reporter=junit --test-reporter-destination="$out/node.xml" test/*.test.js > "$out/node.log" 2>&1
     echo "node rc=$?" | tee "$out/node.rc") ;;
  python)
    cp "$($venv/bin/python -c 'import detpy._core as c; print(c.__file__)')" python/detpy/
    files=$(for s in 0 1 2 3; do $venv/bin/python release/shard.py 4 $s tests 'test_*.py' '**/test_*.py' '*_test.py' '**/*_test.py' --only shared release/python-tests.txt; done)
    $venv/bin/python -m pytest -q -p no:randomly --junitxml="$out/python.xml" $files \
      --deselect tests/test_review_r017.py::test_h2_report_says_ci_never_sees_tmp_name_exhaustion_but_p8_does -rfE > "$out/python.log" 2>&1
    echo "python rc=$?" | tee "$out/python.rc" ;;
  attacks)
    cp "$($venv/bin/python -c 'import detpy._core as c; print(c.__file__)')" python/detpy/
    PATH="$venv/bin:$PATH" python3 tests/attacks.py > "$out/attacks.log" 2>&1; echo "attacks rc=$?" | tee "$out/attacks.rc" ;;
esac
