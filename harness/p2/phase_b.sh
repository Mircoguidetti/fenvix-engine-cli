#!/usr/bin/env bash
# P2 Phase B runs of one repository (PREREG section 6, gate note 3): through fixed_run.py with the branch engine,
# out harness/p2/data/phaseB/<repo>. 1) CPU profile (--cpu-prof; it also warms the page cache, as the timed rounds 2-3
# are warm); 2) DETJS_PHASES=1 (passed with --env, never exported), trace phases-<repo>.jsonl. Each followed by its summary JSON and a checkpoint commit pushed.
#   phase_b.sh ENGINE_CHECKOUT REPO WORKERS
set -u
ENG=$1; REPO=$2; W=$3
P2=$(cd "$(dirname "$0")" && pwd); REPOROOT=$(cd "$P2/../.." && pwd)
SPEC=$REPOROOT/harness/parallel_measure/specs.json
OUT=${PHASEB_OUT:-$REPOROOT/harness/p2/data/phaseB}; D=$OUT/$REPO  # PHASEB_OUT: another out dir (P2 C6)
export PM_WORK=${PM_WORK:-/root/pm}
checkpoint() {
  ( cd "$REPOROOT" && git add -A "$OUT" 2>/dev/null
    git commit -q -m "P2 checkpoint: phaseB $REPO ($1)

Claude-Session: https://claude.ai/code/session_01YAF6DhJzRTSxmDKxqkVCm3" -- "$OUT" >/dev/null 2>&1
    for i in 1 2 3 4; do git push -q origin claude/p2-speed 2>/dev/null && break; sleep $((2**i)); done )
}
( while sleep 1800; do checkpoint "30-min"; done ) & TICK=$!
trap 'kill $TICK 2>/dev/null' EXIT
echo "== $(date -u +%FT%TZ) $REPO cpuprof w$W"
rm -rf "$D/cpuprof"; mkdir -p "$D/cpuprof"
python3 "$P2/fixed_run.py" --spec "$SPEC" --name "$REPO" --engine "$ENG" --label cpuprof --workers "$W" \
  --trace-name "cpuprof-$REPO.jsonl" --node-options "--cpu-prof --cpu-prof-dir=$D/cpuprof" --no-events --out "$OUT"
python3 "$P2/phases_summary.py" cpuprof "$D/cpuprof" "$D/cpuprof-summary.json" --top 40 >/dev/null
echo "summary exit $?"
checkpoint "cpuprof"
echo "== $(date -u +%FT%TZ) $REPO phases w$W"
python3 "$P2/fixed_run.py" --spec "$SPEC" --name "$REPO" --engine "$ENG" --label phases --workers "$W" \
  --trace-name "phases-$REPO.jsonl" --env DETJS_PHASES=1 --no-events --out "$OUT"
python3 "$P2/phases_summary.py" phases "$D/phases-$REPO.jsonl.phases.jsonl" "$D/phases-summary.json" >/dev/null
echo "summary exit $?"
checkpoint "phases"
echo "== $(date -u +%FT%TZ) done"
