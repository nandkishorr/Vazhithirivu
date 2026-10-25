from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import LineString, Point
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from incidents.models import CrossingReport
from railways.models import RailwayCrossing, RailwayTrack
from routing.providers import RouteCandidate, RoutingError

LNG, LAT = 76.30, 10.00

BROWSER = "test-browser-key"
SERVER = "server-secret-xyz"


def ew(offset=0.0):
    return LineString(
        (LNG - 0.01, LAT + offset), (LNG + 0.01, LAT + offset), srid=4326
    )


def candidate(index, geometry, duration=660, distance=7000, labels=("DEFAULT_ROUTE",)):
    return RouteCandidate(
        index=index,
        geometry=geometry,
        distance_m=distance,
        duration_s=duration,
        static_duration_s=duration,
        description="Test road",
        labels=labels,
        warnings=(),
    )


class FakeProvider:
    name = "google"
    attribution = "Routes by Google"
    traffic_aware = False
    supports_exclusion = False

    def __init__(self, routes=(), error=None):
        self._routes = list(routes)
        self._error = error
        self.calls = 0

    def compute_routes(self, origin, destination, intermediates=None):
        self.calls += 1
        self.last_origin = origin
        self.last_destination = destination
        if intermediates:
            return []
        if self._error:
            raise self._error
        return list(self._routes)


