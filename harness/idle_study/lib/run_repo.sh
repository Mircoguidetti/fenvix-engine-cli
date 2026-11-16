#!/bin/bash
# Idle-share and baseline-flakiness study: one repository.
#   run_repo.sh NAME
# Reads harness/idle_study/repos.json (repo, ref, ...) and repos/NAME.sh (setup / reset / run_tests).
# Writes harness/idle_study/results/NAME.json.
set -uo pipefail

NAME=$1
IS=$(cd "$(dirname "$0")/.." && pwd)
CFG="$IS/repos/$NAME.sh"
export IDLE_OUT="${RUNNER_TEMP:-/tmp}/idle_out/$NAME"
RESULT="$IS/results/$NAME.json"
W="${RUNNER_TEMP:-/tmp}/target"
RUNS=${RUNS_OVERRIDE:-$(jq -r --arg n "$NAME" '.[$n].runs // 6' "$IS/repos.json")}
REPO=$(jq -r --arg n "$NAME" '.[$n].repo' "$IS/repos.json")
REF=$(jq -r --arg n "$NAME" '.[$n].ref' "$IS/repos.json")
BUDGET_S=$(( ${BUDGET_MIN:-280} * 60 ))
RUN_TIMEOUT_MIN=${RUN_TIMEOUT_MIN:-$(jq -r --arg n "$NAME" '.[$n].run_timeout_min // 60' "$IS/repos.json")}
JOB_T0=$(date +%s)
mkdir -p "$IDLE_OUT" "$IS/results"
: >"$IDLE_OUT/svc.pids"

sudo mkdir -p /sys/fs/cgroup/idle_test /sys/fs/cgroup/idle_svc

# shellcheck source=/dev/null
source "$IS/lib/helpers.sh"
reset() { :; }
# shellcheck source=/dev/null
source "$CFG"

write_meta() {  # write_meta STATUS
  jq -n --arg name "$NAME" --arg repo "$REPO" --arg ref "$REF" --arg status "$1" \
    --argjson setup_s "${SETUP_S:-null}" \
    --arg runner "$(nproc) vCPU, $(free -g | awk '/Mem:/{print $2}') GiB, $(. /etc/os-release; echo "$PRETTY_NAME")" \
    --slurpfile cfg <(jq --arg n "$NAME" '.[$n]' "$IS/repos.json") \
    '{name:$name, repo:$repo, ref:$ref, status:$status, setup_s:$setup_s, runner:$runner, config:$cfg[0],
      run_id: env.GITHUB_RUN_ID, measured_at: (now|todate)}' >"$IDLE_OUT/meta.json"
}

echo "::group::clone $REPO@$REF"
git clone -q --filter=blob:none --no-checkout "https://github.com/$REPO.git" "$W" && git -C "$W" checkout -q "$REF"
if [ "$(jq -r --arg n "$NAME" '.[$n].submodules // false' "$IS/repos.json")" = true ]; then
  git -C "$W" submodule update --init --recursive --depth 1 -q
fi
echo "::endgroup::"
cd "$W" || exit 1

echo "::group::setup"
T=$(date +%s)
( set -e; setup ) 2>&1 | tee "$IDLE_OUT/setup.log"
rc=${PIPESTATUS[0]}
# setup() runs in a subshell above so a failing step stops it; re-source exports it declared
[ -f "$IDLE_OUT/env.sh" ] && source "$IDLE_OUT/env.sh"
SETUP_S=$(( $(date +%s) - T ))
echo "::endgroup::"
if [ "$rc" != 0 ]; then
  echo "setup failed rc=$rc"
  for f in "$IDLE_OUT"/*.log; do
    case "$f" in */setup.log) continue ;; esac
    { echo "----- $(basename "$f")"; tail -n 40 "$f"; } >>"$IDLE_OUT/setup.log"
  done
  { echo "----- docker ps -a"; docker ps -a --format '{{.Names}} {{.Status}}'; } >>"$IDLE_OUT/setup.log" 2>&1
  write_meta setup_failed
  python3 "$IS/lib/summarize.py" "$IDLE_OUT" "$IDLE_OUT/meta.json" "$RESULT"
  exit 0
fi

sampler_start() {  # sampler_start OUT.json
  rm -f "$1" "$1.pid"
  sudo python3 "$IS/lib/sampler.py" "$1" 0.5 &
  SP=$!
  for _ in $(seq 1 50); do [ -s "$1.pid" ] && break; sleep 0.1; done
}
sampler_stop() {  # sampler_stop OUT.json
  sudo kill -TERM "$(cat "$1.pid")" 2>/dev/null
  wait "$SP" 2>/dev/null
  for _ in $(seq 1 20); do [ -f "$1" ] && break; sleep 0.5; done
}

# baseline: services up and idle, nothing else running
sleep 5
sampler_start "$IDLE_OUT/baseline.json"
sleep 20
sampler_stop "$IDLE_OUT/baseline.json"

for ((i = 1; i <= RUNS; i++)); do
  if (( $(date +%s) - JOB_T0 > BUDGET_S )); then echo "time budget reached after $((i-1)) runs"; break; fi
  RD="$IDLE_OUT/run$i"; mkdir -p "$RD/junit"
  export JUNIT_DIR="$RD/junit"
  export PLAYWRIGHT_JUNIT_OUTPUT_FILE="$JUNIT_DIR/playwright.xml"
  if [ "$i" -gt 1 ]; then
    echo "::group::reset before run $i"
    ( set -e; reset ) >>"$IDLE_OUT/reset.log" 2>&1 || echo "reset rc=$? (continuing)"
    tail -5 "$IDLE_OUT/reset.log"
    echo "::endgroup::"
  fi
  echo "::group::run $i/$RUNS"
  sampler_start "$RD/sampler.json"
  sleep 0.6
  T0=$(date +%s.%N)
  (
    me=$BASHPID   # (inside a pipeline $BASHPID would be the pipeline child's pid)
    echo "$me" | sudo tee /sys/fs/cgroup/idle_test/cgroup.procs >/dev/null 2>"$RD/cg.err"
    { echo "tee_rc=$? pid=$me"; cat /proc/self/cgroup; cat "$RD/cg.err"; } >"$RD/cg.txt" 2>&1
    exec timeout -k 30 "${RUN_TIMEOUT_MIN}m" bash -c "set -o pipefail; source '$IS/lib/helpers.sh'; source '$CFG'; export PLAYWRIGHT_JUNIT_OUTPUT_FILE='$JUNIT_DIR/playwright.xml'; cd '$W'; run_tests"
  ) >"$RD/test.log" 2>&1
  rc=$?
  T1=$(date +%s.%N)
  sampler_stop "$RD/sampler.json"
  tail -15 "$RD/test.log"
  python3 "$IS/lib/parse_tests.py" "$(jq -r --arg n "$NAME" '.[$n].parser // "junit"' "$IS/repos.json")" "$JUNIT_DIR" "$RD/test.log" "$RD/tests.json"
  jq -n --argjson rc "$rc" --argjson w "$(python3 -c "print(round($T1 - $T0, 3))")" '{rc:$rc, wall_s:$w}' >"$RD/meta.json"
  echo "run $i: rc=$rc wall=$(jq .wall_s "$RD/meta.json")s"
  echo "::endgroup::"
done

write_meta ok
python3 "$IS/lib/summarize.py" "$IDLE_OUT" "$IDLE_OUT/meta.json" "$RESULT"
