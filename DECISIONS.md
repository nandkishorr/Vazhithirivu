# Architecture Decisions — Vazhithirivu

Record lasting decisions here. Add date, decision, rationale, and consequences. Do not log every small implementation detail.

## ADR-001 — Django server-rendered UI
- Status: Proposed
- Decision: Use Django templates with Tailwind CSS, HTMX and Alpine.js; Leaflet or Google Maps JavaScript API provides the map surface.
- Rationale: Fast MVP delivery, low frontend complexity, server-rendered product and familiar Python backend.
- Consequence: Keep interactive map behavior in focused JavaScript modules rather than building a separate SPA.

## ADR-002 — PostGIS is the local geographic query source
- Status: Proposed
- Decision: Import OSM-derived crossing/track data into PostgreSQL/PostGIS and query locally.
- Rationale: Avoid a network data query for every user or GPS update; support spatial indexes and city/route queries.
- Consequence: Build an idempotent importer and documented refresh/reconciliation workflow. Do not run full imports at web startup.

## ADR-003 — Separate geography, incidents, real users, and simulation
- Status: Proposed
- Decision: OSM reference geometry, live/community reports, real-user data and simulator records are distinct concerns with explicit source/run IDs.
- Rationale: Prevent simulated states from corrupting reference data or misleading real users.
- Consequence: Simulator start/stop/reset must never mutate or delete real-user records.

## ADR-004 — Routing provider abstraction and detour verification
- Status: Proposed
- Decision: Hide routing providers behind a service interface and validate candidate routes against affected crossings.
- Rationale: A provider's alternative route is not guaranteed to avoid an arbitrary road segment.
- Consequence: Only offer a detour as verified if geometry/topology confirms avoidance; otherwise communicate uncertainty.

## ADR-005 — Opt-in location sharing
- Status: Proposed
- Decision: Request browser location only after explicit user action; allow immediate stop; minimize retention and restrict access.
- Rationale: Protect precise location privacy.
- Consequence: Do not collect location silently or broadcast exact coordinates publicly by default.

## ADR-006 — All services run as containers
- Status: Accepted (2026-10-24, project owner)
- Decision: PostgreSQL/PostGIS, Redis, web, Celery workers, importer jobs and the simulator all run as Docker Compose services. Development and tests do not use host-installed Postgres/Redis/GDAL.
- Rationale: Reproducible environments. The host Postgres (Homebrew 17) lacks PostGIS and the host lacks GDAL.
- Consequences: The web image must include GDAL/GEOS/PROJ. Tests run via `docker compose run --rm web …`. Don't publish the DB on host port 5432, because Homebrew Postgres already uses it. `postgis/postgis` images are amd64-only, so pin an image and document whether emulation or a multi-arch image is used on Apple Silicon.
- Implementation (Session 01, 2026-10-25): `docker-compose.yml` with `db` (`${POSTGIS_IMAGE:-postgis/postgis:17-3.5}`, `platform: linux/amd64`, owner chose official images over multi-arch community images; `16-3.4` selectable) and `web` (python:3.12-slim-bookworm + GDAL/GEOS/PROJ). DB port not published.

## ADR-007 — Environment-driven split settings, PostGIS-only database
- Status: Accepted (2026-10-25, Session 01)
- Decision: `config/settings/{base,dev,test,prod}.py` read config via `django-environ` (`.env` optional, real env wins). `DATABASE_URL` must resolve to the PostGIS backend; there is no SQLite fallback. Prod requires a real `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`. Static files use WhiteNoise; WSGI runs on gunicorn. Redis/Celery/Channels are deferred until a feature needs them (realtime, Session 07).
- Rationale: Spatial features must never silently run on a database that cannot support them. Booting dev must need no paid keys or secrets.
- Consequences: Tests require the Compose PostGIS service. `/healthz/` (liveness) and `/readyz/` (DB + PostGIS) are the operational checks.

## ADR-008 — Tailwind v4 standalone CLI, no Node toolchain
- Status: Accepted (2026-10-25, Session 02)
- Decision: Compile Tailwind CSS v4 (pinned 4.3.3, per-arch sha256 verified) with the standalone CLI in a `tailwind` Dockerfile stage; the app image copies the compiled `static/css/app.css` before `collectstatic`. Dev uses the Compose `tailwind` watcher service. Compiled CSS is not committed.
- Rationale: No npm/Node dependency tree just for CSS; reproducible, checksum-verified builds.
- Consequences: Upgrading Tailwind = bump `TAILWIND_VERSION` + both checksums (see RUNBOOK). `@source` must include `core/**/*.py` because badge classes live in template tags.

