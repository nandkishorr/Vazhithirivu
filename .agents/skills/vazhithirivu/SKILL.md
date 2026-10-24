---
name: vazhithirivu
description: Repository-specific engineering workflow for Vazhithirivu, a Django/PostGIS railway-crossing intelligence and smart-rerouting application with an optional isolated simulator.
---

# Vazhithirivu Engineering Skill

## Always load context first
Read:
1. `AGENTS.md`
2. This skill
3. `PROJECT_STATE.md`
4. Relevant sections of `DECISIONS.md`, `ROADMAP.md`, `DATA_SOURCES.md`, and `RUNBOOK.md`

Then inspect `git status` and relevant code. Do not assume prior session work is absent because it is not in chat.

## Domain model
Keep these concerns separate:
- **Reference geography:** OSM tracks/crossings and source metadata.
- **Incident data:** timestamped reports, expiry, derived status and uncertainty.
- **Real users:** explicit opt-in location sessions and navigation sessions.
- **Simulation:** run-scoped simulated vehicles, gate cycles, events and metrics.
- **Routing:** provider abstraction, route geometry, crossing association and detour validation.
- **Presentation:** Django templates, Tailwind, HTMX/Alpine, map UI.

Never store a gate's simulated open/closed state by mutating the imported OSM crossing record.

## OSM import workflow
- Prefer a country/regional PBF extract and a repeatable importer.
- Import `railway=level_crossing` nodes and relevant railway/road geometries/tags.
- Use stable OSM object IDs/type to deduplicate and support updates.
- Make imports idempotent and report counts, skipped records and failures.
- Keep small fixtures for tests; tests must not depend on live Overpass.
- Do not fetch OSM/Overpass data for every user, route, or GPS update.
- Do not automatically download the full India extract during web container startup.
- Document source, attribution, ODbL obligations, extract date and refresh method.
- Missing OSM crossings must be handled through admin correction/manual additions; never claim the dataset is complete.

## Spatial and routing workflow
- Use PostGIS/GeoDjango and spatial indexes for nearby crossing queries.
- Prefer route topology and route geometry association over simple proximity buffers.
- Track route order/distance for crossings encountered along the route.
- Hide provider specifics behind a routing service.
- Treat alternative routes as candidates, not automatically valid detours.
- Verify that the candidate avoids the crossing/blocked road segment.
- If avoidance cannot be verified, say so in the UI and don't claim the route is safe.
- Handle quotas, timeouts, no-route responses and missing API credentials gracefully.
- Never fabricate durations or use a closure prediction as fact.

## Incident intelligence
- Store report source, timestamp, expiry, and any confidence/verification metadata.
- Stale or conflicting reports should result in an uncertain/unknown state.
- Absence of a closure report does not prove a gate is open.
- Deduplicate reports and suppress repeated prompts for the same incident.
- Never describe community reports or simulator events as official railway data.
- For MVP, prefer transparent deterministic rules over AI-generated status.

## Location privacy
- Request browser geolocation only after an explicit action.
- Provide immediate pause/stop controls.
- Scope updates to a permitted session; throttle submissions.
- Don't publicly broadcast exact coordinates by default.
- Apply retention/expiry and cleanup; avoid indefinite trails.
- Keep simulation identities and real-user identities completely separate.

## Simulator workflow
- Simulator is optional and independently controlled via Docker Compose profile/service.
- Every run and simulated record has a simulation run ID and simulation source flag.
- Reuse the same incident/reroute decision services, with source separation.
- Stopping simulation stops future events/tasks but never deletes real-user data.
- Vehicle movement is along route geometry; animate client-side between coarse updates.
- Do not schedule a task per vehicle frame.
- Provide deterministic, replayable scenarios and explicit start/pause/stop/reset behavior.

## UI/UX workflow
- Tailwind CSS is the design system; build reusable Django template partials.
- Map-first, responsive layout: desktop side panel, mobile bottom sheet.
- Include loading, empty, error, permission-denied, stale-status and provider-unavailable states.
- Use semantic status colors plus labels/icons.
- Provide accessible focus, keyboard behavior, ARIA and reduced-motion support.
- Keep map layers stable; update existing markers/polylines rather than rebuilding the whole map on every tick.
- Simulated values and markers must be clearly labelled.
- Verify Tailwind production build is included in Docker.

## Testing
- Unit-test OSM parsing/idempotency with fixtures.
- Test spatial queries and route-crossing association.
- Test status freshness/conflicts and detour avoidance.
- Test location session boundaries/expiry.
- Test simulator lifecycle and prove it cannot mutate real-user records.
- Mock external providers; do not rely on live Google/Overpass in automated tests.
- Run targeted tests first, then broader checks if time permits.
- Record actual command and outcome in `PROJECT_STATE.md`.

## Session handoff
Before finishing:
1. Summarize changed files and actual test results.
2. Update `PROJECT_STATE.md` with current state, blockers, and next 3–7 steps.
3. Update `DECISIONS.md` only for lasting decisions.
4. Update this skill only when a reusable domain workflow or invariant changes.
5. Do not paste the full conversation into project memory. Keep only durable, actionable facts.
