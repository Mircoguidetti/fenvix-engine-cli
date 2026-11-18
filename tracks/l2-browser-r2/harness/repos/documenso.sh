# documenso/documenso: Playwright api + license projects against the Remix server on Postgres + Inbucket + MinIO,
# as in .github/workflows/e2e-tests.yml (CI: retries 4, 10 API workers). Known flaky (idle study): 3 API tests
# (ECONNRESET under load) and 1 UI test. The server is started here (CI: start-server-and-test) so that it runs
# under `detjs serve`; NODE_OPTIONS keeps the suite's `--import tsx`.
export NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH=./example/cert.p12 DANGEROUS_BYPASS_RATE_LIMITS=true
PW_DIR=packages/app-tests
PW_ARGS="--project=api --project=license"
PW_ENV="NODE_OPTIONS=--import=tsx NODE_ENV=test"
# Round 2: every run starts from the database as seeded by setup (detjs state, Postgres template copy).
STATE_SPEC=detjs-state.json
STATE_WHERE=outside

setup() {
  cp .env.example .env
  corepack enable npm || true
  npm ci --no-audit
  npm run prisma:generate
  npm run build -w @documenso/remix
  npm run dx:up
  npx playwright install --with-deps chromium
  sleep 5
  npm run prisma:migrate-dev
  npm run prisma:seed
  echo '{"postgres": ["postgres://documenso:password@127.0.0.1:54320/documenso"]}' > detjs-state.json
}

server_start() {  # MODE SEED
  bg_start "$L2_OUT/server.pid" "$L2_OUT/server-$1.log" bash -c "source '$L2_H/lib.sh'; export NODE_ENV=test; detjs_serve $1 ${2:-none} -- npm run start -w @documenso/remix"
  wait_http http://localhost:3000 300
}

server_stop() {
  bg_stop "$L2_OUT/server.pid"
}
