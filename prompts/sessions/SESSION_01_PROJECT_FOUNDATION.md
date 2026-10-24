# Session 01 — Project Foundation

## Objective
Make the existing application reliably configurable and runnable for local development.


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
1. Recheck `PROJECT_STATE.md` and verify the audit findings against the current repository.
2. Preserve the current framework if it is already working and compatible. If no app exists, create the minimal Django project structure.
3. Establish clean environment-based configuration for development and production settings, including secret key, allowed hosts, database URL/settings, debug mode, static files, and optional third-party keys.
4. Add or improve `.env.example` with placeholders only. Ensure `.env`, credentials, and local data files are ignored by Git where appropriate.
5. Configure PostgreSQL/PostGIS settings in a way that supports local development. If PostGIS is not available in the execution environment, document the limitation and keep configuration testable; do not silently substitute a database that cannot support spatial functionality in the intended deployment.
6. Add or repair Docker Compose services only where needed: web, database with PostGIS, and supporting Redis only if the current architecture requires it. Keep simulator optional and do not build it yet.
7. Add a health-check endpoint or equivalent simple operational check if appropriate.
8. Provide clear setup, migration, test, and run commands in `RUNBOOK.md`.
9. Add tests for settings/health behavior where practical.

## Out of scope
- No complete map implementation.
- No OSM import pipeline.
- No simulated vehicles.
- No hardcoded secrets or required paid API credentials just to boot basic development mode.

## Acceptance criteria
- A developer can follow documented steps to configure and start the app, or the exact environmental blocker is documented.
- Configuration is environment-driven.
- Existing tests still pass, and new foundational tests pass.
- No unrelated changes are introduced.
