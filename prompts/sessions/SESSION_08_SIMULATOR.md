# Session 08 — Isolated Traffic and Crossing Simulator

## Objective
Add an optional simulator for hackathon demos without contaminating real-user or reference data.


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
1. Inspect the data model and Docker setup. Define explicit simulator ownership/namespace and isolation boundaries before coding.
2. Implement an optional simulator service/profile that can generate configurable simulated vehicles and gate open/close events for demo scenarios.
3. Keep simulation state in dedicated simulator tables or an explicit isolated data namespace. Never write simulated status into OSM reference rows or ordinary community-report rows.
4. Allow configuration for vehicle count (e.g. 50–200), scenario duration, crossing event timing, and deterministic/random seed where useful.
5. Keep movement simulation coarse-grained. Interpolate vehicle animation on the client between backend updates; do not enqueue a task for every animation frame.
6. Demonstrate the flow: simulated route encounters a simulated closed crossing, an alert appears, and an alternative route is calculated/verified where supported.
7. Make simulator start/stop/reset commands explicit and safe. The main application must still work with simulator stopped.
8. Label all simulator data clearly in UI and API responses. Never present it as real-world traffic or official crossing status.
9. Add tests proving simulator writes cannot mutate real-user reports or OSM reference records.
10. Document simulator commands, configuration, reset behavior, and isolation in `RUNBOOK.md`.

## Acceptance criteria
- Simulator is optional and can be started/stopped independently.
- Resetting simulation removes only simulation-owned data.
- Real-user reports and reference infrastructure remain unchanged.
- A documented demo scenario works or has explicit external-service limitations.
