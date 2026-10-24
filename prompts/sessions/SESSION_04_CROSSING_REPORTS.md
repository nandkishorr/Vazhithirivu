# Session 04 — Community Crossing Reports

## Objective
Implement user-submitted crossing reports and robust status/freshness semantics.


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
1. Inspect the existing data model and API patterns; do not duplicate existing report functionality.
2. Implement a report model linked to a crossing where possible. Capture reported status, creation time, source/type, and any appropriate confidence/validation metadata.
3. Define a small, explicit status vocabulary, such as `OPEN_REPORTED`, `CLOSED_REPORTED`, `UNKNOWN`, and `CONFLICTING` if useful. Clearly distinguish a user's report from a verified official status.
4. Add server-side validation, rate limiting or an appropriate abuse-prevention hook, and permission rules for creating, listing, and reviewing reports.
5. Implement report submission and retrieval endpoints/views with useful error responses and CSRF protection for browser forms.
6. Derive the current display state from recent reports using a documented freshness window and conflict policy. A lack of reports must result in `UNKNOWN`, never “open”.
7. Expose report age, source, and uncertainty to the UI. Avoid displaying confidence as a scientific probability unless it is actually calibrated.
8. Add tests for valid reports, invalid input, stale reports, conflicting reports, permissions, and absence of reports.
9. Document retention and moderation assumptions. Do not expose reporter identity or precise user location publicly without a justified need and explicit design.

## Acceptance criteria
- Reports are persisted and validated.
- Stale/conflicting/no-report cases produce safe, understandable states.
- API/UI clearly communicate that reports are community-sourced and not official railway information.
- Tests cover key state transitions and access control.
