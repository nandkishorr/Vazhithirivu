# Session 10 — Product Polish and Release Readiness

## Objective
Make the implemented Vazhithirivu application coherent, demonstrable, documented, and ready for a controlled pilot or hackathon demo.


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
1. Review the actual end-to-end product against `MASTER_PROMPT.md` and `ROADMAP.md`.
2. Fix broken flows, confusing labels, inconsistent status semantics, layout defects, accessibility gaps, and obvious performance issues.
3. Verify desktop and mobile behavior, including location permission denial, unavailable APIs, empty data, stale/conflicting reports, route warnings, and simulator-disabled mode.
4. Ensure every demo/test dataset is explicitly labelled and isolated. Do not fabricate live crossing conditions.
5. Review onboarding, first-run empty states, map API setup, OSM import instructions, Docker commands, environment variables, migrations, test commands, and troubleshooting.
6. Ensure `README.md` explains the product, architecture, local setup, environment configuration, data sources/attribution, simulator usage, limitations, and safety disclaimer.
7. Run the full practical verification suite: Django checks, migrations check, automated tests, lint/format checks available, and startup/smoke test where environment permits.
8. Inspect `git diff --check`, `git status`, and the final diff. Do not remove unrelated user work.
9. Update `PROJECT_STATE.md` with the actual release status, verified features, outstanding blockers, and suggested next steps. Do not call it production-ready if deployment, security, or data coverage remains unverified.

## Acceptance criteria
- A new developer can follow the README/RUNBOOK to set up the app or see precisely what blocks setup.
- Critical flows are tested and the app is demonstrable with clearly labelled demo data.
- Known limitations and external dependencies are transparent.
- No secrets or private location data are committed.
- Final report separates completed, partially completed, and unverified items.
