from django.test import SimpleTestCase

from routing.polyline import decode, to_linestring


class DecodeTests(SimpleTestCase):
    def test_google_documented_sample(self):
        points = decode("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        self.assertEqual(
            points,
            [
                (38.5, -120.2),
                (40.7, -120.95),
                (43.252, -126.453),
            ],
        )

    def test_empty(self):
        self.assertEqual(decode(""), [])


class ToLineStringTests(SimpleTestCase):
    def test_builds_lng_lat_linestring(self):
        line = to_linestring([(10.0, 76.0), (10.1, 76.1)])
        self.assertEqual(line.srid, 4326)
        self.assertEqual(list(line.coords), [(76.0, 10.0), (76.1, 10.1)])

    def test_none_for_fewer_than_two_distinct(self):
        self.assertIsNone(to_linestring([]))
        self.assertIsNone(to_linestring([(10.0, 76.0)]))
        self.assertIsNone(to_linestring([(10.0, 76.0), (10.0, 76.0)]))
