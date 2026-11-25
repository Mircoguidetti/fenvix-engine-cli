#!/usr/bin/env bash
# P2: timed rounds (and optionally the fixed-epoch runs) of one repository, with a checkpoint commit pushed every
# 30 minutes and after every step. Usage:
#   run_rounds.sh ENGINE_CHECKOUT OUT_DIR REPO "1 2 3" [FIXED_LABELS...]
# ENGINE_CHECKOUT: the checkout whose measure.py/detjs/addon run (measure.py runs the engine of its own checkout).
# FIXED_LABELS: fixed-epoch runs after the rounds (fixed_run.py --engine ENGINE_CHECKOUT --label L).
set -u
ENG=$1; OUT=$2; REPO=$3; ROUNDS=$4; shift 4
P2=$(cd "$(dirname "$0")" && pwd); REPOROOT=$(cd "$P2/../.." && pwd)
SPEC=$REPOROOT/harness/parallel_measure/specs.json
export PM_WORK=${PM_WORK:-/root/pm}
checkpoint() {
  ( cd "$REPOROOT" && python3 "$P2/post.py" "$OUT" "$REPO" >/dev/null 2>&1
    git add -A "$OUT" 2>/dev/null
    git commit -q -m "P2 checkpoint: $(basename "$OUT") $REPO ($1)

Claude-Session: https://claude.ai/code/session_01YAF6DhJzRTSxmDKxqkVCm3" -- "$OUT" >/dev/null 2>&1
    for i in 1 2 3 4; do git push -q origin claude/p2-speed 2>/dev/null && break; sleep $((2**i)); done )
}
( while sleep 1800; do checkpoint "30-min"; done ) & TICK=$!
trap 'kill $TICK 2>/dev/null' EXIT
for k in $ROUNDS; do
  echo "== $(date -u +%FT%TZ) $REPO round $k"
  python3 "$ENG/harness/parallel_measure/measure.py" --spec "$SPEC" --name "$REPO" --reps 1 --first-rep "$k" \
    --workers 2,4 --timeout 7200 --out "$OUT"
  echo "measure exit $?"
  checkpoint "round $k"
done
for L in "$@"; do
  echo "== $(date -u +%FT%TZ) $REPO fixed $L"
  python3 "$P2/fixed_run.py" --spec "$SPEC" --name "$REPO" --engine "$ENG" --label "$L" --out "$OUT"
  checkpoint "fixed $L"
done
echo "== $(date -u +%FT%TZ) done"
