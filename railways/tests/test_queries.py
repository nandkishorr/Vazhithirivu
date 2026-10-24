from django.contrib.gis.geos import Point
from django.db import connection
from django.test import TestCase

from railways.models import RailwayCrossing
from railways.queries import (
    BBoxError,
    crossings_in_bbox,
    crossings_in_bbox_queryset,
    parse_bbox,
)

BBOX = (76.0, 9.0, 77.0, 10.0)


def make_crossing(**kwargs):
    defaults = {
        "source": "osm",
        "osm_type": "node",
        "osm_id": 1,
        "location": Point(76.5, 9.5, srid=4326),
        "railway_value": "level_crossing",
    }
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


class ParseBboxTests(TestCase):
    def test_valid_bbox(self):
        self.assertEqual(
            parse_bbox("76.18,9.85,76.45,10.15", 1.5),
            (76.18, 9.85, 76.45, 10.15),
        )

    def test_span_exactly_at_limit_is_ok(self):
        self.assertEqual(
            parse_bbox("0,0,1.5,1.5", 1.5), (0.0, 0.0, 1.5, 1.5)
        )

    def test_invalid_bboxes(self):
        invalid = [
            "",
            None,
            "1,2,3",
            "1,2,3,4,5",
            "a,b,c,d",
            "nan,9,77,10",
            "inf,9,77,10",
            "77,9,76,10",  # west >= east
            "76,10,77,9",  # south >= north
            "76,9,77,91",  # lat out of range
            "181,9,182,10",  # lng out of range
        ]
        for raw in invalid:
            with self.subTest(raw=raw):
                with self.assertRaises(BBoxError) as ctx:
                    parse_bbox(raw, 1.5)
                self.assertEqual(ctx.exception.code, "invalid_bbox")

    def test_too_large_bbox(self):
        for raw in ("0,0,2,0.5", "0,0,0.5,2", "0,0,2,2"):
            with self.subTest(raw=raw):
                with self.assertRaises(BBoxError) as ctx:
                    parse_bbox(raw, 1.5)
                self.assertEqual(ctx.exception.code, "bbox_too_large")


class CrossingsInBboxTests(TestCase):
    def test_includes_excludes_and_boundary(self):
        inside_osm = make_crossing(osm_id=11)
        inside_manual = make_crossing(
            source="manual",
            osm_type="",
            osm_id=None,
            location=Point(76.2, 9.8, srid=4326),
        )
        boundary = make_crossing(
            osm_id=13, location=Point(77.0, 9.5, srid=4326)
        )
        make_crossing(osm_id=14, location=Point(75.0, 9.5, srid=4326))
        make_crossing(osm_id=15, is_active=False)
        make_crossing(osm_id=16, is_suppressed=True)

        rows, truncated = crossings_in_bbox(BBOX, limit=10)
        self.assertFalse(truncated)
        self.assertEqual(
            [c.pk for c in rows],
            [inside_osm.pk, inside_manual.pk, boundary.pk],
        )

    def test_ordered_by_pk(self):
        a = make_crossing(osm_id=21)
        b = make_crossing(osm_id=22)
        c = make_crossing(osm_id=23)
        rows, _ = crossings_in_bbox(BBOX, limit=10)
        self.assertEqual(
            [x.pk for x in rows], sorted([a.pk, b.pk, c.pk])
        )

    def test_limit_and_truncated(self):
        for i in range(3):
            make_crossing(osm_id=30 + i)
        rows, truncated = crossings_in_bbox(BBOX, limit=2)
        self.assertEqual(len(rows), 2)
        self.assertTrue(truncated)
        rows, truncated = crossings_in_bbox(BBOX, limit=3)
        self.assertEqual(len(rows), 3)
        self.assertFalse(truncated)

    def test_bbox_query_uses_spatial_index(self):
        make_crossing(osm_id=40)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'railways_railwaycrossing'"
            )
            indexes = cursor.fetchall()
        gist = [
            name
            for name, indexdef in indexes
            if "gist" in indexdef.lower() and "location" in indexdef.lower()
        ]
        self.assertTrue(
            gist, "no GiST index on railways_railwaycrossing.location"
        )
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
            plan = crossings_in_bbox_queryset(BBOX).explain()
        self.assertIn(gist[0], plan)
