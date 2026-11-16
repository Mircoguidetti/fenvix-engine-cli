# misskey-dev/misskey: backend e2e (vitest) on Postgres + Redis, as in .github/workflows/test-backend.yml job e2e
setup() {
  pg_docker postgres 54312 postgres:18 -e POSTGRES_DB=test-misskey -e POSTGRES_HOST_AUTH_METHOD=trust
  redis_docker redis 56312 redis:8
  corepack enable
  pnpm i --frozen-lockfile
  cp .github/misskey/test.yml .config
  pnpm build
  pnpm --filter backend build:e2e
}

run_tests() {
  cd packages/backend && npx vitest run --config vitest.config.e2e.ts \
    --reporter=dot --reporter=junit --outputFile.junit="$JUNIT_DIR/vitest.xml"
}
