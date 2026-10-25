"""Crossing-to-crossing rail-line topology (ADR-020).

Builds ``CrossingLink`` rows: for every active crossing, the nearest N
crossings measured *along the connected track network* — not by radius.
That is what "the consecutive crossings on the same line" means: a train
passing one gate reaches exactly these gates next, in either direction.

The network is a plain graph: every track-way vertex is a node (vertices
shared between ways are the junctions), consecutive vertices of a way
are edges weighted by their geographic length. Each crossing snaps to
the nearest network vertex within ``snap_tolerance_m`` — an OSM
``railway=level_crossing`` node is a member of its way, so this is an
exact hit for imported data and a small tolerance for manual rows.

A crossing too far from every track vertex gets no links, so the feature
degrades silently rather than guessing. Rebuilding is a full delete +
bulk insert: the table is derived state, small, and cheap to redo after
an import or admin correction.
"""
import heapq
import math
from dataclasses import dataclass, field

from django.db import transaction

from .models import CrossingLink, RailwayCrossing, RailwayTrack

_EARTH_RADIUS_M = 6371000.0
# Vertices are snapped to this grid so ways sharing an OSM node (which
# have bit-identical coordinates) always land on the same graph node,
# and float noise within ~1 m still merges.
_SNAP_DEG = 1e-5
# Grid cell used for nearest-vertex lookup (~330 m — small, few buckets).
_CELL_DEG = 0.003


def _snap(lon, lat):
    return (round(lon / _SNAP_DEG), round(lat / _SNAP_DEG))


