#!/bin/bash
# Level 2 browser study, one repository: clone at the pinned commit, setup(), then study.py.
#   run_repo.sh NAME      (env: DETJS_BIN = path of detjs's bin/detjs.js)
# Writes tracks/l2-browser-r2/results/NAME.json.
set -uo pipefail

NAME=$1
export L2_H=$(cd "$(dirname "$0")" && pwd)
export L2_OUT="${RUNNER_TEMP:-/tmp}/l2_out/$NAME"
export L2_WORK="${RUNNER_TEMP:-/tmp}/l2_target"
export L2_RESULT="$L2_H/../results/$NAME.json"
mkdir -p "$L2_OUT" "$(dirname "$L2_RESULT")"
: >"$L2_OUT/env.sh"
REPO=$(jq -r --arg n "$NAME" '.[$n].repo' "$L2_H/repos.json")
REF=$(jq -r --arg n "$NAME" '.[$n].ref' "$L2_H/repos.json")

fail() {  # fail STATUS LOG
  jq -n --arg n "$NAME" --arg repo "$REPO" --arg ref "$REF" --arg s "$1" --rawfile log <(tail -c 6000 "$2" 2>/dev/null || true) \
    '{name:$n, repo:$repo, ref:$ref, status:$s, log_tail:$log, run_id: env.GITHUB_RUN_ID}' >"$L2_RESULT"
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
( set -e; source "$L2_H/lib.sh"; source "$L2_H/repos/$NAME.sh"; setup ) 2>&1 | tee "$L2_OUT/setup.log"
rc=${PIPESTATUS[0]}
echo "::endgroup::"
export L2_SETUP_S=$(( $(date +%s) - T ))
[ "$rc" = 0 ] || fail setup_failed "$L2_OUT/setup.log"

python3 "$L2_H/study.py" "$NAME" || fail study_crashed "$L2_OUT/study.log"
