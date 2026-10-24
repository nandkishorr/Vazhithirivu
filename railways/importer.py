"""OSM railway reference-data importer.

Reads a local .osm.pbf or .osm XML file (no network access), upserts
``RailwayCrossing`` nodes and ``RailwayTrack`` ways keyed by
(osm_type, osm_id) and optionally reconciles rows that disappeared from
the extract via soft-delete.

Road-segment import is intentionally out of scope for this session; it
will be added with the routing work (Session 06).
"""

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone

import osmium
from django.contrib.gis.geos import LineString, Point, Polygon
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.utils import timezone

from .models import OsmImportRun, RailwayCrossing, RailwayTrack

ADVISORY_LOCK_KEY = 72841631
OSM_EPOCH = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)

# Crossing display-label context (all OSM-derived; nothing invented).
PLACE_VALUES = frozenset(
    {
        "city",
        "town",
        "suburb",
        "village",
        "quarter",
        "neighbourhood",
        "hamlet",
        "locality",
    }
)
# Lower rank = preferred road for the crossing's derived label.
HIGHWAY_RANK = {
    "motorway": 0,
    "trunk": 1,
    "primary": 2,
    "secondary": 3,
    "tertiary": 4,
    "unclassified": 5,
    "residential": 6,
    "living_street": 7,
    "service": 8,
    "track": 9,
}
HIGHWAY_RANK_DEFAULT = 10
PLACE_CELL_DEG = 0.02  # ~2 km; grid index for nearest-place lookups
PLACE_MAX_DIST_M = 3000
PLACE_CELL_RADIUS = 2  # ceil(3000 m / ~2.2 km per cell)


def best_name(tags, max_len=255):
    """OSM display name preference: name:en, else name."""
    return (tags.get("name:en") or tags.get("name") or "")[:max_len]


def _haversine_m(lon1, lat1, lon2, lat2):
    from math import asin, cos, pi, sin, sqrt

    r = pi / 180
    dlat = (lat2 - lat1) * r
    dlon = (lon2 - lon1) * r
    a = sin(dlat / 2) ** 2 + cos(lat1 * r) * cos(lat2 * r) * sin(dlon / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


def _nearest_place(lon, lat, grid):
    from math import floor

    cx, cy = floor(lon / PLACE_CELL_DEG), floor(lat / PLACE_CELL_DEG)
    best = None
    for dx in range(-PLACE_CELL_RADIUS, PLACE_CELL_RADIUS + 1):
        for dy in range(-PLACE_CELL_RADIUS, PLACE_CELL_RADIUS + 1):
            for plon, plat, pname, ptype in grid.get((cx + dx, cy + dy), ()):
                d = _haversine_m(lon, lat, plon, plat)
                if d <= PLACE_MAX_DIST_M and (best is None or d < best[0]):
                    best = (d, pname, ptype)
    return best


@dataclass(frozen=True)
class ImportFilters:
    crossing_railway_values: frozenset = frozenset({"level_crossing"})
    track_railway_values: frozenset = frozenset(
        {"rail", "narrow_gauge", "light_rail"}
    )

    def as_dict(self):
        return {
            "crossing_railway_values": sorted(self.crossing_railway_values),
            "track_railway_values": sorted(self.track_railway_values),
        }


@dataclass
class ImportResult:
    run_id: int | None
    status: str
    counts: dict = field(default_factory=dict)


def empty_counts():
    return {
        "created": {"crossing": 0, "track": 0},
        "updated": {"crossing": 0, "track": 0},
        "reactivated": {"crossing": 0, "track": 0},
        "deactivated": {"crossing": 0, "track": 0},
        "parsed": {"crossing": 0, "track": 0},
        "crossings_with_road": 0,
        "crossings_with_place": 0,
        "skipped": {},
    }


def parse_bbox(value):
    """Parse "minlon,minlat,maxlon,maxlat" into a 4-tuple of floats."""
    try:
        parts = [float(p) for p in value.split(",")]
    except ValueError:
        raise CommandError(
            f"invalid --bbox {value!r}: expected minlon,minlat,maxlon,maxlat numbers"
        )
    if len(parts) != 4:
        raise CommandError(
            f"invalid --bbox {value!r}: expected 4 comma-separated numbers"
        )
    minlon, minlat, maxlon, maxlat = parts
    if not (-180 <= minlon <= 180 and -180 <= maxlon <= 180):
        raise CommandError(f"invalid --bbox {value!r}: longitude out of range")
    if not (-90 <= minlat <= 90 and -90 <= maxlat <= 90):
        raise CommandError(f"invalid --bbox {value!r}: latitude out of range")
    if not (minlon < maxlon and minlat < maxlat):
        raise CommandError(
            f"invalid --bbox {value!r}: min must be smaller than max"
        )
    return (minlon, minlat, maxlon, maxlat)


def acquire_import_lock():
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [ADVISORY_LOCK_KEY])
        return cur.fetchone()[0]


