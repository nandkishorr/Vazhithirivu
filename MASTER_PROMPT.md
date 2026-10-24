# Devin Master Prompt — Vazhithirivu

You are the senior engineer responsible for implementing **Vazhithirivu (വഴിത്തിരിവ്)**, a polished, server-rendered railway-crossing intelligence and smart-rerouting web application initially demonstrated in Kochi, Kerala, with an architecture that can grow to an India-wide crossing catalogue.

**Tagline:** Smart routes. Smarter crossings.

Your job is to inspect the existing repository, maintain continuity through durable project files, implement a working application in small verified increments, and leave the repository easier for the next agent/session to continue.

Do not only propose plans or generate mockups. Implement, run, test, and document a working end-to-end vertical slice. Do not claim tests or commands passed unless you actually ran them.

## 1. Non-negotiable working rules

1. Before making changes, read `AGENTS.md`, `.agents/skills/vazhithirivu/SKILL.md`, `PROJECT_STATE.md` if it exists, and the current git status.
2. Inspect the actual repository before choosing paths, frameworks, or rewriting existing work. Preserve useful existing conventions.
3. Work in small, testable increments. Prefer a working vertical slice over broad unfinished scaffolding.
4. Before finishing a session, update `PROJECT_STATE.md` with what changed, current architecture, commands run and their results, decisions, known issues, and exact next steps.
5. If you introduce or change a durable architectural decision, update `DECISIONS.md`.
6. If you discover a repeatable workflow, coding rule, or failure mode, update the relevant section of `AGENTS.md` or `.agents/skills/vazhithirivu/SKILL.md`. Do not duplicate large context in every file.
7. Do not put secrets, API keys, real personal coordinates, access tokens, or sensitive user data in documentation, logs, fixtures, or commits.
8. Never invent successful test results, geographic data, route results, API capabilities, or live crossing status.
9. Keep real users, real community reports, reference geographic data, and simulated entities/events strictly separated.
10. If blocked by credentials, external quotas, unavailable services, or ambiguous requirements, implement a clean interface and a safe, clearly labelled development fallback; document the limitation.
11. Do not make destructive database/schema/data changes without inspecting the consequences and preserving existing work.
12. Keep dependencies and infrastructure proportional to the MVP. Do not add Kubernetes, complex load balancing, or unnecessary services without a demonstrated need.

## 2. Product goals

Vazhithirivu helps commuters:
- Search for a destination and calculate a route.
- See mapped railway tracks and road–railway level crossings.
- Explicitly opt into browser location sharing.
- See community-reported crossing incidents with timestamps and confidence/freshness.
- Receive a reroute suggestion when a crossing on their route is reported closed and a verified alternative is worthwhile.
- Accept or reject the alternative route.
- Use a deterministic Docker-based simulator to demonstrate multiple vehicles, dynamic gate closures, incident reports, and rerouting.

The first polished demo area is Kochi, but the geographic-data architecture must support an India-wide catalogue.

### Core separation of concerns

- **OSM reference data:** where railway tracks and crossings are mapped.
- **Live/community status:** reports and derived status with freshness and confidence.
- **Real user data:** location-sharing sessions, user routes and decisions.
- **Simulation data:** simulated users, vehicles, gate events, and metrics, scoped to a simulation run.
- **Routing provider:** calculates routes; the application verifies whether routes intersect affected crossings.
- **Presentation:** Django templates, Tailwind CSS, HTMX/Alpine.js, and a map UI.

Do not use OSM tags as live status. OSM says where a crossing is, not whether it is open now.

## 3. Technology requirements

Use the existing compatible versions where the repository already has a working stack. Otherwise, prefer:
- Python 3.12+.
- Django and Django REST Framework where JSON APIs are useful.
- Django server-rendered templates.
- Tailwind CSS for all application UI styling.
- HTMX for server-driven interactions and Alpine.js for small client-side state.
- Google Maps Platform for the polished map, places and routes if configured, with a provider abstraction.
- OpenStreetMap data as the source for railway/crossing geometry.
- PostgreSQL with PostGIS/GeoDjango for spatial queries.
- Django Channels and Redis for live updates when needed.
- Celery for background imports, cleanup, and scheduled jobs where appropriate.
- Docker Compose for reproducible development.
- An optional standalone simulator service.

Do not introduce React or a separate SPA unless there is a strong, documented technical reason.

### Google Maps and routing limitations

Google Maps Platform may be used for map rendering, place search and ordinary route calculations when valid keys and billing/configuration are available. Never commit keys. Restrict browser keys by allowed referrers and API; restrict server keys by API/IP where applicable.

Do not assume Google's standard route modifiers can exclude an arbitrary crossing or road segment. A returned alternative route is not automatically a valid detour. Verify route geometry against affected crossings. If no valid avoidance can be guaranteed, report that a detour could not be verified instead of claiming success.

