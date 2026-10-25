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
- Status: Implemented by ADR-013 (Session 06)
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

## ADR-012 — Map crossings via bounded bbox API; browser-only geolocation
- Status: Accepted (2026-10-25, Session 05)
- Decision: `GET /api/crossings/?bbox=w,s,e,n` (incidents app) replaces the home page's embedded crossing JSON. `railways.queries.parse_bbox` validates the box (`invalid_bbox` / `bbox_too_large`, max span `MAP_BBOX_MAX_SPAN_DEG` = 1.5°) and `crossings_in_bbox` caps results at `MAP_CROSSINGS_LIMIT` (500) with a `truncated` flag, ordered by pk, GiST-indexed `location__intersects`. Derived community status rides along via `incidents.services.derive_statuses` — one bulk `CrossingReport` query grouped in Python, so the endpoint costs a constant two queries regardless of result size. The frontend loads crossings on map `idle` (300 ms debounce) only at zoom ≥ `MAP_CROSSINGS_MIN_ZOOM` (12), pads the visible bounds 20% per side rounded outward to 3 decimals, skips refetches while the view stays inside a <60 s-old fetched bbox, aborts superseded requests, and refreshes on `visibilitychange` only when data is stale — no polling. Markers are diffed by id, never rebuilt; pins are coloured per derived state plus a glyph (✕/✓/!/…/?) so status never relies on colour alone; without a Map ID, legacy circle `Marker`s show the same colour+glyph. Geolocation stays one-shot and browser-only: `getCurrentPosition` on explicit click, a token invalidates late callbacks after Stop, denied/unsupported/insecure-context/timeout/unavailable each map to a message, and an accuracy `Circle` is always drawn when available so the fix's imprecision is visible.
- Rationale: embedded JSON scaled with the whole dataset and refreshed never; a bounded, never-cached endpoint scales with the viewport and keeps statuses honest without N+1 queries. Keeping coordinates in the browser preserves ADR-005's privacy posture.
- Consequences: Only the rounded on-screen bbox reaches the server — it can approximate which area a user is looking at. Gunicorn writes no access log by default, but the dev `runserver` logs request lines including the bbox; treat dev access logs as location-adjacent data. If India-wide data arrives, `MAP_CROSSINGS_LIMIT` + `bbox_too_large` keep responses bounded at the cost of a "zoom in" state at low zoom.

## ADR-013 — Google Routes provider + geometry-verified avoidance
- Status: Accepted (Session 06)
- Decision: A `routing` app owns route planning. `routing.providers.GoogleRoutesProvider` calls the Routes API `computeRoutes` server-side with `GOOGLE_MAPS_SERVER_KEY` over stdlib urllib (no new dependency); alternatives come in one call. `routing.services.plan_route` throttles provider calls per client per clock hour (`ROUTING_MAX_REQUESTS_PER_HOUR`, Django cache), analyses each candidate's crossings with raw PostGIS SQL (`routing.analysis`), then bulk-derives community status in one `derive_statuses` call. A crossing is `on_route` only when the route line passes within `ROUTE_CROSSING_ON_ROUTE_M` (20 m) AND the line intersects a mapped track within `ROUTE_TRACK_MATCH_M` (30 m) of the node; crossings inside `ROUTE_CROSSING_NEAR_M` (50 m) without track evidence are `possible`. Blocking = primary-route `closed_reported` crossings. Alternatives are evaluated only when blocking is non-empty: `verified` requires every blocking crossing farther than `ROUTE_AVOID_CLEARANCE_M` (100 m) and no `closed_reported` crossing on the alternative itself; `passes`/`uncertain`/`unverifiable` are shown honestly. Only `verified` may claim avoidance — and only after a user-confirmed switch (`[data-route-select]` buttons).
- Rationale: the Routes API has no point/segment exclusion, so avoidance can only be verified geometrically. `TRAFFIC_UNAWARE` (Essentials SKU) is the default; `TRAFFIC_AWARE` (Pro SKU) is opt-in via `ROUTING_GOOGLE_ROUTING_PREFERENCE` and durations are labelled "Google estimate, with/without live traffic". Google ToS bar persisting route content — no routing models exist; geometry lives only in the request/response and the `route-data` JSON for the map.
- Consequences: If guaranteed exclusion is ever required, Valhalla `exclude_locations` or GraphHopper are documented future options behind the same `Waypoint`/`RouteCandidate` interface. User location can be the route origin only via explicit opt-in: "Use my location" writes lat/lng into hidden form fields and they reach the server as GET params solely when the user submits Find route — they are never stored or logged in the DB (ADR-005/ADR-012). The throttle is per-process on the locmem cache; switch the cache backend to Redis when multi-worker enforcement matters. Errors map to `not_configured|no_route|quota|auth|timeout|invalid_request|provider_error|rate_limited` and never contain the API key.

