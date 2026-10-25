# Project State — Vazhithirivu

> This file is the handoff point between agent sessions. Update it at the end of every meaningful work session.

## Status
- Current milestone (uncommitted, 2026-10-25): **Session 14 (static simulated users + auto-selected verified detour, ADR-021)** — verified: 332 tests green, live sim smoke (parked users → dwell prompt → confirm → `closed_simulated` → same-line `closed_inferred` → `selected:"r1"` detour) green.
- Previous milestone (uncommitted): **Session 13 (same-line status propagation + via-point detour synthesis, ADR-020)** — verified (332 tests). Earlier uncommitted Sessions 10/10b/11/12 sit underneath in the same tree.
- Docs session (2026-10-25): **`README.md` rewritten** — was the dev-bundle description; now documents the real architecture (data planes, status pipeline, verified routing, simulator, privacy model, API surface) plus a full setup guide (all env keys, Google Cloud steps, every command). Docs-only change.
- Git: `main` = `8bac7a5` (Sessions 08+09 committed). Branch `wip/crossing-labels` still incomplete — don't merge.

## What changed — Session 14 (uncommitted; ADR-021)
- **Static simulated users — no moving vehicles** (owner request). `simulator/engine.py`: `spawn_vehicles` now parks *every* `--vehicles` user in a queue slot on an approach to a gated crossing (round-robin across gates, alternating sides, `SIM_QUEUE_GAP_M`/`SIM_QUEUE_SPACING_M` + jitter; seeded random crossing when no gate is scheduled). `_advance_vehicles` (movement, queue clamping, path bounce) replaced by `_update_dwell`: a parked user counts `waiting`+`wait_ticks` only while its crossing's gate is physically closed; both clear on open. `_gate_specs_by_crossing` deleted; `speed_mps` stored as 0; `path`/`progress_m`/`direction` kept as placement geometry — **no migration** (`SimulatedVehicle` name/fields unchanged; "vehicle" is historical). The ADR-018 prompt → confirm → `SimulationGateEvent` flow is untouched.
- **Dead config removed**: `SIM_VEHICLE_MIN_SPEED_MPS`, `SIM_VEHICLE_MAX_SPEED_MPS`, `SIM_QUEUE_VEHICLES` from `config/settings/base.py`, `simulator/checks.py` (`simulator.E003` deleted, E004 trimmed), `.env.example`. Stale `.env` keys are ignored harmlessly.
- **Auto-selected verified detour** (owner request: "route [should avoid] the closed gates"). `routing/services.py`: `RoutePlan.preferred_route_id` = first `verified` alternative when the primary is blocked, else `"r0"`. `core/views.py` `_route_data` adds `"selected"`. `templates/routing/_route_plan.html`: "Recommended" badge, `aria-pressed`/`data-selected` and the visible panel now follow the preferred route; a blocked primary is tagged "Closed gate on/near route". `static/js/map.js` `applyRouteData` honours `data.selected` (validated, falls back to `"r0"`) via `selectRoute`.
- **Copy**: map.js sim banner + marker title say "simulated users"; `simulator/views.py` disclaimer and the `simulator` command help/output say users not vehicles; `simulator/admin.py` list shows `crossing`/`waiting` instead of `speed_mps`/`direction`.
- **Tests**: `simulator/tests/test_engine.py` — `test_users_never_move` (replaces position-advance/bounce tests), `test_users_park_near_gated_crossing`, `test_gate_close_waits_users_then_prompt_confirm_open`, `test_dwell_counter_resets_when_gate_reopens` (replaces queue-clamp test). `routing/tests/test_services.py` + `routing/tests/test_views.py` — `preferred_route_id`/`"selected"`/hidden-panel assertions.

