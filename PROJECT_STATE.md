# Project State — Vazhithirivu

> This file is the handoff point between agent sessions. Update it at the end of every meaningful work session.

## Status
- Current milestone: **Session 04 (community crossing reports) implemented, 2026-10-25.** M1 in progress. Next: nearby-crossing query + map markers (Session 05).
- Product: Vazhithirivu (വഴിത്തിരിവ്), "Smart routes. Smarter crossings."
- Target demo: Kochi, Kerala; future dataset target: India-wide mapped railway crossings.
- Stack: Django 5.2 LTS, server-rendered templates, Tailwind CSS v4 (standalone CLI, ADR-008), Google Maps JavaScript API + Places API (New) (ADR-009), PostgreSQL 17 + PostGIS 3.5, Docker Compose. Not yet added: HTMX/Alpine (not needed yet), Redis/Channels/Celery (Session 07+).
- **Every service runs as a container** (ADR-006). Do not use the host's Homebrew Postgres.
- Owner preferences (also in AGENTS.md): Google Maps is the map provider (Leaflet removed); run one consolidated verification pass at the end of a session, not intermediate tests/screenshots.

## Architecture invariants
- OSM geometry is reference data, not live crossing status.
- Community reports, real user locations, and simulation events are separate.
- Location sharing is explicit opt-in and can be stopped immediately.
- A detour is valid only after checking that it avoids the affected crossing/blocked segment.
- Do not query Overpass for each user or location update; import data and query PostGIS.
- Full-country OSM import must be explicit, never run at web startup.
- Database must be PostGIS; there is no SQLite fallback (ADR-007).
- Google server key is never rendered into templates; tests never call Google.

## What exists now
Session 01: settings split (`config/settings/{base,dev,test,prod}.py`), `/healthz/`, `/readyz/`, Dockerfile, Compose `db` + `web`.

Session 02 (uncommitted):
- **Tailwind**: `assets/tailwind/input.css` (theme, `.btn*`, `.field*`, `.card`, `.badge`, `.sheet`, reduced-motion rule; `@source` covers templates, `static/js`, `core/**/*.py`). Dockerfile `tailwind` stage (v4.3.3, sha256-verified) → `static/css/app.css` copied into the app image. Compose `tailwind` watcher service. `static/css/app.css` is git/docker-ignored.
- **Components**: `core/templatetags/ui.py` (`{% icon %}` 18 inline Lucide SVGs, `{% status_badge %}` open/closed/unknown/stale/conflicting with unknown fallback, `{% source_badge %}` osm/community/simulated); `templates/components/` alert, empty_state, error_state, spinner, skeleton, badge partials.
- **Pages**: `templates/base.html` (skip link, `lang="ml"` span); `/` → `core.views.home` / `templates/core/home.html`: header, desktop side panel / mobile bottom sheet, GET route form (no-destination warning; non-blank → "Route planning isn't available yet", no fabricated durations), opt-in location card (idle/requesting/active/denied/unavailable), crossing empty state ("OSM data not imported yet"), status legend with "not official / no report ≠ open". Map region: loading, API-unavailable / auth-failure, noscript, and not-configured states. `/ui/` component gallery (DEBUG only, labelled "Demo content").
- **Google Maps**: official bootstrap loader rendered only when `GOOGLE_MAPS_BROWSER_KEY` set; config via `json_script`. `static/js/map.js` (Map with Map ID, `PlaceAutocompleteElement` on From/To with India region + Kochi bias, `gmp-select` → hidden `*_place_id`, `gm_authFailure` handler). `static/js/app.js` (bottom sheet, click-only one-shot geolocation, coords stay in browser, AdvancedMarker only with Map ID).
- **Config**: `GOOGLE_MAPS_MAP_ID`, `MAP_DEFAULT_LAT/LNG/ZOOM` added; `.env.example` lists all Google keys (blank placeholders) with restriction guidance. `core/checks.py`: warnings `core.W001` (no browser key), `core.W002` (no Map ID).
- Docs updated: RUNBOOK (Tailwind + Google key setup), DATA_SOURCES (Google, Lucide ISC), README (attribution), DECISIONS (ADR-008, ADR-009), ROADMAP.

