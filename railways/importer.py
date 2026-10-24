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
    # C++-side pre-filter: only railway-tagged objects reach Python. Verified
    # with pyosmium 4.3: filtered-out untagged nodes are still stored in the
    # location index, so track ways keep their geometry.
    fp = fp.with_filter(osmium.filter.KeyFilter("railway"))

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
                    continue
                if bbox and not _coords_intersect_bbox(coords, bbox):
                    yield ("skip", "outside_bbox")
                    continue
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


def _parse_and_write(path, filters, bbox, location_index, batch_size, run, dry_run):
    counts = empty_counts()
    buffers = {"crossing": [], "track": []}
    models = {"crossing": RailwayCrossing, "track": RailwayTrack}

    for kind, *rest in _iter_features(path, filters, bbox, location_index):
        if kind == "skip":
            _skip(counts, rest[0])
            continue
        obj, tags, specific = rest
        if dry_run:
            counts["parsed"][kind] += 1
            continue
        buffers[kind].append(
            models[kind](**specific, **_common_kwargs(obj, tags, run))
        )
        if len(buffers[kind]) >= batch_size:
            flush_batch(models[kind], buffers[kind], run, counts)
            buffers[kind] = []

    if not dry_run:
        for kind, buf in buffers.items():
            if buf:
                flush_batch(models[kind], buf, run, counts)
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
