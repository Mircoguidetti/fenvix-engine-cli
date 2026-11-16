# bookwyrm-social/bookwyrm: pytest -n 3 on Postgres, as in .github/workflows/python.yml
export POSTGRES_HOST=127.0.0.1 POSTGRES_PASSWORD=hunter2

setup() {
  pg_docker postgres 5432 postgres:17 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=hunter2
  python -m pip install --upgrade "pip>=25.1.0"
  pip install --group main --group dev
  cp .env.example .env
  python ./manage.py compile_themes
  python ./manage.py collectstatic --no-input
}

run_tests() {
  pytest -n 3 -p no:rerunfailures --junitxml="$JUNIT_DIR/pytest.xml"
}
