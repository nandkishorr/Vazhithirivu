"""Google encoded-polyline decoding (precision-5 algorithm)."""
from django.contrib.gis.geos import LineString


def decode(encoded, precision=5):
    """Decode an encoded polyline string into ``[(lat, lng), ...]``."""
    points = []
    index = 0
    lat = 0
    lng = 0
    factor = 10**precision
    length = len(encoded)

    while index < length:
        shift = 0
        result = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        lat += ~(result >> 1) if result & 1 else result >> 1

        shift = 0
        result = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        lng += ~(result >> 1) if result & 1 else result >> 1

        points.append((lat / factor, lng / factor))

    return points


def to_linestring(points):
    """Build a SRID-4326 ``LineString`` from ``(lat, lng)`` points.

    Returns ``None`` when the points contain fewer than two distinct
    coordinates.
    """
    coords = [(lng, lat) for lat, lng in points]
    distinct = set(coords)
    if len(distinct) < 2:
        return None
    return LineString(coords, srid=4326)
