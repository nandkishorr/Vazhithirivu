# Session 00 — Repository Audit and Baseline

## Objective
Establish an accurate understanding of the existing repository and create a reliable baseline before feature work.


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
1. Inspect the full repository structure, current branch, `git status`, dependency manifests, environment configuration, Docker files, Django apps, templates, static assets, database configuration, and existing tests.
2. Read the project documents listed above. If missing, note exactly which are missing; do not invent their contents.
3. Determine what is already implemented, what is broken, and which roadmap milestones are actually complete.
4. Run the existing test suite and available format/lint/type checks without destructive changes.
5. Verify whether the app can start in the current environment. Do not claim it starts unless you actually verify it.
6. Produce a concise architecture and gap assessment in `PROJECT_STATE.md`.
7. Update `ROADMAP.md` only where the actual repository evidence justifies it. Do not mark implementation milestones complete merely because files exist.
8. If shared instruction files are absent, create only the missing baseline files using the project requirements already agreed; do not overwrite existing project-specific files.

## Deliverables
- Accurate `PROJECT_STATE.md`.
- Baseline test/startup results and blockers.
- A prioritized sequence of the next implementation steps.
- No broad feature implementation in this session unless a small fix is necessary to make the baseline testable.

## Acceptance criteria
- Current repository state and working tree are recorded.
- Existing tests were run or their blocker is explicit.
- The next session can start without re-auditing everything from scratch.