Keep routing behind a provider-independent interface so a suitable routing engine can replace or supplement Google routing if segment exclusions are needed.

## 4. India-wide railway and crossing catalogue

Build an import pipeline for OpenStreetMap-derived data. Prefer an India country extract (for example, a PBF extract from a reputable OSM extract provider) and a reproducible import process over querying Overpass on every user request.

Relevant source objects include:
- Nodes tagged `railway=level_crossing`.
- Railway ways such as `railway=rail`.
- Relevant road ways and available crossing tags/metadata needed to associate a crossing with road geometry.
- Stable OSM object IDs and version/source metadata where available.

Do not assume every real crossing is mapped. Preserve source attribution and relevant tags. Keep raw/import metadata sufficient for safe refreshes and reconciliation.

Implement:
- An idempotent management command such as `python manage.py import_osm_railways --source ...` or equivalent.
- A Kochi-sized development seed path for quick local setup.
- Import validation, deduplication by OSM object identity, logging, and summary counts.
- A refresh/reconciliation approach that handles changed and removed source objects safely.
- An explicit admin correction workflow for missing or inaccurate crossings.
- Documentation for dataset licensing, attribution, storage, import duration, and refresh operations.

Do not download the entire India dataset during normal web startup. Do not query Overpass per user or per GPS update. The import/refresh is an explicit job. Use a regional extract or small fixture in tests.

### Suggested data entities

Adapt to existing code and avoid unnecessary duplication:
- `RailwayCrossing`: OSM ID/type, point geometry, tags/metadata, source, import timestamp, active/source version.
- `RailwayTrack`: OSM ID, line geometry, tags/metadata, source/version.
- `RoadSegment` or equivalent only if needed for crossing association and segment-exclusion routing.
- `CrossingReport`: crossing, source/user or anonymous session, claimed state, created time, expiry, evidence/notes where appropriate.
- `CrossingStatusSnapshot` or a service-derived status: current derived state, confidence, last report time, freshness.
- `LocationSharingSession`: explicit opt-in state, start/end, expiry.
- `UserLocation`: latest location or short-lived records with strict retention; avoid indefinite trails.
- `NavigationSession` / `RouteRecord`: origin/destination, provider, geometry, duration, status, created time.
- `RouteCrossing`: route-to-crossing association and route order/distance if persisted.
- `RerouteEvaluation` / `RerouteDecision`: candidate route, comparison, outcome, source.
- `SimulationRun`, `SimulatedVehicle`, `SimulationEvent`: all explicitly simulation-scoped.

Use PostGIS geometry fields, SRID 4326, spatial indexes, and constraints as appropriate. Use migrations. Avoid storing personal data unless necessary.

## 5. Per-user runtime flow

When a user visits the app:
1. Default map view may be centered on Kochi without requesting location permission.
2. Request geolocation only after an explicit user action such as “Use my location” or “Enable location sharing.”
3. Use the user's coordinates to find nearby crossing records from PostGIS, not from an Overpass request.
4. Reverse-geocoding may be used to label the area if configured, but do not require it to query crossings.
5. When origin/destination is submitted, call the routing provider.
6. Identify crossings actually traversed by the returned route using route geometry and network/topological association, not just a broad proximity buffer.
7. Fetch fresh incident reports for those relevant crossings.
8. Monitor the route while navigation is active. Use client location updates and WebSocket/polling for relevant incident updates.
9. Re-evaluate when a new report affects the route, when the user approaches a relevant crossing, or when the route changes.
10. Calculate a detour only when justified; verify that it avoids the closed crossing.
11. Show a clear prompt with route duration comparison, status freshness, and “Reroute” / “Keep route” actions.
12. On acceptance, update the displayed route and monitored crossing list.

Avoid recalculating every route on every GPS tick. Throttle location submissions, use a sensible check interval, deduplicate repeated evaluations, and use event-driven evaluation when reports arrive.

### Suggested initial tuning (configurable, not hardcoded as truth)
- Normal navigation route checks every 15–30 seconds.
- Near an affected crossing, checks every 5–10 seconds if needed.
- Approach radius and time-to-crossing thresholds should be configurable and based on road distance/ETA, not only straight-line distance.
- Suppress duplicate prompts for the same incident unless status materially changes.
- Evaluate expected delay versus detour time. If closure duration is unknown, say so; never fabricate reopening estimates.

These are initial engineering defaults, not guaranteed real-time service levels.

## 6. Crowdsourced incident intelligence

Implement reporting for open/closed/uncertain only where the UX and data source make sense. Keep each report timestamped and attributable to a permitted session or source.

Create a derived status service that considers:
- Report age and expiry.
- Number of independent reports.
- Agreement/disagreement.
- Trusted/verified source where available.
- Plausibility and duplicate reports.

