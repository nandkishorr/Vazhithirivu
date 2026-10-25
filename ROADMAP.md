# Roadmap — Vazhithirivu

Prioritize complete vertical slices. Mark each milestone with status, evidence and blockers.

## M0 — Repository discovery and durable handoff — DONE (Session 00, 2026-10-24)
- [x] Inspect existing repository and preserve conventions. Evidence: there is no app code, only the spec bundle and a deleted-but-uncommitted `LICENSE` (see `PROJECT_STATE.md`).
- [x] Confirm Python/Django/Tailwind versions and current Docker setup. Evidence: no Python/Django/Tailwind/Docker project files exist yet. Host Docker 29.8.2/Compose v5.5.1 works, and the `postgis/postgis:16-3.4` container starts (amd64 under emulation).
- [x] Fill `PROJECT_STATE.md` with actual repository facts.
- [x] Record architecture decisions. Added ADR-006 (all services containerised). Exact run commands are deferred to Session 01, because no app exists to run.

## M1 — Local map and crossing catalogue — IN PROGRESS
- [x] Docker Compose: Django + PostgreSQL/PostGIS. All services are containerised (ADR-006), and the DB port is not published. Redis is deferred (ADR-007). Evidence: Session 01, 10 tests OK, `/readyz/` 200 with PostGIS 3.5.2.
- [x] Env-driven settings (dev/test/prod), `.env.example`, `.gitignore`, health endpoints.
- [x] Tailwind build integrated with Django and Docker. Evidence: Session 02, Tailwind 4.3.3 standalone CLI stage, `app.css` present in prod image (ADR-008).
- [~] Google Maps JavaScript API map page + Place Autocomplete (ADR-009). Implemented and unit-tested; not yet exercised in a browser with real keys.
- [x] Crossing/track models and small test fixture. Evidence: Session 03, `railways` app, synthetic `sample_v1/v2.osm` fixtures (ADR-010).
- [x] Idempotent OSM import command. Evidence: Session 03, `import_osm_railways` (pyosmium 4.3.2). Real Kochi import (Geofabrik southern zone + bbox): 127 crossings / 330 tracks; rerun created 0.
- [x] Nearby crossing query using PostGIS (bbox/nearby endpoint). Evidence: Session 05, `GET /api/crossings/?bbox=` (bounded, GiST-indexed, `MAP_CROSSINGS_LIMIT` cap, constant-query derived statuses; ADR-012).
- [~] Map markers sourced from the local database. Bbox-loaded, status-coloured pins with glyphs + details panel + live status fetch; not yet clicked in a real browser (RUNBOOK smoke checklist).
- [~] Human-readable crossing labels (road name / nearest place from OSM). Incomplete WIP on branch `wip/crossing-labels`.
- [x] Attribution and source metadata visible/documented. DATA_SOURCES/RUNBOOK + "© OpenStreetMap contributors" in the home crossing panel.

## M2 — Route planning and crossing association
- [x] Provider-independent routing interface. Evidence: Session 06, `routing.providers` (`Waypoint`/`RouteCandidate`/`RoutingError`) + Google Routes impl (ADR-013).
- [x] Origin/destination selection and route display. Evidence: Session 06, GET form → route panels + map polylines (`_route_plan.html`, `map.js setupRoutes`).
- [x] Route geometry and travel-time metadata. Evidence: Session 06, encoded polyline → PostGIS LineString; km + "Google estimate, without live traffic".
- [x] Identify crossings actually traversed by a route. Evidence: Session 06, `routing.analysis` — on_route requires track intersection evidence; nearby-only is `possible`.
- [x] Validate alternative route avoidance. Evidence: Session 06, `verified` only when all blocking crossings >100 m away and the alternative has no own closed crossing; honest passes/uncertain/unverifiable states.
- [x] Tests with mocked providers and fixed geometries. Evidence: Session 06, `routing/tests/` (polyline, provider, analysis, services, views, checks).

## M3 — Incident intelligence
- [x] Timestamped community reports.
- [x] Expiry, duplicate handling and conflicting-report logic.
- [~] Status freshness and confidence display (done on crossing detail page, JSON API and the map marker panel; browser marker-click not yet verified).
- [x] Route-aware incident evaluation. Evidence: Session 06, `plan_route` bulk-derives statuses and sets warning levels (closed on/near route, conflicting).
- [x] Reroute prompt with accept/reject actions. Evidence: Session 06, user-confirmed `[data-route-select]` switching with aria-live announcements; verified-only avoidance claims.
- [x] Realtime status pushes with polling fallback. Evidence: Session 07, `/ws/crossings/` (bounded ID subscriptions, snapshot-on-subscribe, server-derived pushes) + ≤1/min map refresh; ADR-014. Not yet exercised in a real browser.

## M4 — Opt-in real-user location
- [x] Explicit permission action (browser-only, click-triggered `getCurrentPosition`; journey mode uses `watchPosition` behind a Start button — coordinates only ever leave the browser inside an active session).
- [x] Pause/stop sharing (Stop button removes marker/circle and invalidates pending callbacks; journey "End" stops the watch and ends the session server-side).
- [x] Throttled location updates and session scope. Evidence: Session 10, `navigation` app — UUID `JourneySession` capability token, `NAV_MIN_UPDATE_SECONDS` server-side min interval + client distance/time gating, `NAV_SESSION_MAX_HOURS` TTL (ADR-017).
- [x] Privacy controls and expiry/cleanup. Evidence: session TTL + `purge_navigation_sessions` (`NAV_SESSION_RETENTION_DAYS`); dismissed-alert suppression client-side; session schema holds no coordinates/user/route.
- [x] No public exposure of exact location by default. Evidence: positions are POST bodies answered transiently — no coordinate columns, no WS channel, nothing echoed back.

## M5 — Optional simulator — DONE (Session 08, ADR-015)
- [x] Independent Docker Compose profile/service (`--profile simulation` → `run_simulator`; app works without it).
- [x] Simulation run IDs and isolated data (`simulator_*` tables, run-scoped, cascade reset; `active_slot` enforces one active run).
- [x] Deterministic gate cycles (`--seed` + `--gate ID:CLOSE:OPEN` / `--random-gates`) as the physical schedule; status surfaces only via presence inference → confirmation prompt → human confirm (or `--auto-confirm`). Evidence: Session 10, ADR-018.
- [x] 1–200 static simulated users parked at real crossings — on **synthetic** approach lines perpendicular to the nearest track (no road geometry is imported; labelled as demo). Users never move (Session 14, ADR-021).
- [x] WebSocket updates and client-side display (`ws/simulation/` coarse ticks + `/api/simulation/` poll fallback). Not yet exercised in a real browser.
- [x] Reuse incident/reroute services — registered status overlay (`effective_statuses`); simulated closures block routes through the same verification flow, labelled everywhere.
- [x] Start/pause/stop/reset + isolation tests proving reports/reference data untouched (48 new tests).

## M6 — Product polish
- [~] Responsive Tailwind UI, desktop panel and mobile bottom sheet (shell built Session 02; not visually verified on devices).
- [~] Loading/error/empty/stale states (built Session 02, see `/ui/` in DEBUG); toasts pending.
- [ ] Accessible controls and reduced-motion support.
- [ ] API quota and provider-failure handling.
- [ ] Documentation, runbook and demo script.