## ADR-014 — Realtime status pushes via Channels/WebSocket; polling as the fallback
- Status: Accepted (Session 07)
- Decision: Crossing status changes are pushed over a single public WebSocket endpoint `ws://…/ws/crossings/` (Channels + `daphne`, `AuthMiddlewareStack` + `AllowedHostsOriginValidator`). Clients subscribe by crossing ID only — `{"type":"subscribe","crossing_ids":[…]}` replaces the whole set, capped at `REALTIME_MAX_SUBSCRIPTIONS` (500) and rate-limited to one subscribe per `REALTIME_SUBSCRIBE_MIN_SECONDS` (1 s); only active, non-suppressed IDs are joined (invalid/hidden IDs are silently dropped so the response never reveals them). There is no subscription mechanism for anything else — no private data or user locations exist on the socket. On each subscribe the server sends a `status.snapshot` for the whole set (one query), which also closes gaps from disconnects.
- Publishes originate from `CrossingReport` `post_save`/`post_delete` → `transaction.on_commit` → `incidents.updates.publish_crossing_status`, which re-derives the status server-side and `group_send`s to `crossing.<pk>` — freshness/conflict rules stay server-authoritative and pushes carry the same payload as the HTTP API plus `as_of` (clients drop out-of-order frames). Identical consecutive payloads are suppressed via the shared cache; a failed send only logs. Expiry produces no DB event, so time-based ageing still relies on the client's periodic refresh — the map polls `requestLoad()` at most once a minute while visible (itself bounded by the existing staleness/coverage guards), which doubles as the WebSocket-unavailable fallback.
- Redis (`redis:7-alpine` Compose service, `REDIS_URL`) backs the channel layer and the default cache, making pushes and the routing throttle shared across workers. With `REDIS_URL` blank, a per-process in-memory layer/cache is used — fine for single-process dev runserver; `incidents.W001` warns about it. Prod image runs `daphne` (HTTP+WS); `gunicorn` WSGI remains an option where WebSockets are disabled (clients fall back to polling).
- Rationale: marker statuses previously refreshed only on map moves or ≥60 s staleness, so a fresh closed-report could sit unseen on a visible crossing. Report frequency is already DB-bounded, so one push per durable write is cheap; subscriptions bound fan-out to what each client displays.
- Consequences: `daphne`/`channels` join `INSTALLED_APPS` (dev `runserver` serves ASGI automatically). The consumer is read-only and anonymous-safe because statuses are public. Multi-worker deploys need `REDIS_URL`; the in-memory fallback cannot cross processes.

## ADR-015 — Isolated simulator: dedicated tables + status overlay hook
- Status: Accepted (Session 08)
- Decision: A `simulator` app owns all demo state in `simulator_*` tables
  (`SimulationRun`, `SimulatedVehicle`, `SimulationGateEvent`,
  `SimulationEvent`), every row scoped to a run and cascade-deleted by it.
  The simulator never writes `CrossingReport` rows and never mutates
  `railways` reference rows. Simulated gate state reaches the shared read
  pipeline through a hook in `incidents.services` —
  `register_status_overlay(provider)` — which `simulator` registers at app
  ready; `incidents` itself never imports the simulator.
- `effective_status(es)` merges community status with the overlay into
  `EffectiveStatus`: a community `closed_reported` always wins; otherwise
  an active run's latest gate event yields the distinct states
  `closed_simulated`/`open_simulated`. Only an *active* (running/paused)
  run contributes — stopping/finishing a run ends the overlay immediately
  and republishes affected crossings. At most one active run
  (DB-enforced `active_slot`); stale `running` rows are marked stopped on
  heartbeat loss.
