import json
import re

from django.contrib.gis.geos import Point
from django.test import Client, TestCase, override_settings

from railways.models import RailwayCrossing

_MAP_KEY = override_settings(
    GOOGLE_MAPS_BROWSER_KEY="test-browser-key",
    GOOGLE_MAPS_MAP_ID="test-map-id",
)


def make_crossing(**kwargs):
    defaults = {
        "source": "osm",
        "osm_type": "node",
        "location": Point(76.30, 9.95, srid=4326),
        "railway_value": "level_crossing",
    }
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


def crossings_json(response):
    match = re.search(
        r'<script id="crossings-data" type="application/json">(.*?)</script>',
        response.content.decode(),
        re.DOTALL,
    )
    assert match is not None, "crossings-data script tag not found"
    return json.loads(match.group(1))


@_MAP_KEY
class CrossingMarkerTests(TestCase):
    def test_visible_crossings_in_json_and_detail_card(self):
        osm_c = make_crossing(
            osm_id=11,
            name="Ernakulam Crossing",
            crossing_barrier="full",
            location=Point(76.31, 9.96, srid=4326),
        )
        manual_c = make_crossing(
            source="manual",
            osm_type="",
            osm_id=None,
            name="Manual Fix",
            location=Point(76.32, 9.97, srid=4326),
        )
        make_crossing(osm_id=12, is_active=False)
        make_crossing(osm_id=13, is_suppressed=True)

        response = Client().get("/")
        self.assertEqual(response.status_code, 200)

        data = crossings_json(response)
        self.assertEqual(len(data), 2)
        by_id = {c["id"]: c for c in data}
        self.assertIn(osm_c.pk, by_id)
        self.assertIn(manual_c.pk, by_id)

        o = by_id[osm_c.pk]
        self.assertAlmostEqual(o["lat"], 9.96)
        self.assertAlmostEqual(o["lng"], 76.31)
        self.assertEqual(o["name"], "Ernakulam Crossing")
        self.assertEqual(o["barrier"], "full")
        self.assertEqual(o["source"], "osm")
        self.assertEqual(o["osm_type"], "node")
        self.assertEqual(o["osm_id"], 11)

        m = by_id[manual_c.pk]
        self.assertEqual(m["source"], "manual")
        self.assertIsNone(m["osm_id"])

        content = response.content.decode()
        self.assertIn('id="crossing-detail"', content)
        self.assertIn('id="crossing-empty"', content)
        self.assertIn("Status unknown", content)
        self.assertIn("doesn't mean the gate is open", content)
        self.assertIn('data-source-variant="osm"', content)
        self.assertIn('data-source-variant="manual"', content)
        self.assertIn("data-crossing-barrier", content)
        self.assertIn("data-crossing-coords", content)
        self.assertIn("data-crossing-osm-link", content)
        self.assertIn("https://www.openstreetmap.org/copyright", content)
        self.assertIn("No crossing selected", content)

    def test_no_crossings_keeps_import_empty_state(self):
        response = Client().get("/")
        self.assertContains(response, "hasn't been imported yet")
        self.assertNotContains(response, 'id="crossing-detail"')

    def test_crossing_name_escaping(self):
        make_crossing(osm_id=20, name="</script><b>x")
        response = Client().get("/")
        body = response.content.decode()
        self.assertNotIn("</script><b>x", body)
        data = crossings_json(response)
        self.assertEqual(data[0]["name"], "</script><b>x")


class CrossingMarkerNoKeyTests(TestCase):
    @override_settings(DEBUG=True, GOOGLE_MAPS_BROWSER_KEY="", GOOGLE_MAPS_MAP_ID="")
    def test_no_key_no_crossings_data(self):
        make_crossing(osm_id=30)
        response = Client().get("/")
        self.assertContains(response, "Google Maps isn't configured")
        self.assertNotContains(response, "crossings-data")
        self.assertContains(
            response, "Crossings appear on the map once Google Maps is configured."
        )
