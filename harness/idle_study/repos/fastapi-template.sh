# fastapi/full-stack-fastapi-template: Playwright e2e, as in .github/workflows/playwright.yml (one shard instead of four)
setup() {
  (cd backend && uv sync)
  (cd frontend && bun ci)
  bash scripts/generate-client.sh
  docker compose build
  docker compose down -v --remove-orphans
  docker compose run --rm backend bash scripts/prestart.sh
  mkdir -p frontend/test-results && chmod 777 frontend/test-results
}

reset() {
  docker compose down -v --remove-orphans
  docker compose run --rm backend bash scripts/prestart.sh
}

run_tests() {
  rm -f frontend/test-results/junit.xml
  docker compose run --rm \
    -e PLAYWRIGHT_JUNIT_OUTPUT_FILE=test-results/junit.xml \
    playwright bunx playwright test --retries=0 --reporter=line,junit
  rc=$?
  cp frontend/test-results/junit.xml "$JUNIT_DIR/" 2>/dev/null
  return $rc
}
