#!/usr/bin/env bash
# P2 C4 paired measure on one boot: per repository, the fix-1 engine (before) then the head engine (after), each
# with its rounds and fixed-epoch runs (run_rounds.sh). Usage: c4_pair.sh "REPO..." "ROUNDS" [before|after|both] [fixed]
set -u
P2=$(cd "$(dirname "$0")" && pwd); D=$P2/data
REPOS=$1; ROUNDS=$2; SIDE=${3:-both}; FIXED=${4:-fixed}
clean() { pkill -f vitest; pkill -f jest-worker; pkill -f 'bin/jest'; true; }
for r in $REPOS; do
  if [ "$SIDE" != after ]; then
    if [ "$FIXED" = fixed ]; then "$P2/run_rounds.sh" /home/user/fx-fix1 "$D/fix1-c" "$r" "$ROUNDS" fix1c; else "$P2/run_rounds.sh" /home/user/fx-fix1 "$D/fix1-c" "$r" "$ROUNDS"; fi
    clean
  fi
  if [ "$SIDE" != before ]; then
    if [ "$FIXED" = fixed ]; then "$P2/run_rounds.sh" /home/user/fx-fix2 "$D/fix-2" "$r" "$ROUNDS" fix2 fix2r; else "$P2/run_rounds.sh" /home/user/fx-fix2 "$D/fix-2" "$r" "$ROUNDS"; fi
    clean
  fi
done
echo "c4_pair done: $REPOS / $ROUNDS / $SIDE / $FIXED"
