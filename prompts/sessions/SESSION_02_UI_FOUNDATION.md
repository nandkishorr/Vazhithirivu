# Session 02 — UI Foundation and Design System

## Objective
Build the responsive visual shell of Vazhithirivu with realistic application states, ready for map and crossing features.


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
1. Inspect existing templates and styles; reuse working components and conventions.
2. Establish a coherent visual identity for **Vazhithirivu (വഴിത്തിരിവ്)** with the tagline **Smart routes. Smarter crossings.**
3. Build a polished, responsive application shell with header/navigation, main map region placeholder, route/search panel, crossing detail panel placeholder, and mobile-friendly bottom sheet or equivalent.
4. Use Tailwind CSS if already configured or introduce it in the simplest maintainable way. Use server-rendered templates; use HTMX/Alpine.js only where they add value.
5. Create reusable styles/components for status labels, buttons, form fields, cards, alerts, loading indicators, empty states, and error states.
6. Include permission-denied, no-location, no-destination, loading, stale-data, and API-unavailable UI states. Clearly label any demo content.
7. Ensure keyboard usability, visible focus states, semantic markup, sufficient contrast, and reduced-motion support.
8. Keep the map as a real integration point, not a fake static map presented as live.
9. Add frontend/template tests or smoke checks where the repository supports them.

## Visual direction
- Map-first and uncluttered.
- Clear crossing states using both color and text/icon; never color alone.
- Desktop: map with a compact side panel.
- Mobile: full-width map with a usable bottom sheet and touch-friendly controls.
- Restrained animations; avoid distracting effects.
- Do not overbuild dashboards or unrelated pages.

## Acceptance criteria
- Main page renders and adapts to mobile and desktop sizes.
- Key loading, empty, error, and permission states are present.
- Components are reusable and consistent.
- No fabricated live data or false operational claims.