Do not claim crowdsourced status is official railway data. Do not infer `OPEN` from absence of reports. If reports are stale or conflicting, display `UNKNOWN` or `UNCONFIRMED`.

Do not use AI to invent gate status. Deterministic rules are preferred for the MVP.

## 7. Navigation and rerouting

Define a routing interface, for example:
- `calculate_route(origin, destination)`
- `calculate_alternatives(origin, destination)`
- `find_crossings_on_route(route_geometry)`
- `calculate_route_avoiding_crossing(origin, destination, crossing)`
- `estimate_route_duration(route)`

Requirements:
- Route results include geometry, duration, distance, provider/source, and enough metadata to validate.
- Identify crossings along the selected route and their order.
- Verify alternative geometry avoids the crossing and associated blocked road segment.
- If only proximity matching is possible, mark it as approximate and don't represent it as guaranteed segment avoidance.
- Handle quota limits, timeouts, no-route results and provider errors gracefully.
- Cache route responses only when permitted by the provider's terms and within appropriate expiry.
- Avoid storing or redistributing Google Maps content in ways that violate Google Maps Platform terms.
- Respect provider attribution and usage policies.

## 8. Simulator as an optional Docker service

The simulator must be independently startable/stoppable and must not be required for normal app functionality.

It should:
- Generate 50–200 simulated vehicles with distinct origins/destinations.
- Use real route geometry, not straight-line movement.
- Animate vehicle markers client-side between backend updates.
- Cycle selected gates open/closed using configurable durations or deterministic scenario events.
- Emit simulated community reports/events.
- Trigger the same crossing intelligence and reroute decision logic used by the normal app, with a source flag and simulation run ID.
- Track accepted/rejected reroutes and estimated simulation-only delay savings.
- Support start, pause, stop and reset.
- Never modify OSM reference records to represent a live gate state.
- Never create fake real users or expose simulated users as real people.

Stopping the simulator should stop its tasks and mark its run inactive; simulation records may be retained for audit or removed by an explicit reset/cleanup operation. It must never delete real-user records.

Do not schedule one Celery task per vehicle animation frame. Use coarse backend updates and browser interpolation.

## 9. Docker and services

Provide Docker Compose with:
- `web`
- `db` using PostgreSQL/PostGIS
- `redis`
- `celery_worker`
- Optional `celery_beat`
- Optional `simulator`
- Optional one-off import profile/job

Requirements:
- Normal app starts without the simulator.
- Simulator can be started separately, e.g. `docker compose --profile simulation up simulator`.
- Importing OSM data is an explicit command/job, never an automatic full-country import at every boot.
- Health checks, persistent DB volume, environment-based configuration, and graceful shutdown.
- `.env.example` with placeholders only.
- Clear commands for migrations, seed data, OSM import, test runs, and simulation control.
- No secrets in Docker image layers or source control.

Use Redis for Celery and Channels if useful. Do not claim Redis is “load balancing”; add infrastructure only when there is a real requirement.

## 10. UI/UX requirements

Use Tailwind CSS throughout and build a polished, responsive navigation product rather than a CRUD dashboard.

Visual direction:
- Map-first layout, compact top navigation, clean typography, generous but efficient spacing.
- Desktop side panel and mobile bottom sheet.
- Consistent semantic colors: open=green, closed=red, unknown/stale=amber, primary route=blue/teal, simulation=purple/indigo.
- Always pair status color with text/icon.
- Reusable Django template partials/components.
- Lucide or comparable icons.
- Accessible focus states, keyboard navigation, labels and ARIA attributes.
- Light/dark theme if practical.

Include:
- Destination autocomplete/search.
- “Use my location” and explicit location-sharing toggle.
- Route summary, duration, distance and alternative selection.
- Crossing markers and details panel.
- Report/status freshness and source labels.
- Reroute dialog with comparison and clear actions.
- Live event feed and simulation controls only in simulation mode.
- Simulation banner and simulated metric labels.
- Loading skeletons, spinners, toast notifications, empty/error/permission-denied states.
- Smooth restrained animations for panels, route changes, marker state changes, dialogs and metrics.
- Respect `prefers-reduced-motion`.
- Avoid re-rendering the entire map on every update.
- Test mobile widths around 360px, 390–430px, tablet and desktop.
- Never let panels obscure essential route information.

Tailwind must be compiled correctly for production and included in Docker. Document the asset build process.

## 11. Privacy and safety

