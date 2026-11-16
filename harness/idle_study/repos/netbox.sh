# netbox-community/netbox: Django test --parallel --keepdb on Postgres + Redis, as in .github/workflows/ci.yml
export NETBOX_CONFIGURATION=netbox.configuration_testing

setup() {
  redis_docker redis 6379 redis:8
  pg_docker postgres 5432 postgres:18 -e POSTGRES_USER=netbox -e POSTGRES_PASSWORD=netbox
  sed -i 's/^psycopg\[c,pool\]==/psycopg[binary,pool]==/' requirements.txt
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  pip install -r requirements_testing.txt
  python netbox/manage.py collectstatic --no-input
  python netbox/manage.py migrate --no-input --run-syncdb
  docker exec postgres pg_dump -U netbox -Fc netbox >/tmp/test_netbox.dump
  docker exec postgres createdb -U netbox test_netbox
  docker exec -i postgres pg_restore -U netbox -d test_netbox --exit-on-error </tmp/test_netbox.dump
}

run_tests() {
  python netbox/manage.py test netbox/ --parallel --keepdb --timing -v 2
}