def release_import_lock():
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", [ADVISORY_LOCK_KEY])


def _skip(counts, reason):
    counts["skipped"][reason] = counts["skipped"].get(reason, 0) + 1


def _object_timestamp(obj):
    ts = obj.timestamp
    if ts is None or ts <= OSM_EPOCH:
        return None
    return ts


def _point_in_bbox(lon, lat, bbox):
    minlon, minlat, maxlon, maxlat = bbox
    return minlon <= lon <= maxlon and minlat <= lat <= maxlat


def _coords_intersect_bbox(coords, bbox):
    minlon, minlat, maxlon, maxlat = bbox
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    return not (
        max(xs) < minlon
        or min(xs) > maxlon
        or max(ys) < minlat
        or min(ys) > maxlat
    )


def flush_batch(model, objs, run, counts):
    """Upsert one batch. Returns (created, updated, reactivated)."""
    kind = "crossing" if model is RailwayCrossing else "track"
    if model is RailwayCrossing:
        update_fields = [
            "location",
            "tags",
            "name",
            "railway_value",
            "crossing_barrier",
            "road_name",
            "road_ref",
            "road_highway",
            "road_osm_id",
            "nearest_place_name",
            "nearest_place_type",
            "nearest_place_distance_m",
            "osm_version",
            "osm_timestamp",
            "last_seen_run",
            "is_active",
            "deactivated_at",
            "updated_at",
        ]
    else:
        update_fields = [
            "geometry",
            "tags",
            "name",
            "railway_value",
            "usage",
            "service",
            "osm_version",
            "osm_timestamp",
            "last_seen_run",
            "is_active",
            "deactivated_at",
            "updated_at",
        ]

    # Dedupe by identity within the batch (last wins) so ON CONFLICT never
    # has to touch the same row twice.
    by_identity = {}
    for obj in objs:
        by_identity[(obj.osm_type, obj.osm_id)] = obj
    objs = list(by_identity.values())

    existing_ids = set(
        model.objects.filter(
            osm_type=objs[0].osm_type,
            osm_id__in=[o.osm_id for o in objs],
        ).values_list("osm_id", flat=True)
    )
    inactive_ids = set(
        model.objects.filter(
            osm_type=objs[0].osm_type,
            osm_id__in=[o.osm_id for o in objs],
            is_active=False,
        ).values_list("osm_id", flat=True)
    )

    now = timezone.now()
    created = updated = reactivated = 0
    for obj in objs:
        obj.last_seen_run = run
        obj.is_active = True
        obj.deactivated_at = None
        obj.created_at = now
        obj.updated_at = now
        if obj.osm_id in existing_ids:
            updated += 1
            if obj.osm_id in inactive_ids:
                reactivated += 1
        else:
            created += 1

    with transaction.atomic():
        model.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=["osm_type", "osm_id"],
            update_fields=update_fields,
        )

    counts["created"][kind] += created
    counts["updated"][kind] += updated
    counts["reactivated"][kind] += reactivated
    return created, updated, reactivated


