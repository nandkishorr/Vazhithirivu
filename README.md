# Vazhithirivu — Complete Devin Development Bundle

**Product:** Vazhithirivu (വഴിത്തിരിവ്)  
**Tagline:** Smart routes. Smarter crossings.

This bundle combines the project-wide instructions, architecture and data-source decisions, continuity files, engineering skill, and session-by-session implementation prompts.

## Repository structure

```text
repository-root/
├── AGENTS.md
├── MASTER_PROMPT.md
├── PROJECT_STATE.md
├── DECISIONS.md
├── ROADMAP.md
├── DATA_SOURCES.md
├── RUNBOOK.md
├── .agents/
│   └── skills/
│       └── vazhithirivu/
│           └── SKILL.md
└── prompts/
    └── sessions/
        ├── README.md
        ├── SESSION_00_REPOSITORY_AUDIT.md
        ├── SESSION_01_PROJECT_FOUNDATION.md
        ├── SESSION_02_UI_FOUNDATION.md
        ├── SESSION_03_RAILWAY_DATA.md
        ├── SESSION_04_CROSSING_REPORTS.md
        ├── SESSION_05_MAP_AND_LOCATION.md
        ├── SESSION_06_ROUTING.md
        ├── SESSION_07_REALTIME_UPDATES.md
        ├── SESSION_08_SIMULATOR.md
        ├── SESSION_09_TESTING_AND_SECURITY.md
        └── SESSION_10_POLISH_AND_RELEASE.md
```

## How to use this bundle

1. Extract this bundle into your existing repository or copy its files into the repository root.
2. **Do not blindly overwrite existing files.** Compare them first and merge project-specific decisions and current progress.
3. Keep `AGENTS.md` and `.agents/skills/vazhithirivu/SKILL.md` as persistent instructions for Devin.
4. Start a Devin session with `prompts/sessions/SESSION_00_REPOSITORY_AUDIT.md`.
5. After checking the changes and acceptance criteria, use the next session prompt in numeric order.
6. At the beginning of every session, Devin should inspect `PROJECT_STATE.md` and the actual repository. At the end, it must update `PROJECT_STATE.md` with real changes, tests, blockers, and the next steps.
7. Use `MASTER_PROMPT.md` as the overall product specification. The session prompts break implementation into manageable milestones; they do not replace the shared safety and architecture instructions.

## Session sequence

| Session | Focus |
|---|---|
| 00 | Repository audit and baseline |
| 01 | Project foundation, configuration, database, Docker |
| 02 | UI foundation and design system |
| 03 | PostGIS models and OpenStreetMap import |
| 04 | Community crossing reports and status freshness |
| 05 | Map integration and opt-in geolocation |
| 06 | Routing and verified crossing avoidance |
| 07 | Realtime updates and freshness |
| 08 | Isolated simulator |
| 09 | Security, privacy, integration testing |
| 10 | Product polish and release readiness |

## Important safety rules

- Community reports are not official railway information.
- No report does not mean a crossing is open.
- Stale or conflicting reports must be treated as unknown/uncertain.
- Never advise crossing a closed gate or bypassing railway barriers.
- Never claim a route avoids a crossing unless the implementation verifies it.
- Keep OSM reference data, community reports, real-user data, and simulator data separate.
- Never commit secrets, `.env` files, or private location data.

## Scope note

This bundle contains specifications and implementation prompts. It does **not** mean the application has already been implemented or tested. Devin must verify the repository and report actual test results.
