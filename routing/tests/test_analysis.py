from django.contrib.gis.geos import LineString, Point
from django.test import TestCase

from railways.models import RailwayCrossing, RailwayTrack
from routing.analysis import crossings_along_route, distances_to_crossings

# A crossing at lng 76.30, lat 10.00 with a railway track running N-S.
CROSSING_LNG, CROSSING_LAT = 76.30, 10.00


def crossing(**kwargs):
    defaults = dict(
        location=Point(CROSSING_LNG, CROSSING_LAT, srid=4326),
        railway_value="level_crossing",
        source="manual",
        name="Test crossing",
    )
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


def track(**kwargs):
    defaults = dict(
        geometry=LineString(
            (CROSSING_LNG, CROSSING_LAT - 0.01),
            (CROSSING_LNG, CROSSING_LAT + 0.01),
            srid=4326,
        ),
        railway_value="rail",
        source="manual",
    )
    defaults.update(kwargs)
    return RailwayTrack.objects.create(**defaults)


def ew_route(offset_deg=0.0):
    """E-W route across the crossing longitude, offset N/S in degrees."""
    return LineString(
        (CROSSING_LNG - 0.01, CROSSING_LAT + offset_deg),
        (CROSSING_LNG + 0.01, CROSSING_LAT + offset_deg),
        srid=4326,
    )


class CrossingsAlongRouteTests(TestCase):
    def test_route_through_crossing_with_track_is_on_route(self):
        c = crossing()
        track()
        results = crossings_along_route(ew_route())
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.crossing_id, c.pk)
        self.assertEqual(r.match, "on_route")
        self.assertTrue(r.track_evidence)
        self.assertLess(r.distance_m, 5)
        # Route is ~2.2 km long; crossing is at the midpoint.
        self.assertTrue(500 < r.along_m < 1500)

    def test_parallel_route_not_crossing_track_is_possible(self):
        crossing()
        track()
        # ~35 m north of the crossing; route never intersects the track.
        results = crossings_along_route(ew_route(offset_deg=0.00032))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].match, "possible")
        self.assertFalse(results[0].track_evidence)

    def test_near_crossing_without_track_is_possible(self):
        crossing()
        # ~10 m off but no tracks in the DB at all.
        results = crossings_along_route(ew_route(offset_deg=0.00009))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].match, "possible")
        self.assertFalse(results[0].track_evidence)

    def test_crossing_200m_away_absent(self):
        crossing()
        track()
        results = crossings_along_route(ew_route(offset_deg=0.0018))
        self.assertEqual(results, [])

    def test_inactive_and_suppressed_excluded(self):
        crossing(is_active=False)
        crossing(is_suppressed=True, name="suppressed")
        track()
        self.assertEqual(crossings_along_route(ew_route()), [])

    def test_two_crossings_ordered_along_route(self):
        west = crossing(
            location=Point(CROSSING_LNG - 0.005, CROSSING_LAT, srid=4326),
            name="West",
        )
        east = crossing(
            location=Point(CROSSING_LNG + 0.005, CROSSING_LAT, srid=4326),
            name="East",
        )
        track(
            geometry=LineString(
                (CROSSING_LNG - 0.005, CROSSING_LAT - 0.01),
                (CROSSING_LNG - 0.005, CROSSING_LAT + 0.01),
                srid=4326,
            )
        )
        results = crossings_along_route(ew_route())
        ids = [r.crossing_id for r in results]
        self.assertEqual(ids, [west.pk, east.pk])
        self.assertLess(results[0].along_m, results[1].along_m)

    def test_distances_to_crossings(self):
        c1 = crossing()
        c2 = crossing(
            location=Point(CROSSING_LNG, CROSSING_LAT + 0.01, srid=4326)
        )
        distances = distances_to_crossings(ew_route(), [c1.pk, c2.pk])
        self.assertLess(distances[c1.pk], 5)
        self.assertGreater(distances[c2.pk], 1000)

    def test_distances_empty_input(self):
        self.assertEqual(distances_to_crossings(ew_route(), []), {})
