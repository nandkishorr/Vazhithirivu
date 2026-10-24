# Project State — Vazhithirivu

> This file is the handoff point between agent sessions. Update it at the end of every meaningful work session.

## Status
- Current milestone: **M0 complete (repository audit, Session 00, 2026-10-24).** Next: M1 / Session 01 (project foundation).
- Product: Vazhithirivu (വഴിത്തിരിവ്), "Smart routes. Smarter crossings."
- Target demo: Kochi, Kerala; future dataset target: India-wide mapped railway crossings.
- Stack target: Django server-rendered templates, Tailwind CSS, HTMX/Alpine, Google Maps Platform where configured, OSM reference data, PostgreSQL/PostGIS, optional Redis/Channels/Celery, Docker Compose.
- **Every service, including PostgreSQL/PostGIS, runs as a container** (owner decision, ADR-006). Do not use the host's Homebrew Postgres.
- Simulator: optional isolated service; normal app must work without it.

## Architecture invariants
- OSM geometry is reference data, not live crossing status.
- Community reports, real user locations, and simulation events are separate.
- Location sharing is explicit opt-in and can be stopped immediately.
- A detour is valid only after checking that it avoids the affected crossing/blocked segment.
- Do not query Overpass for each user or location update; import data and query PostGIS.
- Full-country OSM import must be explicit, never run at web startup.

## Verified repository facts (Session 00 audit, 2026-10-24)
- Remote `origin` = `https://github.com/nandkishorr/Vazhithirivu.git`; branch `main`, up to date with `origin/main`.
- Git history: one commit (`2127645 Initial commit`), which adds only `LICENSE` (MIT, © 2026 Nandkishor R).
- Working tree:
  - `LICENSE` is **deleted but not committed**. Not restored, because this may be the owner's intent. **Owner decision needed**: restore it with `git restore LICENSE` or confirm deletion. Also check MIT code licensing against ODbL obligations for distributed OSM-derived data.
  - Untracked: the specification bundle (`AGENTS.md`, `MASTER_PROMPT.md`, `PROJECT_STATE.md`, `DECISIONS.md`, `ROADMAP.md`, `DATA_SOURCES.md`, `RUNBOOK.md`, `README.md`, `.agents/skills/vazhithirivu/SKILL.md`, `prompts/sessions/SESSION_00..10` + `README.md`) and a macOS `.DS_Store`.
- All shared instruction files listed in Session 00 are present; none were missing.
- **No application code exists.** There are no:
  - dependency manifests (`requirements*.txt`, `pyproject.toml`, `package.json`)
  - Django project/apps, `manage.py`, models, migrations, templates or static assets
  - Tailwind config
  - `Dockerfile` or `docker-compose.yml`
  - `.env.example` or `.gitignore`
  - tests, CI config, or lint/format config
- The root `README.md` describes the spec bundle, not the product. Session 10 should replace or expand it.

### Reusable existing work
- Specification, safety rules, domain model, roadmap and the session prompt sequence are complete and consistent. No architecture conflicts were found between `MASTER_PROMPT.md`, `AGENTS.md`, `SKILL.md`, `DECISIONS.md` and the session prompts.
- Minor inconsistencies to settle during implementation:
  - Map provider: ADR-001/AGENTS name Leaflet; MASTER_PROMPT prefers Google Maps when configured. Recommendation: Leaflet + OSM tiles as the default/no-key path, with Google Maps behind a provider switch. Record the choice as an ADR in Session 02/05.
  - Routing engine: none chosen. Google alternatives cannot guarantee crossing avoidance (ADR-004). Evaluate a self-hostable engine with exclusion support (GraphHopper/OSRM/openrouteservice) in Session 06.

