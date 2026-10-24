# Session 05 — Map Integration and Geolocation

## Objective
Connect the UI to real map data and crossing records, with explicit, privacy-respecting location access.


## Mandatory shared instructions

Before coding, read `AGENTS.md`, `MASTER_PROMPT.md`, `PROJECT_STATE.md`, `DECISIONS.md`, `ROADMAP.md`, `DATA_SOURCES.md`, `RUNBOOK.md`, and `.agents/skills/vazhithirivu/SKILL.md` if present. Inspect the repository, Git status, current branch, current tests, and existing implementation. Preserve user changes and working features. Do not reset, clean, or overwrite unrelated work.

Use the documented architecture as the default: Django, server-rendered templates, Tailwind CSS, HTMX/Alpine.js as useful, PostgreSQL/PostGIS/GeoDjango, Django REST Framework where needed, Channels/Redis for genuine realtime needs, Celery for suitable background jobs, Docker Compose. Avoid introducing React, Kubernetes, or unnecessary services without evidence that they are needed. Google Maps Platform can provide maps/places/routes when configured; OpenStreetMap provides railway infrastructure data. Use provider abstractions and do not hardcode secrets.

Mandatory safety and data rules:
- Keep OSM reference infrastructure, community reports, real-user data, and simulator data separate.
- No report must never be interpreted as “open”.
- Stale or conflicting reports become “unknown” or an explicitly uncertain state.
- Show source and freshness; community reports are not official railway information.
- Never recommend crossing a closed gate or bypassing railway barriers.
- Do not claim a route avoids a crossing unless the route geometry or supported exclusion mechanism verifies it.
- Location is opt-in, stoppable, session-scoped where possible, and not public by default.
- Keep secrets out of Git and `.env`; use `.env.example` with placeholders.

For this session, implement code rather than returning only a plan. Add tests for the changed behavior, run checks available in the environment, and report actual outcomes honestly. If external credentials are unavailable, implement testable abstractions/fallbacks and document what remains blocked.

At the end, update `PROJECT_STATE.md` with: milestone status, changes made, important files, commands/tests and their real outcomes, limitations/blockers, and the next 3–7 concrete steps. Update `ROADMAP.md`, `RUNBOOK.md`, or `DECISIONS.md` when needed. Inspect `git diff` and `git status`. Do not commit unless explicitly asked or repository workflow requires it.

## Tasks
1. Inspect the UI shell and data endpoints created in earlier sessions.
2. Integrate Google Maps JavaScript API if configured, using environment-driven settings and documented key restrictions. If credentials are unavailable, provide a clear local fallback/degraded state without claiming a live map works.
3. Implement origin/destination search using Places/autocomplete only when configured and within provider terms.
4. Request browser geolocation only after an explicit user action. Handle permission denial, unsupported browser, timeout, inaccurate fixes, and unavailable location.
5. Implement a backend endpoint/query for crossings in the current map bounds or a suitable radius. Use spatial indexes and bounded result sizes.
6. Render crossing markers with accessible status labels and distinguish unknown/stale states. Add a crossing detail panel showing source and last report time.
7. Throttle map-bound requests; do not fetch on every tiny pan/animation event. Avoid excessive polling.
8. Keep location data private and session-scoped where possible; do not persist exact user location unless needed and documented.
9. Add tests for spatial queries and endpoint behavior. Add manual smoke-test instructions for map credentials.

## Acceptance criteria
- Map integration works when configured, or a clearly documented fallback is shown.
- Geolocation is explicitly user-initiated and gracefully handles errors.
- Map markers reflect backend data and uncertainty rather than hardcoded “live” states.
- Spatial queries are bounded and use appropriate indexes.
