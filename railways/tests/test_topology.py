"""Same-line crossing topology tests (ADR-020).

Tracks are built as connected vertex chains; crossings snap onto
vertices, so links measure along-track distance, never radius.
"""
from django.contrib.gis.geos import LineString, Point
from django.test import TestCase

from railways.models import CrossingLink, RailwayCrossing, RailwayTrack
from railways.topology import rebuild_crossing_links


def track(coords, **kwargs):
    defaults = {
        "source": "manual",
        "osm_type": "",
        "osm_id": None,
        "geometry": LineString(coords, srid=4326),
        "railway_value": "rail",
    }
    defaults.update(kwargs)
    return RailwayTrack.objects.create(**defaults)


def crossing(lon, lat, **kwargs):
    defaults = {
        "source": "manual",
        "osm_type": "",
        "osm_id": None,
        "location": Point(lon, lat, srid=4326),
        "railway_value": "level_crossing",
    }
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


def links_from(crossing):
    return list(
        CrossingLink.objects.filter(from_crossing=crossing).order_by("rank")
    )


class RebuildLinksTests(TestCase):
    # One straight E-W line: vertices ~1.1 km apart, crossings on 4 of them.
    LINE = [
        (76.00, 10.00),
        (76.01, 10.00),
        (76.02, 10.00),
        (76.03, 10.00),
        (76.04, 10.00),
    ]

    def test_consecutive_links_ranked_by_track_distance(self):
        track(self.LINE)
        c1 = crossing(76.01, 10.00)
        c2 = crossing(76.02, 10.00)
        c3 = crossing(76.03, 10.00)
        c4 = crossing(76.04, 10.00)
        counts = rebuild_crossing_links(
            max_neighbors=3,
            snap_tolerance_m=30,
            max_distance_m=15000,
        )
        self.assertEqual(counts["linked"], 4)
        self.assertEqual(counts["unsnapped"], 0)
        # End-of-line crossing only has neighbours on one side.
        c4_links = links_from(c4)
        self.assertEqual(
            [l.to_crossing_id for l in c4_links], [c3.pk, c2.pk, c1.pk]
        )
        self.assertEqual([l.rank for l in c4_links], [1, 2, 3])
        self.assertAlmostEqual(c4_links[0].distance_m, 1102, delta=50)
        self.assertAlmostEqual(c4_links[2].distance_m, 3306, delta=100)
        # c2's rank-1 neighbours are c1 and c3 (one per direction).
        c2_targets = {l.to_crossing_id for l in links_from(c2)}
        self.assertEqual(c2_targets, {c1.pk, c3.pk, c4.pk})

    def test_max_neighbors_caps_links(self):
        track(self.LINE)
        for x in (76.01, 76.02, 76.03, 76.04):
            crossing(x, 10.00)
        rebuild_crossing_links(
            max_neighbors=1,
            snap_tolerance_m=30,
            max_distance_m=15000,
        )
        for link_set in CrossingLink.objects.values_list(
            "from_crossing_id", flat=True
        ).distinct():
            self.assertLessEqual(
                CrossingLink.objects.filter(
                    from_crossing_id=link_set
                ).count(),
                1,
            )

    def test_max_distance_caps_links(self):
        track(self.LINE)
        crossing(76.01, 10.00)
        crossing(76.02, 10.00)
        crossing(76.03, 10.00)
        rebuild_crossing_links(
            max_neighbors=3,
            snap_tolerance_m=30,
            max_distance_m=1200,
        )
        # ~1.1 km spacing: only the immediately adjacent crossings link;
        # the middle one gets one per direction (two links total).
        self.assertTrue(
            all(
                link.distance_m <= 1200
                for link in CrossingLink.objects.all()
            )
        )
        self.assertEqual(CrossingLink.objects.count(), 4)

    def test_off_track_crossing_gets_no_links(self):
        track(self.LINE)
        crossing(76.02, 10.00)
        crossing(76.50, 10.50)  # ~50 km away from every vertex
        counts = rebuild_crossing_links(
            max_neighbors=3,
            snap_tolerance_m=30,
            max_distance_m=15000,
        )
        self.assertEqual(counts["unsnapped"], 1)
        self.assertEqual(counts["links"], 0)

    def test_parallel_tracks_do_not_link(self):
        track(self.LINE)
        shifted = [(x, y + 0.005) for x, y in self.LINE]
        track(shifted)
        a = crossing(76.02, 10.00)
        b = crossing(76.03, 10.00)
        crossing(76.02, 10.005)  # on the parallel line
        crossing(76.03, 10.005)
        rebuild_crossing_links(
            max_neighbors=3,
            snap_tolerance_m=30,
            max_distance_m=15000,
        )
        # a/b link only to each other; nothing crosses between the lines.
        for link in links_from(a) + links_from(b):
            self.assertIn(link.to_crossing_id, {a.pk, b.pk})

    def test_branch_at_shared_vertex_connects(self):
        track(self.LINE)
        # Branch going south from the 76.02 vertex.
        track([(76.02, 10.00), (76.02, 9.99), (76.02, 9.98)])
        main = crossing(76.01, 10.00)
        branch = crossing(76.02, 9.99)
        junction = crossing(76.02, 10.00)
        rebuild_crossing_links(
            max_neighbors=3,
            snap_tolerance_m=30,
            max_distance_m=15000,
        )
        # The branch crossing reaches the junction crossing through the
        # shared vertex — same connected line.
        targets = {l.to_crossing_id for l in links_from(branch)}
        self.assertIn(junction.pk, targets)
        self.assertIn(main.pk, targets)

    def test_rebuild_is_idempotent(self):
        track(self.LINE)
        crossing(76.02, 10.00)
        crossing(76.03, 10.00)
        first = rebuild_crossing_links(
            max_neighbors=3,
            snap_tolerance_m=30,
            max_distance_m=15000,
        )
        second = rebuild_crossing_links(
            max_neighbors=3,
            snap_tolerance_m=30,
            max_distance_m=15000,
        )
        self.assertEqual(first["links"], second["links"])
        self.assertEqual(CrossingLink.objects.count(), first["links"])

    def test_inactive_rows_are_ignored(self):
        track(self.LINE)
        crossing(76.02, 10.00)
        crossing(76.03, 10.00, is_active=False)
        crossing(76.03, 10.00)
        counts = rebuild_crossing_links(
            max_neighbors=3,
            snap_tolerance_m=30,
            max_distance_m=15000,
        )
        self.assertEqual(counts["linked"], 2)
