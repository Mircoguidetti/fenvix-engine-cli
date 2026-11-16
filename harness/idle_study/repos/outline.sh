# outline/outline: vitest server projects on Postgres, as in .github/workflows/ci.yml job test-server (shard 1 of 3 instead of 6 parallel jobs)
export NODE_ENV=test DATABASE_URL=postgres://postgres:password@localhost:5432/outline_test REDIS_URL=redis://127.0.0.1:6379
export URL=http://localhost:3000 NODE_OPTIONS=--max-old-space-size=8192
export SECRET_KEY=F0E5AD933D7F6FD8F4DBB3E038C501C052DC0593C686D21ACB30AE205D2F634B UTILS_SECRET=123456
export SLACK_VERIFICATION_TOKEN=123456 SMTP_USERNAME=localhost

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
