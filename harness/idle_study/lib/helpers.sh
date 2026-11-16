# Helpers sourced by run_repo.sh and by every repos/<name>.sh.
# shellcheck shell=bash

# Run a long-lived background service (app server, mail sink, ...) inside the idle_svc cgroup,
# so its CPU is attributed to "services" rather than to the runner.
svc_bg() {
  local log=$1; shift
  ( echo "$BASHPID" | sudo tee /sys/fs/cgroup/idle_svc/cgroup.procs >/dev/null; exec "$@" ) >"$log" 2>&1 &
  echo $! >>"$IDLE_OUT/svc.pids"
}

# persist NAME VALUE: export now and keep it for the test runs (setup() runs in a subshell)
persist() {
  export "$1=$2"
  printf 'export %s=%q\n' "$1" "$2" >>"$IDLE_OUT/env.sh"
}

# wait_http URL [seconds]
wait_http() {
  local url=$1 t=${2:-120} i
  for ((i = 0; i < t; i++)); do
    curl -fs -o /dev/null --max-time 3 "$url" && return 0
    sleep 1
  done
  echo "wait_http: $url did not answer in ${t}s" >&2
  return 1
}

# wait_cmd SECONDS command...   (retry a command once per second)
wait_cmd() {
  local t=$1 i; shift
  for ((i = 0; i < t; i++)); do
    "$@" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "wait_cmd: '$*' did not succeed in ${t}s" >&2
  return 1
}

# GitHub-Actions-style service container: svc_docker NAME IMAGE [docker run args...]
# Ports are published by the caller (-p 5432:5432); health is up to the caller (wait_*).
svc_docker() {
  local name=$1 image=$2; shift 2
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" "$@" "$image" >/dev/null
}

pg_docker() {   # pg_docker NAME PORT IMAGE [extra env args...]
  local name=$1 port=$2 image=$3; shift 3
  svc_docker "$name" "$image" -p "$port:5432" "$@"
  wait_cmd 90 docker exec "$name" pg_isready -U postgres
  sleep 2
  wait_cmd 60 docker exec "$name" pg_isready -U postgres
}

redis_docker() {  # redis_docker NAME PORT [IMAGE]
  svc_docker "$1" "${3:-redis:7}" -p "$2:6379"
  wait_cmd 60 docker exec "$1" redis-cli ping
}

# Playwright: no retries, JUnit into $JUNIT_DIR (appended to the project's own command line)
PW_FLAGS="--retries=0 --reporter=line,junit"
export PLAYWRIGHT_JUNIT_OUTPUT_FILE="${JUNIT_DIR:-/tmp}/playwright.xml"