def _read_header(path):
    """Return (coverage_box_tuple_or_None, source_timestamp_or_None)."""
    reader = osmium.io.Reader(str(path))
    try:
        header = reader.header()
        box = None
        try:
            b = header.box()
            if b.valid():
                box = (
                    b.bottom_left.lon,
                    b.bottom_left.lat,
                    b.top_right.lon,
                    b.top_right.lat,
                )
        except Exception:
            box = None
        ts_raw = header.get("osmosis_replication_timestamp") or ""
        ts = None
        if ts_raw:
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            except ValueError:
                ts = None
        return box, ts
    finally:
        reader.close()


def _coverage_polygon(coverage):
    if coverage is None:
        return None
    poly = Polygon.from_bbox(coverage)
    poly.srid = 4326
    return poly


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _common_kwargs(obj, tags, run):
    return {
        "osm_version": obj.version if obj.version > 0 else None,
        "osm_timestamp": _object_timestamp(obj),
        "tags": tags,
        "name": tags.get("name", "")[:255],
        "first_seen_run": run,
        "last_seen_run": run,
    }


def _iter_features(path, filters, bbox, location_index):
    """Yield (kind, obj, tags, specific_kwargs) or ("skip", reason).

    kind is "crossing" or "track". obj is the osmium object (for
    version/timestamp); specific_kwargs holds geometry + value fields.
    """
    fp = osmium.FileProcessor(str(path)).with_locations(location_index)
    # C++-side pre-filter: only objects with a railway/highway/place tag
    # reach Python. Verified with pyosmium 4.3: filtered-out untagged nodes
    # are still stored in the location index, so ways keep their geometry.
    fp = fp.with_filter(osmium.filter.KeyFilter("railway", "highway", "place"))

    for obj in fp:
        tags = dict(obj.tags)
        railway_value = tags.get("railway")

        if obj.is_node():
            if railway_value in filters.crossing_railway_values:
                try:
                    lon, lat = obj.location.lon, obj.location.lat
                except osmium.InvalidLocationError:
                    yield ("skip", "crossing_invalid_geometry")
                    continue
                if bbox and not _point_in_bbox(lon, lat, bbox):
                    yield ("skip", "outside_bbox")
                    continue
                yield (
                    "crossing",
                    obj,
                    tags,
                    {
                        "osm_type": "node",
                        "osm_id": obj.id,
                        "location": Point(lon, lat, srid=4326),
                        "railway_value": railway_value[:64],
                        "crossing_barrier": tags.get("crossing:barrier", "")[
                            :64
                        ],
                    },
                )
            elif tags.get("place") in PLACE_VALUES and best_name(tags):
                yield ("place", obj, tags, {})
            # Nodes with other railway values (station, halt, abandoned, ...)
            # and untagged way nodes are ignored.
        elif obj.is_way():
            if railway_value in filters.crossing_railway_values:
                yield ("skip", "crossing_not_node")
                continue
            if railway_value in filters.track_railway_values:
                coords = []
                for n in obj.nodes:
                    try:
                        loc = n.location
                        if loc.valid():
                            coords.append((loc.lon, loc.lat))
                    except osmium.InvalidLocationError:
                        continue
                if len(coords) < 2:
                    yield ("skip", "track_invalid_geometry")
                elif bbox and not _coords_intersect_bbox(coords, bbox):
                    yield ("skip", "outside_bbox")
                else:
                    yield (
                        "track",
                        obj,
                        tags,
                        {
                            "osm_type": "way",
                            "osm_id": obj.id,
                            "geometry": LineString(coords, srid=4326),
                            "railway_value": railway_value[:64],
                            "usage": tags.get("usage", "")[:64],
                            "service": tags.get("service", "")[:64],
                        },
                    )
            # Ways with other railway values (abandoned, disused, platform,
            # level_crossing handled above, ...) are ignored.
            # A way tagged with both railway and highway still counts as a
            # candidate road for any crossing node on it.
            if tags.get("highway"):
                yield ("road", obj, tags, {})
        elif obj.is_relation():
            if railway_value in filters.crossing_railway_values:
                yield ("skip", "crossing_not_node")
            # Other relations are ignored.


