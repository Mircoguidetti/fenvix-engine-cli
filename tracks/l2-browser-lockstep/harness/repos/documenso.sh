# documenso, round 4 (lockstep): round 3's script, plus the database clock on the engine clock. Postgres runs under
# libfaketime with a timestamp file (FAKETIME_TIMESTAMP_FILE, re-read on every call); the app server (detjs serve)
# writes the engine time T into it at every lockstep step (DETJS_LS_DB_CLOCK_FILE, src/pw/server.js), so now() and
# column defaults in the database follow the same clock as the runner, the pages and the server.
# shellcheck source=/dev/null
source "$L2_H3/repos/documenso.sh"

r3_setup() { :; }
eval "$(declare -f setup | sed '1s/setup/r3_setup/')"

DBCLOCK_DIR="${L2_OUT}/dbclock"

setup() {
  r3_setup
  if [ "${L2_DB_CLOCK:-1}" = 1 ]; then
    e5_prepare
    mkdir -p "$DBCLOCK_DIR" && chmod 777 "$DBCLOCK_DIR"
    printf '%s\n' "$(date -u -d "${L2_EPOCH:-2026-01-01T00:00:00Z}" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -u '+%Y-%m-%d %H:%M:%S')" > "$DBCLOCK_DIR/ts"
    chmod 666 "$DBCLOCK_DIR/ts"
    local vol
    vol=$(cat "$L2_OUT/pg-volume")
    docker rm -f database >/dev/null 2>&1 || true
    docker run -d --name database --user postgres -p 54320:5432 -v "$vol:/var/lib/postgresql/data" -v "$DBCLOCK_DIR:/detjs-clock" \
      -e POSTGRES_USER=documenso -e POSTGRES_PASSWORD=password -e POSTGRES_DB=documenso pg-faketime \
      env "LD_PRELOAD=$FAKELIB" FAKETIME_TIMESTAMP_FILE=/detjs-clock/ts FAKETIME_NO_CACHE=1 FAKETIME_DONT_FAKE_MONOTONIC=1 postgres >/dev/null
    wait_cmd 90 docker exec database pg_isready -U documenso
    sleep 2
    docker exec database psql -U documenso -tAc "select now()" | tee "$L2_OUT/pg-now"
    persist L2_DBCLOCK_FILE "$DBCLOCK_DIR/ts"
  fi
}

server_start() {  # MODE SEED
  local pre=""
  if [ -n "${L2_DBCLOCK_FILE:-}" ]; then
    if [ "$1" = det ]; then pre="export DETJS_LS_DB_CLOCK_FILE='$L2_DBCLOCK_FILE';"
    else date -u '+@%Y-%m-%d %H:%M:%S' > "$L2_DBCLOCK_FILE"; fi  # plain runs: the database clock runs in real time
  fi
  bg_start "$L2_OUT/server.pid" "$L2_OUT/server-$1.log" bash -c "source '$L2_H/lib.sh'; export NODE_ENV=test; $pre detjs_serve $1 ${2:-none} -- npm run start -w @documenso/remix"
  wait_http http://localhost:3000 300
}