Session 03 (uncommitted, on top of uncommitted Session 02; ADR-010):
- **`railways` app** (in `INSTALLED_APPS`). `railways/models.py`: `OsmImportRun` (path/url, sha256, size, header replication timestamp, coverage bbox, filters, counts, status/error); abstract `OsmReferenceFeature` (source osm/manual, osm_type/id/version/timestamp, full tags, first/last_seen_run, is_active/deactivated_at); `RailwayCrossing` (Point 4326, railway_value, crossing_barrier, is_suppressed/suppression_reason/admin_notes, **no status field**); `RailwayTrack` (LineString 4326, usage/service). Non-partial unique `(osm_type, osm_id)`, check constraint (osm rows need identity), GiST + is_active indexes. Migration `railways/migrations/0001_initial.py`.
- `railways/importer.py` (`run_import`, `ImportFilters`, `flush_batch`, `_reconcile`): pyosmium 4.3.2 `FileProcessor.with_locations().with_filter(KeyFilter("railway"))` (verified untagged way nodes still resolve). Advisory lock, stale `running` runs marked failed, per-batch atomic upserts, `--bbox`, `--dry-run`, `--reconcile` (bbox + filter-scoped soft-delete, all-or-nothing, `--max-deactivate-fraction` abort). Skip reasons: `crossing_not_node`, `track_invalid_geometry`, `crossing_invalid_geometry`, `outside_bbox`.
- `railways/management/commands/import_osm_railways.py` (thin CLI), `railways/admin.py` (GISModelAdmin; OSM fields read-only on osm rows; manual crossings + suppression; runs view-only).
- Tests: `railways/tests/test_import.py`, `test_models.py`, synthetic fixtures `railways/tests/fixtures/sample_v1.osm`/`sample_v2.osm` (+ tmp PBF written in-test).
- `requirements/base.txt` + `osmium==4.3.2`; Compose `osm-import` service (`profiles: ["import"]`, `./data/osm` read-only at `/data/osm`).
- Docs: DATA_SOURCES (Geofabrik URLs/sizes, ODbL/attribution, filters, corrections, refresh), RUNBOOK (OSM import section), DECISIONS ADR-010, ROADMAP.
- `core/tests/test_ui.py`: no-key test now forces blank Google settings (it failed when `.env` held a real key).

Session 04 (uncommitted, on top of uncommitted Sessions 02–03; ADR-011):
- **`incidents` app** (in `INSTALLED_APPS` after `railways`). `incidents/models.py`: `CrossingReport` (FK→`RailwayCrossing` PROTECT related_name `reports`; `reported_state` open/closed; `source` community-only; `reporter` FK null SET_NULL `crossing_reports`; `created_at` settable `default=timezone.now`; `expires_at`; moderation `visible`/`hidden` + `moderated_by`/`moderated_at`/`moderation_note`; ordering `-created_at`; indexes (crossing, created_at) + (reporter, created_at); CheckConstraints expires>created + valid state/moderation). Migration `incidents/migrations/0001_initial.py`.
- `incidents/services.py`: `derive_status` → `CrossingStatus` (states `closed_reported`/`open_reported`/`conflicting`/`stale`/`unknown`); fresh 15 min strict, stale→60, conflict window 5 min, per-reporter dedup (deleted reporters key `deleted:<pk>`), supporting/opposing counts; `create_report` (select_for_update per user; ReportNotAllowed, duplicate→(existing,False), flip<30s→RateLimited, >20/hr→RateLimited with retry); `public_recent_reports`, `status_label`.
- Views+URLs (`incidents/urls.py` at root): `GET /crossings/<pk>/` (`crossing_detail`, `templates/incidents/crossing_detail.html`), `POST /crossings/<pk>/report/` (`crossing_report_submit`, PRG + messages), `GET /api/crossings/<pk>/status/` (`api_crossing_status`, never_cache), `POST /api/crossings/<pk>/reports/` (`api_crossing_reports`; 401 anon, 429+`Retry-After`, JSON+form). All hide inactive/suppressed crossings (404; API `{"error":"not_found"}`). `incidents/forms.py` `CrossingReportForm`.
- Interim auth: `accounts/login|logout/` Django auth views (`config/urls.py`), `templates/registration/login.html`. Google sign-in still pending.
- Admin `incidents/admin.py`: read-only except `moderation_status`/`moderation_note`, no add, hide/restore actions set `moderated_by`/`at`; `save_model` stamps moderation on status change.
- `incidents/checks.py` `incidents.E001` requires `0 < conflict <= fresh < stale`. Settings: `REPORT_*` (env-int defaults 15/60/5/2/30/20/30) + `LOGIN_URL`/`LOGIN_REDIRECT_URL`/`LOGOUT_REDIRECT_URL`; `.env.example` placeholders.
- `incidents/management/commands/purge_crossing_reports.py` (`--days`, `--dry-run`; not scheduled — run manually/cron, documented in RUNBOOK).
- `core/templatetags/ui.py`: status-badge aliases `closed_reported`/`open_reported`; `manual` source badge ("Manually added reference").
- Tests: `incidents/tests/{test_status,test_reports,test_views,test_admin,test_purge}.py` + badge cases in `core/tests/test_ui.py`.
- Docs: DECISIONS ADR-011, DATA_SOURCES community-reports section, RUNBOOK reports section, ROADMAP M3 ticks.

