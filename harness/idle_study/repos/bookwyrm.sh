# bookwyrm-social/bookwyrm: pytest -n 3 on Postgres, as in .github/workflows/python.yml
export POSTGRES_HOST=127.0.0.1 PGPORT=5432 POSTGRES_USER=postgres POSTGRES_PASSWORD=hunter2 POSTGRES_DB=github_actions
export SECRET_KEY=beepbeep EMAIL_HOST_USER= EMAIL_HOST_PASSWORD=

setup() {
  pg_docker postgres 5432 postgres:17 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=hunter2
  python -m pip install --upgrade "pip>=25.1.0"
  pip install --group main --group dev
  cp .env.example .env
  python ./manage.py compile_themes
  python ./manage.py collectstatic --no-input
}

run_tests() {
  pytest -n "$(serial_or 0 3)" -p no:rerunfailures --junitxml="$JUNIT_DIR/pytest.xml"
}
