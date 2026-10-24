# Session 07 — Realtime Updates and Freshness

## Objective
Deliver relevant crossing status changes to connected users without excessive load or leaking location data.


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
1. Verify whether real-time updates are necessary for the implemented user flows and inspect existing Channels/Redis setup.
2. Implement Django Channels/WebSockets only where they provide meaningful benefit. Provide a polling or refresh fallback if WebSockets are unavailable.
3. Subscribe clients only to relevant crossing IDs or a bounded area. Do not broadcast precise user locations to other users.
4. Notify clients when new reports change a crossing's derived display state. Include timestamps and status provenance.
5. Enforce freshness and conflict rules on the server, not just in client JavaScript.
6. Throttle/coalesce noisy updates and avoid one background task per animation frame or per tiny client location change.
7. Handle reconnects, stale connections, permission/authentication checks, and missed updates.
8. Add tests for update delivery/authorization and stale-state behavior. Mock channel layers as appropriate.
9. Document local Redis and Channels setup plus fallback behavior in `RUNBOOK.md`.

## Acceptance criteria
- Relevant clients receive crossing-state changes or have a reliable fallback.
- Users cannot subscribe to arbitrary private data or other users' precise locations.
- Server-side status/freshness remains authoritative for the app's display semantics.
- Tests and run instructions are updated.