## Commands/tests run (Session 04, actual outcomes)
| Command | Result |
|---|---|
| `docker compose run --rm web python manage.py makemigrations incidents` | `incidents/migrations/0001_initial.py` created |
| `... makemigrations --check --dry-run` | No changes detected |
| `... manage.py check` | No issues (0 silenced) |
| `... manage.py migrate` | `incidents.0001_initial` applied |
| `... manage.py test --settings=config.settings.test` | **Ran 87 tests, OK** (46 prior + 41 new) |
| Smoke on dev server: temp manual crossing; `GET /crossings/7/` | 200 |
| `GET /api/crossings/7/status/` | 200, `state: "unknown"`, `official: false` |
| `GET /accounts/login/` | 200 |
| anon `POST /api/crossings/7/reports/` (no CSRF token) | 403 (Django's HTML CSRF rejection — expected; 401 only once a valid CSRF token is sent) |
| `docker compose run --rm tailwind tailwindcss -i assets/tailwind/input.css -o static/css/app.css --minify` | Done in 50ms (tailwind service was already running and rebuilding too) |
| Temp smoke crossing deleted afterwards | confirmed 0 remaining |

Limitations: no Google sign-in yet (admin-created accounts only); rate limiting is per-user DB-based (no Redis); purge is not scheduled; crossing markers/map UI not built yet; API CSRF failures return Django's default HTML 403 page, not JSON.

## Commands/tests run (Session 03, actual outcomes)
| Command | Result |
|---|---|
| `docker compose build web` | OK (osmium 4.3.2 manylinux_2_28 aarch64 wheel) |
| `docker compose run --rm web python manage.py makemigrations --check --dry-run` | No changes |
| `docker compose run --rm web python manage.py check` | No issues |
| `docker compose run --rm web python manage.py migrate` | `railways.0001_initial` applied |
| CLI smoke on dev DB with `sample_v1.osm`: `--dry-run`, then 2 real imports | dry-run wrote nothing; run 1 created crossing=3/track=2; run 2 created=0, updated=3/2. Synthetic rows/runs deleted afterwards |
| `docker compose --profile import config` | valid |
| `docker build -t vazhithirivu .` | OK |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` (after the reconcile-scope rework) | **Ran 46 tests, OK**. An earlier attempt failed on a stale `test_vazhithirivu` DB left by a killed run; dropped and reran clean |

Real Kochi import (2026-10-25): Geofabrik `southern-zone-latest.osm.pbf` (558,661,592 bytes, md5 matched, data up to 2026-10-23T20:20:51Z), `--bbox 76.18,9.85,76.45,10.15`. Dry run parsed 127 crossings/330 tracks. Import run 3 created 127/330 (~10 s wall). Rerun run 4 created 0 and updated 127/330. 33,605 objects skipped as `outside_bbox`. Tables: 176 kB + 496 kB. The dev DB now holds real Kochi OSM data. A full southern-zone or India import is not measured.

## Commands/tests run (Session 02, actual outcomes — single end-of-session gate)
| Command | Result |
|---|---|
| `docker compose build web tailwind` | OK; Tailwind binary `sha256sum -c` OK |
| `docker compose up -d` | db + web healthy, tailwind watcher running; wrote `static/css/app.css` (~31 KB) |
| `docker compose run --rm tailwind tailwindcss -i assets/tailwind/input.css -o static/css/app.css --minify` | OK |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 26 tests, OK** (10 existing + 16 new) |
| `docker compose run --rm web python manage.py check` | No errors; `core.W001`/`W002` warnings (keys blank — expected) |
| curl `/`, `/?destination=`, `/?destination=Kochi`, `/ui/`, `/static/css/app.css`, `/healthz/` | all 200 |
| `docker build -t vazhithirivu .` | OK; `/app/staticfiles/css/app.css` present; prod-settings `collectstatic` OK |
| Review fix: Google bootstrap snippet had been pasted with line breaks inside `new` and a string literal (JS syntax error). Joined to one line; `node --check` OK; `manage.py test core.tests.test_ui` → 16 OK |

Re-run after review fix, with a keyless `.env` copied from `.env.example` (git-ignored): `docker compose build web tailwind` OK; `docker compose up -d --force-recreate` → db/web healthy, tailwind up; test suite **26 OK**; `check` → only W001/W002; `/`, `/?destination=`, `/?destination=Kochi`, `/ui/`, `/static/css/app.css`, `/healthz/`, `/readyz/` all 200; home shows "Google Maps isn't configured" and renders no Google loader.

Not run: browser rendering with real Google keys (none configured), device/visual screenshots (skipped per owner).

## Known risks / open questions
- Google Maps path is untested in a real browser: needs `GOOGLE_MAPS_BROWSER_KEY` + `GOOGLE_MAPS_MAP_ID`. Check autocomplete `gmp-select`, Map ID styling, AdvancedMarker, `gm_authFailure`, and that the bottom sheet doesn't cover Google's logo/terms on mobile.
- Template tests only grep HTML; they can't catch JS syntax errors (the loader bug above slipped past them). Consider a `node --check` step or a browser smoke test in CI.
- Google terms: Places/Maps content caching/storage limits; Google route alternatives can't guarantee crossing avoidance (ADR-004).
- PostGIS runs under amd64 emulation on Apple Silicon (slow). `libgdal-dev` makes the image large.
- MIT code license vs ODbL obligations for distributed OSM-derived data still to review.
- Routing engine with segment exclusion not chosen (Session 06).
- `main` is ahead of `origin/main` (Session 00/01 commits) and not pushed; Sessions 02 and 03 are uncommitted.
- Importer untested on real data: OSM tagging quirks at scale, `flex_mem` memory on the full India extract (use `--location-index dense_file_array,...`), and run time are unknown.
- Reconcile leaves tracks that cross the bbox boundary alone (`__within`), so stale boundary tracks can stay active after a regional refresh.
- No UI shows "© OpenStreetMap contributors" yet (needed once crossings render). The ODbL share-alike review for distributing DB dumps is still open.
- Test settings still read `.env`. Any test that depends on blank keys must override settings explicitly.

## Next steps
1. Owner: review and commit Sessions 02 + 03; push `main` when ready.
2. **Deferred by owner (2026-10-25):** Google key setup + browser check. `.env` exists (copied from `.env.example`, keys blank). When keys are added: `docker compose up -d --force-recreate web`, then verify map + Map ID style, Place Autocomplete, "Use my location" marker, and that the mobile sheet doesn't cover Google's logo/terms. Do this at the latest in Session 05 (map & location), which builds on the Google map.
3. Real Kochi import: download `southern-zone-latest.osm.pbf` (+ `.md5`) into `data/osm/`, run `--dry-run`, then `docker compose --profile import run --rm osm-import --source /data/osm/southern-zone-latest.osm.pbf --bbox 76.18,9.85,76.45,10.15`. Record counts, duration and DB size in RUNBOOK. Spot-check a few crossings against openstreetmap.org.
4. Session 05: nearby-crossing PostGIS query (active, non-suppressed, osm + manual) + map markers linking to `/crossings/<id>/` with source badge and "© OpenStreetMap contributors" attribution; wire the status JSON (`/api/crossings/<id>/status/`) into the map UI.
6. Google sign-in via a vetted package (replaces interim LoginView); keep admin-created accounts working.
7. Schedule `purge_crossing_reports` once Celery beat exists (Session 07); consider a JSON 403 body for API CSRF failures.
8. Add lint tooling (ruff) and a `node --check static/js/*.js` step; CI running `manage.py test` in Compose.
9. Slim the Dockerfile (runtime-only GDAL libs).
