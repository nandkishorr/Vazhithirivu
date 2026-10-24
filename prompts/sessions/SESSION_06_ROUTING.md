# Session 06 — Routing and Verified Crossing Avoidance

## Objective
Implement destination routing and safe rerouting behavior around a reported closed crossing.


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
1. Inspect current map, crossing query, and provider integration.
2. Create a routing provider abstraction with a configured Google Maps route provider if supported by project setup. Keep credentials out of source code.
3. Implement route calculation from origin to destination and display route summary/geometry using the selected provider.
4. Identify crossings intersecting or lying near the route using spatial calculations and sensible tolerances. Avoid treating every nearby crossing as definitely on the route.
5. When a relevant crossing has a sufficiently fresh closed report, show a clear warning and offer an alternative route only if a supported route provider or routing engine can calculate one.
6. Verify that the alternative route geometry avoids the affected crossing/road segment. If verification is not possible, say so and do not claim avoidance. Consider a routing provider with edge/segment exclusion if needed.
7. Do not infer that a crossing is open when there is no report. Make unknown/stale status visible without over-warning.
8. Make the reroute action user-confirmed; do not silently replace a route without communicating the change.
9. Add tests for route-crossing association, closed report handling, alternative-route verification, and unverified fallback behavior. Mock external APIs.
10. Document provider limitations, quotas/configuration, and fallback behavior.

## Safety constraints
Never recommend crossing a closed gate, bypassing barriers, or taking an unverified route as a guaranteed safe detour. This is route-planning assistance, not official railway or emergency guidance.

## Acceptance criteria
- Normal route calculation works with configured provider credentials.
- Relevant closed reports trigger a clear, contextual warning.
- Alternative avoidance is only claimed when verified.
- Provider failures and missing credentials are handled honestly.
