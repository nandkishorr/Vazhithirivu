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
- Test suite: `docker compose run --rm web python manage.py test --settings=config.settings.test` *(verified 2026-10-25: 91 tests OK)*. Django creates `test_vazhithirivu` with PostGIS, which needs the container superuser (the default). If a killed run leaves a stale `test_vazhithirivu`, answer `yes` to the prompt or pass `--noinput` so Django recreates it.
- System check: `docker compose run --rm web python manage.py check` *(verified: no issues)*
- Prod deploy check: `docker compose run --rm -e DJANGO_SETTINGS_MODULE=config.settings.prod -e DJANGO_SECRET_KEY=<50+ random chars> -e DJANGO_ALLOWED_HOSTS=example.com web python manage.py check --deploy` *(verified)*. Only `security.W004` (HSTS) remains until `DJANGO_SECURE_HSTS_SECONDS` is set.

## Production notes (not yet deployed)
- Image default CMD: `gunicorn config.wsgi:application --bind 0.0.0.0:8000`. The image runs as non-root `app`, and static files are collected at build time (WhiteNoise compressed manifest storage in prod).
- Prod requires `DJANGO_SECRET_KEY` (no `django-insecure…` or `change-me` values) and `DJANGO_ALLOWED_HOSTS`. `DJANGO_SECURE_SSL_REDIRECT` defaults to true, and `/healthz/` and `/readyz/` are exempt from the redirect.
- Build the prod image with base requirements: `docker build -t vazhithirivu .` (the `REQUIREMENTS` build arg defaults to `requirements/base.txt`).

## PostGIS image
- Default `postgis/postgis:17-3.5` (owner choice: official image). It is amd64-only and runs emulated on Apple Silicon (`platform: linux/amd64`). Alternative: `POSTGIS_IMAGE=postgis/postgis:16-3.4`. Switching major versions requires a fresh volume (`docker compose down -v`, which destroys data) or a dump/restore.

## OSM import
The `import_osm_railways` command imports `railway=level_crossing` nodes and
`railway=rail|narrow_gauge|light_rail` ways from a local `.osm.pbf`/`.osm`
extract into the `railways` app's PostGIS tables. Downloads are manual;
nothing is fetched at web startup.

### Download (manual)
```bash
mkdir -p data/osm
curl -fLO --output-dir data/osm \
  https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf
curl -fLO --output-dir data/osm \
  https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf.md5
(cd data/osm && md5sum -c southern-zone-latest.osm.pbf.md5)
```
Full India: `asia/india-latest.osm.pbf` (~1.6 GB). `data/osm/` is git- and
docker-ignored and mounted read-only into the `osm-import` service.

### Running
```bash
# Always dry-run a new extract first:
docker compose --profile import run --rm osm-import \
  --source /data/osm/southern-zone-latest.osm.pbf --dry-run

# Kochi demo area (recommended for the southern-zone extract):
docker compose --profile import run --rm osm-import \
  --source /data/osm/southern-zone-latest.osm.pbf \
  --source-url https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf \
  --bbox 76.18,9.85,76.45,10.15
```
Flags: `--batch-size` (default 2000), `--crossing-values`/`--track-values`
(comma lists overriding the default tag sets), `--location-index`
(default `flex_mem`; for the full India extract use
`dense_file_array,/tmp/osm-idx` — the file lives inside the throwaway
container), `--bbox minlon,minlat,maxlon,maxlat`, `--reconcile`,
`--max-deactivate-fraction` (default 0.2), `--dry-run`, `--source-url`.

### Refresh / reconciliation
- Re-running on the same or a newer extract is safe and idempotent
  (`(osm_type, osm_id)` upserts; `first_seen_run`/`last_seen_run` track
  provenance). Rerunning the same file is also the restart path after a
  failure — already-flushed batches are valid newer data.
