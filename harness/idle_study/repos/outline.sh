# outline/outline: vitest server projects on Postgres, as in .github/workflows/ci.yml job test-server (shard 1 of 3 instead of 6 parallel jobs)
setup() {
  sudo systemctl start postgresql.service
  until pg_isready -h localhost; do sleep 1; done
  sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'password';"
  sudo -u postgres createdb outline_test
  corepack enable
  yarn install --immutable
  yarn sequelize db:migrate
}

run_tests() {
  TZ=UTC yarn vitest run --project "server*" --maxWorkers=4 --shard=1/3 \
    --reporter=dot --reporter=junit --outputFile.junit="$JUNIT_DIR/vitest.xml"
}