@override_settings(GOOGLE_MAPS_BROWSER_KEY=BROWSER, GOOGLE_MAPS_SERVER_KEY=SERVER)
class RouteViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = get_user_model().objects.create_user("rep", password="x")
        self.crossing = RailwayCrossing.objects.create(
            location=Point(LNG, LAT, srid=4326),
            railway_value="level_crossing",
            source="manual",
            name="Main crossing",
        )
        RailwayTrack.objects.create(
            geometry=LineString(
                (LNG, LAT - 0.01), (LNG, LAT + 0.01), srid=4326
            ),
            railway_value="rail",
            source="manual",
        )
        self._patcher = patch("routing.providers.get_provider")
        self.mock_get_provider = self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _closed_report(self):
        now = timezone.now()
        return CrossingReport.objects.create(
            crossing=self.crossing,
            reported_state=CrossingReport.STATE_CLOSED,
            reporter=self.user,
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )

    def _get(self, provider, extra=""):
        self.mock_get_provider.return_value = provider
        return self.client.get(
            "/?origin=Edappally%2C+Kochi&destination=Vyttila%2C+Kochi" + extra
        )

    def test_closed_warning_and_verified_alternative(self):
        self._closed_report()
        provider = FakeProvider(
            [candidate(0, ew()), candidate(1, ew(0.00135), labels=())]
        )
        response = self._get(provider)
        self.assertContains(response, "Reported closed on your route")
        self.assertContains(response, "Main crossing")
        self.assertContains(response, "Use this route")
        self.assertContains(response, "Alternative route avoids")
        self.assertContains(response, 'data-route-panel="r0"')
        self.assertContains(response, "not official railway information")
        self.assertContains(response, "without live traffic")
        # The verified alternative is pre-selected, not the blocked
        # primary (ADR-021): r1's panel is the visible one and the map
        # payload selects it.
        self.assertContains(response, '"selected": "r1"')
        self.assertContains(
            response, 'data-route-panel="r0" hidden', count=1
        )
        self.assertContains(
            response, 'data-route-panel="r1"', count=1
        )

    def test_alternatives_selectable_without_blocking(self):
        """With no closed crossing, alternates are still selectable."""
        provider = FakeProvider(
            [
                candidate(0, ew()),
                candidate(1, ew(0.00135), duration=900, distance=9500, labels=()),
            ]
        )
        response = self._get(provider)
        self.assertContains(response, "Route options")
        self.assertContains(response, 'data-route-select="r1"')
        self.assertContains(response, 'data-route-panel="r1"')
        self.assertContains(response, "Recommended")
        self.assertContains(response, "+4 min")
        # No blocking → the primary stays the selected route.
        self.assertContains(response, '"selected": "r0"')

    def test_unverified_alternative_no_avoidance_claim(self):
        self._closed_report()
        provider = FakeProvider(
            [candidate(0, ew()), candidate(1, ew(0.00063), labels=())]
        )
        response = self._get(provider)
        self.assertContains(response, "couldn't verify")
        self.assertContains(response, "Show on map (not verified)")
        self.assertNotContains(response, "Alternative route avoids")

    def test_route_data_json_script_and_no_server_key(self):
        provider = FakeProvider([candidate(0, ew())])
        response = self._get(provider)
        self.assertContains(response, 'id="route-data"')
        self.assertContains(response, '"coords"')
        self.assertNotContains(response, SERVER)

    def test_missing_origin(self):
        response = self.client.get("/?destination=Vyttila")
        self.assertContains(response, "Add a starting point")

    @override_settings(GOOGLE_MAPS_BROWSER_KEY="")
    def test_no_browser_key_provider_not_called(self):
        provider = FakeProvider([candidate(0, ew())])
        self.mock_get_provider.return_value = provider
        response = self.client.get(
            "/?origin=Edappally&destination=Vyttila"
        )
        self.assertEqual(provider.calls, 0)
        self.assertContains(response, "Route planning needs the map")

    def test_quota_error_rendering(self):
        provider = FakeProvider(error=RoutingError("quota"))
        response = self._get(provider)
        self.assertContains(response, "Routing is busy")

    def test_no_crossings(self):
        self.crossing.is_active = False
        self.crossing.save()
        provider = FakeProvider([candidate(0, ew())])
        response = self._get(provider)
        self.assertContains(response, "No mapped crossings found on this route")

    def test_place_id_included(self):
        provider = FakeProvider([candidate(0, ew())])
        self._get(provider, extra="&origin_place_id=ChIJabc-123")
        self.assertEqual(provider.last_origin.place_id, "ChIJabc-123")

    def test_bad_place_id_falls_back_to_address(self):
        provider = FakeProvider([candidate(0, ew())])
        self._get(provider, extra='&origin_place_id=bad"id<script>')
        self.assertEqual(provider.last_origin.place_id, "")
        self.assertEqual(provider.last_origin.address, "Edappally, Kochi")

    def test_origin_coords_passed_to_provider(self):
        provider = FakeProvider([candidate(0, ew())])
        self._get(
            provider, extra="&origin_lat=10.0261&origin_lng=76.3125"
        )
        self.assertEqual(provider.last_origin.lat, 10.0261)
        self.assertEqual(provider.last_origin.lng, 76.3125)

    def test_place_id_wins_over_coords(self):
        provider = FakeProvider([candidate(0, ew())])
        self._get(
            provider,
            extra="&origin_place_id=ChIJabc&origin_lat=10.0&origin_lng=76.0",
        )
        self.assertEqual(provider.last_origin.place_id, "ChIJabc")
        self.assertIsNone(provider.last_origin.lat)

    def test_invalid_coords_ignored(self):
        provider = FakeProvider([candidate(0, ew())])
        self._get(provider, extra="&origin_lat=999&origin_lng=abc")
        self.assertIsNone(provider.last_origin.lat)
        self.assertIsNone(provider.last_origin.lng)

    def test_coord_hidden_inputs_rendered(self):
        provider = FakeProvider([candidate(0, ew())])
        response = self._get(
            provider, extra="&origin_lat=10.0261&origin_lng=76.3125"
        )
        self.assertContains(response, 'name="origin_lat"')
        self.assertContains(response, 'value="10.0261"')

    def test_destination_coords_passed_to_provider(self):
        provider = FakeProvider([candidate(0, ew())])
        self._get(
            provider, extra="&destination_lat=10.05&destination_lng=76.31"
        )
        self.assertEqual(provider.last_destination.lat, 10.05)
        self.assertEqual(provider.last_destination.lng, 76.31)

    def test_destination_place_id_wins_over_coords(self):
        provider = FakeProvider([candidate(0, ew())])
        self._get(
            provider,
            extra="&destination_place_id=ChIJxyz&destination_lat=10.0&destination_lng=76.0",
        )
        self.assertEqual(provider.last_destination.place_id, "ChIJxyz")
        self.assertIsNone(provider.last_destination.lat)

    def test_invalid_destination_coords_ignored(self):
        provider = FakeProvider([candidate(0, ew())])
        self._get(
            provider, extra="&destination_lat=999&destination_lng=abc"
        )
        self.assertIsNone(provider.last_destination.lat)
        self.assertIsNone(provider.last_destination.lng)

    def test_my_location_without_coords_is_missing_origin(self):
        """The literal 'My location' must never be geocoded."""
        provider = FakeProvider([candidate(0, ew())])
        self.mock_get_provider.return_value = provider
        response = self.client.get(
            "/?origin=My+location&destination=Vyttila%2C+Kochi"
        )
        self.assertEqual(provider.calls, 0)
        self.assertContains(response, "Add a starting point")

    def test_my_location_with_coords_plans(self):
        provider = FakeProvider([candidate(0, ew())])
        self.mock_get_provider.return_value = provider
        self.client.get(
            "/?origin=My+location&origin_lat=10.0261&origin_lng=76.3125"
            "&destination=Vyttila%2C+Kochi"
        )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(provider.last_origin.lat, 10.0261)

    def test_journey_buttons_rendered_per_route(self):
        provider = FakeProvider(
            [candidate(0, ew()), candidate(1, ew(0.00135), labels=())]
        )
        response = self._get(provider)
        self.assertContains(response, 'data-journey-start="r0"')
        self.assertContains(response, 'data-journey-start="r1"')
        self.assertContains(response, 'data-journey-nav="r0"')
        self.assertContains(response, "Start journey")
        self.assertContains(response, "Open in Google Maps")

    def test_format_json_returns_html_and_route_data(self):
        provider = FakeProvider([candidate(0, ew())])
        response = self._get(provider, extra="&format=json")
        self.assertEqual(response["Content-Type"], "application/json")
        body = response.json()
        self.assertEqual(body["route_state"], "planned")
        self.assertIn("data-route-panel", body["html"])
        self.assertIn("routes", body["route_data"])
        self.assertEqual(body["route_data"]["routes"][0]["id"], "r0")
        self.assertIn("coords", body["route_data"]["routes"][0])

    def test_format_json_error_states(self):
        response = self.client.get(
            "/?destination=Vyttila&format=json"
        )
        body = response.json()
        self.assertEqual(body["route_state"], "missing_origin")
        self.assertIn("Add a starting point", body["html"])
        self.assertIsNone(body["route_data"])

        response = self.client.get("/?origin=Edappally&destination=&format=json")
        body = response.json()
        self.assertEqual(body["route_state"], "empty")
        self.assertIn("Add a destination", body["html"])

    def test_format_json_no_params(self):
        response = self.client.get("/?format=json")
        body = response.json()
        self.assertEqual(body["route_state"], "")
        self.assertEqual(body["html"].strip(), "")
        self.assertIsNone(body["route_data"])