- Runtime: the optional Compose `simulator` service (`--profile
  simulation`) runs `run_simulator`, ticking vehicles + gate events once
  per `tick_seconds`; the same engine is manually drivable via
  `manage.py simulator tick`. Vehicle paths are synthetic linestrings
  through real crossings (perpendicular to the nearest mapped track) —
  honest demo geometry, not real road/provider data. Positions publish
  over `ws/simulation/` in coarse ticks (browser interpolates); gate
  closures reuse `incidents.updates` so crossing pins/route warnings see
  the effective status. `routing` treats `closed_simulated` as blocking
  exactly like `closed_reported`, with "(simulated)" labels everywhere.
- Rationale: hackathon demos need visible traffic and gate cycles without
  contaminating real data. A registered overlay keeps separation
  one-directional (`simulator` → `incidents`), labels demo data at every
  surface, and makes the whole overlay disappear when a run ends — so
  reset/stop can never leave fake status behind.
- Consequences: `CrossingReport` stays community-only; all public status
  payloads now carry `simulated` (+ `simulation`/`community_state` when
  overlaid). Without `REDIS_URL`, sim WS frames can't cross containers —
  `/api/simulation/` polling is the fallback. A failed `start_run` keeps a
  `failed` run row for audit (like `OsmImportRun`).

## Updating decisions
When a proposal becomes implemented, update its status and include the implementation reference/PR if known. Add a new ADR rather than silently rewriting a decision whose rationale materially changed.

## ADR-016 — Click-to-route destinations + dynamic reroute; "My location" default origin
- Status: Accepted (Session 09)
- Decision: Clicking anywhere on the map (a POI via its `placeId`, or any
  point via lat/lng) sets it as the route destination and re-plans from
  the current origin *without a page reload*. The clicked point is
  resolved through the **Geocoding API** so the destination is a real
  selectable Google place/address (POI clicks keep their `placeId`; bare
  clicks adopt the nearest result's) — pinned coordinates are only the
  fallback when geocoding is unavailable. `GET /?…&format=json`
  returns `{route_state, html, route_data}` where `html` is the
  re-rendered `routing/_route_result.html` partial and `route_data` the
  same map payload as the embedded script. `#route-result` is swapped and
  the URL synced via `history.pushState`; on any fetch failure the client
  falls back to a normal navigation. `destination_lat`/`destination_lng`
  are now accepted alongside `destination_place_id` (place id still wins).
  The crossing detail card gains a "Route here" button that routes to the
  crossing's coordinates. Double-click zoom is disabled because click
  events drive routing.
- "My location" is the default origin: the From field reads "My location"
  unless the user opted out or the page already carries an origin. The
  *choice* is persisted in `localStorage` (`vz.origin.myLocation`); the
  coordinates never are. On load, a fresh fix is requested silently only
  when `navigator.permissions` already reports `granted`; on `prompt`/`denied`
  an inline alert asks the user to enable access — never a card, never an
  unprompted browser permission dialog. Origin submits with "My location"
  but no fix are intercepted client-side, fixed, then resubmitted; the
  server also rejects literal "My location" without coords
  (`missing_origin`) so it can never be geocoded.
- Rationale: owner-requested UX (map-first rerouting, minimal chrome).
  Keeping reroute rendering server-side (`format=json`) avoids
  duplicating the plan template in JS and keeps error states honest.
- Consequences: the old "Your location" card and its `loc-*` states are
  gone; location feedback is a small inline `#loc-alert` (role=status /
  role=alert). Route option switching uses event delegation on
  `data-route-select` because `#route-result` innerHTML is swapped.
  Endpoint A/B pins are derived from route geometry endpoints. The
  routing throttle (per-client/hour) also guards click-driven reroutes.

## ADR-017 — Journey sessions: session-scoped position checks + Google Maps handoff
- Status: Accepted (Session 10)
- Decision: A `navigation` app owns opt-in journey sessions for real
  users. `POST /api/navigation/sessions/` creates a `JourneySession` —
  a UUID capability token with `created_at`/`ended_at`/
  `last_position_check_at` and **no coordinates, route content or user
  identity** — throttled per client (`NAV_MAX_SESSIONS_PER_HOUR`).
  `POST …/position/` accepts `{lat,lng}` only inside an active session,
  enforces `NAV_MIN_UPDATE_SECONDS`, and answers one
  `railways.queries.crossings_near_point` call (raw SQL geography
  `ST_DWithin` + `ST_Distance`, bounded by `NAV_NEARBY_RADIUS_M` /
  `NAV_NEARBY_LIMIT`) plus one bulk `effective_statuses` — the
  position is used transiently and never stored. Crossings inside
  `NAV_ALERT_RADIUS_M` with a blocking status
  (`closed_reported`/`closed_simulated`, same states routing treats
  as blocking) are returned in `alerts`. `POST …/end/` is idempotent;
  sessions expire after `NAV_SESSION_MAX_HOURS` and
  `purge_navigation_sessions` deletes rows older than
  `NAV_SESSION_RETENTION_DAYS`. CSRF stays on (`@ensure_csrf_cookie`
  on home + `X-CSRFToken` header) — these are real-user endpoints,
  unlike the csrf-exempt simulator demo API.
- Frontend: each route panel offers "Start journey — watch for closed
  gates" (browser `watchPosition`; a teal journey marker with a
  heading arrow; throttled checks by `min_update_seconds` +
  `min_update_distance_m`; a red popup lists closed gates inside the
  alert radius and tags ones `on_route` on the selected route;
  dismissing suppresses that alert until it leaves the radius or its
  status changes) and "Open in Google Maps" (the universal
  `maps/dir/?api=1` directions URL — place ids, or coordinates only
  when the user already opted in; Google may choose its own path, we
  do not claim it is ours). When the selected route already carries a
  blocking crossing, a pre-navigation warning card lists it before
  either action runs — user-confirmed, like route switching.
