# Data Sources, Licensing and Provider Constraints

Update this file when a provider or dataset changes. Verify current terms before production use.

## OpenStreetMap
- Use OSM-derived data for railway tracks, mapped level-crossing nodes, road geometry and available tags.
- Common crossing tag: `railway=level_crossing`.
- Import a country/regional PBF extract into PostGIS with `import_osm_railways` (`railways` app). Do not query Overpass for each user, route, or GPS update.
- Keep OSM object identity/type and source/version/import metadata (done via `osm_type`/`osm_id`, `osm_version`, `osm_timestamp`, full `tags` copy, and `OsmImportRun` provenance: sha256, size, source URL, header timestamp, effective filters, coverage bbox, per-kind counts).
- Coverage is incomplete; support manual corrections and do not claim all crossings are mapped.
- Provide required attribution and review ODbL obligations for derived database distribution.
- Public OSM tile servers have a separate usage policy; do not assume unlimited production tile use.

### Extract provider: Geofabrik
- Provider: Geofabrik download server (https://download.geofabrik.de).
- India extract: https://download.geofabrik.de/asia/india-latest.osm.pbf (~1.6 GB as listed on 2026-10-24).
- Southern Zone extract (includes Kerala; preferred for the Kochi demo, combined with `--bbox`): https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf (~532 MB as listed on 2026-10-24).
- Geofabrik extracts do not include user/changeset metadata; they do include object version and timestamp, which we store for traceability.
- License: Open Database License (ODbL) 1.0. Required attribution: "© OpenStreetMap contributors" with a link to https://www.openstreetmap.org/copyright. Before distributing a derived database dump (e.g. the imported PostGIS tables), review ODbL share-alike obligations for produced works vs. derivative databases.
- Downloads are manual (see RUNBOOK); verify the `.md5` checksum published alongside each extract.

### What the importer keeps
- Crossings: OSM **nodes** whose `railway` value is in the crossing set (default `level_crossing`; override with `--crossing-values`). Ways/relations tagged with a crossing value are skipped (`crossing_not_node`) — crossings are point objects.
- Tracks: OSM **ways** whose `railway` value is in the track set (default `rail`, `narrow_gauge`, `light_rail`; override with `--track-values`). Lifecycle-tagged ways (`abandoned`, `disused`, `razed`, …) are excluded simply by not being in the set.
- Everything else is ignored; skipped objects are counted per reason on the import run.
- `--bbox` limits the import to a region and doubles as the reconciliation scope.
- No live status, gate state, or train data is imported — OSM tags describe mapped infrastructure only (ADR-003).
- Road segments are not imported yet; they arrive with routing work (Session 06).

### Refresh and corrections
- Refresh = re-run the importer on a newer extract. Upserts are idempotent via `(osm_type, osm_id)`; `first_seen_run`/`last_seen_run` track provenance.
- `--reconcile` soft-deletes active OSM rows inside the coverage bbox that the new extract no longer contains (`is_active=False`, never `DELETE`). A safety threshold (`--max-deactivate-fraction`, default 0.2) aborts the run if an implausibly large share of rows would disappear. Reconcile candidates are limited to the run's effective crossing/track filter values, so features whose `railway` tag moved outside the current filter set are still retired while rows of other values are untouched.
- Admin corrections: `source='manual'` rows are never touched by the importer, and `is_suppressed`/`suppression_reason`/`admin_notes` survive re-imports and reconciliation.

## Google Maps Platform
- APIs used now: Maps JavaScript API (map display, dynamic `importLibrary` bootstrap loader) and Places API (New) via `PlaceAutocompleteElement` for the From/To fields.
- `GOOGLE_MAPS_BROWSER_KEY` is public by design and rendered in the page; restrict it by HTTP referrer and to exactly the Maps JavaScript API and Places API (New).
- `GOOGLE_MAPS_MAP_ID` enables cloud-based map styling and is required for `AdvancedMarkerElement` (used for the opt-in user-location marker).
- `GOOGLE_MAPS_SERVER_KEY` is used for server-side Routes API (`computeRoutes`) route planning; it must never be sent to the browser. Restrict it to the Routes API only, no referrer restriction (server-to-server), IP restriction in production. Billing: `TRAFFIC_UNAWARE` uses the Essentials SKU (the default); `TRAFFIC_AWARE` uses the Pro SKU — opt-in only. At most ~3 routes are returned per request. Route geometry/content is never persisted in the database.
- Map attribution and legal notices are rendered by Google itself; do not hide or cover them.
- Google Maps Platform terms restrict caching/storing of Google content; do not persist Google-sourced place data or geometry without checking current terms.
- Verify current pricing, quotas and billing requirements before production use.
- Do not assume standard route modifiers can exclude an arbitrary railway crossing/road segment.
- Verify all route candidates against crossing geometry; use a different routing engine if guaranteed segment exclusions are required.
- Mock Google services in automated tests; never hit Google APIs in the test suite.

## UI assets
- Lucide icons (https://lucide.dev), ISC license — inline SVG path data in `core/templatetags/ui.py`.
- Tailwind CSS standalone CLI, pinned version + sha256 (see Dockerfile and RUNBOOK).
- Google Maps Extended Component Library (`gmpx-place-picker` for From/To), Apache-2.0, loaded pinned at `0.6.15` from `ajax.googleapis.com` (see `templates/core/home.html`). It renders its own internal input; typed-but-unselected text is synced on submit in `static/js/map.js` — treat its shadow-DOM internals as unstable.

## Routing providers
- Google Routes API is the configured provider (`routing.providers.GoogleRoutesProvider`, ADR-013). It has no point/segment exclusion: crossing avoidance is verified afterwards against route geometry, never assumed.
- If guaranteed segment exclusion is required, Valhalla (`exclude_locations`) or GraphHopper are documented future options behind the same provider interface; confirm quotas, licensing and exclusion semantics before adopting.
- Mock providers in automated tests; never hit routing APIs in the test suite.

## Community crossing reports
- `incidents.CrossingReport` rows are user-submitted open/closed observations tied to a crossing. They are **unverified** and never presented as official railway information.
- Only signed-in users report; the reporter identity is private and never rendered in public HTML or JSON (public payloads expose state, timestamp, age and source only). No reporter location or IP is stored.
- Reports are fresh for 15 minutes, shown as stale up to 60 minutes, then ignored; conflicting recent reports yield an explicit "conflicting" state. Retention is 30 days (`purge_crossing_reports`, manual/cron). Staff can hide abusive reports via admin moderation.

## Status sources
- OSM tags describe mapped infrastructure, not live open/closed status.
- Community reports are unverified unless a documented verification source exists.
- Simulation status must always be labelled as simulated.
- Do not infer open status from absence of closure reports.

## Refresh and attribution
- Geographic import/refresh must be explicit, idempotent, logged, and separate from normal web startup.
- Document attribution in the UI and README.
