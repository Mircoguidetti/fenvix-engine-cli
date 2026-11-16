# lukevella/rallly: Playwright integration tests on Postgres + Mailpit, as in .github/workflows/ci.yml job integration-shard
# (services on the runner's localhost instead of a job container; shard 1 of 3)
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rallly
export DIRECT_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rallly
export SMTP_HOST=localhost SMTP_PORT=1025 MAILPIT_API_URL=http://localhost:8025/api CI=true

setup() {
  pg_docker postgres 5432 postgres:18-alpine -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=rallly
  svc_docker mailpit axllent/mailpit -p 1025:1025 -p 8025:8025
  corepack enable
  pnpm install --frozen-lockfile
  pnpm db:generate
  pnpm turbo build:test --filter=@rallly/web
  pnpm db:deploy
  pnpm --filter @rallly/web exec playwright install --with-deps chromium
}

run_tests() {
  pnpm --filter @rallly/web test:integration --shard=1/3 --retries=0 --reporter=line,junit
}
