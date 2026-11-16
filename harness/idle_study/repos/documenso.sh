# documenso/documenso: Playwright e2e against the Remix server on Postgres + Inbucket + MinIO, as in .github/workflows/e2e-tests.yml
# (one job: api + license projects, then ui shard 1/6)
export NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH=./example/cert.p12 DANGEROUS_BYPASS_RATE_LIMITS=true

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
}

run_tests() {
  E2E_PLAYWRIGHT_ARGS="--project=api --project=license --retries=0 --reporter=line,junit" \
    PLAYWRIGHT_JUNIT_OUTPUT_FILE="$JUNIT_DIR/api.xml" npm run test:e2e -w @documenso/app-tests
  a=$?
  E2E_PLAYWRIGHT_ARGS="--project=ui --shard=1/6 --retries=0 --reporter=line,junit" \
    PLAYWRIGHT_JUNIT_OUTPUT_FILE="$JUNIT_DIR/ui.xml" npm run test:e2e -w @documenso/app-tests
  b=$?
  return $(( a | b ))
}
