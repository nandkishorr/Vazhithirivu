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


def map_config_json(response):
    match = re.search(
        r'<script id="map-config" type="application/json">(.*?)</script>',
        response.content.decode(),
        re.DOTALL,
    )
    assert match is not None, "map-config script tag not found"
    return json.loads(match.group(1))


@_MAP_KEY
class CrossingMarkerTests(TestCase):
    def test_page_config_and_detail_card(self):
        make_crossing(
            osm_id=11,
            name="Ernakulam Crossing",
            crossing_barrier="full",
            location=Point(76.31, 9.96, srid=4326),
        )
        make_crossing(
            source="manual",
            osm_type="",
            osm_id=None,
            name="Manual Fix",
            location=Point(76.32, 9.97, srid=4326),
        )

        response = Client().get("/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Crossings are no longer embedded — the map fetches the bbox API.
        self.assertNotIn("crossings-data", content)
        self.assertNotIn("Ernakulam Crossing", content)
        self.assertNotIn("Manual Fix", content)

        config = map_config_json(response)
        self.assertEqual(config["crossingsUrl"], "/api/crossings/")
        self.assertEqual(
            config["crossingsWsUrl"], "ws://testserver/ws/crossings/"
        )
        self.assertEqual(config["crossingsMinZoom"], 12)
        self.assertEqual(config["bboxMaxSpan"], 1.5)

        self.assertIn('id="crossings-status"', content)
        self.assertIn("data-crossings-status-text", content)

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
        self.assertIn(
            'data-status-url-template="/api/crossings/0/status/"', content
        )
        self.assertIn('data-detail-url-template="/crossings/0/"', content)
        for key in (
            "closed_reported",
            "open_reported",
            "conflicting",
            "stale",
            "unknown",
        ):
            self.assertIn(f'data-status-variant="{key}"', content)
        self.assertIn("data-status-summary", content)
        self.assertIn("data-status-error", content)
        self.assertIn("data-crossing-detail-link", content)
        self.assertIn("Report or view details", content)

    def test_status_endpoint_for_marker_crossing(self):
        # The marker panel fetches /api/crossings/<id>/status/ for crossings
        # returned by the bbox endpoint — verify it works end to end.
        from django.contrib.auth import get_user_model

        from incidents.services import create_report

        crossing = make_crossing(osm_id=40)
        user = get_user_model().objects.create_user("marker-tester")
        create_report(user, crossing, "closed")

        response = Client().get(f"/api/crossings/{crossing.pk}/status/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"]["state"], "closed_reported")

    def test_no_crossings_keeps_import_empty_state(self):
        response = Client().get("/")
        self.assertContains(response, "hasn't been imported yet")
        self.assertNotContains(response, 'id="crossing-detail"')


class CrossingMarkerNoKeyTests(TestCase):
    @override_settings(DEBUG=True, GOOGLE_MAPS_BROWSER_KEY="", GOOGLE_MAPS_MAP_ID="")
    def test_no_key_no_crossings_data(self):
        make_crossing(osm_id=30)
        response = Client().get("/")
        self.assertContains(response, "Google Maps isn't configured")
        self.assertNotContains(response, "crossings-data")
        self.assertNotContains(response, 'id="crossings-status"')
        self.assertContains(
            response, "Crossings appear on the map once Google Maps is configured."
        )