## ADR-009 — Google Maps Platform as the map and place-search provider
- Status: Accepted (2026-10-25, owner decision; supersedes the Leaflet option in ADR-001)
- Decision: Map UI uses the Maps JavaScript API (official dynamic bootstrap loader, cloud-styled via `GOOGLE_MAPS_MAP_ID`); origin/destination search uses Places API (New) `PlaceAutocompleteElement`. Embed-API iframes are not used because overlays (crossings, user location, routes) are impossible on them. Leaflet is removed. No frontend drawing beyond the opt-in user-location marker for now.
- Rationale: Owner requirement for Google Maps UI and Google place search.
- Consequences: Keys come from `.env` (`GOOGLE_MAPS_BROWSER_KEY`, `GOOGLE_MAPS_MAP_ID`, `GOOGLE_MAPS_SERVER_KEY`); missing keys produce system-check warnings `core.W001/W002` and a "not configured" map state, never a crash. The server key is never rendered. Railway/crossing data still comes from OSM in PostGIS (ADR-002); Google route alternatives still require detour verification (ADR-004). Tests never call Google.

## ADR-010 — OSM railway import: pyosmium, upsert by identity, scoped soft-delete reconciliation
- Status: Accepted (2026-10-25, Session 03)
- Decision: A separate `railways` app holds reference data (`RailwayCrossing` points, `RailwayTrack` lines, `OsmImportRun` provenance). `import_osm_railways` reads a local PBF/XML extract with pyosmium (C++-side `KeyFilter("railway")` + location index), and upserts in per-batch transactions keyed by a non-partial unique `(osm_type, osm_id)`. Runs are serialized with a Postgres advisory lock. Filters are explicit (default crossings `railway=level_crossing`; tracks `rail`, `narrow_gauge`, `light_rail`). Reconciliation is opt-in (`--reconcile`). It runs only after a fully successful import, only inside the run's coverage bbox and filter values, and only as a soft delete (`is_active=False`). It aborts above `--max-deactivate-fraction` (default 0.2). `source='manual'` rows and admin suppression/notes are never touched by the importer.
- Rationale: Reruns must be idempotent, restartable and safe. A partial or regional extract must never mass-delete data outside it. OSM is incomplete, so admin corrections must survive refreshes.
- Consequences: A failed run leaves the earlier batches it already wrote (newer valid data) and marks itself failed; rerunning is the restart path. No live status is stored on crossing rows (ADR-003). Road segments are deferred to routing (Session 06). Data is downloaded manually; the importer never touches the network.

## ADR-011 — Community crossing reports: login-only, deterministic derived status
- Status: Accepted (2026-10-25, Session 04)
- Decision: A separate `incidents` app owns `CrossingReport` (FK to `RailwayCrossing`, PROTECT) — incident data never mutates the reference crossing row (ADR-003). Reports store `reported_state` (open/closed only), `source` (`community` only for now; the simulator will add a run-scoped source later), `reporter` (FK, SET_NULL, never exposed publicly), `created_at`/`expires_at` and moderation fields. No reporter location or IP is stored.
- Derived status is computed on read in `incidents.services.derive_status` from visible community reports only: a report is fresh for `REPORT_FRESH_MINUTES` (15, strict `expires_at > now`), shown stale until `REPORT_STALE_MINUTES` (60), then the state is `unknown`. Absence of reports is never "open". Only the newest report per reporter counts (dedup); opposite-state reports within `REPORT_CONFLICT_WINDOW_MINUTES` (5) of the newest produce `conflicting` with plain supporting/opposing counts — an older opposite report is a gate transition, not a conflict. No percentages or probabilities.
- Submission policy in `create_report` (transaction + `select_for_update` on the user row): authenticated active users only; duplicate same-state report inside `REPORT_DUPLICATE_WINDOW_MINUTES` (2) returns the existing row; flipping state within `REPORT_MIN_FLIP_SECONDS` (30) and `REPORT_MAX_PER_HOUR` (20) reports/hour raise `RateLimited`. Rate limiting is per-user and DB-based — no Redis.
- Moderation is admin-only: reports can't be added via admin, staff hide/restore via actions or the change form (`moderated_by`/`moderated_at` recorded). Hidden reports are excluded everywhere public. Retention is 30 days via the manual/cron `purge_crossing_reports` command (no Celery yet).
- Auth is the interim Django `LoginView`/`LogoutView` at `/accounts/`; accounts are created by an administrator until Google sign-in lands (vetted package, future session). Public read endpoints expose only anonymised fields (state, created_at, age, source).
- Rationale: transparent, deterministic rules are auditable and safe for MVP; keeping reports append-only and anonymised protects reporters and prevents "no report = open" misreadings.
- Consequences: Derived status is recomputed per request (cheap at this scale); a materialized snapshot can come later if needed. JSON API (`/api/crossings/<pk>/status|reports/`) exists for the future map UI; HTML PRG form is the only submission UI for now.

## Updating decisions
When a proposal becomes implemented, update its status and include the implementation reference/PR if known. Add a new ADR rather than silently rewriting a decision whose rationale materially changed.
