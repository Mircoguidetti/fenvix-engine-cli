#!/bin/bash
# Level 2 browser round 4 (lockstep), one gate/measurement job for one repository: clone at the pinned commit, setup(), exp.py.
#   run_exp.sh JOB NAME      (env: DETJS_BIN = path of detjs's bin/detjs.js)
# Writes tracks/l2-browser-r3/results/JOB-NAME.json. Repository scripts: harness/repos/NAME.sh, else round 2's.
set -uo pipefail

JOB=$1 NAME=$2
H4=$(cd "$(dirname "$0")" && pwd); H3="$H4/../../l2-browser-r3/harness"
export L2_H="$H3/../../l2-browser-r2/harness" L2_H3="$H3"
export L2_OUT="${RUNNER_TEMP:-/tmp}/l2_out/$JOB-$NAME"
export L2_WORK="${RUNNER_TEMP:-/tmp}/l2_target"
export L2_RESULT="$H4/../results/$JOB-$NAME.json"
mkdir -p "$L2_OUT" "$(dirname "$L2_RESULT")"
: >"$L2_OUT/env.sh"
SCRIPT="$H4/repos/$NAME.sh"; [ -f "$SCRIPT" ] || SCRIPT="$H3/repos/$NAME.sh"; [ -f "$SCRIPT" ] || SCRIPT="$L2_H/repos/$NAME.sh"
REPO=$(jq -s -r --arg n "$NAME" '(.[0] * .[1] * .[2])[$n].repo' "$L2_H/repos.json" "$H3/repos.json" "$H4/repos.json")
REF=$(jq -s -r --arg n "$NAME" '(.[0] * .[1] * .[2])[$n].ref' "$L2_H/repos.json" "$H3/repos.json" "$H4/repos.json")

fail() {  # fail STATUS LOG
  jq -n --arg n "$NAME" --arg j "$JOB" --arg repo "$REPO" --arg ref "$REF" --arg s "$1" --rawfile log <(tail -c 6000 "$2" 2>/dev/null || true) \
    '{name:$n, job:$j, repo:$repo, ref:$ref, status:$s, log_tail:$log, run_id: env.GITHUB_RUN_ID}' >"$L2_RESULT"
  exit 0
}

echo "::group::clone $REPO@$REF"
git clone -q --filter=blob:none --no-checkout "https://github.com/$REPO.git" "$L2_WORK" && git -C "$L2_WORK" checkout -q "$REF" \
  || { echo "clone failed" >"$L2_OUT/setup.log"; fail clone_failed "$L2_OUT/setup.log"; }
echo "::endgroup::"
cd "$L2_WORK" || exit 1

echo "::group::setup"
T=$(date +%s)
# shellcheck source=/dev/null
( set -e; source "$L2_H/lib.sh"; source "$SCRIPT"; setup ) 2>&1 | tee "$L2_OUT/setup.log"
rc=${PIPESTATUS[0]}
echo "::endgroup::"
export L2_SETUP_S=$(( $(date +%s) - T ))
[ "$rc" = 0 ] || fail setup_failed "$L2_OUT/setup.log"

python3 "$H4/gate.py" "$JOB" "$NAME" || fail exp_crashed "$L2_OUT/exp.log"