- Rationale: the product's value is warning drivers approaching a
  closed gate; real turn-by-turn is delegated to Google Maps instead
  of re-built in-app, while crossing-status alerts stay ours.
  Keeping positions out of the database preserves ADR-005's privacy
  posture while sessions satisfy the "updates only inside a
  permitted session" rule.
- Consequences: the position endpoint never echoes or stores
  coordinates (asserted by tests — the session schema has no
  coordinate columns). Anonymous use is allowed (sessions are
  unguessable UUIDs); abuse is bounded by the start throttle, the
  per-session min interval and the TTL. No location channel exists on
  WebSockets — checks are HTTP POST only. Journey mode needs
  `watchPosition`, i.e. HTTPS/localhost and an explicit Start click;
  "Open in Google Maps" alone needs no location permission.

## ADR-018 — Simulated presence inference: queues → prompt → human confirmation
- Status: Accepted (Session 10)
- Decision: `--gate ID:CLOSE[:OPEN]` now describes the *physical* gate
  schedule of the demo world — it makes simulated users stop and queue
  at the crossing and no longer writes `SimulationGateEvent` rows
  directly. Each `SimulatedVehicle` doubles as a user device and
  remembers the crossing its path passes through (`crossing`,
  `crossing_progress_m`, `waiting`, `wait_ticks`); `SIM_QUEUE_VEHICLES`
  staged users spawn already queued per gated crossing (deterministic),
  and passers-by are clamped into the same queue. Presence inference
  (`_detect_prompts` each tick) raises a `SimulationPrompt` when at
  least `SIM_DWELL_MIN_USERS` waiting users stay within
  `SIM_DWELL_RADIUS_M` for `SIM_DWELL_SECONDS`; one prompt per
  run+crossing+closure (unique `truth_close_tick`). Only a confirmed
  prompt writes a `closed` gate event (`POST
  /api/simulation/prompts/<id>/confirm/`); dismiss writes nothing, and
  pending prompts expire on `SIM_PROMPT_TTL_SECONDS`, gate reopen, or
  run end. A physical reopen after a confirmed closure surfaces `open`
  automatically — the queue disperses, no second confirmation.
  `--auto-confirm` resolves prompts instantly through the same code
  path for click-free demos. Prompts ride `sim.tick`/snapshot/
  `/api/simulation/` payloads and broadcast as `sim.prompt` /
  `sim.prompt.resolved` frames on `sim.control`; the web app renders
  violet confirmation cards that POST the URLs from the payload.
