"""Route ↔ crossing association on PostGIS (raw SQL, geography distances).

A level crossing counts as *on* the route only when the route line both
passes the crossing node and actually crosses the mapped railway track
there (``track_evidence``). A crossing that is merely near the route line
— e.g. on a parallel road — is ``possible``, never definite. Avoidance
clearance uses the same geography distances.
"""
from dataclasses import dataclass

from django.conf import settings
from django.db import connection


@dataclass(frozen=True)
class RouteCrossing:
    crossing_id: int
    name: str
    lat: float
    lng: float
    source: str
    osm_type: str
    osm_id: int | None
    distance_m: float
    along_m: float
    match: str  # "on_route" | "possible"
    track_evidence: bool

    @property
    def along_km(self):
        return f"{self.along_m / 1000:.1f}"


def crossings_along_route(geometry):
    """Crossings near ``geometry`` (a LineString), ordered along the route."""
    near_m = settings.ROUTE_CROSSING_NEAR_M
    on_route_m = settings.ROUTE_CROSSING_ON_ROUTE_M
    track_m = settings.ROUTE_TRACK_MATCH_M
    pad = near_m / 80000.0  # generous degrees pad for bbox prefilters

    sql = """
        WITH route AS (
            SELECT ST_GeomFromEWKT(%s) AS geom
        )
        SELECT
            c.id,
            c.name,
            ST_Y(c.location) AS lat,
            ST_X(c.location) AS lng,
            c.source,
            c.osm_type,
            c.osm_id,
            ST_Distance(c.location::geography, route.geom::geography)
                AS distance_m,
            ST_LineLocatePoint(route.geom, c.location)
                * ST_Length(route.geom::geography) AS along_m,
            EXISTS (
                SELECT 1
                FROM railways_railwaytrack t
                WHERE t.is_active
                  AND t.geometry && ST_Expand(route.geom, %s)
                  AND ST_Intersects(t.geometry, route.geom)
                  AND ST_DWithin(
                      ST_Intersection(t.geometry, route.geom)::geography,
                      c.location::geography,
                      %s
                  )
            ) AS track_evidence
        FROM railways_railwaycrossing c, route
        WHERE c.is_active
          AND NOT c.is_suppressed
          AND c.location && ST_Expand(route.geom, %s)
          AND ST_DWithin(c.location::geography, route.geom::geography, %s)
        ORDER BY along_m
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [geometry.ewkt, pad, track_m, pad, near_m])
        rows = cursor.fetchall()

    results = []
    for row in rows:
        (
            cid, name, lat, lng, source, osm_type, osm_id,
            distance_m, along_m, track_evidence,
        ) = row
        match = (
            "on_route"
            if distance_m <= on_route_m and track_evidence
            else "possible"
        )
        results.append(
            RouteCrossing(
                crossing_id=cid,
                name=name or "",
                lat=lat,
                lng=lng,
                source=source,
                osm_type=osm_type or "",
                osm_id=osm_id,
                distance_m=distance_m,
                along_m=along_m,
                match=match,
                track_evidence=track_evidence,
            )
        )
    return results


def distances_to_crossings(geometry, crossing_ids):
    """Metres from the route to each crossing id (geography distance)."""
    ids = list(crossing_ids)
    if not ids:
        return {}
    sql = """
        WITH route AS (
            SELECT ST_GeomFromEWKT(%s) AS geom
        )
        SELECT c.id,
               ST_Distance(c.location::geography, route.geom::geography)
        FROM railways_railwaycrossing c, route
        WHERE c.id = ANY(%s)
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [geometry.ewkt, ids])
        return {row[0]: row[1] for row in cursor.fetchall()}
