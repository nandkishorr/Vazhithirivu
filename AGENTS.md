# AGENTS.md — Repository Instructions

## Project
Vazhithirivu (വഴിത്തിരിവ്): railway-crossing intelligence and smart rerouting. See `PROJECT_STATE.md` for the current implementation state and next steps.

## Required session workflow
1. Read this file, `.agents/skills/vazhithirivu/SKILL.md`, and `PROJECT_STATE.md` before coding.
2. Inspect `git status`, repository structure, and relevant existing code.
3. Follow `DECISIONS.md`, `ROADMAP.md`, `DATA_SOURCES.md`, and `RUNBOOK.md` where relevant.
4. Implement small verified increments; don't replace working architecture without a documented reason.
5. Run relevant tests/checks and record the actual results.
6. Before ending, update `PROJECT_STATE.md` with changed files, tests, unresolved issues, and 3–7 concrete next steps.
7. Update `DECISIONS.md` for durable architecture changes and the skill file only for reusable workflows/rules.

## Non-negotiable rules
- Django server-rendered templates, Tailwind CSS, Leaflet/map UI, PostgreSQL/PostGIS; use existing compatible project conventions.
- Keep OSM reference geometry, community reports, real-user data, and simulation data separate.
- Geolocation is opt-in, stoppable, session-scoped, and not publicly exposed as exact coordinates by default.
- Never represent simulated/community-reported status as official railway status.
- Never claim an alternative route avoids a crossing unless its geometry/road-segment behavior has been verified.
- Never fabricate crossing coordinates, live statuses, route durations, test results, or successful commands.
- Never commit secrets or API keys. Provide `.env.example` with placeholders.
- Do not query Overpass per user or GPS update. Import OSM data into PostGIS and query locally.
- Do not run a full-country OSM import at application startup.
- Simulator is optional and isolated. Stopping/resetting it must not alter real-user records or OSM reference data.
- Do not create one Celery task per vehicle animation frame. Animate between coarse updates in the browser.
- Respect third-party API quotas, terms, attribution and data licensing.
- Avoid unnecessary infrastructure. Redis is for actual caching/broker/channel needs, not a synonym for load balancing.

## Owner preferences
- Testing cadence: implement the whole session's scope first, then run one consolidated verification pass at the end (build, test suite, check, smoke). Skip intermediate test runs and screenshots unless asked.
- Map provider: Google Maps Platform (Maps JavaScript API + Places API (New)); keys are configured later via `.env` (see `.env.example`).

## End-of-session handoff
Update `PROJECT_STATE.md` every session. Include:
- Current milestone and implementation status.
- What changed and important files.
- Exact commands/tests run and their actual outcomes.
- Known bugs, external dependencies and unverified assumptions.
- Next 3–7 concrete steps, in priority order.

Keep this file concise. Durable architecture decisions belong in `DECISIONS.md`; setup commands belong in `RUNBOOK.md`; source/license/import details belong in `DATA_SOURCES.md`.