- Rationale: the product premise is inferring gate state from real
  users' dwell near crossings, with a human confirmation before it
  affects routes — the demo should rehearse that loop, not a timetable.
  Keeping surfaced status behind `SimulationGateEvent` means routing,
  badges and pushes needed no change.
- Consequences: the prompt endpoints are `csrf_exempt` — they mutate
  only `simulator_*` demo rows and carry no identity. Confirmed
  closures still reach status as `closed_simulated` and block routes
  identically to `closed_reported`. Dwell/radius values are
  demo-compressed defaults (`SIM_*` env knobs, `simulator.E004`); a
  real deployment would use minutes, not ~20 s.

## ADR-019 — Google sign-in via django-allauth (socialaccount)
- Status: Accepted (Session 12)
- Decision: Google OAuth 2.0 sign-in is provided by `django-allauth`
  (`allauth` + `allauth.account` + `allauth.socialaccount` +
  `allauth.socialaccount.providers.google`). Credentials come from
  `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` (settings
  `SOCIALACCOUNT_PROVIDERS["google"]["APP"]`, no `SocialApp` DB rows,
  no `django.contrib.sites`). `allauth.urls` is mounted at `accounts/`
  *after* our own `login`/`logout` patterns so the existing Tailwind
  `registration/login.html` keeps serving `/accounts/login/`; allauth's
  account URLs remain reachable underneath (`account_login`,
  `account_signup`, password reset, connections) because allauth
  internals reverse them. The login page's Google button POSTs to
  `{% provider_login_url "google" %}` (LOGIN_ON_GET stays off).
- Policy: public username/password signup stays closed
  (`core.adapters.AccountAdapter.is_open_for_signup` → `signup_closed`);
  Google sign-in self-registers (`SOCIALACCOUNT_AUTO_SIGNUP` default).
  `SOCIALACCOUNT_EMAIL_AUTHENTICATION` + `_AUTO_CONNECT` are on, so a
  Google-verified email matching an existing user (e.g. an
  administrator-created reporter) logs into and links that account.
  `SOCIALACCOUNT_STORE_TOKENS` stays off — we only need identity.
- Rationale: ADR-011 deferred sign-in to a "vetted package"; allauth is
  the standard Django social-auth implementation and keeps the OAuth
  state/nonce/callback handling, `email_verified` enforcement and
  account-linking edge cases upstream.
- Consequences: `requests` is an undeclared allauth dependency — pinned
  explicitly. Without credentials the app boots normally, the button is
  hidden (`GOOGLE_OAUTH_ENABLED` context flag), and `core.W003` warns on
  a half-set pair. The Google redirect URI is
  `<origin>/accounts/google/login/callback/`. `EMAIL_BACKEND` is
  env-tunable (console in dev) for allauth's account emails. Styled
  overrides exist for `socialaccount/login.html`, `login_cancelled`,
  `login_error` and `account/signup_closed`; other allauth account
  pages fall back to its own templates.

## ADR-020 — Same-line status propagation + via-point detour synthesis
- Status: Accepted (Session 13, owner-requested)
- Decision: Two related changes. (1) A new derived-topology table
  `railways.CrossingLink` stores each crossing's nearest
  `RAILWAY_LINK_MAX_NEIGHBORS` (default 3) crossings measured *along the
  connected track network* — built by `railways/topology.py`
  (`rebuild_crossing_links`, graph of way-vertex nodes + Dijkstra;
  crossings snap to the nearest vertex within `RAILWAY_LINK_SNAP_M`,
  neighbours capped at `RAILWAY_LINK_MAX_DISTANCE_M`). Links rebuild at
  the end of every OSM import and on demand via
  `manage.py link_crossings`; admin sees them read-only. A live
  `closed`/`open` state — community `*_reported` or `*_simulated` — is
  surfaced on the consecutive crossings as the new derived states
  `closed_inferred` / `open_inferred`, carrying `inference` provenance
  (source crossing, along-track distance, simulated flag). Inference is
  one hop (an inferred state is never a source), applies only to
  `unknown`/`stale` targets, closed beats open when links disagree, and
  suppressed/inactive sources never propagate. Report writes republish
  neighbour statuses over the existing `crossing.<pk>` WS groups.
  (2) When a crossing blocks the primary route and the provider returns
  no alternative, `plan_route` synthesizes up to
  `ROUTE_DETOUR_MAX_CALLS` extra candidates: a `via` waypoint offset
  `ROUTE_DETOUR_VIA_OFFSET_M` perpendicular to the route at the blocked
  crossing. Synthesized candidates get the identical crossing analysis
  and avoidance verification — a detour that still passes the crossing
  is `passes`, never "avoids" — and are labelled "Detour via side
  roads"/"detour suggestion" (`RouteCandidate.synthesized`,
  `providers.Waypoint.via`). Each via call consumes the per-client
  throttle budget; `ROUTE_DETOUR_ENABLED=0` disables.