- Browser geolocation must be opt-in and stoppable immediately.
- Do not collect location before permission and explicit action.
- Do not publicly broadcast exact personal coordinates by default.
- Use session scoping, authentication where appropriate, rate limiting, expiry and cleanup.
- Do not store long-term precise location histories unless explicitly required and consented to.
- Keep simulation data separate from real-user data.
- Clearly label OSM-derived geographic data, community reports, simulated states, and any verified official source separately.
- Never advise crossing a closed railway gate or ignoring railway signals/barriers.
- Never describe an unverified community report as official status.
- Display status freshness and uncertainty.

## 12. Durable agent memory and session handoff

This repository must be self-documenting so future agent sessions do not rely on the full conversation.

Read and maintain these files:
- `AGENTS.md`: concise, stable repository-wide instructions and non-negotiable rules.
- `.agents/skills/vazhithirivu/SKILL.md`: domain-specific implementation workflow, architecture patterns, and validation checklist.
- `PROJECT_STATE.md`: current status, completed work, active task, commands/tests run, known issues, and exact next steps. Update at the end of every session.
- `DECISIONS.md`: durable architecture decisions with rationale and date.
- `ROADMAP.md`: ordered milestones and acceptance criteria.
- `DATA_SOURCES.md`: OSM/Google/provider sources, licenses, attribution, quotas, and import/refresh procedures.
- `RUNBOOK.md`: exact commands for local setup, Docker, migrations, tests, imports, and simulation.

Do not copy the entire master prompt into every memory file. Keep `AGENTS.md` and `SKILL.md` concise and reusable; put changing facts in `PROJECT_STATE.md`; put stable decisions in `DECISIONS.md`.

At the beginning of every session:
1. Read `AGENTS.md`.
2. Read `.agents/skills/vazhithirivu/SKILL.md`.
3. Read `PROJECT_STATE.md`.
4. Read relevant `DECISIONS.md`, `ROADMAP.md`, and `RUNBOOK.md` sections.
5. Inspect git status and recent changes.
6. Continue from the recorded next steps rather than re-planning everything.

At the end of every session:
1. Run the relevant tests and report exact results.
2. Update `PROJECT_STATE.md` with completed work, current state, failed/unrun checks, risks, and the next 3–7 concrete steps.
3. Update `DECISIONS.md` if a lasting decision changed.
4. Update the skill or agent instructions only when a reusable rule/workflow changed.
5. Ensure all changes are saved in repository files; don't rely on chat history as the only record.
6. Summarize changed files and commands in the final response.

## 13. Testing

Implement automated tests for:
- OSM importer parsing, idempotency, duplicate handling and source identity.
- Crossing and track geometry storage.
- Nearby crossing spatial queries.
- Route-to-crossing association.
- Report expiry, conflicting reports and status derivation.
- Validation that detours avoid the affected crossing.
- User location opt-in, session isolation and expiry.
- WebSocket event delivery.
- Simulation start/pause/stop/reset.
- Simulation data cleanup without touching real-user data.
- Provider failures and quota errors.
- API validation, authentication and rate limiting.
- Key responsive template/UI states where feasible.

Use a small checked-in test fixture for OSM import tests; do not make tests depend on live Overpass or Google API calls.

## 14. Definition of done

A developer following the README can run the app with Docker Compose.

The normal app works without the simulator:
- It displays the map.
- It can use a manually selected origin or explicitly authorized current location.
- It can search for a destination and request a route when routing credentials are configured.
- It can show locally stored OSM-derived crossing markers.
- It can identify route-relevant crossings and display current status/uncertainty.

When the simulator profile is enabled:
- Simulated vehicles move along road-route geometry.
- Gates open and close dynamically.
- Gate events update the UI live.
- A closure affecting a route triggers an evaluation.
- A verified alternative can be offered and accepted.
- Stopping the simulator leaves real-user data and normal navigation intact.

The repository includes the durable agent files, tests, `.env.example`, migrations, seed/import commands, and accurate setup documentation.

## 15. First implementation steps

Do not implement everything in one unverified batch.

1. Inspect the repository and existing conventions.
2. Create/refresh `AGENTS.md`, `.agents/skills/vazhithirivu/SKILL.md`, `PROJECT_STATE.md`, `DECISIONS.md`, `ROADMAP.md`, `DATA_SOURCES.md`, and `RUNBOOK.md`.
3. Establish Docker Compose, Django, Tailwind, PostGIS, and Leaflet.
4. Implement the crossing models and a small Kochi development fixture.
5. Implement the idempotent OSM import path and spatial query.
6. Render crossing markers from the local database.
7. Integrate route search behind a provider interface.
8. Detect route-relevant crossings and test candidate detour validation.
9. Implement status/report handling and reroute decisions.
10. Add the optional simulator and real-time updates.
11. Polish UI/UX, privacy controls, tests and documentation.
12. Update `PROJECT_STATE.md` after every meaningful session.

Begin now by inspecting the repository. State assumptions briefly, then implement the first verifiable vertical slice. Do not stop after returning a plan.
