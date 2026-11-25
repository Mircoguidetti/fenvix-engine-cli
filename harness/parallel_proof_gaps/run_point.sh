#!/usr/bin/env bash
# Step M of spec parallel-proof-gaps: one measurement point on the 9 pool repositories.
#   run_point.sh ENGINE_CHECKOUT OUT_DIR [repo ...]
# ENGINE_CHECKOUT: the checkout whose measure.py / detjs run (measure.py runs the engine of its own checkout).
# Per repository: measure.py --reps 1 --workers 2,4 (as P2's Phase A), phases plain and plain_par skipped (the
# runner alone, no engine: the same at every point); serial + parallel w2/w4 + fenvix verify.
set -u
ENG=$1; OUT=$2; shift 2
export PM_WORK=${PM_WORK:-/root/pm}
SPEC=$(cd "$(dirname "$0")/../parallel_measure" && pwd)/specs.json
repos=("$@"); [ ${#repos[@]} -eq 0 ] && repos=(nestjs-pino agentsys alakajam agentlang yalc ironcurtain codex-multi-auth drydock lerna-lite)
mkdir -p "$OUT"
for r in "${repos[@]}"; do
  echo "== $(date -u +%FT%TZ) $r"
  python3 "$ENG/harness/parallel_measure/measure.py" --spec "$SPEC" --name "$r" --reps 1 --workers 2,4 \
    --skip plain,plain_par --timeout 3600 --out "$OUT"
  echo "measure exit $?"
done
echo "== $(date -u +%FT%TZ) done"