- `--reconcile` additionally soft-deletes (`is_active=False`, never
  `DELETE`) active OSM rows inside the coverage bbox (the `--bbox`, else
  the file's header bounds) that the new extract no longer contains. It
  requires a coverage bbox and aborts without deactivating anything if the
  candidate count exceeds `--max-deactivate-fraction` of in-scope rows —
  review the extract, then re-run with a higher fraction if the drop is
  legitimate. Tracks only count when fully within the scope, so
  boundary-clipped tracks are conservatively kept.
- Reconcile candidates are also limited to the run's effective
  `--crossing-values`/`--track-values` filter set, so a narrower-filter
  re-import never deactivates rows outside that set; a feature retagged
  out of the set upstream (e.g. `rail` -> `abandoned`) keeps its stored
  value and is still deactivated.
- Only one import may run at a time (Postgres advisory lock). A crashed
  run leaves a `running` row that the next import marks `failed`
  ("interrupted …") before proceeding.
- `source='manual'` rows and `is_suppressed`/admin notes are never
  modified by the importer.

### Audit
Every import writes an `OsmImportRun` row: sha256, file size, header
`osmosis_replication_timestamp` (if present), effective filters, coverage
bbox, batch size, status, per-kind created/updated/reactivated/deactivated
counts, skipped counts per reason, and the error on failure. Visible
(read-only) in Django admin.

### Importer tests
```bash
docker compose run --rm web python manage.py test railways \
  --settings=config.settings.test
```
(Verified Session 03: 20 railways tests, part of the 46-test suite — see
"Tests and checks".)

Measured 2026-10-25 (macOS arm64, PostGIS under amd64 emulation): Geofabrik
`southern-zone-latest.osm.pbf`, 558,661,592 bytes, data up to
2026-10-23T20:20:51Z, md5 `cefc03473f8b2b133bc383622a081ff5`, imported with
`--bbox 76.18,9.85,76.45,10.15` (Kochi). Result: 127 crossings and 330 tracks
created, 33,605 railway objects skipped as `outside_bbox`. Run time was about
7 s inside the container (about 10 s including container start). A second
identical run created 0 and updated 127/330. Table sizes: crossings 176 kB,
tracks 496 kB. A full southern-zone or India import (no bbox) is not yet measured.

## Community crossing reports
- Sign-in: interim Django auth at `/accounts/login/` / `/accounts/logout/` (Google sign-in comes later). Create a reporter/admin user with:
  ```bash
  docker compose run --rm web python manage.py createsuperuser
  ```
- Crossing pages: `/crossings/<id>/` (HTML detail + report form). JSON for the future map: `GET /api/crossings/<id>/status/` and `POST /api/crossings/<id>/reports/` (`{"state": "open"|"closed"}`, CSRF token required for session auth; 401 anon, 429 + `Retry-After` when rate limited).
- Freshness/rate-limit policy is env-tunable (`REPORT_*`, see `.env.example`); invalid combinations fail `manage.py check` (`incidents.E001`).
- Moderation: staff hide/restore reports in Django admin (actions or the change form); hidden reports vanish from all public output.
- Retention purge (not scheduled — run manually or via cron):
  ```bash
  docker compose run --rm web python manage.py purge_crossing_reports --dry-run
  docker compose run --rm web python manage.py purge_crossing_reports        # default: REPORT_RETENTION_DAYS
  docker compose run --rm web python manage.py purge_crossing_reports --days 60
  ```

## Simulation
- Not implemented yet (Session 08). Start only via an optional Compose profile; reset only simulation-scoped records.

## Google Maps
- The map needs `GOOGLE_MAPS_BROWSER_KEY` (Maps JavaScript API + Places API (New); restrict by HTTP referrer and those APIs) and `GOOGLE_MAPS_MAP_ID` (Maps Management / Map Styles in Cloud Console; needed for cloud styling and the location marker). `GOOGLE_MAPS_SERVER_KEY` is reserved for future server-side use — never expose it to the browser.
- Blank values are OK: the app boots, `core.W001`/`core.W002` warnings are emitted, and the map region shows a not-configured (DEBUG) or generic unavailable state.

## Tailwind assets
- Tailwind CSS v4 standalone CLI (no Node/npm), pinned in the Dockerfile via `TAILWIND_VERSION` + per-arch sha256 from the release's `sha256sums.txt`.
- Dev watcher (starts with `docker compose up -d`): the `tailwind` service writes `static/css/app.css` on every change.
- One-off build: `docker compose run --rm tailwind tailwindcss -i assets/tailwind/input.css -o static/css/app.css --minify` *(verified)*.
- Prod image: the `tailwind` build stage compiles `static/css/app.css`; the app stage copies it before `collectstatic` *(verified — `docker build -t vazhithirivu .`)*.
- To bump the version: pick a release from https://github.com/tailwindlabs/tailwindcss/releases, set `TAILWIND_VERSION`, and update the two sha256 values from that release's `sha256sums.txt`.
- `static/css/app.css` is a build artifact — git- and docker-ignored.

## Troubleshooting
- `web` exits with `ImproperlyConfigured`: check `DATABASE_URL` scheme is `postgis://` and prod vars are set.
- `/readyz/` 503: `docker compose ps db`, `docker compose logs db web`.
- Slow DB on Apple Silicon: expected (amd64 emulation).
- Redis: not used yet. It will be added with Channels/Celery (Session 07+).
- Route failure: check provider key, quota, network and provider abstraction logs; never fabricate fallback durations.
- Crossing absent: check OSM coverage, import filters and admin correction workflow.
