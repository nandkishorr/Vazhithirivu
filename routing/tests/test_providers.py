import io
import json
import urllib.error
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from routing.providers import (
    FIELD_MASK,
    GoogleRoutesProvider,
    RoutingError,
    Waypoint,
    get_provider,
)

KEY = "test-server-key-xyz"

ROUTES_BODY = {
    "routes": [
        {
            "distanceMeters": 9000,
            "duration": "900s",
            "staticDuration": "850s",
            "description": "Other road",
            "routeLabels": [],
            "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
        },
        {
            "distanceMeters": 7312,
            "duration": "672s",
            "staticDuration": "650s",
            "description": "NH 66",
            "routeLabels": ["DEFAULT_ROUTE"],
            "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
            "warnings": ["Something"],
        },
    ]
}


def _response(body):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return Resp(json.dumps(body).encode())


def _http_error(code):
    return urllib.error.HTTPError(
        "https://x", code, "err", {}, io.BytesIO(b"{}")
    )


class GoogleRoutesProviderTests(SimpleTestCase):
    def setUp(self):
        self.provider = GoogleRoutesProvider(
            api_key=KEY, timeout=8, routing_preference="TRAFFIC_UNAWARE"
        )

    def _request(self, mock_urlopen):
        return mock_urlopen.call_args[0][0]

    @patch("routing.providers.urllib.request.urlopen")
    def test_request_headers_and_body(self, mock_urlopen):
        mock_urlopen.return_value = _response(ROUTES_BODY)
        self.provider.compute_routes(
            Waypoint(place_id="ChIJ123"), Waypoint(address="Vyttila, Kochi")
        )
        req = self._request(mock_urlopen)
        self.assertEqual(req.get_header("X-goog-api-key"), KEY)
        self.assertEqual(req.get_header("X-goog-fieldmask"), FIELD_MASK)
        body = json.loads(req.data)
        self.assertEqual(body["origin"], {"placeId": "ChIJ123"})
        self.assertEqual(body["destination"], {"address": "Vyttila, Kochi"})
        self.assertTrue(body["computeAlternativeRoutes"])
        self.assertEqual(body["polylineQuality"], "HIGH_QUALITY")
        self.assertEqual(body["travelMode"], "DRIVE")
        self.assertNotIn("routingPreference", body)
        self.assertEqual(
            mock_urlopen.call_args[1]["timeout"], 8
        )

    @patch("routing.providers.urllib.request.urlopen")
    def test_latlng_waypoint_body(self, mock_urlopen):
        mock_urlopen.return_value = _response(ROUTES_BODY)
        self.provider.compute_routes(
            Waypoint(lat=10.0261, lng=76.3125),
            Waypoint(address="Vyttila, Kochi"),
        )
        body = json.loads(self._request(mock_urlopen).data)
        self.assertEqual(
            body["origin"],
            {"location": {"latLng": {"latitude": 10.0261, "longitude": 76.3125}}},
        )

    def test_place_id_takes_precedence_over_latlng(self):
        wp = Waypoint(place_id="ChIJ123", lat=10.0, lng=76.0)
        self.assertEqual(wp.as_api(), {"placeId": "ChIJ123"})

    @patch("routing.providers.urllib.request.urlopen")
    def test_traffic_aware_adds_preference(self, mock_urlopen):
        provider = GoogleRoutesProvider(
            api_key=KEY, timeout=8, routing_preference="TRAFFIC_AWARE"
        )
        mock_urlopen.return_value = _response(ROUTES_BODY)
        provider.compute_routes(
            Waypoint(address="a"), Waypoint(address="b")
        )
        body = json.loads(self._request(mock_urlopen).data)
        self.assertEqual(body["routingPreference"], "TRAFFIC_AWARE")

    @patch("routing.providers.urllib.request.urlopen")
    def test_parsing_and_default_route_first(self, mock_urlopen):
        mock_urlopen.return_value = _response(ROUTES_BODY)
        candidates = self.provider.compute_routes(
            Waypoint(address="a"), Waypoint(address="b")
        )
        self.assertEqual(len(candidates), 2)
        first = candidates[0]
        self.assertEqual(first.index, 0)
        self.assertIn("DEFAULT_ROUTE", first.labels)
        self.assertEqual(first.distance_m, 7312)
        self.assertEqual(first.duration_s, 672)
        self.assertEqual(first.static_duration_s, 650)
        self.assertEqual(first.description, "NH 66")
        self.assertIsNotNone(first.geometry)
        self.assertEqual(candidates[1].index, 1)

    @patch("routing.providers.urllib.request.urlopen")
    def test_empty_routes_is_no_route(self, mock_urlopen):
        mock_urlopen.return_value = _response({})
        with self.assertRaises(RoutingError) as ctx:
            self.provider.compute_routes(
                Waypoint(address="a"), Waypoint(address="b")
            )
        self.assertEqual(ctx.exception.code, "no_route")

    def _assert_code(self, side_effect, code):
        with patch(
            "routing.providers.urllib.request.urlopen",
            side_effect=side_effect,
        ):
            with self.assertRaises(RoutingError) as ctx:
                self.provider.compute_routes(
                    Waypoint(address="a"), Waypoint(address="b")
                )
            self.assertEqual(ctx.exception.code, code)
            self.assertNotIn(KEY, str(ctx.exception))

    def test_http_400(self):
        self._assert_code(_http_error(400), "invalid_request")

    def test_http_403(self):
        self._assert_code(_http_error(403), "auth")

    def test_http_401(self):
        self._assert_code(_http_error(401), "auth")

    def test_http_429(self):
        self._assert_code(_http_error(429), "quota")

    def test_http_500(self):
        self._assert_code(_http_error(500), "provider_error")

    def test_url_error(self):
        self._assert_code(
            urllib.error.URLError("connection refused"), "timeout"
        )

    def test_socket_timeout(self):
        import socket

        self._assert_code(socket.timeout(), "timeout")

    def test_bad_json(self):
        class Bad:
            def read(self):
                return b"not json"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch(
            "routing.providers.urllib.request.urlopen", return_value=Bad()
        ):
            with self.assertRaises(RoutingError) as ctx:
                self.provider.compute_routes(
                    Waypoint(address="a"), Waypoint(address="b")
                )
            self.assertEqual(ctx.exception.code, "provider_error")
            self.assertNotIn(KEY, str(ctx.exception))


class GetProviderTests(SimpleTestCase):
    @override_settings(GOOGLE_MAPS_SERVER_KEY="", ROUTING_PROVIDER="google")
    def test_not_configured_without_key(self):
        with self.assertRaises(RoutingError) as ctx:
            get_provider()
        self.assertEqual(ctx.exception.code, "not_configured")

    @override_settings(
        GOOGLE_MAPS_SERVER_KEY="k",
        ROUTING_PROVIDER="google",
        ROUTING_TIMEOUT_SECONDS=8,
        ROUTING_GOOGLE_ROUTING_PREFERENCE="TRAFFIC_UNAWARE",
    )
    def test_google_provider(self):
        provider = get_provider()
        self.assertIsInstance(provider, GoogleRoutesProvider)

    @override_settings(GOOGLE_MAPS_SERVER_KEY="k", ROUTING_PROVIDER="other")
    def test_unknown_provider(self):
        with self.assertRaises(RoutingError):
            get_provider()
