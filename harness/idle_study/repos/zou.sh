# cgwire/zou: pytest -n logical (not integration) then -m integration, on Postgres + Redis + Meilisearch, as in .github/workflows/ci.yml
export MEILI_MASTER_KEY=testkey0123456789 PGPASSWORD=mysecretpassword
export DEBUG=1 MAIL_DEBUG_BODY=1 MAIL_ENABLED=False

setup() {
  pg_docker postgres 5432 postgres:18 -e POSTGRES_PASSWORD=mysecretpassword
  svc_docker meilisearch getmeili/meilisearch:v1.1 -p 7700:7700 -e MEILI_MASTER_KEY=testkey0123456789
  redis_docker redis 6379 redis:7-alpine
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends ffmpeg
  pip install --upgrade pip setuptools
  pip install -r requirements.txt
  psql -U postgres -h 127.0.0.1 -c 'ALTER SYSTEM SET fsync = off' -c 'ALTER SYSTEM SET synchronous_commit = off' -c 'ALTER SYSTEM SET full_page_writes = off' -c 'SELECT pg_reload_conf()'
  wait_http http://localhost:7700/health 60
}

run_tests() {
  py.test -n logical --dist loadscope -m "not integration" -p no:rerunfailures --junitxml="$JUNIT_DIR/parallel.xml"
  a=$?
  INDEXER_KEY=$MEILI_MASTER_KEY py.test -m integration -rs -p no:rerunfailures --junitxml="$JUNIT_DIR/integration.xml"
  b=$?
  return $(( a | b ))
}
