# Vazhithirivu (വഴിത്തിരിവ്)

**Smart routes. Smarter crossings.** — a railway level-crossing intelligence and
rerouting app for Kerala. It shows live community-reported gate status on a map,
warns you when a crossing on your route is (probably) closed, and verifies
whether an alternative route genuinely avoids it.

## Table of contents

- [What it does](#what-it-does)
- [Tech stack](#tech-stack)
- [Architecture overview](#architecture-overview)
- [The four data planes](#the-four-data-planes)
- [Django apps](#django-apps)
- [How crossing status works](#how-crossing-status-works)
- [How routing and verified detours work](#how-routing-and-verified-detours-work)
- [How the simulator works](#how-the-simulator-works)
- [Journey sessions and privacy](#journey-sessions-and-privacy)
- [Frontend architecture](#frontend-architecture)
- [API surface](#api-surface)
- [Infrastructure](#infrastructure)
- [Getting started](#getting-started)
- [Testing](#testing)
- [Honesty and safety rules](#honesty-and-safety-rules)
- [Documentation map](#documentation-map)

## What it does

- Renders imported **OSM level crossings** on a Google Map, colored by a
  derived open/closed status.
- **Community reports** (open/closed, login-only) drive a deterministic,
  auditable status — no AI, no percentages, no "official" claims.
- **Same-line inference**: a reported/surfaced closure propagates one hop to the
  neighboring crossings on the same rail line, clearly labelled "likely".
- **Route planning** through the Google Routes API, with per-route crossing
  analysis and *geometry-verified* avoidance — a detour is only called
  "verified" when the math proves it clears the blocked crossing.
- **Journey mode**: opt-in position checks that alert you to closed gates
  ahead — positions are never stored.
- **An isolated simulator** that demos the full loop: static simulated users
  parked at a physically-closed gate → presence inference raises a confirmation
  prompt → a human confirms → the crossing shows "simulated closed" and routes
  replan around it.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12 · Django 5.2 (server-rendered templates) |
| Spatial DB | PostgreSQL 17 + PostGIS (all crossing/track/track-graph queries) |
| Map / places | Google Maps JavaScript API + Places API (New) + Geocoding API |
| Routing | Google Routes API `computeRoutes` (server-side) |
| Realtime | Django Channels + Daphne over Redis (`channels-redis`) |
| CSS | Tailwind CSS v4 (standalone CLI, checksum-verified, no Node) |
| OSM import | pyosmium (local PBF/XML extracts — never live Overpass calls) |
| Auth | Django auth + `django-allauth` Google OAuth (password signup closed) |
| Deploy | Docker Compose: `db`, `redis`, `web`, plus opt-in profiles |

## Architecture overview

```text
                          ┌──────────────────────────────────────────┐
                          │              Browser (map.js)             │
                          │  Google Map · markers · routes · journey  │
                          └───────┬───────────────▲──────────┬────────┘
                  HTTP/JSON (API) │               │ WS push  │ WS sim
                                  │               │          │
┌─────────────────────────────────▼───────────────┴──────────▼────────┐
│                        Django (daphne / runserver)                  │
│                                                                     │
│  core ──► home page, health, auth glue, ui kit                      │
│                                                                     │
│  railways ──► OSM reference: crossings · tracks · import runs       │
│               └─ CrossingLink (same-line topology graph)            │
│                                                                     │
│  incidents ──► CrossingReport + status derivation engine            │
│                ├─ derive_status(es)   (community only)              │
│                ├─ effective_status(es) (community ⊕ overlay ⊕ infer)│
│                └─ publish → WS group crossing.<pk>                  │
│                                                                     │
│  routing ──► plan_route: Google computeRoutes → candidate analysis  │
│              → detour verification / via-point synthesis            │
│                                                                     │
│  navigation ──► JourneySession tokens, transient position checks    │
│                                                                     │
│  simulator ──► run-scoped demo world; registers a status overlay    │
│                hook into incidents (one-directional)                │
└────────┬───────────────────┬───────────────────────┬───────────────┘
         │                   │                       │
   ┌─────▼─────┐      ┌──────▼──────┐        ┌───────▼────────┐
   │  PostGIS  │      │    Redis    │        │ Google Routes  │
   │ reference │      │ channel +   │        │ API (server    │
   │  + state  │      │ shared cache│        │ key, ToS-bound)│
   └───────────┘      └─────────────┘        └────────────────┘
```

## The four data planes

The single most important architectural rule (ADR-003): four kinds of data are
kept strictly separate, and merging happens **only at read time** in the status
service — never by mutating rows.

| Plane | Lives in | Written by | Key rule |
|---|---|---|---|
| **Reference geography** | `railways_*` | `import_osm_railways`, admin | No live status on these rows, ever |
| **Community incidents** | `incidents_crossingreport` | Logged-in users | Append-only, expiring, moderated |
| **Real users** | `navigation_journeysession` | Journey API | Sessions store no coordinates/route/identity |
| **Simulation** | `simulator_*` | `run_simulator` / `simulator` command | Never touches the other three; all rows cascade-delete with the run |

```text
  community reports ──► derive_status ──┐
                                        ├──► effective_status ──► UI / API / routing
  simulator overlay ──► (hook) ────────┤          │
                                        │        ▼
  crossing links (same line) ──► propagation: *_inferred
```

- `derive_status(es)` reads **community reports only** — used for the
  "community" half of a merged payload.
- `effective_status(es)` merges in the registered simulator overlay, then
  propagates live states to `CrossingLink` neighbours as `*_inferred`.
- The simulator registers its overlay via `incidents.services.register_
  status_overlay()` at app-ready; `incidents` never imports `simulator`.

## Django apps

| App | Responsibility |
|---|---|
| `config/` | Split settings (`base/dev/test/prod`), ASGI/WSGI, root URLs. Env-driven via `django-environ`; PostGIS-only `DATABASE_URL` — no SQLite fallback. |
| `core/` | Home view (`/` — the whole product page), `/healthz/` + `/readyz/`, auth adapters (Google sign-in, closed password signup), context processors, system checks, UI template tags, `ui/` gallery. |
| `railways/` | `RailwayCrossing` (points), `RailwayTrack` (lines), `OsmImportRun` (provenance), `CrossingLink` (same-line topology). Importer + `link_crossings` + spatial queries (`crossings_in_bbox`, `crossings_near_point`). |
| `incidents/` | `CrossingReport` + the status engine (`services.py`), report submission form/API, bbox map API, WebSocket consumer (`ws/crossings/`), publish fan-out, retention purge. |
| `routing/` | `plan_route` service, `GoogleRoutesProvider` (stdlib urllib), route↔crossing analysis (raw PostGIS SQL), detour verification + via-point synthesis, per-client throttle. No routing models — Google ToS bars persisting route content. |
| `navigation/` | `JourneySession` (UUID capability token), session/position/end API, per-client + per-session throttles, retention purge. |
| `simulator/` | `SimulationRun`/`SimulatedVehicle`/`SimulationGateEvent`/`SimulationPrompt`/`SimulationEvent`, tick engine, `ws/simulation/` consumer, sim API, management commands. Optional Compose profile. |

## How crossing status works

All statuses are **derived on read** — nothing stores "the current state" on a
crossing row.

### Community reports → derived status (`incidents.services.derive_status`)

- A report is `open` or `closed`, has `created_at`/`expires_at`, a `source`
  (`community`) and a `reporter` (never exposed publicly; no IP/location kept).
- Fresh window: `REPORT_FRESH_MINUTES` (15). Stale until
  `REPORT_STALE_MINUTES` (60). After that → `unknown`.
- Only the newest report per reporter counts (dedup). Opposite-state reports
  within `REPORT_CONFLICT_WINDOW_MINUTES` (5) of the newest → `conflicting`
  with plain supporting/opposing counts.
- **Absence of reports is never "open".**
- Submission guards (`create_report`, transactional): login required,
  duplicate-window dedup, min flip interval, hourly cap — all DB-based, no
  Redis needed.

### Full state list

| State | Meaning |
|---|---|
| `unknown` | No usable reports |
| `stale` | Newest report too old to rely on |
| `open_reported` / `closed_reported` | Fresh community consensus |
| `conflicting` | Recent reports disagree |
| `open_simulated` / `closed_simulated` | Active sim run's gate event (always labelled) |
| `open_inferred` / `closed_inferred` | Propagated from a same-line neighbour ("likely") |

Merge rules: a community `closed_reported` always beats the overlay; only an
**active** run contributes simulated states; inference is **one hop**, only
onto `unknown`/`stale` targets, and closed beats open when links disagree.

### Same-line propagation (ADR-020)

`railways.topology.rebuild_crossing_links` builds a vertex/edge graph from
imported track ways, snaps each crossing to a vertex (≤ 30 m), and Dijkstras
out to the ≤ 3 nearest crossings along the connected track network (≤ 15 km).
Links rebuild after every OSM import or via `manage.py link_crossings`. A live
`closed`/`open` (reported *or* simulated) surfaces on linked neighbours as
`closed_inferred`/`open_inferred` with provenance (`inference: {from, distance,
source_state}`) — so a train's gate cycle shows up at the next crossings on the
line, honestly labelled.

### Realtime fan-out (ADR-014)

`CrossingReport` `post_save`/`post_delete` → `transaction.on_commit` →
re-derive → `group_send` to `crossing.<pk>` (and linked neighbours' groups).
Clients of `ws/crossings/` subscribe by crossing ID (whole-set replace, ≤ 500),
get a `status.snapshot` on subscribe, and drop out-of-order frames via `as_of`.
The bounded bbox HTTP refetch (≤ 1/min while visible) remains the fallback and
covers time-based ageing (expiry produces no DB event).

## How routing and verified detours work

`routing.services.plan_route` (`GET /` with origin/destination params; also
`format=json` for no-reload reroutes):

1. **Throttle** — per client per clock hour (`ROUTING_MAX_REQUESTS_PER_HOUR`,
   shared cache).
2. **Provider call** — `GoogleRoutesProvider.compute_routes` (Routes API,
   `TRAFFIC_UNAWARE` default; server key, urllib; alternatives in one call).
3. **Crossing analysis** (`routing.analysis`, raw PostGIS SQL): a crossing is
   `on_route` only if the polyline passes within 20 m **and** a mapped track
   intersects within 30 m of the node; within 50 m without track evidence →
   `possible`.
4. **Status** — one bulk `effective_statuses` call per route set.
5. **Blocking** — primary-route crossings in a blocking state
   (`closed_reported`, `closed_simulated`, `closed_inferred`).
6. **Verification** (only when blocking is non-empty): an alternative is
   `verified` iff every blocking crossing is > 100 m from it **and** it has no
   blocking crossing of its own. Otherwise it's honestly labelled `passes` /
   `uncertain` / `unverifiable`. A route switch is always user-confirmed.
7. **Detour synthesis** — if the provider returned a single route while
   something blocks, synthesize ≤ 2 extra candidates through a `via` waypoint
   offset 300 m perpendicular at the blocked crossing ("Detour via side
   roads"). Identical verification applies; deduped; each call spends throttle
   budget; `ROUTE_DETOUR_ENABLED=0` disables.
8. **Auto-select** — when the primary route is blocked and an alternative
   verifies, `RoutePlan.preferred_route_id` selects it automatically
   ("Recommended" badge, visible panel, selected polyline). The blocked route
   stays selectable as "Route 1" with its full warning — the detour is
   preferred, never the closure hidden (ADR-021).

The map UI also supports click-to-route (POI `placeId` or a reverse-geocoded
point), "Route here" from a crossing card, and an "Open in Google Maps"
universal directions handoff — labelled as Google's own path, never ours.

## How the simulator works

Optional, isolated, and designed to rehearse the product's real premise:
*inferring* gate state from user presence, with human confirmation.

```text
--gate 8:1:40  (physical truth: gate at crossing 8 closed between ticks 1–40)
        │
        ▼
static users parked at the crossing count as waiting (SIM_QUEUE_* slots)  ──  hidden truth
        │
        ▼  dwell detection: ≥ MIN_USERS waiting ≥ DWELL_SECONDS within RADIUS
SimulationPrompt (pending) ──► violet card in the UI / sim.prompt WS frame
        │
        ├── confirm ──► SimulationGateEvent(closed) ──► closed_simulated
        ├── dismiss ──► nothing
        └── TTL / reopen / run end ──► expired
```

- `SimulationRun` holds config + lifecycle + heartbeat; `active_slot` enforces
  **at most one active run** at the DB level; stale `running` rows are stopped
  on heartbeat loss.
- Simulated users are **static** (ADR-021): each one parks in a queue slot
  near a real crossing and never moves — the `wait` flag (darkened pin)
  tracks gate truth. Positions publish in coarse ticks on `ws/simulation/`.
- Reset/stop never deletes real-user data — every row is run-scoped and
  cascade-deletes. The status overlay disappears the moment no run is active.
- `--auto-confirm` resolves prompts through the same code path for click-free
  demos. Without Redis, `/api/simulation/` polling is the WS fallback.

## Journey sessions and privacy

Location privacy is a design constraint (ADR-005/ADR-017), not a disclaimer:

- Geolocation is requested only after an explicit click; a Stop control halts
  it immediately (a token invalidates late callbacks).
- "My location" *choice* persists in `localStorage`; coordinates never do.
- Journey mode (`watchPosition`) POSTs positions to a `JourneySession` — a
  UUID capability token storing **no coordinates, route or identity**. The
  position is answered transiently (`crossings_near_point` + one bulk status
  call) and **never persisted** — asserted by tests.
- Sessions expire (`NAV_SESSION_MAX_HOURS`), are throttled
  (`NAV_MAX_SESSIONS_PER_HOUR`, `NAV_MIN_UPDATE_SECONDS`), and are purged by
  `purge_navigation_sessions`. Ended/expired → `410`; too fast → `429`.
- CSRF stays on for real-user APIs (the csrf-exempt sim endpoints only mutate
  `simulator_*` demo rows). No location data exists on any WebSocket channel.
- The bbox map API necessarily reveals which rounded viewport a client looked
  at — documented in ADR-012.

## Frontend architecture

- Server-rendered Django templates + Tailwind v4; `static/js/map.js` is the
  one interactive module (Google Maps JS API, `AdvancedMarkerElement` with a
  `GOOGLE_MAPS_MAP_ID`, legacy-marker fallback without it).
- Crossings load via `GET /api/crossings/?bbox=` on map `idle` (300 ms
  debounce, zoom ≥ 12, ≤ 500/box, `truncated` flag, 20 % padding, 60 s
  staleness guard, request aborting — no polling loop). Markers are diffed by
  id, never rebuilt.
- Status pins are level-crossing warning signs — status color + glyph (✕/✓/!/≈/?)
  so status never depends on color alone; badge + legend vocabulary matches.
- Reroutes swap `#route-result` innerHTML with a server-rendered partial
  (`format=json` → `{route_state, html, route_data}`) and `history.pushState`;
  failure falls back to full navigation.
- Journey UI: teal marker + heading arrow, pre-navigation blocking warning,
  red alert popup for gates in `NAV_ALERT_RADIUS_M`, dismiss-until-change.
- Simulated users/markers/cards are always visibly labelled.

## API surface

### HTTP

| Endpoint | Purpose |
|---|---|
| `GET /` | Map-first home; route planning params; `format=json` for partial reroute |
| `GET /healthz/` · `/readyz/` | Liveness · readiness (DB + PostGIS) |
| `GET /crossings/<pk>/` | Crossing detail page |
| `POST /crossings/<pk>/report/` | Submit an open/closed report (login) |
| `GET /api/crossings/?bbox=w,s,e,n` | Bounded crossing + status fetch for the viewport |
| `GET /api/crossings/<pk>/status/` · `/reports/` | Single-crossing status · anonymised reports |
| `POST /api/navigation/sessions/` | Start a journey session (throttled → `429`) |
| `POST /api/navigation/sessions/<uuid>/position/` | Transient position check → nearby crossings + `alerts` |
| `POST /api/navigation/sessions/<uuid>/end/` | End a session (idempotent) |
| `GET /api/simulation/` | Sim snapshot (run, vehicles, gates, prompts) — poll fallback |
| `POST /api/simulation/prompts/<id>/confirm\|dismiss/` | Resolve a gate-check prompt (csrf-exempt, sim rows only) |
| `GET/POST /accounts/…` | Login/logout + `allauth` (`/accounts/google/login/`) |
| `/admin/` | Reference data, reports moderation, runs, links (read-only where derived) |

### WebSocket

| Channel | Frames |
|---|---|
| `ws/crossings/` | `subscribe {crossing_ids}` → `status.snapshot`, `crossing.status` pushes |
| `ws/simulation/` | `sim.snapshot`, `sim.tick` (vehicles/gates/prompts), `sim.prompt`, `sim.prompt.resolved` |

## Infrastructure

`docker-compose.yml` services:

| Service | Role |
|---|---|
| `db` | `postgis/postgis:17-3.5` (`linux/amd64`; `16-3.4` supported). Port not published — host Postgres may own 5432. |
| `redis` | `redis:7-alpine` — channel layer + shared cache (routing/nav throttles, push dedup). Blank `REDIS_URL` = per-process in-memory fallback (single process only; `incidents.W001` warns). |
| `web` | Django dev server; prod image runs `daphne` (HTTP+WS) or `gunicorn` (WSGI only). Includes GDAL/GEOS/PROJ. |
| `osm-import` | Profile `import` — one-shot `import_osm_railways` against `data/osm/*.pbf`. Never runs at web startup. |
| `simulator` | Profile `simulation` — `run_simulator` tick loop. App works without it. |
| `tailwind` | Dev watcher rebuilding `static/css/app.css` (standalone CLI, pinned+sha256-verified — no Node). |

The `Dockerfile` has two stages: `tailwind` (compiles CSS) → app image (copies
the compiled CSS, runs `collectstatic` + `gunicorn`/`daphne`).

## Getting started

Full operational detail lives in [`RUNBOOK.md`](RUNBOOK.md); this is the
complete path from zero to a running demo.

### Prerequisites

- Docker Desktop (or Docker Engine + Compose v2). **No host Python, Postgres,
  GDAL or Node needed** — everything runs in containers (ADR-006).
- Apple Silicon: `postgis/postgis` is amd64-only; Compose runs it emulated
  (`platform: linux/amd64` is already set).
- Optional: a Google Cloud project with billing — needed for the live map,
  place search, routing and sign-in. The app boots without it (the map shows
  "not configured", the Google button hides), so you can explore
  Django/OSM/reports first.

### 1 · Environment file

```bash
cp .env.example .env
```

`.env` is git- and docker-ignored — never commit it. Real environment
variables always win; `DJANGO_READ_DOT_ENV=0` ignores the file. Dev defaults
boot with an empty or missing `.env`; you only must edit it for Google keys
and production.

### 2 · Keys and environment variables

Core (dev defaults work; **bold** = required in production):

| Variable | Dev default | Notes |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | `dev` / `test` / `prod` |
| `DJANGO_SECRET_KEY` | `change-me` | **Required in prod** — 50+ random chars |
| `DJANGO_DEBUG` | `true` | `false` in prod |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | **Required in prod** |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | — | `https://…` origins in prod |
| `DJANGO_LOG_LEVEL` | `INFO` | |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `vazhithirivu` | Compose `db` container credentials |
| `DATABASE_URL` | composed by Compose | Must be `postgis://…` — any other backend fails loudly |
| `POSTGIS_IMAGE` | `postgis/postgis:17-3.5` | `16-3.4` also supported |
| `WEB_PORT` | `8000` | Host port for the app |
| `REDIS_URL` | `redis://redis:6379/0` | Blank = in-process fallback (single process only) |
| `EMAIL_BACKEND` | console (dev) | SMTP in prod for allauth account mail |

Google Maps Platform — all optional for boot, needed for the real product:

| Variable | Used by | Scope |
|---|---|---|
| `GOOGLE_MAPS_BROWSER_KEY` | Maps JS API, Places API (New), Geocoding API | Rendered into pages — public by design |
| `GOOGLE_MAPS_MAP_ID` | Cloud map styling + `AdvancedMarkerElement` | Rendered into pages |
| `GOOGLE_MAPS_SERVER_KEY` | Routes API `computeRoutes` | Server-side only — never sent to the browser |
| `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET` | "Sign in with Google" (django-allauth) | Server-side; button hidden until both set |

Google Cloud Console steps:

1. Create/select a project, enable billing.
2. APIs & Services → Library → enable **Maps JavaScript API**, **Places API
   (New)**, **Geocoding API** (browser key) and **Routes API** (server key).
3. Credentials → **Create API key** ×2:
   - Browser key — restrict by HTTP referrer (`localhost:8000/*` + your prod
     origin) and to the three browser APIs.
   - Server key — restrict to Routes API, **no** referrer restriction
     (server-to-server); add an IP restriction in prod.
4. Map Management → create a **Map ID** (also unlocks cloud styling).
5. Credentials → **OAuth client ID** (Web application), authorized redirect
   URI `http://localhost:8000/accounts/google/login/callback/` — plus your
   `https://` origin in prod. Same project as the Maps keys.
6. Put all five values in `.env`, restart `web`.

Behaviour tuning — every knob has a sane default in `.env.example`; uncomment
to change:

- **Reports**: `REPORT_FRESH_MINUTES`, `REPORT_STALE_MINUTES`,
  `REPORT_CONFLICT_WINDOW_MINUTES`, `REPORT_DUPLICATE_WINDOW_MINUTES`,
  `REPORT_MIN_FLIP_SECONDS`, `REPORT_MAX_PER_HOUR`, `REPORT_RETENTION_DAYS`
- **Map API**: `MAP_CROSSINGS_LIMIT`, `MAP_BBOX_MAX_SPAN_DEG`,
  `MAP_CROSSINGS_MIN_ZOOM`, `MAP_DEFAULT_LAT/LNG/ZOOM`
- **Realtime**: `REALTIME_MAX_SUBSCRIPTIONS`, `REALTIME_SUBSCRIBE_MIN_SECONDS`
- **Routing**: `ROUTING_PROVIDER`, `ROUTING_TIMEOUT_SECONDS`,
  `ROUTING_GOOGLE_ROUTING_PREFERENCE`, `ROUTING_MAX_REQUESTS_PER_HOUR`,
  `ROUTE_CROSSING_ON_ROUTE_M`, `ROUTE_CROSSING_NEAR_M`, `ROUTE_TRACK_MATCH_M`,
  `ROUTE_AVOID_CLEARANCE_M`, `ROUTE_DETOUR_ENABLED`,
  `ROUTE_DETOUR_VIA_OFFSET_M`, `ROUTE_DETOUR_MAX_CALLS`
- **Same-line links**: `RAILWAY_LINK_MAX_NEIGHBORS`, `RAILWAY_LINK_SNAP_M`,
  `RAILWAY_LINK_MAX_DISTANCE_M`
- **Simulator**: `SIM_TICK_SECONDS`, `SIM_DEFAULT_VEHICLES`,
  `SIM_MAX_VEHICLES`, `SIM_DEFAULT_DURATION_SECONDS`, `SIM_PATH_LENGTH_M`,
  `SIM_HEARTBEAT_STALE_SECONDS`, `SIM_DWELL_RADIUS_M`, `SIM_DWELL_SECONDS`,
  `SIM_DWELL_MIN_USERS`, `SIM_PROMPT_TTL_SECONDS`, `SIM_QUEUE_GAP_M`,
  `SIM_QUEUE_SPACING_M`
- **Journeys**: `NAV_ALERT_RADIUS_M`, `NAV_NEARBY_RADIUS_M`,
  `NAV_NEARBY_LIMIT`, `NAV_MIN_UPDATE_SECONDS`, `NAV_MIN_UPDATE_DISTANCE_M`,
  `NAV_SESSION_MAX_HOURS`, `NAV_MAX_SESSIONS_PER_HOUR`,
  `NAV_SESSION_RETENTION_DAYS`

### 3 · Build, migrate, run

```bash
docker compose build web        # app image (tailwind stage compiles CSS first)
docker compose up -d            # db + redis + web + tailwind watcher
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser   # admin/reporter login
# → http://localhost:8000   (change the host port via WEB_PORT)
```

Verify:

```bash
curl -i localhost:8000/healthz/   # 200 {"status":"ok"} (no DB)
curl -i localhost:8000/readyz/    # 200 {"status":"ok","checks":{"database":"ok","postgis":"ok"}}
```

Daily commands:

```bash
docker compose run --rm web python manage.py check         # system checks
docker compose exec db psql -U vazhithirivu -d vazhithirivu
docker compose down          # stop (data persists in the pgdata volume)
docker compose down -v       # ⚠ stop AND delete the database
```

### 4 · Import crossings (OSM → PostGIS)

Download a Geofabrik extract once — manual, nothing fetches at startup:

```bash
mkdir -p data/osm
curl -fLO --output-dir data/osm \
  https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf
curl -fLO --output-dir data/osm \
  https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf.md5
(cd data/osm && md5sum -c southern-zone-latest.osm.pbf.md5)
```

Dry-run first, then import the Kochi demo area:

```bash
docker compose --profile import run --rm osm-import \
  --source /data/osm/southern-zone-latest.osm.pbf --dry-run

docker compose --profile import run --rm osm-import \
  --source /data/osm/southern-zone-latest.osm.pbf \
  --source-url https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf \
  --bbox 76.18,9.85,76.45,10.15
# same-line links rebuild automatically at the end of every import; or:
docker compose run --rm web python manage.py link_crossings
```

Key flags: `--bbox minlon,minlat,maxlon,maxlat` · `--reconcile` (soft-deletes
rows gone from the new extract, abort-guarded by
`--max-deactivate-fraction`) · `--batch-size` ·
`--crossing-values`/`--track-values` · `--location-index
dense_file_array,/tmp/osm-idx` for the ~1.6 GB full-India file · `--dry-run`.
Reruns are idempotent (`(osm_type, osm_id)` upserts); `source='manual'` rows
are never touched.

### 5 · Simulator (optional)

```bash
docker compose --profile simulation up -d simulator    # tick service
docker compose exec web python manage.py simulator start \
  --vehicles 60 --seed 42 --duration 600 --gate 8:3:60
docker compose exec web python manage.py simulator status
docker compose exec web python manage.py simulator pause / resume / stop
docker compose exec web python manage.py simulator tick --n 10   # manual drive
docker compose exec web python manage.py simulator reset          # delete ALL sim rows
# watch parked users darken → confirm the "Simulated gate check" card →
# crossing turns simulated-closed → routes through it auto-select a
# verified detour
```

`--gate ID:CLOSE[:OPEN]` is repeatable; `--random-gates N` picks seeded
crossings; `--auto-confirm` confirms prompts instantly. `reset` refuses while
a run is active and deletes only `simulator_*` rows.

### 6 · Maintenance commands

```bash
docker compose run --rm web python manage.py purge_crossing_reports --dry-run
docker compose run --rm web python manage.py purge_crossing_reports      # REPORT_RETENTION_DAYS
docker compose run --rm web python manage.py purge_navigation_sessions   # NAV_SESSION_RETENTION_DAYS
docker compose run --rm tailwind tailwindcss \
  -i assets/tailwind/input.css -o static/css/app.css --minify            # one-off CSS rebuild
```

## Testing

```bash
docker compose run --rm web python manage.py test --settings=config.settings.test
docker compose run --rm web python manage.py check
```

332 tests (as of Session 14) covering: importer idempotency on fixtures (no
live Overpass), spatial queries and route-crossing association, status
freshness/conflict/dedup/throttle, propagation + detour synthesis, WS
protocols, journey-session privacy (schema has no coordinate columns), and
simulator isolation (it cannot mutate real-user rows). External providers are
always faked/mocked — tests never call Google.

## Honesty and safety rules

These are load-bearing product rules, not marketing copy:

- Community/simulated/inferred status is **never** presented as official
  railway information; simulated values are always labelled.
- No report ≠ open gate. Stale or conflicting reports mean uncertainty, shown
  as such.
- A route is only called "avoids" after geometry verification — otherwise the
  UI says exactly what is and isn't known.
- The app never advises crossing a closed gate or bypassing barriers.
- No fabricated coordinates, durations, or statuses anywhere.
- Secrets stay in `.env` (gitignored); `.env.example` holds placeholders.

## Documentation map

| File | Contents |
|---|---|
| [`RUNBOOK.md`](RUNBOOK.md) | Setup, import, simulator, realtime, Google keys, smoke tests, troubleshooting |
| [`DECISIONS.md`](DECISIONS.md) | ADR-001…021 — every architectural decision and its rationale |
| [`DATA_SOURCES.md`](DATA_SOURCES.md) | OSM/Geofabrik + ODbL, Google Platform terms, attribution, licensing |
| [`ROADMAP.md`](ROADMAP.md) | Milestones M0–M6 and status |
| [`PROJECT_STATE.md`](PROJECT_STATE.md) | Session-by-session handoff: what changed, actual test results, next steps |
| [`AGENTS.md`](AGENTS.md) | Contributor/agent rules and session workflow |
| `.agents/skills/vazhithirivu/` | Reusable engineering workflow/invariants |
| [`MASTER_PROMPT.md`](MASTER_PROMPT.md) · `prompts/` | Original product spec and session prompt bundle |

## Attribution

Map imagery & place/route data: Google Maps Platform (see `DATA_SOURCES.md`
for terms). Railway/crossing reference data: © OpenStreetMap contributors,
ODbL (Geofabrik extracts). Icons: Lucide (ISC). Tailwind CSS (MIT).
