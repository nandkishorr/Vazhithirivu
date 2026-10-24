# Session 09 — Security, Privacy, and Integration Testing

## Objective
Perform a focused security/privacy review and strengthen automated coverage across the product.


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
1. Review actual implemented flows end to end and compare them with the safety/data-boundary requirements.
2. Check authentication/authorization, CSRF, input validation, rate limiting, secrets management, debug settings, allowed hosts, CORS if used, and error leakage.
3. Review geolocation collection, retention, logs, public endpoints, and report attribution. Remove accidental exposure of precise user locations or reporter details.
4. Verify OSM, community report, real-user, and simulator data separation, including reset/import operations.
5. Add integration tests for the most important flow: choose origin/destination, view route and crossings, submit or receive a report, detect a relevant closed crossing, and offer only a verified avoidance route.
6. Test missing map credentials, external provider errors, no reports, stale reports, conflicting reports, permission denial, empty spatial results, and simulator-off mode.
7. Run migrations/checks/tests and any configured formatter/linter. Fix regressions caused by the implementation.
8. Avoid adding security packages without a concrete need. Document risks that require production infrastructure or external provider settings.
9. Update `PROJECT_STATE.md`, `ROADMAP.md`, and `RUNBOOK.md` with verified outcomes.

## Acceptance criteria
- Critical user flows have meaningful automated coverage.
- Security/privacy issues found in scope are fixed or explicitly documented with impact and remediation.
- Test results are actual, reproducible, and accurately reported.
