# Runbook — Vazhithirivu

Commands marked *(verified)* were run successfully in Session 01 (2026-10-25) on macOS arm64 with Docker 29.8.2 / Compose v5.5.1. Everything runs in containers (ADR-006). No host Python, Postgres or GDAL is needed.

## Environment
- Optional for dev: `cp .env.example .env`. The stack boots without `.env` using dev defaults *(verified)*.
- Settings modules: `config.settings.dev` (default), `config.settings.test`, `config.settings.prod`.
- Key variables: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_LOG_LEVEL`, `POSTGRES_DB/USER/PASSWORD`, `POSTGIS_IMAGE`, `WEB_PORT`, optional `GOOGLE_MAPS_BROWSER_KEY` / `GOOGLE_MAPS_SERVER_KEY`.
- Compose builds `DATABASE_URL` (`postgis://…@db:5432/…`) for `web`. Only a `postgis://` URL is accepted; any other backend raises `ImproperlyConfigured`.
- Set `DJANGO_READ_DOT_ENV=0` to ignore `.env`. Real environment variables always override `.env`.
- Never commit `.env`. It is git- and docker-ignored.

## Docker (dev)
- Build: `docker compose build web` *(verified)*
- Start: `docker compose up -d` (db + web; web waits for a healthy db) *(verified)*
- Migrate: `docker compose run --rm web python manage.py migrate` *(verified)*
- App: http://localhost:8000 (change the host port with `WEB_PORT`). The DB is **not** published to the host, because host port 5432 is Homebrew Postgres.
- psql: `docker compose exec db psql -U vazhithirivu -d vazhithirivu` *(verified)*
- Admin user: `docker compose run --rm web python manage.py createsuperuser`
- Stop: `docker compose down` (the data volume `pgdata` persists; `down -v` deletes it, which destroys data).
- `web` bind-mounts the repo at `/app` and runs `runserver`, so code reloads automatically.

## Health checks
- Liveness: `curl -i localhost:8000/healthz/` → `200 {"status":"ok"}` (no DB access) *(verified)*
- Readiness: `curl -i localhost:8000/readyz/` → `200 {"status":"ok","checks":{"database":"ok","postgis":"ok"}}`, or `503` with `"status":"error"`. Error details only go to the server logs *(verified)*

## Tests and checks
- Test suite: `docker compose run --rm web python manage.py test --settings=config.settings.test` *(verified: 10 tests OK)*. Django creates `test_vazhithirivu` with PostGIS, which needs the container superuser (the default).
- System check: `docker compose run --rm web python manage.py check` *(verified: no issues)*
- Prod deploy check: `docker compose run --rm -e DJANGO_SETTINGS_MODULE=config.settings.prod -e DJANGO_SECRET_KEY=<50+ random chars> -e DJANGO_ALLOWED_HOSTS=example.com web python manage.py check --deploy` *(verified)*. Only `security.W004` (HSTS) remains until `DJANGO_SECURE_HSTS_SECONDS` is set.

## Production notes (not yet deployed)
- Image default CMD: `gunicorn config.wsgi:application --bind 0.0.0.0:8000`. The image runs as non-root `app`, and static files are collected at build time (WhiteNoise compressed manifest storage in prod).
- Prod requires `DJANGO_SECRET_KEY` (no `django-insecure…` or `change-me` values) and `DJANGO_ALLOWED_HOSTS`. `DJANGO_SECURE_SSL_REDIRECT` defaults to true, and `/healthz/` and `/readyz/` are exempt from the redirect.
- Build the prod image with base requirements: `docker build -t vazhithirivu .` (the `REQUIREMENTS` build arg defaults to `requirements/base.txt`).

## PostGIS image
- Default `postgis/postgis:17-3.5` (owner choice: official image). It is amd64-only and runs emulated on Apple Silicon (`platform: linux/amd64`). Alternative: `POSTGIS_IMAGE=postgis/postgis:16-3.4`. Switching major versions requires a fresh volume (`docker compose down -v`, which destroys data) or a dump/restore.

## OSM import
- Not implemented yet (Session 03). Do not run the full India import automatically.
- Test importer with the small fixture first. Never use live Overpass in automated tests.
- Record input file checksum, source URL/date, imported counts, skipped counts and errors.

## Simulation
- Not implemented yet (Session 08). Start only via an optional Compose profile; reset only simulation-scoped records.

## Tailwind assets
- Not implemented yet (Session 02). Record dev/prod build commands here once verified; the production image must include compiled CSS.

## Troubleshooting
- `web` exits with `ImproperlyConfigured`: check `DATABASE_URL` scheme is `postgis://` and prod vars are set.
- `/readyz/` 503: `docker compose ps db`, `docker compose logs db web`.
- Slow DB on Apple Silicon: expected (amd64 emulation).
- Redis: not used yet. It will be added with Channels/Celery (Session 07+).
- Route failure: check provider key, quota, network and provider abstraction logs; never fabricate fallback durations.
- Crossing absent: check OSM coverage, import filters and admin correction workflow.
