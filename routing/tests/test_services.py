from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import LineString, Point
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from incidents.models import CrossingReport
from railways.models import RailwayCrossing, RailwayTrack
from routing.providers import RouteCandidate, RoutingError, Waypoint
from routing.services import plan_route

LNG, LAT = 76.30, 10.00


def ew(offset=0.0):
    return LineString(
        (LNG - 0.01, LAT + offset), (LNG + 0.01, LAT + offset), srid=4326
    )


def ns(offset=0.0):
    """N-S track crossing the latitude at the given lng offset."""
    return LineString(
        (LNG + offset, LAT - 0.01), (LNG + offset, LAT + 0.01), srid=4326
    )


def candidate(index, geometry, duration=600, distance=6000, labels=("DEFAULT_ROUTE",)):
    return RouteCandidate(
        index=index,
        geometry=geometry,
        distance_m=distance,
        duration_s=duration,
        static_duration_s=duration,
        description="",
        labels=labels,
        warnings=(),
    )


class FakeProvider:
    name = "fake"
    attribution = "Fake routes"
    traffic_aware = False
    supports_exclusion = False
    calls = 0

    def __init__(self, routes=(), error=None):
        self._routes = list(routes)
        self._error = error
        FakeProvider.calls = 0

    def compute_routes(self, origin, destination):
        FakeProvider.calls += 1
        if self._error:
            raise self._error
        return list(self._routes)


class PlanRouteTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("reporter", password="x")
        self.crossing = RailwayCrossing.objects.create(
            location=Point(LNG, LAT, srid=4326),
            railway_value="level_crossing",
            source="manual",
            name="Main crossing",
        )
        self.track = RailwayTrack.objects.create(
            geometry=ns(), railway_value="rail", source="manual"
        )
        self.origin = Waypoint(address="a")
        self.destination = Waypoint(address="b")
        self._patcher = patch("routing.providers.get_provider")
        self.mock_get_provider = self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _plan(self, provider, client_key="client-1"):
        self.mock_get_provider.return_value = provider
        return plan_route(self.origin, self.destination, client_key)

    def _closed_report(self, crossing=None, user=None, age_minutes=5):
        now = timezone.now() - timedelta(minutes=age_minutes)
        return CrossingReport.objects.create(
            crossing=crossing or self.crossing,
            reported_state=CrossingReport.STATE_CLOSED,
            reporter=user or self.user,
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )

    def test_no_reports_no_warning_alternatives_not_evaluated(self):
        provider = FakeProvider([candidate(0, ew()), candidate(1, ew(0.002))])
        plan = self._plan(provider)
        self.assertTrue(plan.ok)
        self.assertIsNone(plan.warning_level)
        self.assertEqual(plan.blocking, ())
        primary = plan.routes[0]
        self.assertEqual(primary.counts.get("unknown"), 1)
        for route in plan.routes[1:]:
            self.assertIsNone(route.verification)

    def test_fresh_closed_on_route_verified_alternative(self):
        self._closed_report()
        # Alternative ~150 m north of the crossing (clearance > 100 m).
        provider = FakeProvider(
            [candidate(0, ew()), candidate(1, ew(0.00135), labels=())]
        )
        plan = self._plan(provider)
        self.assertTrue(plan.ok)
        self.assertEqual(plan.warning_level, "closed_on_route")
        self.assertEqual(len(plan.blocking), 1)
        self.assertEqual(plan.blocking[0].crossing.match, "on_route")
        alt = plan.routes[1]
        self.assertEqual(alt.verification, "verified")
        self.assertTrue(plan.has_verified_alternative)
        self.assertGreater(alt.avoided_clearance_m, 100)

    def test_alternative_through_crossing_passes(self):
        self._closed_report()
        provider = FakeProvider(
            [candidate(0, ew()), candidate(1, ew(0.00005), labels=())]
        )
        plan = self._plan(provider)
        self.assertEqual(plan.routes[1].verification, "passes")
        self.assertFalse(plan.has_verified_alternative)

    def test_missing_distance_is_unverifiable_not_verified(self):
        """A blocking crossing with no measured distance fails closed."""
        self._closed_report()
        provider = FakeProvider(
            [candidate(0, ew()), candidate(1, ew(0.00135), labels=())]
        )
        with patch(
            "routing.services.distances_to_crossings", return_value={}
        ):
            plan = self._plan(provider)
        self.assertEqual(plan.routes[1].verification, "unverifiable")
        self.assertFalse(plan.has_verified_alternative)

    def test_alternative_70m_away_uncertain(self):
        self._closed_report()
        provider = FakeProvider(
            [candidate(0, ew()), candidate(1, ew(0.00063), labels=())]
        )
        plan = self._plan(provider)
        self.assertEqual(plan.routes[1].verification, "uncertain")

    def test_single_route_no_alternative(self):
        self._closed_report()
        provider = FakeProvider([candidate(0, ew())])
        plan = self._plan(provider)
        self.assertEqual(len(plan.routes), 1)
        self.assertEqual(plan.warning_level, "closed_on_route")
        self.assertFalse(plan.has_verified_alternative)

    def test_alternative_with_own_closed_crossing_passes(self):
        self._closed_report()
        # Second crossing ~1.5 km north, on the alternative's line.
        other = RailwayCrossing.objects.create(
            location=Point(LNG, LAT + 0.00135, srid=4326),
            railway_value="level_crossing",
            source="manual",
            name="Far crossing",
        )
        # The N-S track already crosses the alternative line at `other`.
        self._closed_report(crossing=other)
        provider = FakeProvider(
            [candidate(0, ew()), candidate(1, ew(0.00135), labels=())]
        )
        plan = self._plan(provider)
        self.assertEqual(plan.routes[1].verification, "passes")

    def test_stale_report_no_closed_warning(self):
        self._closed_report(age_minutes=30)  # expired (15 min fresh window)
        provider = FakeProvider([candidate(0, ew()), candidate(1, ew(0.002))])
        plan = self._plan(provider)
        self.assertIsNone(plan.warning_level)
        self.assertEqual(plan.routes[0].counts.get("stale"), 1)
        self.assertFalse(plan.has_verified_alternative)

    def test_conflicting_on_route(self):
        user2 = get_user_model().objects.create_user("reporter2", password="x")
        self._closed_report(age_minutes=4)
        CrossingReport.objects.create(
            crossing=self.crossing,
            reported_state=CrossingReport.STATE_OPEN,
            reporter=user2,
            created_at=timezone.now() - timedelta(minutes=4),
            expires_at=timezone.now() + timedelta(minutes=11),
        )
        provider = FakeProvider([candidate(0, ew())])
        plan = self._plan(provider)
        self.assertEqual(plan.warning_level, "conflicting_on_route")

    def test_provider_error_passes_through(self):
        provider = FakeProvider(error=RoutingError("quota"))
        plan = self._plan(provider)
        self.assertFalse(plan.ok)
        self.assertEqual(plan.error, "quota")

    def test_get_provider_error_passes_through(self):
        self.mock_get_provider.side_effect = RoutingError("not_configured")
        plan = plan_route(self.origin, self.destination, "client-1")
        self.assertFalse(plan.ok)
        self.assertEqual(plan.error, "not_configured")

    @override_settings(ROUTING_MAX_REQUESTS_PER_HOUR=2)
    def test_throttle_rate_limited(self):
        provider = FakeProvider([candidate(0, ew())])
        self._plan(provider)
        self._plan(provider)
        plan = self._plan(provider)
        self.assertFalse(plan.ok)
        self.assertEqual(plan.error, "rate_limited")
        self.assertEqual(FakeProvider.calls, 2)

    def test_derive_statuses_called_once(self):
        self._closed_report()
        provider = FakeProvider(
            [candidate(0, ew()), candidate(1, ew(0.00135), labels=())]
        )
        with patch(
            "routing.services.incident_services.derive_statuses",
            wraps=__import__(
                "incidents.services", fromlist=["derive_statuses"]
            ).derive_statuses,
        ) as mock_derive:
            self._plan(provider)
            self.assertEqual(mock_derive.call_count, 1)
