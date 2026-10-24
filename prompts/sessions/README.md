# Vazhithirivu — Session-by-Session Devin Prompts

Use these prompts in order, one Devin session at a time. Each file is a self-contained task prompt, but it also requires Devin to read the shared project instructions and verify the real repository state before coding.

## Shared instructions
Keep these existing files at the repository root:
- `AGENTS.md`
- `MASTER_PROMPT.md`
- `PROJECT_STATE.md`
- `DECISIONS.md`
- `ROADMAP.md`
- `DATA_SOURCES.md`
- `RUNBOOK.md`
- `.agents/skills/vazhithirivu/SKILL.md`

Do not replace these files blindly if they already contain project-specific decisions. Merge changes carefully.

## Recommended workflow
1. Start with `SESSION_00_REPOSITORY_AUDIT.md`.
2. In each later session, paste the corresponding Markdown prompt into Devin.
3. Run only one session prompt at a time. Let Devin implement, test, and update `PROJECT_STATE.md`.
4. Before starting the next session, inspect the diff and confirm the prior session's acceptance criteria.
5. If a session is already complete, Devin should verify it and move on only when the criteria genuinely pass.
6. If the repository differs from the assumed stack or earlier work, preserve working code and adapt rather than blindly following a stale plan.

## Session list
- `SESSION_00_REPOSITORY_AUDIT.md` — repository audit and baseline
- `SESSION_01_PROJECT_FOUNDATION.md` — Django configuration, database, Docker
- `SESSION_02_UI_FOUNDATION.md` — layout and visual design system
- `SESSION_03_RAILWAY_DATA.md` — PostGIS models and OSM import
- `SESSION_04_CROSSING_REPORTS.md` — community reports and status semantics
- `SESSION_05_MAP_AND_LOCATION.md` — map, geolocation, crossing markers
- `SESSION_06_ROUTING.md` — routing and verified avoidance
- `SESSION_07_REALTIME_UPDATES.md` — live updates and freshness handling
- `SESSION_08_SIMULATOR.md` — isolated simulator
- `SESSION_09_TESTING_AND_SECURITY.md` — security, privacy, integration tests
- `SESSION_10_POLISH_AND_RELEASE.md` — UX, docs, deployment readiness

## Product identity
**Vazhithirivu (വഴിത്തിരിവ്)**  
**Smart routes. Smarter crossings.**

Core safety rule: community reports are not official railway data. No report does not mean open. Stale/conflicting information must become unknown. Never advise crossing a closed gate. Never claim an alternative route avoids a crossing unless that is verified.
