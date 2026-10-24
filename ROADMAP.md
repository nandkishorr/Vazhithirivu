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
- [ ] Tailwind build integrated with Django and Docker.
- [ ] Leaflet or Google Maps JavaScript API map page.
- [ ] Crossing/track models and small test fixture.
- [ ] Idempotent OSM import command.
- [ ] Nearby crossing query using PostGIS.
- [ ] Map markers sourced from the local database.
- [ ] Attribution and source metadata visible/documented.

## M2 — Route planning and crossing association
- [ ] Provider-independent routing interface.
- [ ] Origin/destination selection and route display.
- [ ] Route geometry and travel-time metadata.
- [ ] Identify crossings actually traversed by a route.
- [ ] Validate alternative route avoidance.
- [ ] Tests with mocked providers and fixed geometries.

## M3 — Incident intelligence
- [ ] Timestamped community reports.
- [ ] Expiry, duplicate handling and conflicting-report logic.
- [ ] Status freshness and confidence display.
- [ ] Route-aware incident evaluation.
- [ ] Reroute prompt with accept/reject actions.

## M4 — Opt-in real-user location
- [ ] Explicit permission action.
- [ ] Pause/stop sharing.
- [ ] Throttled location updates and session scope.
- [ ] Privacy controls and expiry/cleanup.
- [ ] No public exposure of exact location by default.

## M5 — Optional simulator
- [ ] Independent Docker Compose profile/service.
- [ ] Simulation run IDs and isolated data.
- [ ] Deterministic gate cycles.
- [ ] 50–200 simulated vehicles along route geometry.
- [ ] WebSocket updates and client-side animation.
- [ ] Reuse incident/reroute services.
- [ ] Start/pause/stop/reset tests proving real data remains untouched.

## M6 — Product polish
- [ ] Responsive Tailwind UI, desktop panel and mobile bottom sheet.
- [ ] Loading/error/empty/stale states and toasts.
- [ ] Accessible controls and reduced-motion support.
- [ ] API quota and provider-failure handling.
- [ ] Documentation, runbook and demo script.
