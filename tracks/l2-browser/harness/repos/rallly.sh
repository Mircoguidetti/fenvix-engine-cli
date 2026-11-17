# lukevella/rallly: Playwright integration tests against Next.js (webServer `next start`) on Postgres + Mailpit,
# as in .github/workflows/ci.yml job integration-shard (shard 1 of 3, workers 1).
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rallly
export DIRECT_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rallly
export SMTP_HOST=localhost SMTP_PORT=1025 MAILPIT_API_URL=http://localhost:8025/api CI=true
PW_DIR=apps/web
PW_ARGS="--shard=1/3"

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
