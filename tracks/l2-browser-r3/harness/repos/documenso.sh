# documenso, round 3: round 2's script (setup, server, state) plus experiment E5 (review R-011): the database clock
# and the clock of the Node process holding Prisma's Rust query engine under libfaketime.
# shellcheck source=/dev/null
source "$L2_H/repos/documenso.sh"

# E5_FAKETIME (set by exp.py per variant): empty = real clocks; otherwise the FAKETIME value given to Postgres and
# to the app server process (FAKETIME_DONT_FAKE_MONOTONIC=1: timers and the event loop keep real monotonic time).
FAKELIB=/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1

server_start() {  # MODE SEED
  local pre=""
  if [ -n "${E5_FAKETIME:-}" ]; then
    pre="export LD_PRELOAD=$FAKELIB FAKETIME='${E5_FAKETIME}' FAKETIME_DONT_FAKE_MONOTONIC=1 FAKETIME_NO_CACHE=1;"
  fi
  bg_start "$L2_OUT/server.pid" "$L2_OUT/server-$1.log" bash -c "source '$L2_H/lib.sh'; export NODE_ENV=test; $pre detjs_serve $1 ${2:-none} -- npm run start -w @documenso/remix"
  wait_http http://localhost:3000 300
}

e5_prepare() {  # once: libfaketime on the runner and a Postgres 15 image with it
  sudo apt-get install -y -q libfaketime >/dev/null
  printf 'FROM postgres:15\nRUN apt-get update -q && apt-get install -y -q libfaketime && rm -rf /var/lib/apt/lists/*\n' \
    | docker build -q -t pg-faketime - >/dev/null
  docker inspect database --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' >"$L2_OUT/pg-volume"
  test -s "$L2_OUT/pg-volume"
}

e5_db() {  # e5_db [FAKETIME]: restart the database container on the same data volume, with or without libfaketime
  # Round 3 second attempt: LD_PRELOAD only on the postgres command (not the container env, which docker exec and the
  # entrypoint inherit); container logs kept on failure (first attempt: no server, no log).
  local vol img=postgres:15 cmd=(postgres)
  vol=$(cat "$L2_OUT/pg-volume")
  if [ -n "${1:-}" ]; then
    img=pg-faketime
    cmd=(env "LD_PRELOAD=$FAKELIB" "FAKETIME=$1" FAKETIME_DONT_FAKE_MONOTONIC=1 FAKETIME_NO_CACHE=1 postgres)
  fi
  docker rm -f database >/dev/null 2>&1 || true
  docker run -d --name database -p 54320:5432 -v "$vol:/var/lib/postgresql/data" \
    -e POSTGRES_USER=documenso -e POSTGRES_PASSWORD=password -e POSTGRES_DB=documenso "$img" "${cmd[@]}" >/dev/null
  if ! wait_cmd 90 docker exec database pg_isready -U documenso; then
    docker ps -a --filter name=database
    docker logs database 2>&1 | tail -40
    return 1
  fi
  sleep 2
  docker exec database psql -U documenso -tAc "select now(), clock_timestamp()" | tee "$L2_OUT/pg-now"
}
