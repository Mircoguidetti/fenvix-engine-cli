# §6 Desk survey: per-worker databases

Done by a research sub-agent with web search. Every documentation fetch failed: the session's network blocks these
hosts (DNS ENOTFOUND). So every row is UNVERIFIED. Claims rest on search-result snippets and, where marked, on general
knowledge. To verify, fetch these URLs from a network that allows them.

| Tool | Per-worker database built in | How (one line) | Official documentation URL | Status |
|---|---|---|---|---|
| Rails | yes | `parallelize(workers: N)` (process mode) creates and migrates one database per worker with a numeric suffix (`-0`, `-1`, ...) | https://guides.rubyonrails.org/testing.html#parallel-testing | UNVERIFIED (fetch blocked; search snippets) |
| Django | yes | `manage.py test --parallel` clones the test database per worker process (`_1`, `_2`, ...) | https://docs.djangoproject.com/en/stable/ref/django-admin/#cmdoption-test-parallel | UNVERIFIED (fetch blocked; general knowledge) |
| pytest-django with xdist | plugin | with pytest-xdist, each worker gets a database with the worker id suffix (`test_x_gw0`, ...) | https://pytest-django.readthedocs.io/en/latest/database.html | UNVERIFIED (fetch blocked; search snippet) |
| Prisma | no | user code: a per-worker `DATABASE_URL` or `?schema=` built from `JEST_WORKER_ID` / `VITEST_POOL_ID` | https://www.prisma.io/docs/orm/prisma-client/testing/integration-testing | UNVERIFIED (fetch blocked; general knowledge) |
| TypeORM | no | user code: worker-id database name plus migrations in setup | https://typeorm.io/ | UNVERIFIED (not fetched; general knowledge) |
| Knex | no | user code: template copy or schema per worker | https://knexjs.org/guide/ | UNVERIFIED (not fetched; general knowledge) |
| Sequelize | no | user code | https://sequelize.org/docs/v6/ | UNVERIFIED (not fetched; general knowledge) |
| Drizzle | no | user code: PGlite or a database per `VITEST_POOL_ID` in setup files | https://orm.drizzle.team/docs/get-started/pglite-new | UNVERIFIED (not fetched; third-party guides) |
| Testcontainers | no (building block) | start a container per worker; Postgres module `Snapshot()`/`Restore()` (Go/Node) resets via a template database | https://node.testcontainers.org/modules/postgresql/ | UNVERIFIED (not fetched; search snippets) |
| PostgreSQL template databases | no (primitive) | `CREATE DATABASE w1 TEMPLATE migrated` clones quickly; the template must have no other connections | https://www.postgresql.org/docs/current/manage-ag-templatedbs.html | UNVERIFIED (fetch blocked; search snippet) |
| PGlite | no (primitive) | in-process Postgres (`new PGlite()` in memory): one instance per worker or test file | https://pglite.dev/docs/about | UNVERIFIED (fetch blocked; search snippet) |