- Rationale: a train at one gate reaches the consecutive gates on the
  same line within minutes, so the same status is genuinely useful — but
  only as honestly-labelled inference, not a fabricated direct report.
  Google's `computeAlternativeRoutes` frequently returns a single route;
  the via-point nudge surfaces the side-road route (e.g. via KPK Menon
  Rd) that drivers would otherwise never see.
- Consequences: propagation lives in `effective_statuses`, so the bbox
  map, single status, WS pushes, journey alerts and routing all get
  `*_inferred` for free; `derive_statuses` stays community-only.
  `closed_inferred` is a routing `BLOCKING_STATE` and a journey
  `ALERT_STATE`, always labelled "likely". Typed-but-unselected
  origin/destination text is now synced into the hidden form fields on
  every reroute path (map click, "Route here", "Open in Google Maps"),
  so a custom source works everywhere "My location" does; a custom
  source clears any stale my-location coords before the request.

## ADR-021 — Static simulated users + auto-selected verified detour
- Status: Accepted (Session 14, owner-requested)
- Decision: Two related changes. (1) Simulated users are *static*:
  every `SimulatedVehicle` row is a parked user device that never moves
  — no more ping-ponging passers-by. `spawn_vehicles` places all
  `--vehicles` users in queue slots on the approaches to the run's
  gated crossings (round-robin, alternating sides, `SIM_QUEUE_GAP_M` +
  `SIM_QUEUE_SPACING_M` + jitter), or at seeded random crossings when
  no gate is scheduled. `_advance_vehicles` is replaced by
  `_update_dwell`: a parked user counts as `waiting` (darkened pin)
  only while its crossing's physical gate is closed, and `wait_ticks`
  accumulates/reset for presence inference exactly as before — the
  ADR-018 prompt → confirm → `SimulationGateEvent` flow is unchanged.
  `SIM_VEHICLE_MIN/MAX_SPEED_MPS` and `SIM_QUEUE_VEHICLES` are removed
  (dead config; `simulator.E003` deleted). `speed_mps` is stored as 0;
  the `path`/`progress_m`/`direction` fields remain as placement
  geometry. (2) When the primary route is blocked and at least one
  alternative verifies as avoiding the closure, that route is the
  *preferred* one: `RoutePlan.preferred_route_id` (first `verified`
  alternative, else `"r0"`), surfaced as `route_data.selected`, drives
  the "Recommended" badge, the visible route panel, and the map's
  selected polyline — the blocked primary stays selectable as
  "Route 1" with a "Closed gate on/near route" tag.
- Rationale: the demo story is users detected at rest near a gate
  (dwell → inference → confirmation), not simulated traffic; moving
  vehicles added noise without contributing to inference. And when a
  gate on the route is closed, "give me a route" should mean the
  verified way around it, not the blocked line with a warning and an
  extra click.
- Consequences: no migration — `SimulatedVehicle` keeps its name and
  fields ("vehicle" is now historical). The map payload keys
  (`vehicles`, `vehicle_count`) are unchanged; `wait` now reflects
  gate truth rather than a parked-forever flag. Auto-selecting a
  detour never *hides* the blocked route — it remains a selectable
  option with its full warning, so the closure evidence stays visible.
  Stale `SIM_VEHICLE_*`/`SIM_QUEUE_VEHICLES` keys in existing `.env`
  files are ignored.