## Commands/tests run (Session 14, actual outcomes)
| Command | Result |
|---|---|
| `node --check static/js/map.js` | OK |
| `docker compose run --rm web python manage.py check` | No issues (0 silenced) |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 332 tests, OK** |
| `simulator start --vehicles 8 --seed 42 --gate 8:2:12` + `/api/simulation/` | 8 parked users at crossing 8, `wait:false`, `gates:{}` |
| `simulator tick` ×2 | gate closed at tick 2: all 8 `wait:true`; positions byte-identical across ticks 2→5 (zero moved); status still unsurfaced |
| `simulator tick --n 3` | prompt #4 pending at tick 5 (`waiting_users: 4` inside the 20 m dwell radius) |
| `POST /api/simulation/prompts/4/confirm/` | `confirmed` + `gates{"8":"closed"}` → `/api/crossings/8/status/` = `closed_simulated` (run 7) |
| `GET /?origin_lat…&destination_lat…&format=json` ×3 | routes through the area flag `closed_inferred` crossing 123 (same-line propagation from crossing 8's confirmed closure); the blocked route with a verified alternative returns `"selected":"r1"` — detour auto-selected |
| `simulator tick --n 7` | reopen at tick 12 → auto `open` → `open_simulated`; all `wait` cleared, users still parked |
| `simulator stop` + `reset` | 216 sim rows deleted; crossing 8 → `unknown`, `simulated:false`; `/api/simulation/` `active:false`; simulator service restarted |

Not verified: auto-selected detour and static pins in a real browser (markup/JSON/curl-verified only); prompt card click path unchanged from Session 10.

> **Demo run left active (2026-10-25)**: run #8 `Sim run 7` — 16 static users parked 4-per-gate at crossings **107 (Malabar Gate, 9.93665, 76.27533), 15, 29, 127** (same railway line, staggered close ticks 2/6/10/14). All four confirmed → `closed_simulated`; all 16 users `waiting`. Gates stay closed for the 900 s duration — stop with `manage.py simulator stop`, then `simulator reset` clears all sim rows and reverts statuses.

## What changed — Session 13 (uncommitted; ADR-020)
- **Same-line propagation** (owner request: "up to 3 crosses in the same line"): new `railways.CrossingLink` (migration `0002`) stores each crossing's ≤`RAILWAY_LINK_MAX_NEIGHBORS` (3) nearest crossings measured along the connected track network. `railways/topology.py` `rebuild_crossing_links` builds a vertex/edge graph from active track ways (shared snapped vertices = junctions), snaps each crossing to the nearest vertex ≤`RAILWAY_LINK_SNAP_M` (30 m), Dijkstra capped at `RAILWAY_LINK_MAX_DISTANCE_M` (15 km); `manage.py link_crossings` + auto-rebuild at end of `import_osm_railways`; read-only admin; `railways.E001`. On the real Kochi import: 99/127 crossings linked, 297 links, 28 unsnapped.
- **Inferred states**: `incidents.services` gains `closed_inferred`/`open_inferred` + `STATUS_META`; `effective_statuses` propagates a live `closed`/`open` (`*_reported` or `*_simulated`) to linked neighbours — one hop only, only onto `unknown`/`stale` targets, closed beats open, suppressed/inactive sources excluded; `EffectiveStatus.inference` carries provenance. `derive_statuses` stays community-only. Payloads expose `inferred`/`inference`; `signals._publish` republishes neighbour `crossing.<pk>` groups on report writes.
- **UI**: badges + legend entries + `data-status-variant` spans (ui.py `link` icon; red likely-closed, teal likely-open); map.js pin styles (`≈` glyph on reported colours), `KNOWN_STATES`, status summary naming the source crossing, marker titles, route-crossing labels; `NAV_ALERT_STATES`/`ALERT_STATES` + `BLOCKING_STATES` include `closed_inferred` — journey popup and pre-nav confirm show "likely closed (same line)" wording; `crossing_detail.html` links to the source crossing.
- **Detour synthesis** (owner report: no alternatives for a custom source — Google returned one route): `providers.Waypoint.via` + `compute_routes(..., intermediates=)`; when `blocking` and exactly one route came back, `plan_route` synthesizes ≤`ROUTE_DETOUR_MAX_CALLS` (2) candidates through a `via` waypoint offset `ROUTE_DETOUR_VIA_OFFSET_M` (300 m) perpendicular to the route at the blocking crossing. Each call consumes `allow_request`; identical geometries deduped; candidates marked `synthesized` + "Detour via side roads"; identical verification — a detour that still passes is `passes`, never "avoids". `ROUTE_DETOUR_ENABLED` switch, `routing.E003`. Route options/panels tag "detour suggestion"/"Suggested detour".
- **Custom-source fix**: `syncRouteFields()` (map.js) syncs typed-but-unselected picker text into the hidden `origin`/`destination` fields on form submit AND every dynamic path (`reroute()`, `openInGoogleMaps`) — previously only "My location"/picked places worked outside submit. A custom source clears stale my-location coords so the server can't prefer them over the typed address.
- **Honesty**: `blocking_word` (reported/simulated/likely-closed) parameterizes verification text; `RoutePlan.blocking_all_inferred`; "Crossing likely closed on your route (same line)" title when all blocking entries are inferred; `counts` renders "(inferred)".
- **Tests**: `railways/tests/test_topology.py` (8), `incidents/tests/test_propagation.py` (12), `DetourSynthesisTests` (5); `intermediates` param added to all FakeProviders; `inferred` key added to the map-api payload test.

## Commands/tests run (Session 13, actual outcomes)
| Command | Result |
|---|---|
| `node --check static/js/map.js` | OK |
| `docker compose run --rm web python manage.py makemigrations` | `railways.0002_crossinglink` created |
| `... manage.py migrate` + `check` | applied; no issues (0 silenced) |
| `... manage.py test --settings=config.settings.test` | **Ran 332 tests, OK** (interim failures all fixed) |
| `... manage.py link_crossings` (dev DB, real Kochi data) | `linked=99 links=297 unsnapped=28 tracks=330` |
| Live shell: temp closed report on crossing 123 → `effective_status(8)` | `closed_inferred` + inference `{from: 123, 464.8 m, closed_reported}`; rows cleaned up |
| `... tailwind tailwindcss -i … -o static/css/app.css --minify` | Done (teal badge classes present) |

Not verified: inferred pins/alerts and detour cards in a real browser; a live Google via-point call (synthesis is mocked in tests).

## What changed — Session 12 (Google sign-in, ADR-019; uncommitted)
- **`django-allauth==65.20.0` + `requests==2.34.2`** added to `requirements/base.txt` (requests is an undeclared allauth dependency — pinned explicitly).
- **`config/settings/base.py`**: env vars `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET`/`EMAIL_BACKEND`; apps `allauth`, `allauth.account`, `allauth.socialaccount`, `allauth.socialaccount.providers.google`; `allauth.account.middleware.AccountMiddleware`; `AUTHENTICATION_BACKENDS`; `SOCIALACCOUNT_PROVIDERS["google"]` (scope profile+email, `APP` attached only when both creds set); `SOCIALACCOUNT_EMAIL_AUTHENTICATION` + `_AUTO_CONNECT` (verified-email link to existing accounts); `ACCOUNT_ADAPTER="core.adapters.AccountAdapter"`; `GOOGLE_OAUTH_ENABLED` flag.
- **`core/adapters.py`**: local username/password signup closed (Google self-registers; admin-created accounts keep working).
- **`core/context_processors.py`**: `GOOGLE_OAUTH_ENABLED` for the login button. **`core/checks.py`**: `core.W003` when only one OAuth credential is set.
- **`config/urls.py`**: `accounts/` → `include("allauth.urls")` mounted *after* our `login`/`logout` so the Tailwind page keeps winning `/accounts/login/`; gives `/accounts/google/login/` (POST → Google), `/accounts/google/login/callback/`, plus allauth account URLs (`account_signup` renders our styled closed page; password reset etc. available).
- **Templates**: `registration/login.html` Google button (POST, official G mark, `{% provider_login_url %}` carries `next`); styled overrides `socialaccount/login.html` (GET confirm), `login_cancelled.html`, `login_error.html`, `account/signup_closed.html`.
- **`config/settings/dev.py`**: console `EMAIL_BACKEND`. Docs: `.env.example` (OAuth setup + callback URI), `RUNBOOK.md` (Google sign-in section), `DATA_SOURCES.md` (scopes; tokens not stored), `DECISIONS.md` ADR-019.
- **Tests**: `core/tests/test_google_auth.py` (10): button shown/hidden, password login intact, POST→Google 302 (client_id/callback/state/scope), GET confirm page, `next` propagation, callback rejects missing state (401/302, not 500), signup closed + POST creates no user, `account_login` name resolves.

## Commands/tests run (Session 12, actual outcomes)
| Command | Result |
|---|---|
| `docker compose build web` | OK (allauth 65.20.0 + requests 2.34.2 installed) |
| `docker compose run --rm web python manage.py migrate` | account 0001–0009 + socialaccount 0001–0006 applied |
| `docker compose run --rm web python manage.py check` | No issues (0 silenced) |
| `docker compose run --rm tailwind tailwindcss -i … --minify` | Done |
| `python manage.py test --settings=config.settings.test` | 307 tests: **1 failure + 13 errors — all from the parallel session's in-flight crossing-links/line-inference WIP** (`railways.test_import` ×13: missing `RAILWAY_LINK_*` settings; `test_map_api` payload expects `inferred` key). All 10 `test_google_auth` + all auth tests pass. |
| Live `curl /accounts/login/` (no creds) | 200, Google button hidden, admin note shown |
| Live `curl /accounts/signup/` | 200, styled "Signup closed" |
| One-off container `GOOGLE_OAUTH_CLIENT_ID/SECRET=dummy` + Django `Client` | button renders; POST `/accounts/google/login/` → 302 `accounts.google.com/o/oauth2/v2/auth` with correct client_id, callback `…/accounts/google/login/callback/`, state |

Not verified: a real Google consent→callback→user-creation roundtrip (needs Cloud Console OAuth client creds — see RUNBOOK "Google sign-in"); `GET/POST /accounts/google/login/` with no creds returns 500 `ImproperlyConfigured` (standard allauth for an unconfigured provider; the button is never shown, so the URL is undiscoverable).

> **ADR number collision**: the parallel crossing-links session also labels its work ADR-019 (see `railways/topology.py`); whichever lands DECISIONS.md second should renumber to ADR-020.

## What changed — Session 11 (uncommitted)
- **`static/js/map.js`**: crossing markers are now a level-crossing warning sign instead of a generic `PinElement` glyph pin — `crossingSignSvg` builds the inline SVG (status-coloured diamond band + rim, white field, dark road/track pictogram, ground shadow, corner badge keeping the glyph as the non-colour status cue), `crossingIconUrl` encodes the same SVG as a data URI for the legacy (no Map ID) `Marker` path, `crossingSignEl` wraps it for `AdvancedMarkerElement.content` with `anchorLeft`/`anchorTop` on the diamond tip; selected state = CSS scale 1.18 around the tip. Route-closure mini-markers (`addRouteCrossingMarkers`) use the same icon at 0.78 scale. `LEGACY_ICON_SCALE` removed; `STATE_STYLE` colours/glyphs unchanged (`border` is now the band rim).
- **`templates/core/home.html`**: legend note explaining the sign markers.
- Verified by rendering the real `crossingSignSvg` output via headless Chrome (all 7 states + scale/selected variants). Not yet seen on a live Google Map — confirm tip anchoring and badge overlap in a browser.

## Commands/tests run (Session 11, actual outcomes)
| Command | Result |
|---|---|
| `node --check static/js/map.js` | OK |
| `docker compose run --rm web python manage.py check` | No issues (0 silenced) |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 297 tests, OK** |
| `curl /` | 200; legend sign-marker line present |

## What changed — Session 10b (uncommitted; ADR-017, navigation app)
- **`navigation` app**: `JourneySession` — UUID capability token (`created_at`/`ended_at`/`last_position_check_at`; **no coordinates, route content or user identity**). `POST /api/navigation/sessions/` (per-client throttle `NAV_MAX_SESSIONS_PER_HOUR` → 429), `POST …/<uuid>/position/` `{lat,lng}` → nearby crossings + `alerts` (blocking `closed_reported`/`closed_simulated` inside `NAV_ALERT_RADIUS_M`), `POST …/<uuid>/end/` (idempotent). Session TTL `NAV_SESSION_MAX_HOURS` (ended/expired → 410); `NAV_MIN_UPDATE_SECONDS` → 429 `too_fast` + `Retry-After`. CSRF kept (`@ensure_csrf_cookie` on home + `X-CSRFToken`); positions are transient — never stored (tested: schema has no coord columns). `purge_navigation_sessions --days` retention command; view-only admin; `navigation.E001/E002` checks; `railways.queries.crossings_near_point` (raw SQL geography, nearest-first, capped).
- **Frontend** (`map.js` `setupJourney`): route panels gain "Start journey — watch for closed gates" (`watchPosition` opt-in, teal marker w/ heading arrow, throttled checks by server `config`, red popup listing closed gates + "on your route" tags, dismiss suppressed until it leaves the radius/status changes) and "Open in Google Maps" (`maps/dir/?api=1` universal URL — place ids or opted-in coords; Google picks its own path). A pre-navigation warning card lists blocking crossings before either action. `home.html`: `#journey-banner`, `#journey-alert`, `#journey-confirm`; `map_config` gains `navigationStartUrl`/`navigationSessionUrlTemplate`; two new Lucide icons (`navigation`, `external-link`).
- **Cross-session note**: the parallel Session-10 session generated `navigation/migrations/0001_initial.py` and fixed `core/views.py`'s placeholder UUID + `services.get_session` (returns `None` on malformed UUID).
- **Tests**: `navigation/tests/` (27: API lifecycle/alerts/throttle/410s/privacy, services, checks, purge) + `crossings_near_point` in `railways/tests/test_queries.py` + template/config assertions in `routing`/`core` tests.

## Commands/tests run (Session 10b, actual outcomes)
| Command | Result |
|---|---|
| `node --check static/js/map.js` | OK |
| `docker compose run --rm web python manage.py migrate` + `check` | `navigation.0001_initial` applied; no issues |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 297 tests, OK** (includes both sessions) |
| `docker compose run --rm tailwind tailwindcss -i … -o static/css/app.css --minify` | Done |
| Live: `POST /api/navigation/sessions/` (csftoken cookie + header) | 201 session+config |
| Live: `POST …/position/` `{lat:9.9312,lng:76.2673}` | 200 `crossings:[]`, radii + disclaimer |
| Live: position POST without CSRF / after `end/` | 403 / `410 session_ended` |
| `curl /` | journey markup + nav URLs present |

Not verified: journey mode in a real browser (watchPosition, popup, banner, Google-Maps handoff, pre-nav warning); `watchPosition` needs HTTPS/localhost.

## What changed — Session 10 (uncommitted; ADR-018)
- **Physical vs surfaced**: `--gate ID:CLOSE[:OPEN]` no longer writes `SimulationGateEvent` on schedule — it queues simulated users. A gate event (what the status overlay reads) is written only by a *confirmed* prompt, or automatically `open` when a physically reopened gate had a confirmed closure.
- **`SimulatedVehicle`** (`migrations/0002`): `crossing`/`crossing_progress_m` (every vehicle's path crossing), `waiting`/`wait_ticks` (queue state). `SIM_QUEUE_VEHICLES` (4) staged users spawn queued per gated crossing, alternating sides; passers-by are clamped into queues at `SIM_QUEUE_GAP_M`/`SIM_QUEUE_SPACING_M` slots.
- **`SimulationPrompt`** (new model): one per run+crossing+`truth_close_tick`; states pending/confirmed/dismissed/expired; `waiting_vehicle_indexes` snapshot.
- **Engine**: `gate_truth()`, `_advance_vehicles` (queue clamp + staged hold + release on reopen), `_detect_prompts` (`SIM_DWELL_RADIUS_M`/`SIM_DWELL_SECONDS`/`SIM_DWELL_MIN_USERS`), `confirm_prompt`/`dismiss_prompt`, TTL (`SIM_PROMPT_TTL_SECONDS`) + reopen + run-end expiry, `auto_confirm` run flag (`--auto-confirm` CLI).
- **API/WS**: `POST /api/simulation/prompts/<id>/confirm|dismiss/` (csrf_exempt — sim rows only); `prompts` in `/api/simulation/` + `sim.snapshot`/`sim.tick`; `sim.prompt`/`sim.prompt.resolved` on `sim.control`.
- **Frontend**: `#sim-prompts` card stack under the banner (confirm/dismiss buttons → POST payload URLs); waiting users get darker pins; poll path carries prompts.
- **Settings**: `SIM_DWELL_RADIUS_M`(20)/`SIM_DWELL_SECONDS`(20)/`SIM_DWELL_MIN_USERS`(1)/`SIM_PROMPT_TTL_SECONDS`(180)/`SIM_QUEUE_GAP_M`(7)/`SIM_QUEUE_SPACING_M`(8)/`SIM_QUEUE_VEHICLES`(4); `simulator.E004`; `.env.example`.
- **Cross-session fixes I made** (parallel session's WIP, needed for a green suite): `core/views.py` placeholder UUID was malformed (`NoReverseMatch` 500 on `/`) → valid nil UUID; generated `navigation/migrations/0001_initial.py` (missing → `navigation_journeysession` table absent in tests); `navigation/services.get_session` returned `ValidationError` on malformed UUID → returns `None` (matches its own test).

## Commands/tests run (Session 10, actual outcomes)
| Command | Result |
|---|---|
| `node --check static/js/map.js` | OK |
| `docker compose run --rm web python manage.py makemigrations simulator` | `0002` created; `migrate` applied |
| `docker compose run --rm web python manage.py check` | No issues (0 silenced) |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 297 tests, OK** (263 + 34 nav tests from parallel session; interim failures all fixed) |
| `simulator start --vehicles 20 --seed 42 --gate 8:1:40` + `/api/simulation/` | tick 8: 4 waiting users, prompt #1 pending at tick 4, `gates: {}` (unsurfaced) |
| `POST /api/simulation/prompts/1/confirm/` | 200 `confirmed` + `gates{"8":"closed"}` → `/api/crossings/8/status/` = `closed_simulated` |
| `simulator stop` + `reset` + status check | overlay reverted (`unknown`, `simulated:false`); 28 sim rows deleted (incl. prompt) |

Not verified: prompt card UI in a real browser (markup/JS unit-pathed only); `sim.prompt` frames in a real browser; auto-reopen live (unit-tested); route replan through a confirmed-closed crossing in a real browser (unit-tested via `test_routing.py`).

## Next steps (priority order)
1. **Browser-verify the Session-14 demo loop**: `simulator start --vehicles 8 --gate <id>:2:60` → parked violet users darken when the gate closes → prompt card → Confirm → crossing `closed_simulated` (+ same-line `closed_inferred`) → Find route → verified detour is auto-selected (still curl-/unit-verified only).
2. **Google sign-in**: owner creates an OAuth Web client in Cloud Console (`<origin>/accounts/google/login/callback/` redirect URI, RUNBOOK "Google sign-in"), sets `GOOGLE_OAUTH_CLIENT_ID`/`SECRET` in `.env`, then browser-verify the full consent→callback→login roundtrip.
3. Browser-verify journey mode (Start → watchPosition → closed-gate popup → End; also the Google-Maps handoff and pre-nav warning) and the sim prompt card — both are unit-/curl-verified only.
4. Commit the uncommitted sessions once the owner confirms and the suite is green again.
5. Browser smoke: WS pin recolour on `crossing.status` push (still never exercised in a real browser).
6. Finish `wip/crossing-labels` branch (needs migration `0002`, tests, rerun of the importer).

## What exists now — Session 09 (uncommitted; ADR-016)
- **Click-to-route**: `map.js` `setupRoutes` rewritten — `map` `click` listener routes to a POI (`placeId`, `event.stop()` suppresses the info window) or any point. `resolveDestination` reverse-geocodes the click (Geocoding API: `placeId` for POIs, `location` for bare clicks) so the destination is a real selectable Google place/address; falls back to "Selected place"/"Pinned location (lat, lng)" when geocoding is unavailable. **Browser key now also needs the Geocoding API** (RUNBOOK/DATA_SOURCES/.env.example updated). `disableDoubleClickZoom: true` (dblclick fires two clicks). Crossing detail card gains `#crossing-route-here` → routes to crossing coords. "Route here"/map clicks go through `ensureOriginThen`: picked place/typed text wins; "My location" or empty From → `window.vz.requestMyLocation` first, reroute on fix.
- **Dynamic reroute**: `core.views.home` accepts `format=json` → `JsonResponse{route_state, html, route_data}`; `html` = new `templates/routing/_route_result.html` (extracted state block) rendered via `render_to_string`. `map.js` `reroute()` builds params from the form fields, fetches, swaps `#route-result` innerHTML, `history.pushState`, reapplies map layers; aborts prior fetches; failure falls back to full navigation. `route_state` announcements via stable `#route-live` (replaced `#route-announce`). Route-option/`data-route-select` clicks now use `document` delegation so they survive the swap.
- **Destination coords**: `destination_lat`/`destination_lng` GET params + hidden form fields; `_waypoint` uses them when no `destination_place_id` (id still wins); `_route_data` adds `description`/`distance_km`/`duration_min` per route.
- **Server guard**: literal `origin="My location"` without valid `origin_lat/lng` → `missing_origin` — never geocoded.
- **Route visuals**: selected route = white casing (weight 12) + solid brand line (weight 8, opacity 1); alternates dashed slate weight 5. **A/B endpoint pins** (blue A start / red B destination) from route geometry endpoints, AdvancedMarker `PinElement` or legacy circle fallback, zIndex 200.
- **Location UI** (`_locate.html` partial in both picker + fallback From fields): small "Use my location" button (privacy promise in `title`) + dismissible inline `#loc-alert` (info/ok/error variants, role=status|alert). The whole "Your location" card section (`loc-idle/requesting/active/denied/unavailable`) removed.
- **Default + saved My location** (`app.js`): empty From defaults to "My location" unless `localStorage["vz.origin.myLocation"]==="0"`; a page-loaded "My location"+coords reuses them (`myLocPos` seed). On load, `navigator.permissions.query` → `granted` = silent fix; `prompt`/`denied` = sticky alert nudge (no unprompted dialog). Fix → marker+circle, ok alert, optional auto-reroute when a destination exists. Picking a real place or submitting other text = `clearMyLocation()` (pref "0", visuals + coords cleared). Picker text seeded from hidden inputs via `customElements.whenDefined("gmpx-place-picker")`. Submit with "My location" but no fix → preventDefault → fix → resubmit.
- **Panel**: `text-base font-bold` primary stats; click-to-route tip line; Refresh link carries destination coords.
- **Tests**: `routing/tests/test_views.py` +8 (destination coords/place-id wins/invalid, My-location guard, `format=json` states incl. no-params). `core/tests/test_ui.py` updated (loc button/alert markup, `route-result`/`route-live`). `test_crossing_markers.py` +Route-here assertions.

## Commands/tests run (Session 09, actual outcomes)
| Command | Result |
|---|---|
| `node --check static/js/map.js static/js/app.js` | OK |
| `docker compose run --rm web python manage.py check` | No issues (0 silenced) |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 247 tests, OK** (239 + 8 new; first run 1 failure — multi-line `{#…#}` comment renders literally in Django, switched partials to `{% comment %}`) |
| `docker compose run --rm tailwind tailwindcss -i assets/tailwind/input.css -o static/css/app.css --minify` | Done |
| `curl /` | 200; `locate-btn`/`loc-alert`/`route-result`/`route-live`/`crossing-route-here`/`id_destination_lat` present; old `loc-*` ids gone; no `{#` leaks |
| `curl '/?destination=Vyttila&format=json'` | `route_state:"missing_origin"`, html alert rendered |
| `curl '/?origin=My+location&origin_lat=10.0261&origin_lng=76.3125&destination=Edachira&format=json'` | `planned`, 2 routes, `duration_min`/`distance_km`/endpoint coords in payload |
| `curl '…&destination=Pinned+location&destination_lat=10.03&destination_lng=76.35&format=json'` | `planned` — destination coords route OK |

Not verified: any of it in a real browser — map click → reroute, POI placeId path + `event.stop()`, picker text seeding, silent-fix on granted permission, loc-alert states, casing/A-B pins visually, `prefers-reduced-motion` unchanged. Follow the RUNBOOK smoke checklist.

## Previous milestone
- Session 08 (isolated simulator) implemented, uncommitted. Optional run-scoped simulator live-verified: 60-vehicle run, gate close/reopen on a real Kochi crossing, simulated status overlay through bbox/status APIs + WS, reset leaves real data untouched. Browser view of vehicles/pins not yet agent-verified.

## What exists now — Session 08 (uncommitted; ADR-015)
- **`simulator` app** (always installed, inert without a run). Models `SimulationRun` (config JSON, seed, status, `active_slot` unique — max one running/paused run, stale-heartbeat recovery), `SimulatedVehicle` (synthetic path through a real crossing perpendicular to nearest track — not road/provider data), `SimulationGateEvent`, `SimulationEvent` (audit log). Migration `0001`.
- **Status overlay**: `incidents.services.register_status_overlay` (registered by `simulator` at ready — one-way dependency). `effective_status(es)` → `EffectiveStatus(state, community, simulation)`; new states `closed_simulated`/`open_simulated` apply only while a run is active; community `closed_reported` always wins. `payloads.effective_status_payload/brief` add `simulated`/`simulation`/`community_state` to bbox, single-status, WS snapshot and push payloads — `status.simulated` is always present.
- **Engine** (`simulator/engine.py`): `start_run` (seeded, `--force` replaces active), `tick_run` (bulk vehicle advance w/ ping-pong, due gate events, heartbeat, auto-finish), `pause/resume/stop/fail`, `reset_simulation` (refuses while active, deletes only sim rows), `drive_run` service loop, `interrupt_stale_runs`. Gate changes call `incidents.updates.publish_crossing_status`; stop/finish republishes all gated crossings (overlay reverts).
- **Commands**: `manage.py simulator start|pause|resume|stop|status|tick|reset` (`--vehicles/--duration/--tick/--seed/--gate ID:CLOSE[:OPEN]/--random-gates/--force`); `manage.py run_simulator` = the Compose `simulator` service (`--profile simulation`), SIGTERM→graceful stop.
- **Realtime**: `ws/simulation/` `SimulationConsumer` — `sim.control` broadcasts (`sim.run.*`), `sim.run.<pk>` group, `{"type":"subscribe","run_id"?}` → `sim.snapshot` + coarse `sim.tick` frames (vehicles+full gate map); `GET /api/simulation/` = same state for polling fallback.
- **Routing**: `plan_route` uses `effective_statuses`; `closed_simulated` blocks like `closed_reported` (BLOCKING_STATES), `blocking_names`/`blocking_all_simulated` label "(simulated)"; `_route_plan.html` shows "Simulated gate closure — demo data" wording.
- **Frontend** (`map.js`): violet `closed/open_simulated` pin styles + badge variants + summary text; `setupSimulation` — WS subscribe + 5 s `/api/simulation/` poll fallback, vehicle markers (violet pin/arrow or circle) interpolated via rAF (reduced-motion → jump), `#sim-banner`, `sim.tick.gates` recolour visible pins via `window.vz.applyPushedStatus`, run end clears + `requestCrossingLoad(true)`. `home.html`: sim banner, 2 badge variants, legend line. `core.views.home` map_config gains `simulationUrl`/`simulationWsUrl`.
- **Settings**: `SIM_TICK_SECONDS` (5), `SIM_DEFAULT_VEHICLES` (60), `SIM_MAX_VEHICLES` (200), `SIM_DEFAULT_DURATION_SECONDS` (600), `SIM_PATH_LENGTH_M` (4000), `SIM_VEHICLE_MIN/MAX_SPEED_MPS` (6/14), `SIM_HEARTBEAT_STALE_SECONDS` (45); `simulator.E001–E003` validate. `.env.example` updated.
- **Tests**: `simulator/tests/` — engine (determinism, tick, gates, lifecycle, unique slot, stale interrupt), status overlay (7 merge rules), **isolation** (reset deletes only sim rows; sim never writes `CrossingReport`/touch railways/users), API, WS consumer, commands, routing integration (simulated blocking → warning + verified alternative + revert). `incidents/test_map_api.py` expected keys +`simulated`.

## Commands/tests run (Session 08, actual outcomes)
| Command | Result |
|---|---|
| `node --check static/js/map.js` | OK |
| `docker compose run --rm web python manage.py makemigrations simulator` | `0001_initial.py` created; `migrate` applied |
| `docker compose run --rm web python manage.py check` | No issues (0 silenced) |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 239 tests, OK** (191 + 48 new; 1st run had 2 failures — atomic rollback hiding failed-run row, bbox key set — both fixed) |
| `docker compose --profile simulation up -d simulator` + `simulator start --vehicles 60 --seed 42 --duration 1800 --gate 8:4:60` | run #2 live: `api/simulation/` active, 20→60 moving vehicles |
| `GET /api/crossings/8/status/` during/after run | `open_simulated` (`simulated:true`, run meta) → `unknown` (`simulated:false`) after finish — overlay reverted |
| `GET /api/crossings/?bbox=…` | `closed_simulated`/`open_simulated` + `simulation{run_id,gate_state}` + `community_state` |
| WS handshake `/ws/simulation/` | 101 Switching Protocols |
| `simulator reset` + row counts | deleted 27 sim rows only; 127 crossings / 330 tracks / reports untouched |
| `docker compose --profile simulation stop simulator` | clean stop |

Not verified: sim vehicle markers/banner/interpolation in a real browser; `sim.run.*` control frames live; route-plan UI with an active simulated block live (unit-tested only).

## Status (previous milestone, superseded)
- Session 07 (realtime status pushes) was committed as `962eaa5`. WS `/ws/crossings/` live-verified end-to-end over Redis; still not exercised in a real browser.
- Product: Vazhithirivu (വഴിത്തിരിവ്), "Smart routes. Smarter crossings."
- Target demo: Kochi, Kerala; future dataset target: India-wide mapped railway crossings.
- Stack: Django 5.2 LTS, server-rendered templates, Tailwind CSS v4 (standalone CLI, ADR-008), Google Maps JavaScript API + Places API (New) (ADR-009), PostgreSQL 17 + PostGIS 3.5, Channels 4.3.2/Daphne 4.2.3 + Redis 7 (ADR-014), Docker Compose. Not yet added: HTMX/Alpine (not needed yet), Celery.
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
Session 07 (uncommitted; ADR-014):
- **Realtime pushes**: `channels==4.3.2`, `channels-redis==4.3.0`, `daphne==4.2.3` in `requirements/base.txt`; `"daphne"`+`"channels"` in `INSTALLED_APPS` (dev `runserver` serves ASGI automatically). `config/asgi.py` = `ProtocolTypeRouter` (http→Django ASGI, websocket→`AllowedHostsOriginValidator`+`AuthMiddlewareStack`+`URLRouter`). `incidents/routing.py`: `ws/crossings/` → `CrossingStatusConsumer` (`incidents/consumers.py`, `AsyncJsonWebsocketConsumer`).
- **Protocol**: client sends `{"type":"subscribe","crossing_ids":[…]}` which **replaces** the set — strict int IDs, cap `REALTIME_MAX_SUBSCRIPTIONS` (500), min interval `REALTIME_SUBSCRIBE_MIN_SECONDS` (1 s, `rate_limited` error + `retry_after_seconds`), inactive/suppressed IDs silently dropped (never revealed). Replies: `status.snapshot` (full subscription, one `derive_statuses` query — also covers missed updates on reconnect), then `crossing.status` frames per `crossing.<pk>` group. Errors: `invalid_message`, `invalid_crossing_ids`, `rate_limited`. Statuses are public → anonymous connections allowed; nothing else is subscribable (no user-location channels exist).
- **Publish path**: `incidents/signals.py` `post_save`/`post_delete` on `CrossingReport` → `transaction.on_commit` → `incidents/updates.py publish_crossing_status` → re-derives server-side (`derive_status`) → `group_send`. Covers new reports, admin moderation and `purge_crossing_reports` deletes. Identical consecutive payloads suppressed via cache fingerprint (`rt:push:<pk>`, 300 s); send failures log + don't raise and aren't marked as pushed. Skips inactive/suppressed crossings.
- **Payload refactor**: `incidents/payloads.py` holds `DISCLAIMER` + `status_payload`/`status_brief`/`report_payload`/`policy_payload` (moved out of `views.py`); the HTTP API responses are unchanged apart from a new top-level `as_of` on `/api/crossings/` and `/api/crossings/<pk>/status/` (server-clock ordering so the client drops out-of-order frames).
- **Redis/cache**: `redis:7-alpine` Compose service (health-checked); `web` gets `REDIS_URL=redis://redis:6379/0` + `depends_on`. `REDIS_URL` set → `RedisChannelLayer` **and** Redis `CACHES` (also makes the routing throttle multi-worker-safe — closes a known risk); blank → in-memory layer + locmem and `incidents.W001` warns. `incidents.E002` validates the REALTIME_* knobs.
- **Prod**: image CMD is now `daphne -b 0.0.0.0 -p 8000 config.asgi:application` (HTTP+WS); gunicorn WSGI remains for WS-less deploys (clients poll).
- **Frontend** (`static/js/map.js`): `cfg.crossingsWsUrl` (from `core.views.home`, `ws(s)://host/ws/crossings/`) → subscribe = marker IDs + selected, resubscribe debounced 1.1 s after `applyCrossings`/`setSelected`; `status.snapshot`/`crossing.status` applied via `as_of` ordering (bbox fetch + detail fetch also stamp `statusAsOf`); pushes update pin + open detail card; reconnect backoff to 30 s, gives up after 10 (retry on `online`), retries after `rate_limited` errors. **Fallback**: unconditional 60 s visible-only `requestLoad()` — also the only path for time-based ageing (expiry produces no push).
- **Tests**: `incidents/tests/test_realtime.py` — `PublishTests` (payload/provenance, coalescing, suppressed/inactive skip, no-layer + send-failure no-ops), `SignalTests` (TransactionTestCase: create/moderate/delete → push), `ConsumerTests` (async communicator over the real `config.asgi.application`: snapshot, group→socket delivery, unsubscribed/suppressed get nothing, resubscribe replaces, invalid messages, id cap, rate limit). Plus `crossingsWsUrl` assertion in `core/tests/test_crossing_markers.py`.

Session 01: settings split (`config/settings/{base,dev,test,prod}.py`), `/healthz/`, `/readyz/`, Dockerfile, Compose `db` + `web`.

Session 02 (committed in `ef9dc94`):
- **Tailwind**: `assets/tailwind/input.css` (theme, `.btn*`, `.field*`, `.card`, `.badge`, `.sheet`, reduced-motion rule; `@source` covers templates, `static/js`, `core/**/*.py`). Dockerfile `tailwind` stage (v4.3.3, sha256-verified) → `static/css/app.css` copied into the app image. Compose `tailwind` watcher service. `static/css/app.css` is git/docker-ignored.
- **Components**: `core/templatetags/ui.py` (`{% icon %}` 18 inline Lucide SVGs, `{% status_badge %}` open/closed/unknown/stale/conflicting with unknown fallback, `{% source_badge %}` osm/community/simulated); `templates/components/` alert, empty_state, error_state, spinner, skeleton, badge partials.
- **Pages**: `templates/base.html` (skip link, `lang="ml"` span); `/` → `core.views.home` / `templates/core/home.html`: header, desktop side panel / mobile bottom sheet, GET route form (no-destination warning; non-blank → "Route planning isn't available yet", no fabricated durations), opt-in location card (idle/requesting/active/denied/unavailable), crossing empty state ("OSM data not imported yet"), status legend with "not official / no report ≠ open". Map region: loading, API-unavailable / auth-failure, noscript, and not-configured states. `/ui/` component gallery (DEBUG only, labelled "Demo content").
- **Google Maps**: official bootstrap loader rendered only when `GOOGLE_MAPS_BROWSER_KEY` set; config via `json_script`. `static/js/map.js` (Map with Map ID, `PlaceAutocompleteElement` on From/To with India region + Kochi bias, `gmp-select` → hidden `*_place_id`, `gm_authFailure` handler). `static/js/app.js` (bottom sheet, click-only one-shot geolocation, coords stay in browser, AdvancedMarker only with Map ID).
- **Config**: `GOOGLE_MAPS_MAP_ID`, `MAP_DEFAULT_LAT/LNG/ZOOM` added; `.env.example` lists all Google keys (blank placeholders) with restriction guidance. `core/checks.py`: warnings `core.W001` (no browser key), `core.W002` (no Map ID).
- Docs updated: RUNBOOK (Tailwind + Google key setup), DATA_SOURCES (Google, Lucide ISC), README (attribution), DECISIONS (ADR-008, ADR-009), ROADMAP.

Session 03 (committed in `ef9dc94`; ADR-010):
- **`railways` app** (in `INSTALLED_APPS`). `railways/models.py`: `OsmImportRun` (path/url, sha256, size, header replication timestamp, coverage bbox, filters, counts, status/error); abstract `OsmReferenceFeature` (source osm/manual, osm_type/id/version/timestamp, full tags, first/last_seen_run, is_active/deactivated_at); `RailwayCrossing` (Point 4326, railway_value, crossing_barrier, is_suppressed/suppression_reason/admin_notes, **no status field**); `RailwayTrack` (LineString 4326, usage/service). Non-partial unique `(osm_type, osm_id)`, check constraint (osm rows need identity), GiST + is_active indexes. Migration `railways/migrations/0001_initial.py`.
- `railways/importer.py` (`run_import`, `ImportFilters`, `flush_batch`, `_reconcile`): pyosmium 4.3.2 `FileProcessor.with_locations().with_filter(KeyFilter("railway"))` (verified untagged way nodes still resolve). Advisory lock, stale `running` runs marked failed, per-batch atomic upserts, `--bbox`, `--dry-run`, `--reconcile` (bbox + filter-scoped soft-delete, all-or-nothing, `--max-deactivate-fraction` abort). Skip reasons: `crossing_not_node`, `track_invalid_geometry`, `crossing_invalid_geometry`, `outside_bbox`.
- `railways/management/commands/import_osm_railways.py` (thin CLI), `railways/admin.py` (GISModelAdmin; OSM fields read-only on osm rows; manual crossings + suppression; runs view-only).
- Tests: `railways/tests/test_import.py`, `test_models.py`, synthetic fixtures `railways/tests/fixtures/sample_v1.osm`/`sample_v2.osm` (+ tmp PBF written in-test).
- `requirements/base.txt` + `osmium==4.3.2`; Compose `osm-import` service (`profiles: ["import"]`, `./data/osm` read-only at `/data/osm`).
- Docs: DATA_SOURCES (Geofabrik URLs/sizes, ODbL/attribution, filters, corrections, refresh), RUNBOOK (OSM import section), DECISIONS ADR-010, ROADMAP.
- `core/tests/test_ui.py`: no-key test now forces blank Google settings (it failed when `.env` held a real key).

Session 04 (committed in `ef9dc94`; ADR-011). This was built in a parallel session; the description below is that session's own record:
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

OSM crossing map markers (after Session 03, committed in `ef9dc94`):
- `core/views.py` `home`: when the map is configured, it sends active, non-suppressed crossings (osm + manual, capped at `CROSSING_MAP_LIMIT = 5000`) as `{{ crossings|json_script:"crossings-data" }}` with `crossing_count`.
- `templates/core/home.html` "Crossing details" panel has three states:
  - map not configured;
  - no crossings imported;
  - `#crossing-empty` plus a hidden `#crossing-detail` card. The card shows the name (fallback "Unnamed level crossing"), `status_badge "unknown"`, "no report doesn't mean the gate is open", the osm/manual source badge, barrier, coordinates, the "View on OpenStreetMap" link and a close button. "© OpenStreetMap contributors" attribution sits in the panel.
- `static/js/map.js` `setupCrossingMarkers`: with a Map ID it uses neutral slate `AdvancedMarkerElement`/`PinElement` markers; otherwise classic `Marker`. Click fills the card via `textContent` and highlights the pin; Escape/close resets. `window.vz.crossingMarkers` holds the markers. `static/js/app.js` exposes `window.vz.expandSheet` (mobile sheet).
- Tests: `core/tests/test_crossing_markers.py` (4). `HomeTests` are now `TestCase`.
- Verified: full suite **Ran 91 tests, OK**; `node --check` clean; `curl /` contains 127 crossings (real `.env` key). **Not verified:** clicking markers in a real browser.
Marker panel live status (committed on `main`, not pushed):
- `templates/core/home.html`: `#crossing-detail` carries `data-status-url-template`/`data-detail-url-template` (built with `{% url %}`), five `data-status-variant` badge spans (unknown visible by default), `data-status-summary` (`aria-live`) + `data-status-error` paragraphs, and a `data-crossing-detail-link` "Report or view details" button.
- `static/js/map.js` `setupCrossingMarkers`: on `showDetail` it resets to Unknown, sets the detail link, and `loadStatus(id)` fetches the status JSON (`credentials: same-origin`, `Accept: application/json`, AbortController, ignored if selection changed). Unknown/stale/reported/conflicting summaries rendered via `textContent` only; failures show Unknown + error note. Status refreshes every 60 s while the card is open (skipped when `document.hidden`), cleared on close/reselect; double marker clicks can't spawn duplicate intervals/fetches. No pin colouring yet — needs a bulk endpoint.
- Review fix: `showDetail` originally called `loadStatus` before `startStatusRefresh`, whose `stopStatusRefresh()` aborted the first fetch (panel stuck on "Checking…" for 60 s). Order swapped; `node --check` OK. JS has no automated tests, so this was caught by review only — a browser click test is still needed.
- Tests: `core/tests/test_crossing_markers.py` extended (card markup assertions + an end-to-end `create_report` → `closed_reported` status check).
- Verified: `node --check static/js/map.js` OK; full suite **Ran 92 tests, OK**; `manage.py check` clean; `curl /` 200 with `data-status-url-template="/api/crossings/0/status/"`; `curl /api/crossings/8/status/` 200 (`state:"unknown"`); `curl /crossings/8/` 200. **Not verified:** marker click in a real browser.

Session 05 (uncommitted; ADR-012):
- `railways/queries.py`: `parse_bbox` (`BBoxError.code` `invalid_bbox` / `bbox_too_large`), `crossings_in_bbox_queryset` (active, non-suppressed, osm + manual, GiST `location__intersects`, ordered by pk), `crossings_in_bbox(bbox, limit)` → `(rows, truncated)`.
- `incidents/services.py`: logic moved into the pure helper `_derive_from_reports`; `derive_status` behaves exactly as before. New `derive_statuses(crossings)` does one report query for many crossings.
- `GET /api/crossings/?bbox=w,s,e,n` (`incidents.views.api_crossings_in_bbox`, name `api_crossings`, never_cache): coords rounded to 6 decimals, `status` {state, label, last_report_at, age}, `official:false`, disclaimer, OSM attribution, `truncated`. It always costs 2 queries, whatever the result size. Settings `MAP_CROSSINGS_LIMIT` (500), `MAP_BBOX_MAX_SPAN_DEG` (1.5), `MAP_CROSSINGS_MIN_ZOOM` (12) are in base.py and `.env.example`.
- `core/views.home`: the embedded `crossings-data` JSON and `CROSSING_MAP_LIMIT` are removed. It now uses an `.exists()` check (`has_crossings`), and `map_config` gains `crossingsUrl`/`crossingsMinZoom`/`bboxMaxSpan`.
- `static/js/map.js`: crossings load on map `idle` with a 300 ms debounce. Nothing loads below zoom 12 ("Zoom in" chip). The view is padded 20% per side and rounded outward to 3 decimals. A refetch is skipped while the view stays inside a fetched bbox under 60 s old; there's a stale refetch on `visibilitychange`, no polling, and an AbortController plus a sequence guard. Markers are diffed by id; the selected one is never removed.
- Pins: colour plus glyph per state (closed ✕ red, open ✓ green, conflicting ! amber, stale … light slate, unknown ? slate — never green). AdvancedMarker `PinElement` is used with a Map ID, legacy circle `Marker` without one. Titles read "… (community reports, not official)". `#crossings-status` chip (aria-live) with OSM attribution. The detail-card status fetch also updates its pin. AdvancedMarker listens to `gmp-click` only.
- Lead review fix: legacy markers were removed via `marker.map = null`, which `google.maps.Marker` ignores. They now use `setMap()` (`setMarkerMap` helper); `node --check` OK.
- `static/js/app.js` geolocation (still one-shot, click-only, coords never sent):
  - error states: unsupported, insecure context (HTTPS hint), denied, position unavailable, timeout (15 s);
  - "Try again" buttons;
  - a token makes late callbacks no-ops after Stop;
  - zooms to 15 when below min zoom;
  - always draws an accuracy `Circle` (so there's an indicator even without a Map ID), notes "±N m" and warns above 1 km;
  - Stop removes the marker and circle and clears "My location".
- Tests:
  - new `railways/tests/test_queries.py` (parsing, inclusion/boundary, limit/truncated, GiST index visible in `EXPLAIN` with `enable_seqscan=off`);
  - new `incidents/tests/test_map_api.py`;
  - `DeriveStatusesTests` (parity with `derive_status`, 1 query);
  - `core/tests/test_crossing_markers.py` rewritten;
  - location markup test in `test_ui.py`.
- Docs: ADR-012, RUNBOOK (endpoint + **manual smoke-test checklist with real Google keys** under "Google Maps"), ROADMAP (M1 bbox ticked, M4 explicit-permission/stop ticked as browser-only), `.env.example`.

Session 06 (uncommitted; ADR-013):
- **`routing` app** (in `INSTALLED_APPS` after `incidents`; **no models** — Google ToS bar persisting route content). `providers.py`: `Waypoint`, `RouteCandidate`, `RoutingError` (codes not_configured/no_route/quota/auth/timeout/invalid_request/provider_error; key never in error text), `GoogleRoutesProvider` (Routes API `computeRoutes` via stdlib urllib; `computeAlternativeRoutes` + `HIGH_QUALITY` polyline in one call; `routingPreference` only sent when TRAFFIC_AWARE; DEFAULT_ROUTE sorted to index 0), `get_provider`. `polyline.py` decode/`to_linestring`. `analysis.py` raw PostGIS SQL: `crossings_along_route` (GiST prefilter + `ST_DWithin` geography 50 m, `along_m` via `ST_LineLocatePoint`, `on_route` needs ≤20 m **and** a mapped-track intersection within 30 m — parallel roads come out `possible`), `distances_to_crossings`. `throttle.py` per-client/hour cap via Django cache (locmem, per-process). `services.py` `plan_route` → `RoutePlan`: one provider call, one bulk `derive_statuses`, warning levels `closed_on_route`/`closed_near_route`/`conflicting_on_route` (unknown/stale never warn); alternatives evaluated only when blocking; `verified` requires >100 m clearance from every blocking crossing and no closed crossing of its own; `passes`/`uncertain`/`unverifiable` rendered honestly (missing distance fails closed to `unverifiable`). `checks.py` `routing.E001/E002/W001`.
- `core.views.home`: new route states `missing_origin`/`planned`; place-id regex + 300-char caps; `route-data` `json_script` for the map. `templates/routing/_route_plan.html`: per-route panels, crossing list ordered along the route with badges + "On route"/"Possibly on route", warning/alternative blocks ("Use this route" only on verified; "Show on map (not verified)" on uncertain; passes → text only), disclaimers + "Routes by Google", `#route-announce` aria-live. `static/js/map.js` `setupRoutes`: polylines (selected brand/solid, alternates slate/dashed — never green for avoids), closed/conflicting route-crossing markers, user-confirmed `data-route-select` switching + fitBounds + announcements.
- Settings: `ROUTING_*`/`ROUTE_*` knobs (timeout 8 s, 60 req/hr/client, 20/50/30/100 m thresholds, `ROUTING_GOOGLE_ROUTING_PREFERENCE=TRAFFIC_UNAWARE` — Essentials SKU; TRAFFIC_AWARE bills Pro). `config/settings/test.py` forces `GOOGLE_MAPS_SERVER_KEY=""` so tests can't reach Google. `.env`/`.env.example` now carry a working server key (Routes API enabled).
- `incidents/services.py`: `CrossingStatus.age` property ("12 min ago").
- Docs: ADR-013 (+ADR-004 marked implemented), DATA_SOURCES (Routes API usage/SKUs/no-storage), RUNBOOK (server-key setup + routing smoke checklist), ROADMAP M2 ticked.

## Commands/tests run (Session 07, actual outcomes — single end-of-session pass)
| Command | Result |
|---|---|
| `node --check static/js/map.js static/js/app.js` | OK |
| `docker compose build web` | OK (channels 4.3.2 / channels-redis 4.3.0 / daphne 4.2.3 installed) |
| `docker compose run --rm web python manage.py makemigrations --check --dry-run` | No changes detected |
| `docker compose run --rm web python manage.py check` | No issues (0 silenced; REDIS_URL set → no W001) |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 191 tests, OK** (173 + 18 realtime) |
| `docker compose up -d` | db + redis + web healthy (`redis:7-alpine` started by depends_on) |
| curl `/`, `/healthz/` | 200; `"crossingsWsUrl": "ws://localhost:8000/ws/crossings/"` in map-config |
| WS handshake, `Origin: http://localhost:8000` | **101 Switching Protocols** (Server: daphne) |
| WS handshake, `Origin: http://evil.example.com` | 403 Access denied (AllowedHostsOriginValidator) |
| Live e2e over real Redis (temp user/crossing-8 report via `websockets` client in a run container): subscribe → `status.snapshot` (`unknown`); `create_report` → `crossing.status` (`closed_reported`, ~40 ms later); report deleted → push back to `unknown`. Temp user/report cleaned up | All payloads carried `policy`, `as_of`, `official:false`, disclaimer |
| `docker build -t vazhithirivu .` | OK; image CMD `daphne -b 0.0.0.0 -p 8000 config.asgi:application` |
| Prod `check --deploy` on the built image | Only expected warnings (core.W001/W002, routing.W001, security.W004) + new `incidents.W001` correctly firing with REDIS_URL blank |

Not verified: WS path in a real browser (pin colour change on push, reconnect/backoff, `rate_limited` retry, snapshot apply); gunicorn WS-less fallback only inferred (client falls back to polling when the socket never opens).

## Commands/tests run (Session 06, actual outcomes — single end-of-session pass + lead review fixes)
| Command | Result |
|---|---|
| `node --check static/js/map.js static/js/app.js` | OK |
| `docker compose run --rm web python manage.py makemigrations --check --dry-run` | No changes detected |
| `docker compose run --rm web python manage.py check` | No issues (server key present → no routing.W001; W001 correctly fires when blank, seen in test output) |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 171 tests, OK** (165 after review fixes + 6 my-location tests) |
| Live: `/?origin=My+location&origin_lat=10.0261&origin_lng=76.3125&destination=Edachira` | 2 routes rendered (r0 8.4 km/24 min via Infopark Rd, r1 9.6 km/26 min), route-data polylines present |
| `docker compose run --rm tailwind tailwindcss -i assets/tailwind/input.css -o static/css/app.css --minify` | Done |
| Live: `GET /?origin=Edappally,+Kochi&destination=Vyttila,+Kochi` (real key) | r0 "about 16 min via Panvel-Kochi-Kanyakumari Hwy", 214 pts, no alternatives, no mapped crossings (HTML: `/tmp/vz_s06_basic.html`) |
| Live: lat,lng raw addresses | Google 400 → honest "Pick a place from the suggestions" (`/tmp/vz_s06_crossing.html`) |
| Live: `Vaduthala→Pachalam` with a temp closed report on crossing 42 | `closed_near_route` warning naming the crossing "near the route at 1.3 km, reported just now"; 4 crossings matched `possible` (route is parallel to the track — PostGIS check confirmed the route crosses a track only once, ~295–643 m from the nodes, so `possible` is correct, not a bug). No alternative returned → honest fallback. Temp user/report deleted (0 left) |

Lead review fixes after the sidekick pass: **fail-open bug** — a blocking crossing missing from `distances_to_crossings` was treated as infinitely far → `verified`; now `unverifiable` + new test. Template: removed per-entry duplicate empty alerts and the `mt-3 mt-3` artifact; near-route warning now names the crossing + report age; "other routes also pass" line deduplicated via `RoutePlan.passing_alternatives`.

Owner bug report (fixed same session): "Use my location" only wrote the text "My location" into From — coords were never sent, so Google geocoded the literal string. Fix (opt-in, ADR-005): `app.js` stores coords in hidden `origin_lat`/`origin_lng` fields on fix, clears them on Stop/typed-origin/autocomplete select; the form sends them only on explicit Find-route submit; `Waypoint(lat,lng)` → Routes API `location.latLng`; fields re-populate from GET so Refresh works. Also fixed: place autocomplete showed blank From/To after reload (`el.value` now seeded). Live-verified: `My location (10.0261,76.3125) → Edachira` returned two routes (8.4 km/24 min via Infopark Rd + 9.6 km/26 min alt), 615/625-pt polylines (`/tmp/vz_s06_myloc.html`).

Not verified: any of it in a real browser (polylines, panel switching, announcements); the `verified`-alternative path never occurred live (Google returned no alternatives in these calls — covered by mocked tests).

Post-review follow-ups (same session, owner-reported):
- **Place pickers → Google web components**: From/To now use `<gmpx-place-picker>` (Extended Component Library 0.6.15, Apache-2.0, pinned CDN script in `home.html`, rendered only when `map_config`; plain inputs remain the no-key fallback). Hidden `origin`/`destination`/`*_place_id` inputs carry the form data; `gmpx-placechange` syncs them; typed-but-unselected text is synced on submit via the picker's shadow input (guarded). "My location" writes text into the picker input + hidden coords.
- **Route alternatives are selectable**: `Route options` button list renders whenever ≥2 routes come back (was only when a crossing blocked) — `data-route-select` switching, `aria-pressed` + `data-selected` styling, per-route delta vs primary (`delta_*` now always computed). Panels show a "From … to …" line since picker text can't be restored after reload.
- Live: `My location → Edachira` renders Route 1 (8.4 km/24 min, Recommended) + Route 2 (9.6 km/26 min) with switch buttons (`/tmp/vz_s06_myloc2.html`). 173 tests OK.

## Commands/tests run (Session 05, actual outcomes — single end-of-session pass)
| Command | Result |
|---|---|
| `node --check static/js/map.js static/js/app.js` | OK (map.js re-checked OK after the lead's `setMarkerMap` fix) |
| `docker compose run --rm web python manage.py makemigrations --check --dry-run` | No changes detected |
| `docker compose run --rm web python manage.py check` | No issues (0 silenced) |
| `docker compose run --rm web python manage.py test --settings=config.settings.test` | **Ran 112 tests, OK** (was 92) |
| `curl 'localhost:8000/api/crossings/?bbox=76.18,9.85,76.45,10.15'` | 200, `count: 127`, `truncated: false` (real Kochi data) |
| `curl …?bbox=a,b,c,d` / `…?bbox=0,0,2,2` | 400 `invalid_bbox` / 400 `bbox_too_large` (`max_span_degrees: 1.5`) |
| `curl -s localhost:8000/ \| grep -c crossings-data` | 0; `/` 200 |
| `docker compose run --rm tailwind tailwindcss -i assets/tailwind/input.css -o static/css/app.css --minify` | Done (chip classes compiled) |

Not verified: anything in a real browser — marker loading/diffing, pin colours, chip, clicks, the legacy-Marker path, geolocation states, the accuracy circle. JS has no automated tests. Follow the RUNBOOK checklist.

WIP on branch `wip/crossing-labels`: derived crossing labels. It's incomplete, with no migration, tests or run.
- Goal: most OSM crossings have no `name` (0 of the 5 sampled in Kochi had one). Label each crossing from the road through it or the nearest named place. All values must come from OSM.
- The WIP branch edits `railways/{models,importer,admin}.py` and the command. To finish it:
  1. Add fields `road_name`, `road_ref`, `road_highway`, `road_osm_id`, `nearest_place_name`, `nearest_place_type`, `nearest_place_distance_m`, plus migration `0002`.
  2. Add a `display_name` property: `name` → "Level crossing on <road> (<ref>)" → "Level crossing near <place>" → "Unnamed level crossing". Prefer `name:en`, else `name`.
  3. Importer: `KeyFilter("railway","highway","place")`. Buffer crossings until the way pass is done, so the road is known.
  4. Pick the road among highway ways containing the crossing node: those with a name/ref first, then rank motorway > trunk > primary > secondary > tertiary > unclassified > residential > living_street > service > track > other (footway/path last), then lowest way id.
  5. Nearest place: `place` in {city, town, suburb, village, quarter, neighbourhood, hamlet, locality}, found via a 0.02° grid, ≤3 km haversine. Don't bbox-filter roads or places. Add counts `crossings_with_road` and `crossings_with_place`.
  6. UI: send `label`, `road`, `place`, `place_distance_m` in the home JSON and use them in map.js. Add "Road (OSM)" / "Nearby place (OSM, approx.)" rows in the panel and in `incidents/crossing_detail.html`.
  7. Tests: extend the synthetic fixtures (road choice, `name:en`, place distance, nothing within 3 km, rename on refresh, idempotency).
  8. Re-import Kochi and record how many crossings got a road and how many a place.

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
- Google Maps path is not verified by an agent in a real browser. `.env` now holds a real browser key, Map ID, and a working server key (Routes API live-verified). Check autocomplete `gmp-select`, Map ID styling, AdvancedMarker, crossing-marker click (it listens to both `gmp-click` and `click`, so the panel may fill twice; harmless), route polyline drawing/switching/`fitBounds`, `gm_authFailure`, and that the bottom sheet doesn't cover Google's logo/terms on mobile.
- Routing: the `verified`-alternative path is unit-tested but never observed live (Google returned no alternatives on the two Kochi pairs tried). The 20 m `on_route` threshold + 30 m track-intersection evidence kept a parallel-road route at `possible` (verified in PostGIS) — real `on_route` matches still need a route that truly crosses a track.
- Realtime (Session 07): browser path unverified (pin updates, reconnect/backoff). Report expiry produces no push — ageing relies on the ≤1/min visible poll, so pins can look up to ~1 min fresher than reality. Behind a reverse proxy, `Upgrade`/`Connection` headers and `wss://` are required; multi-worker requires `REDIS_URL` (in-memory layer can't cross processes). `REMOTE_ADDR` remains the routing-throttle key; behind a proxy set `X-Forwarded-For` handling before trusting it. The throttle/routing cache is shared via Redis only when `REDIS_URL` is set.
- Real OSM data lives only in the local dev DB volume (`pgdata`). Another machine must download and import it again (RUNBOOK "OSM import"). `data/osm/*.pbf` is git-ignored.
- Template tests only grep HTML; they can't catch JS syntax errors (the loader bug above slipped past them). Consider a `node --check` step or a browser smoke test in CI.
- Google terms: Places/Maps content caching/storage limits; Google route alternatives can't guarantee crossing avoidance (ADR-004).
- PostGIS runs under amd64 emulation on Apple Silicon (slow). `libgdal-dev` makes the image large.
- MIT code license vs ODbL obligations for distributed OSM-derived data still to review.
- No routing engine with true segment exclusion yet (ADR-013 chose Google + geometry verification). Valhalla `exclude_locations`/GraphHopper are documented future options.
- Importer tested on the real Kochi bbox only. Memory with `flex_mem` and run time on the full southern-zone or India extract are unknown (for India use `--location-index dense_file_array,...`).
- Reconcile leaves tracks that cross the bbox boundary alone (`__within`), so stale boundary tracks can stay active after a regional refresh.
- OSM attribution is shown in the home crossing panel. The ODbL share-alike review for distributing DB dumps is still open.
- Test settings still read `.env`. Any test that depends on blank keys must override settings explicitly.

## Next steps
1. **Owner: review and commit the uncommitted stack** — Sessions 10–13 are green together (332 tests) and `main` has unpushed commits.
2. **Browser-verify Session 13**: report a crossing closed → neighbour pins flip to "likely closed" live (WS republish); detail card shows the source-crossing link; journey alert + pre-nav confirm wording; then a blocked route with a custom source → "detour suggestion" card appears (live Google via call — mocked tests only so far).
3. Tune propagation knobs on real data: 28/127 Kochi crossings are unsnapped (>30 m from a track vertex — mostly crossings on ways outside the imported bbox edge); consider whether `RAILWAY_LINK_MAX_NEIGHBORS=3`/`RAILWAY_LINK_MAX_DISTANCE_M=15000` produce sensible maps.
4. **Owner: browser smoke with real keys** — click a POI and an empty spot → dynamic reroute (now also with a typed custom source); "Route here" on a crossing; "My location" default + permission alert flow; then the sim checklist from Session 08.
5. Find a Kochi route pair with a real `on_route` match + Google alternative; verify the `verified` card live; tune 20/50/30/100 m thresholds and `ROUTE_DETOUR_VIA_OFFSET_M` (300 m may under-shoot dense city grids).
6. Add a JS check to CI: at least `node --check static/js/*.js`, ideally a Playwright smoke.
7. **Finish crossing labels** from `wip/crossing-labels` (8-step plan in this file), then surface `label` in bbox payload, panel, route list — labels would make `inference.from_name` useful instead of "a crossing".