def _reconcile(run, scope, max_deactivate_fraction, counts, filters):
    """Soft-delete active OSM rows inside ``scope`` that this run did not see.

    Candidates are limited to the run's railway-value filter set, so
    re-importing with a narrower ``--track-values``/``--crossing-values``
    never deactivates rows outside that set. A row whose OSM value changed
    out of the set (e.g. rail -> abandoned) keeps its old stored value and
    is still correctly deactivated.

    Tracks are only candidates when their full geometry lies within the
    scope (``__within``), so tracks clipped by the bbox boundary are
    conservatively left alone.
    """
    checks = (
        (
            RailwayCrossing,
            "location",
            "crossing",
            filters.crossing_railway_values,
        ),
        (
            RailwayTrack,
            "geometry",
            "track",
            filters.track_railway_values,
        ),
    )
    candidate_qs = {}
    for model, geofield, kind, values in checks:
        in_scope = model.objects.filter(
            source="osm",
            is_active=True,
            railway_value__in=values,
            **{f"{geofield}__within": scope},
        )
        candidates = in_scope.exclude(last_seen_run=run)
        candidate_qs[kind] = (candidates, in_scope.count(), candidates.count())

    for kind, (_qs, active_count, cand_count) in candidate_qs.items():
        if cand_count and cand_count > max_deactivate_fraction * active_count:
            raise CommandError(
                f"reconcile aborted for {kind}: {cand_count} deactivation "
                f"candidates exceed {max_deactivate_fraction:.0%} of "
                f"{active_count} active OSM rows in scope - review the "
                f"extract or re-run with a higher --max-deactivate-fraction"
            )

    now = timezone.now()
    with transaction.atomic():
        for kind, (candidates, _active, _cand) in candidate_qs.items():
            n = candidates.update(is_active=False, deactivated_at=now)
            counts["deactivated"][kind] = n


def _road_candidate(obj, tags):
    """Sortable road candidate for a crossing node (lower sort key wins).

    Named-or-ref'd roads always beat unnamed ones, then highway rank, then
    lowest way id for determinism.
    """
    name = best_name(tags)
    ref = (tags.get("ref") or "")[:64]
    highway = tags["highway"][:64]
    key = (
        0 if (name or ref) else 1,
        HIGHWAY_RANK.get(highway, HIGHWAY_RANK_DEFAULT),
        obj.id,
    )
    fields = {
        "road_name": name,
        "road_ref": ref,
        "road_highway": highway,
        "road_osm_id": obj.id,
    }
    return key, fields


def _parse_and_write(path, filters, bbox, location_index, batch_size, run, dry_run):
    from math import floor

    counts = empty_counts()
    # Crossings are buffered (not flushed) until the way pass is done,
    # because the roads/places that give them a derived label arrive after
    # the nodes in a normally ordered OSM file. Crossing counts are small
    # (India-scale: tens of thousands), so in-memory buffering is fine.
    crossing_rows = []
    crossing_node_ids = set()
    track_buf = []
    place_grid = {}
    road_candidates = {}  # crossing node id -> (sort_key, fields)

    for kind, *rest in _iter_features(path, filters, bbox, location_index):
        if kind == "skip":
            _skip(counts, rest[0])
            continue
        obj, tags, specific = rest
        if kind == "place":
            try:
                plon, plat = obj.location.lon, obj.location.lat
            except osmium.InvalidLocationError:
                continue
            cell = (
                floor(plon / PLACE_CELL_DEG),
                floor(plat / PLACE_CELL_DEG),
            )
            place_grid.setdefault(cell, []).append(
                (plon, plat, best_name(tags), tags["place"][:32])
            )
            continue
        if kind == "road":
            key, fields = _road_candidate(obj, tags)
            for n in obj.nodes:
                if n.ref in crossing_node_ids:
                    prev = road_candidates.get(n.ref)
                    if prev is None or key < prev[0]:
                        road_candidates[n.ref] = (key, fields)
            continue
        if kind == "crossing":
            crossing_node_ids.add(obj.id)
            crossing_rows.append(
                {**specific, **_common_kwargs(obj, tags, run)}
            )
        else:  # track
            if dry_run:
                counts["parsed"]["track"] += 1
                continue
            track_buf.append(
                RailwayTrack(**specific, **_common_kwargs(obj, tags, run))
            )
            if len(track_buf) >= batch_size:
                flush_batch(RailwayTrack, track_buf, run, counts)
                track_buf = []

    if not dry_run and track_buf:
        flush_batch(RailwayTrack, track_buf, run, counts)

    # Enrich crossings with road/place context, then flush in batches.
    for row in crossing_rows:
        cand = road_candidates.get(row["osm_id"])
        if cand is not None:
            row.update(cand[1])
            counts["crossings_with_road"] += 1
        place = _nearest_place(row["location"].x, row["location"].y, place_grid)
        if place is not None:
            dist_m, pname, ptype = place
            row["nearest_place_name"] = pname
            row["nearest_place_type"] = ptype
            row["nearest_place_distance_m"] = int(round(dist_m))
            counts["crossings_with_place"] += 1

    if dry_run:
        counts["parsed"]["crossing"] = len(crossing_rows)
        return counts

    for i in range(0, len(crossing_rows), batch_size):
        buf = [RailwayCrossing(**kw) for kw in crossing_rows[i : i + batch_size]]
        if buf:
            flush_batch(RailwayCrossing, buf, run, counts)
    return counts