### Host environment (macOS, Apple Silicon/arm64)
- Docker 29.8.2 + Compose v5.5.1. The daemon was not running at first. It was started with `open -a Docker` and then responded (`aarch64`, 12 CPUs, ~8 GB RAM for Docker).
- Host tools present: Python 3.14.6 (default `python3`), Python 3.13.11, Node 25.6.1, npm 11.9.0, Homebrew PostgreSQL 17.7 (running on :5432, **no PostGIS extension available**), Redis 8.4.0.
- Host tools missing: GDAL/`ogr2ogr`, `osmium`, `uv`, Python 3.12. This is irrelevant if everything runs in containers (ADR-006). GDAL/GEOS/PROJ must be installed in the web image.
- Host port 5432 is already used by Homebrew Postgres. The Compose `db` service must not publish to host 5432; use another host port or don't publish it.

## Commands/tests run (Session 00)
| Command | Result |
|---|---|
| `git status`, `git log`, `git show --stat HEAD`, `git remote -v`, `git branch -a` | Facts above |
| `git diff --check` | Exit 0 |
| Toolchain version probes (`python3`, `node`, `docker`, `psql`, …) | Facts above |
| `psql -d postgres -c "select … from pg_available_extensions where name like 'postgis%'"` (host) | No rows. Host Postgres has no PostGIS |
| `docker run postgis/postgis:16-3.4` + `psql` inside | Container started. `CREATE EXTENSION postgis` reported "already exists", so PostGIS is preinstalled. Docker warned the image is **linux/amd64 only** and runs under emulation on arm64. Container stopped (`--rm`). |
| Test suite | **None exists, so nothing to run.** No lint/type/format tooling is configured. |
| App startup | **Not possible.** There is no application. |

Not verified, deferred to test time by the owner: the full `postgis_full_version()` output, and whether a native arm64 PostGIS image (e.g. a multi-arch community image) should replace the emulated amd64 image.

## Known risks / open questions
- `LICENSE` deletion pending owner decision (see above).
- PostGIS image is amd64-only. Emulation on Apple Silicon is slower; choose and pin a multi-arch image or accept emulation in Session 01.
- Google Maps Platform credentials, billing, quotas, and permitted storage/caching must be configured and verified.
- Google route alternatives do not guarantee exclusion of an arbitrary crossing.
- OSM coverage of level crossings is incomplete and requires quality checks/manual corrections.
- India-wide PBF import size, processing time, and refresh strategy are unmeasured. Docker currently has ~8 GB RAM, which may limit a full-country import.
- Pin dependency versions in Session 01 (Python 3.12/3.13 base image recommended; avoid 3.14 until GeoDjango/psycopg wheels are confirmed).
- Decide whether road-segment graph data is needed for guaranteed crossing avoidance.

## Recommended implementation order
Follows the session prompts, M1→M6:
1. Session 01: Django skeleton, env-driven settings, `.gitignore`, `.env.example`, Dockerfile (GDAL/GEOS/PROJ), Compose `web` + `db` (PostGIS) + `redis`, health endpoint, first tests run in containers.
2. Session 02: Tailwind build pipeline (also in Docker), base layout/partials, map shell.
3. Session 03: `RailwayCrossing`/`RailwayTrack` models, Kochi fixture, idempotent PBF importer.
4. Session 04: reports and derived status (no report means UNKNOWN).
5. Session 05: map markers from PostGIS, bbox endpoint, opt-in geolocation.
6. Session 06: routing abstraction, route–crossing association, verified avoidance.
7. Sessions 07–10: realtime, simulator, security/integration tests, polish/release.

## Next steps
1. Owner: decide on `LICENSE` (restore or confirm deletion). Optionally commit the spec bundle as the baseline.
2. Run `prompts/sessions/SESSION_01_PROJECT_FOUNDATION.md`.
3. In Session 01, all services run in Docker Compose (ADR-006). Pin a PostGIS image (decide between native arm64 and emulated amd64) and avoid publishing host port 5432.
4. Add `.gitignore` (including `.DS_Store`, `.env`, OSM data files) and `.env.example`.
5. Establish the container test command (`docker compose run --rm web python manage.py test`) and record verified output in `RUNBOOK.md`.
