# immich-app/immich: server + CLI e2e (vitest) against the compose stack, as in .github/workflows/test.yml job e2e-tests-server-cli
export VITEST_DISABLE_DOCKER_SETUP=true

setup() {
  corepack enable
  pnpm --filter @immich/sdk --filter @immich/cli install --frozen-lockfile
  pnpm --filter @immich/sdk --filter @immich/cli build
  (cd web && pnpm install --frozen-lockfile && pnpm exec svelte-kit sync)
  cd e2e
  pnpm install --frozen-lockfile
  docker compose up -d --build --renew-anon-volumes --force-recreate --remove-orphans --wait --wait-timeout 300
}

run_tests() {
  # CI sets retry: 4 for vitest; retries are switched off here so flaky tests stay visible
  cd e2e && pnpm exec vitest --run --retry=0 \
    --reporter=dot --reporter=junit --outputFile.junit="$JUNIT_DIR/vitest.xml"
}
