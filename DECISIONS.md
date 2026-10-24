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

## Updating decisions
When a proposal becomes implemented, update its status and include the implementation reference/PR if known. Add a new ADR rather than silently rewriting a decision whose rationale materially changed.
