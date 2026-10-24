# Project State — Vazhithirivu

> This file is the handoff point between agent sessions. Update it at the end of every meaningful work session.

## Status
- Current milestone: **Session 01 (project foundation) complete, 2026-10-25.** M1 in progress. Next: Session 02 (UI foundation, Tailwind).
- Product: Vazhithirivu (വഴിത്തിരിവ്), "Smart routes. Smarter crossings."
- Target demo: Kochi, Kerala; future dataset target: India-wide mapped railway crossings.
- Stack: Django 5.2 LTS, server-rendered templates, PostgreSQL 17 + PostGIS 3.5 (GeoDjango), Docker Compose. Not yet added: Tailwind/HTMX/Alpine (Session 02), Redis/Channels/Celery (Session 07+).
- **Every service runs as a container** (ADR-006). Do not use the host's Homebrew Postgres.
- Simulator: optional isolated service (not built); the normal app must work without it.

## Architecture invariants
- OSM geometry is reference data, not live crossing status.
- Community reports, real user locations, and simulation events are separate.
- Location sharing is explicit opt-in and can be stopped immediately.
- A detour is valid only after checking that it avoids the affected crossing/blocked segment.
- Do not query Overpass for each user or location update; import data and query PostGIS.
- Full-country OSM import must be explicit, never run at web startup.
- Database must be PostGIS; there is no SQLite fallback (ADR-007).

## What exists now (Session 01)
- `manage.py`, `config/` (urls, wsgi, asgi, `settings/{base,dev,test,prod}.py`). Settings use `django-environ`, and `.env` is optional (`DJANGO_READ_DOT_ENV=0` disables it).
- `core/` app: `views.py` has `/healthz/` (liveness, no DB) and `/readyz/` (`SELECT 1` + `PostGIS_Lib_Version()`, 503 on failure, no error details in the body). Tests are in `core/tests/`.
- `requirements/base.txt` pins: Django==5.2.18, psycopg[binary]==3.3.6, django-environ==0.14.0, gunicorn==26.2.0, whitenoise==6.12.0. `requirements/dev.txt` = base for now.
- `Dockerfile` (python:3.12-slim-bookworm, GDAL/GEOS/PROJ, non-root `app`, build-time collectstatic, gunicorn CMD). `.dockerignore`.
- `docker-compose.yml`: `db` (`${POSTGIS_IMAGE:-postgis/postgis:17-3.5}`, `platform: linux/amd64`, `pgdata` volume, pg_isready healthcheck, no host port) and `web` (dev runserver, bind mount, `${WEB_PORT:-8000}`, `/healthz/` healthcheck, optional `.env`).
- `.env.example` (placeholders only), `.gitignore` (covers `.env`, `.DS_Store`, data/PBF files, staticfiles).
- No models beyond Django contrib. No templates or UI yet.

## Repository state (end of Session 01)
- Branch `main`, commits: `2127645` Initial commit (LICENSE) → `f3fd912` spec bundle + Session 00 audit → `ef2f038` Session 01 foundation. `main` is ahead of `origin/main` and **not pushed**.
- `LICENSE` (MIT) restored with `git restore LICENSE` (owner decision, 2026-10-25), unchanged from `2127645`.
- Working tree clean after `ef2f038` (except this file update).
- Containers stopped with `docker compose down`. The `pgdata` volume still holds the migrated dev DB. Run `docker compose up -d` to resume.

## Commands/tests run (Session 01, actual outcomes)
| Command | Result |
|---|---|
| `docker compose build web` | OK |
| `docker compose up -d db web` (no `.env` present) | Both healthy |
| `docker compose run --rm web python manage.py migrate` | Contrib migrations applied |
| `curl -i localhost:8000/healthz/` | 200 `{"status":"ok"}` |
| `curl -i localhost:8000/readyz/` | 200 `{"status":"ok","checks":{"database":"ok","postgis":"ok"}}` |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 10 tests, OK** (re-run after the final prod-key edit: still 10 OK) |
| `docker compose run --rm web python manage.py check` | No issues |
| prod `check --deploy` with dummy secret/hosts | 1 warning, `security.W004` (HSTS=0 by default; this is intended). Zero warnings with `DJANGO_SECURE_HSTS_SECONDS` set (covered by a test) |
| `psql … -c "select postgis_full_version();"` | POSTGIS 3.5.2, PGSQL 170, GEOS 3.9.0, PROJ 7.2.1 |
| `docker compose config` | Valid |

Tests cover: healthz 200/405, readyz 200 against real PostGIS, readyz 503 without leaking the exception, prod failures for a missing/insecure/placeholder secret and missing hosts, prod `check --deploy` passing, rejection of a non-PostGIS `DATABASE_URL` (postgres://, sqlite://), and dev env parsing.

## Known risks / open questions
- `LICENSE` (MIT) restored by owner decision (2026-10-25). Still to check: MIT code licensing vs ODbL obligations for distributed OSM-derived data.
- PostGIS runs under amd64 emulation on Apple Silicon (owner chose official `postgis/postgis` images). This is slower; import performance in Session 03 is unmeasured.
- The `web` bind mount shadows the image's collected static files in dev (harmless; prod image unaffected).
- `libgdal-dev` makes the image large. A runtime-only package set could slim it later.
- Google Maps credentials, quotas and storage terms are not configured or verified. Google alternatives cannot guarantee crossing avoidance.
- OSM crossing coverage is incomplete; the India-wide PBF size and memory requirements (~8 GB Docker RAM) are unmeasured.
- Routing engine with segment exclusion is not chosen (Session 06).
- Spec bundle committed in `f3fd912`; Session 01 foundation committed on top of it (not pushed).

## Next steps
1. Owner: push `main` when ready.
2. Session 02: Tailwind build pipeline (dev watch + production build in Docker), base layout/partials, map shell. Record a map-provider ADR (recommendation: Leaflet + OSM tiles by default, Google behind a switch).
3. Session 03: `RailwayCrossing`/`RailwayTrack` models (SRID 4326, spatial indexes), Kochi fixture, idempotent PBF importer as an explicit command/Compose profile.
4. Add lint/format tooling (e.g. ruff) to `requirements/dev.txt` and CI that runs `manage.py test` in Compose.
5. Consider slimming the Dockerfile (runtime GDAL libs only) and a multi-stage build once Tailwind is added.
