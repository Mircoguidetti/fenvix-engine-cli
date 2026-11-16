# getredash/redash: frontend e2e (Playwright) against the compose stack, as in .github/workflows/ci.yml job frontend-e2e-tests
export COMPOSE_FILE=.ci/compose.e2e.yaml COMPOSE_PROJECT_NAME=e2e E2E_INSTALL_GROUPS=main,all_ds

stack_up() {
  docker compose run --rm server create_db
  docker compose up -d
  timeout 120 sh -c 'until curl -sf http://localhost:5000/ping; do sleep 2; done'
  timeout 180 sh -c 'until docker compose exec -T -e PGPASSWORD=demo e2e-postgres psql -h 127.0.0.1 -U demo -c "select 1 from events limit 1" demo; do sleep 2; done'
  timeout 180 sh -c 'until docker compose exec -T e2e-mysql mysql -h 127.0.0.1 -udemo -pdemo -e "select 1 from events limit 1" demo; do sleep 2; done'
}

setup() {
  sudo npm i -g pnpm@10.30.3
  pnpm install --frozen-lockfile
  pnpm exec playwright install --with-deps chromium
  docker compose build server worker scheduler
  stack_up
}

reset() {
  docker compose down -v --remove-orphans
  stack_up
}

run_tests() {
  pnpm run e2e --retries=0 --reporter=line,junit
}
