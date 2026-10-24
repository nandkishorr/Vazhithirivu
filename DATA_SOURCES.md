# Data Sources, Licensing and Provider Constraints

Update this file when a provider or dataset changes. Verify current terms before production use.

## OpenStreetMap
- Use OSM-derived data for railway tracks, mapped level-crossing nodes, road geometry and available tags.
- Common crossing tag: `railway=level_crossing`.
- Import a country/regional PBF extract or other appropriate source into PostGIS.
- Do not query Overpass for each user, route, or GPS update.
- Keep OSM object identity/type and source/version/import metadata.
- Coverage is incomplete; support manual corrections and do not claim all crossings are mapped.
- Provide required attribution and review ODbL obligations for derived database distribution.
- Public OSM tile servers have a separate usage policy; do not assume unlimited production tile use.
- Record the chosen extract provider, source URL, extract timestamp, import command and refresh strategy in the implementation.

## Google Maps Platform (if configured)
- Potential services: Maps JavaScript API, Places API, Routes API.
- Store API keys in environment variables/secrets, never source control.
- Restrict browser keys by HTTP referrer and allowed APIs; restrict server keys appropriately.
- Verify current pricing, quotas, billing requirements, terms, caching and content-storage restrictions.
- Do not assume standard route modifiers can exclude an arbitrary railway crossing/road segment.
- Verify all route candidates against crossing geometry; use a different routing engine if guaranteed segment exclusions are required.
- Mock Google services in automated tests.

## Routing alternatives
- GraphHopper, openrouteservice, OSRM, or a self-hosted routing engine may be evaluated.
- Confirm current API quotas, licensing, geometry, alternative-route and segment-exclusion capabilities before choosing.
- Encapsulate provider behavior behind a Django service interface.

## Status sources
- OSM tags describe mapped infrastructure, not live open/closed status.
- Community reports are unverified unless a documented verification source exists.
- Simulation status must always be labelled as simulated.
- Do not infer open status from absence of closure reports.

## Refresh and attribution
- Geographic import/refresh must be explicit, idempotent, logged, and separate from normal web startup.
- Document attribution in the UI and README.
