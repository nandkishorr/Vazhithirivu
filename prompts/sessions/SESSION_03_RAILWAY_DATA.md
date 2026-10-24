# Session 03 — Railway Data and OSM Import

## Objective
Create the spatial data foundation and a repeatable OpenStreetMap railway infrastructure import pipeline.


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
1. Inspect existing models and migrations before adding anything.
2. Implement or refine spatial models for railway crossings and relevant railway/road geometry using PostGIS/GeoDjango. Preserve source identifiers and relevant OSM tags for traceability.
3. Treat `railway=level_crossing` as a useful crossing tag and `railway=rail` as a common track tag, but design import filtering to be documented and extensible. Do not assume OSM coverage is complete.
4. Implement an import command for a downloaded OSM PBF extract, with documented support for an appropriate regional or India extract. Do not download a massive extract automatically during tests.
5. Make imports idempotent, batched, restartable where practical, and safe to rerun. Preserve OSM identifiers and avoid duplicate rows.
6. Define a safe refresh/reconciliation strategy for updated extracts. Do not delete records blindly if an import fails partway.
7. Add spatial indexes and appropriate unique constraints. Keep source/reference data separate from reports and simulation records.
8. Add tests using small fixtures or mocked importer inputs. Tests must not depend on live Overpass services or large downloads.
9. Document source attribution, coverage limitations, import commands, expected storage, and refresh approach in `DATA_SOURCES.md` and `RUNBOOK.md`.

## Out of scope
- Do not query Overpass for every user location update.
- Do not implement user reports or live simulation in this session.
- Do not represent OSM data as authoritative or complete railway data.

## Acceptance criteria
- Spatial schema and migrations are correct.
- Import can be run repeatedly without creating duplicates.
- Import failure handling is documented and reasonably safe.
- Tests cover identifier mapping and idempotency.