def run_import(
    path,
    *,
    filters=None,
    bbox=None,
    batch_size=2000,
    reconcile=False,
    max_deactivate_fraction=0.2,
    dry_run=False,
    location_index="flex_mem",
    source_url="",
):
    """Run the import. Returns ImportResult; raises CommandError on failure.

    Failure semantics: the OsmImportRun row is created up front (committed
    immediately), batches flush in their own transactions, so a mid-import
    failure leaves valid earlier batches in place and marks the run failed.
    Re-running the same file is the restart path (upserts are idempotent).
    """
    filters = filters or ImportFilters()
    path = str(path)
    if not os.path.isfile(path):
        raise CommandError(f"source file not found: {path}")

    header_box, source_ts = _read_header(path)
    coverage = bbox or header_box
    if reconcile and coverage is None:
        raise CommandError(
            "--reconcile needs a coverage bbox: pass --bbox or use a file "
            "with a header bounds element"
        )

    file_sha256 = _file_sha256(path)
    file_size = os.path.getsize(path)

    if dry_run:
        counts = _parse_and_write(
            path, filters, bbox, location_index, batch_size, None, True
        )
        return ImportResult(run_id=None, status="dry-run", counts=counts)

    if not acquire_import_lock():
        raise CommandError(
            "another import is running (advisory lock not acquired)"
        )
    try:
        run = OsmImportRun.objects.create(
            source_path=path,
            source_url=source_url,
            file_sha256=file_sha256,
            file_size=file_size,
            source_timestamp=source_ts,
            coverage_bbox=_coverage_polygon(coverage),
            filters=filters.as_dict(),
            reconcile=reconcile,
            batch_size=batch_size,
        )
        OsmImportRun.objects.filter(status=OsmImportRun.STATUS_RUNNING).exclude(
            pk=run.pk
        ).update(
            status=OsmImportRun.STATUS_FAILED,
            error=f"interrupted (found running at start of run {run.pk})",
            finished_at=timezone.now(),
        )

        counts = empty_counts()
        try:
            counts = _parse_and_write(
                path, filters, bbox, location_index, batch_size, run, False
            )
            if reconcile:
                scope = run.coverage_bbox
                _reconcile(
                    run, scope, max_deactivate_fraction, counts, filters
                )
        except Exception as exc:
            run.status = OsmImportRun.STATUS_FAILED
            run.error = (str(exc) or repr(exc))[:2000]
            run.finished_at = timezone.now()
            run.counts = counts
            run.save()
            if isinstance(exc, CommandError):
                raise
            raise CommandError(f"import failed: {exc!r}") from exc

        run.status = OsmImportRun.STATUS_SUCCEEDED
        run.finished_at = timezone.now()
        run.counts = counts
        run.save()
        return ImportResult(run_id=run.pk, status=run.status, counts=counts)
    finally:
        release_import_lock()
