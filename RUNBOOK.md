# Runbook — Vazhithirivu

This is a template. Replace commands with verified repository-specific commands after implementation. Do not claim commands work until tested.

## Environment
- Copy `.env.example` to `.env`.
- Set Django secret, database settings, allowed hosts, map/routing API keys if used.
- Never commit `.env`.

## Docker
- Start normal app: `docker compose up --build`
- Apply migrations: `docker compose exec web python manage.py migrate`
- Create admin: `docker compose exec web python manage.py createsuperuser`
- Run tests: `docker compose exec web python manage.py test`
- Load small demo data: use the implemented management command and record its exact name here.

## OSM import
- Do not run the full India import automatically.
- Use the implemented explicit import command with a local PBF path or configured source.
- Test importer with the small fixture first.
- Record input file checksum, source URL/date, imported counts, skipped counts and errors.
- Never use live Overpass in automated tests.

## Simulation
- Start simulator only using the documented optional Docker Compose profile/service.
- Stop simulator independently.
- Reset only simulation-scoped records; never delete real-user data.
- Confirm the web app and real route search still work with simulator stopped.

## Tailwind assets
- Record exact development and production CSS build commands after confirming the repository's setup.
- Ensure production Docker image includes compiled CSS.

## Troubleshooting
- DB unavailable: check health and connection environment.
- Redis unavailable: confirm whether the feature can degrade gracefully or needs Redis.
- Map blank: verify tile/API key configuration and browser console.
- Route failure: check provider key, quota, network and provider abstraction logs; never fabricate fallback durations.
- Crossing absent: check OSM coverage, import filters and admin correction workflow.
