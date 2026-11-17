# Helpers sourced by run_repo.sh, study.py (through bash) and every repos/<name>.sh.
# shellcheck shell=bash
# A repos/<name>.sh defines:
#   setup()                  install, build, browsers (once per job)
#   PW_DIR, PW_ARGS          directory where `playwright test` runs, selection arguments
#   reset()                  optional: before every run (clean state)
#   server_start MODE SEED   optional: start the app server outside the runner (MODE plain|det)
#   server_stop              optional
#   PW_ENV                   optional: extra environment for the Playwright run ("A=1 B=2")

# persist NAME VALUE: export now and keep it for the test runs (setup() runs in a subshell)
persist() {
  export "$1=$2"
  printf 'export %s=%q\n' "$1" "$2" >>"$L2_OUT/env.sh"
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

wait_cmd() {  # wait_cmd SECONDS command...
  local t=$1 i; shift
  for ((i = 0; i < t; i++)); do
    "$@" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "wait_cmd: '$*' did not succeed in ${t}s" >&2
  return 1
}

svc_docker() {  # svc_docker NAME IMAGE [docker run args...]
  local name=$1 image=$2; shift 2
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" "$@" "$image" >/dev/null
}

pg_docker() {  # pg_docker NAME PORT IMAGE [extra args...]
  local name=$1 port=$2 image=$3; shift 3
  svc_docker "$name" "$image" -p "$port:5432" "$@"
  wait_cmd 90 docker exec "$name" pg_isready -U postgres
  sleep 2
  wait_cmd 60 docker exec "$name" pg_isready -U postgres
}

# bg_start PIDFILE LOG command...: a server in its own process group (stopped with bg_stop)
bg_start() {
  local pidf=$1 log=$2; shift 2
  setsid "$@" >"$log" 2>&1 < /dev/null &
  echo $! >"$pidf"
}

bg_stop() {  # bg_stop PIDFILE
  local pidf=$1 pid
  [ -f "$pidf" ] || return 0
  pid=$(cat "$pidf")
  kill -TERM -- "-$pid" 2>/dev/null || true
  for _ in $(seq 1 30); do kill -0 -- "-$pid" 2>/dev/null || break; sleep 0.5; done
  kill -KILL -- "-$pid" 2>/dev/null || true
  rm -f "$pidf"
}

# detjs_serve MODE SEED -- command...: the command as is (plain) or under `detjs serve --det` (det)
detjs_serve() {
  local mode=$1 seed=$2; shift 3
  if [ "$mode" = det ]; then
    local opts=(--det)
    [ -n "$seed" ] && [ "$seed" != none ] && opts+=("--det-seed=$seed")
    [ -n "${L2_EPOCH:-}" ] && opts+=("--det-epoch=$L2_EPOCH")
    node "$DETJS_BIN" serve "${opts[@]}" -- "$@"
  else
    "$@"
  fi
}
