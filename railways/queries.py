"""Bounded spatial queries for the map UI (ADR-012) and navigation
position checks (ADR-017).

Crossing lookups are always limited to an explicit, size-capped
bounding box or radius so endpoints stay cheap and indexed.
"""
import math

from django.contrib.gis.geos import Polygon
from django.db import connection

from .models import RailwayCrossing


class BBoxError(ValueError):
    """Invalid or oversized ``bbox`` parameter.

    ``code`` is ``"invalid_bbox"`` or ``"bbox_too_large"``.
    """

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def parse_bbox(raw, max_span_deg):
    """Parse ``"west,south,east,north"`` into a 4-tuple of floats.

    Raises :class:`BBoxError` with ``code="invalid_bbox"`` for malformed
    input and ``code="bbox_too_large"`` when either span exceeds
    ``max_span_deg`` degrees. Antimeridian-spanning boxes are rejected
    (``west`` must be < ``east``).
    """
    if not isinstance(raw, str) or not raw:
        raise BBoxError("invalid_bbox")
    parts = raw.split(",")
    if len(parts) != 4:
        raise BBoxError("invalid_bbox")
    try:
        values = [float(part) for part in parts]
    except ValueError:
        raise BBoxError("invalid_bbox") from None
    if any(not math.isfinite(v) for v in values):
        raise BBoxError("invalid_bbox")
    west, south, east, north = values
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise BBoxError("invalid_bbox")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise BBoxError("invalid_bbox")
    if west >= east or south >= north:
        raise BBoxError("invalid_bbox")
    if (east - west) > max_span_deg or (north - south) > max_span_deg:
        raise BBoxError("bbox_too_large")
    return west, south, east, north


def crossings_in_bbox_queryset(bbox):
    """Active, non-suppressed crossings (osm + manual) inside ``bbox``.

    ``bbox`` is a ``(west, south, east, north)`` tuple in SRID 4326.
    Uses the GiST spatial index on ``location``; ``intersects`` includes
    points exactly on the boundary.
    """
    area = Polygon.from_bbox(bbox)
    area.srid = 4326
    return (
        RailwayCrossing.objects.filter(
            is_active=True,
            is_suppressed=False,
            location__intersects=area,
        )
        .order_by("pk")
        .only(
            "id",
            "location",
            "name",
            "crossing_barrier",
            "source",
            "osm_type",
            "osm_id",
        )
    )


def crossings_in_bbox(bbox, limit):
    """Return ``(crossings[:limit], truncated)`` for ``bbox``."""
    rows = list(crossings_in_bbox_queryset(bbox)[: limit + 1])
    return rows[:limit], len(rows) > limit


def crossings_near_point(lat, lng, radius_m, limit):
    """Active crossings within ``radius_m`` of (lat, lng), nearest first.

    Geography distances in metres (same convention as
    ``routing.analysis``). Returns ``[(crossing, distance_m), …]``
    capped at ``limit`` — a position check always stays bounded.
    Two queries: ids/distances, then the model rows.
    """
    sql = """
        SELECT c.id,
               ST_Distance(
                   c.location::geography,
                   ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
               ) AS distance_m
        FROM railways_railwaycrossing c
        WHERE c.is_active
          AND NOT c.is_suppressed
          AND ST_DWithin(
              c.location::geography,
              ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
              %s
          )
        ORDER BY distance_m
        LIMIT %s
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [lng, lat, lng, lat, radius_m, limit])
        rows = cursor.fetchall()
    crossings = RailwayCrossing.objects.in_bulk(row[0] for row in rows)
    return [
        (crossings[row[0]], row[1]) for row in rows if row[0] in crossings
    ]