def _haversine_m(a, b):
    """Metres between two (lon_i, lat_i) snapped grid nodes."""
    lon1, lat1 = a[0] * _SNAP_DEG, a[1] * _SNAP_DEG
    lon2, lat2 = b[0] * _SNAP_DEG, b[1] * _SNAP_DEG
    rad = math.pi / 180.0
    dlat = (lat2 - lat1) * rad
    dlon = (lon2 - lon1) * rad
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(dlon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


@dataclass
class _Network:
    """Adjacency graph + crossing→node attachments for the rail network."""

    adjacency: dict = field(default_factory=dict)
    node_crossings: dict = field(default_factory=dict)
    snapped_to: dict = field(default_factory=dict)
    vertex_cells: dict = field(default_factory=dict)
    vertex_coord: dict = field(default_factory=dict)

    def add_edge(self, a, b, weight_m):
        if weight_m <= 0:
            return
        for u, v in ((a, b), (b, a)):
            neighbours = self.adjacency.setdefault(u, {})
            if v not in neighbours or weight_m < neighbours[v]:
                neighbours[v] = weight_m


def _build_network(track_coords, snap_tolerance_m):
    """Build the node/edge graph and crossing attachments.

    ``track_coords`` is ``[(track_id, [(lon, lat), …]), …]``.
    Returns ``(network, unsnapped_crossing_ids)`` — the caller attaches
    crossings afterwards via :func:`_attach_crossings`.
    """
    net = _Network()
    for _track_id, coords in track_coords:
        nodes = []
        prev = None
        for lon, lat in coords:
            node = _snap(lon, lat)
            if node == prev:
                continue
            nodes.append(node)
            net.vertex_coord[node] = (lon, lat)
            prev = node
        for a, b in zip(nodes, nodes[1:]):
            net.add_edge(a, b, _haversine_m(a, b))
    return net


def _cell_of(lon, lat):
    return (int(lon / _CELL_DEG), int(lat / _CELL_DEG))


def _index_vertices(net):
    for node in net.vertex_coord:
        lon, lat = net.vertex_coord[node]
        net.vertex_cells.setdefault(_cell_of(lon, lat), []).append(node)


def _nearest_vertex(net, lon, lat, tolerance_m):
    """Nearest network vertex within ``tolerance_m``, or ``None``."""
    cx, cy = _cell_of(lon, lat)
    # Cells are ~330 m; for sane snap tolerances a ring or two around the
    # point's own cell always contains the nearest vertex.
    best = None
    best_m = tolerance_m
    rings = max(1, int(tolerance_m / (_CELL_DEG * 111320.0)) + 1)
    for r in range(rings + 1):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                for node in net.vertex_cells.get((cx + dx, cy + dy), ()):
                    d = _haversine_m(_snap(lon, lat), node)
                    if d < best_m:
                        best = node
                        best_m = d
    return best


def _attach_crossings(net, crossings, snap_tolerance_m):
    """Attach each crossing to its nearest network vertex.

    Returns the ids of crossings that had no vertex within tolerance.
    """
    _index_vertices(net)
    unsnapped = []
    for crossing in crossings:
        lon, lat = crossing.location.x, crossing.location.y
        node = _snap(lon, lat)
        if node not in net.vertex_coord:
            node = _nearest_vertex(net, lon, lat, snap_tolerance_m)
        if node is None:
            unsnapped.append(crossing.pk)
            continue
        net.snapped_to[crossing.pk] = node
        net.node_crossings.setdefault(node, []).append(crossing.pk)


def _neighbours_from(net, start_node, source_id, max_neighbors, max_distance_m):
    """Dijkstra from ``start_node``; the first ``max_neighbors`` crossings.

    Returns ``[(crossing_id, distance_m), …]`` ordered by along-track
    distance, excluding ``source_id`` itself. Stops early once enough
    crossings are found or the frontier exceeds ``max_distance_m``.
    """
    dist = {start_node: 0.0}
    heap = [(0.0, start_node)]
    found = []
    while heap and len(found) < max_neighbors:
        d, node = heapq.heappop(heap)
        if d > dist.get(node, math.inf):
            continue
        if d > max_distance_m:
            break
        for cid in sorted(net.node_crossings.get(node, ())):
            if cid != source_id and len(found) < max_neighbors:
                found.append((cid, d))
        for nxt, w in net.adjacency.get(node, {}).items():
            nd = d + w
            if nd < dist.get(nxt, math.inf) and nd <= max_distance_m:
                dist[nxt] = nd
                heapq.heappush(heap, (nd, nxt))
    return found


def rebuild_crossing_links(
    *,
    max_neighbors=None,
    snap_tolerance_m=None,
    max_distance_m=None,
):
    """Rebuild all ``CrossingLink`` rows from active tracks/crossings.

    Defaults come from settings (``RAILWAY_LINK_*``). Returns a counts
    dict for logging/commands. Runs as one transaction: readers either
    see the whole old or whole new link set.
    """
    from django.conf import settings

    if max_neighbors is None:
        max_neighbors = settings.RAILWAY_LINK_MAX_NEIGHBORS
    if snap_tolerance_m is None:
        snap_tolerance_m = settings.RAILWAY_LINK_SNAP_M
    if max_distance_m is None:
        max_distance_m = settings.RAILWAY_LINK_MAX_DISTANCE_M

    tracks = RailwayTrack.objects.filter(is_active=True).only("id", "geometry")
    crossings = list(
        RailwayCrossing.objects.filter(
            is_active=True, is_suppressed=False
        ).only("id", "location")
    )

    track_coords = [
        (t.pk, list(t.geometry.coords))
        for t in tracks
        if t.geometry is not None and len(t.geometry.coords) >= 2
    ]
    net = _build_network(track_coords, snap_tolerance_m)
    _attach_crossings(net, crossings, snap_tolerance_m)

    links = []
    for crossing in crossings:
        node = net.snapped_to.get(crossing.pk)
        if node is None:
            continue
        for rank, (cid, dist_m) in enumerate(
            _neighbours_from(
                net, node, crossing.pk, max_neighbors, max_distance_m
            ),
            start=1,
        ):
            links.append(
                CrossingLink(
                    from_crossing_id=crossing.pk,
                    to_crossing_id=cid,
                    rank=rank,
                    distance_m=round(dist_m, 1),
                )
            )

    with transaction.atomic():
        CrossingLink.objects.all().delete()
        CrossingLink.objects.bulk_create(links)

    return {
        "crossings": len(crossings),
        "linked": len({link.from_crossing_id for link in links}),
        "links": len(links),
        "unsnapped": len(crossings) - len(net.snapped_to),
        "tracks": len(track_coords),
        "nodes": len(net.vertex_coord),
    }
