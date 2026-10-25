"""Journey-session API: start / position check / end (ADR-017)."""
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from incidents.models import CrossingReport
from navigation.models import JourneySession
from railways.models import RailwayCrossing

LNG, LAT = 76.30, 10.00


def make_crossing(**kwargs):
    defaults = dict(
        source="manual",
        osm_type="",
        osm_id=None,
        location=Point(LNG, LAT, srid=4326),
        railway_value="level_crossing",
    )
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


def make_report(crossing, user, state, minutes=15):
    now = timezone.now()
    return CrossingReport.objects.create(
        crossing=crossing,
        reporter=user,
        reported_state=state,
        source=CrossingReport.SOURCE_COMMUNITY,
        created_at=now,
        expires_at=now + timedelta(minutes=minutes),
    )


def start_session(client):
    response = client.post(reverse("api_navigation_start"))
    assert response.status_code == 201
    return JourneySession.objects.get(pk=response.json()["session"]["id"])


class StartSessionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def test_start_returns_session_and_config(self):
        response = self.client.post(reverse("api_navigation_start"))
        self.assertEqual(response.status_code, 201)
        body = response.json()
        session = JourneySession.objects.get()
        self.assertEqual(body["session"]["id"], str(session.pk))
        self.assertIs(body["session"]["ended"], False)
        self.assertIn("expires_at", body["session"])
        self.assertEqual(
            body["config"]["alert_radius_m"], settings.NAV_ALERT_RADIUS_M
        )
        self.assertEqual(
            body["config"]["nearby_radius_m"],
            settings.NAV_NEARBY_RADIUS_M,
        )
        self.assertIn("never stored", body["location_policy"])
        self.assertIs(body["official"], False)
        self.assertIn("not official", body["disclaimer"])

    def test_get_rejected(self):
        self.assertEqual(
            self.client.get(reverse("api_navigation_start")).status_code,
            405,
        )

    @override_settings(NAV_MAX_SESSIONS_PER_HOUR=2)
    def test_start_throttled_per_client(self):
        self.client.post(reverse("api_navigation_start"))
        self.client.post(reverse("api_navigation_start"))
        response = self.client.post(reverse("api_navigation_start"))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "rate_limited")


class PositionCheckTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = get_user_model().objects.create_user("rep")
        self.session = JourneySession.objects.create()

    def _url(self, session=None):
        return reverse(
            "api_navigation_position",
            args=[(session or self.session).pk],
        )

    def _post(self, lat=LAT, lng=LNG, session=None):
        return self.client.post(
            self._url(session),
            data=json.dumps({"lat": lat, "lng": lng}),
            content_type="application/json",
        )

    def test_alerts_on_nearby_closed_crossing(self):
        crossing = make_crossing(name="Gate A")
        make_report(crossing, self.user, CrossingReport.STATE_CLOSED)
        response = self._post()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["alerts"]), 1)
        alert = body["alerts"][0]
        self.assertEqual(alert["id"], crossing.pk)
        self.assertEqual(alert["status"]["state"], "closed_reported")
        self.assertIs(alert["alert"], True)
        self.assertLess(alert["distance_m"], 50)
        self.assertFalse(alert["status"]["simulated"])
        self.assertEqual(
            body["alert_radius_m"], settings.NAV_ALERT_RADIUS_M
        )
        self.assertIn("OpenStreetMap contributors", body["attribution"])
        self.assertIs(body["official"], False)
        self.assertIn("not official", body["disclaimer"])

    def test_open_report_is_not_an_alert(self):
        crossing = make_crossing(name="Open gate")
        make_report(crossing, self.user, CrossingReport.STATE_OPEN)
        body = self._post().json()
        self.assertEqual(body["alerts"], [])
        entry = body["crossings"][0]
        self.assertEqual(entry["status"]["state"], "open_reported")
        self.assertIs(entry["alert"], False)

    @override_settings(NAV_ALERT_RADIUS_M=300.0, NAV_NEARBY_RADIUS_M=600.0)
    def test_closed_beyond_alert_radius_lists_but_doesnt_alert(self):
        crossing = make_crossing(
            name="Mid gate",
            location=Point(LNG + 0.0045, LAT, srid=4326),  # ~500 m
        )
        make_report(crossing, self.user, CrossingReport.STATE_CLOSED)
        body = self._post().json()
        self.assertEqual(len(body["crossings"]), 1)
        entry = body["crossings"][0]
        self.assertEqual(entry["status"]["state"], "closed_reported")
        self.assertIs(entry["alert"], False)
        self.assertEqual(body["alerts"], [])

    def test_unknown_crossing_reports_no_alert(self):
        make_crossing(name="No reports")
        body = self._post().json()
        self.assertEqual(body["alerts"], [])
        self.assertEqual(body["crossings"][0]["status"]["state"], "unknown")

    def test_crossings_ordered_nearest_first(self):
        far = make_crossing(
            name="Far", location=Point(LNG + 0.004, LAT, srid=4326)
        )
        near = make_crossing(
            name="Near", location=Point(LNG + 0.001, LAT, srid=4326)
        )
        body = self._post().json()
        self.assertEqual(
            [c["id"] for c in body["crossings"]], [near.pk, far.pk]
        )

    def test_inactive_and_suppressed_excluded(self):
        make_crossing(is_active=False)
        make_crossing(is_suppressed=True)
        body = self._post().json()
        self.assertEqual(body["crossings"], [])

    def test_min_interval_rate_limit(self):
        self.assertEqual(self._post().status_code, 200)
        response = self._post()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["error"], "too_fast")
        self.assertIn("retry_after_seconds", response.json())
        self.assertIn("Retry-After", response)

    @override_settings(NAV_MIN_UPDATE_SECONDS=0)
    def test_second_check_allowed_without_interval(self):
        self.assertEqual(self._post().status_code, 200)
        self.assertEqual(self._post().status_code, 200)

    def test_invalid_inputs(self):
        response = self.client.post(
            self._url(), data="not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_json")
        response = self.client.post(
            self._url(),
            data=json.dumps([1, 2]),
            content_type="application/json",
        )
        self.assertEqual(response.json()["error"], "invalid_json")
        for payload in (
            {"lat": "north", "lng": LNG},
            {"lat": 95, "lng": LNG},
            {"lat": LAT, "lng": 200},
            {"lat": LAT},
        ):
            response = self.client.post(
                self._url(),
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(
                response.json()["error"],
                "invalid_position",
                msg=str(payload),
            )

    def test_unknown_session_404(self):
        response = self.client.post(
            reverse("api_navigation_position", args=[uuid.uuid4()]),
            data=json.dumps({"lat": LAT, "lng": LNG}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "not_found")

    def test_ended_session_410(self):
        session = JourneySession.objects.create(ended_at=timezone.now())
        response = self._post(session=session)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["error"], "session_ended")

    def test_expired_session_410(self):
        session = JourneySession.objects.create(
            created_at=timezone.now()
            - timedelta(hours=settings.NAV_SESSION_MAX_HOURS + 1)
        )
        self.assertEqual(self._post(session=session).status_code, 410)

    def test_position_never_persisted(self):
        self._post(lat=LAT + 0.01, lng=LNG + 0.01)
        session = JourneySession.objects.get(pk=self.session.pk)
        self.assertIsNotNone(session.last_position_check_at)
        # The session schema has no coordinate columns at all (ADR-017).
        self.assertEqual(
            {f.name for f in session._meta.fields},
            {"id", "created_at", "ended_at", "last_position_check_at"},
        )

    def test_get_rejected(self):
        self.assertEqual(self.client.get(self._url()).status_code, 405)


class EndSessionTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_end_is_idempotent(self):
        session = JourneySession.objects.create()
        url = reverse("api_navigation_end", args=[session.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["ended"], True)
        session.refresh_from_db()
        self.assertIsNotNone(session.ended_at)
        first_ended_at = session.ended_at
        response = self.client.post(url)
        self.assertIs(response.json()["ended"], True)
        session.refresh_from_db()
        self.assertEqual(session.ended_at, first_ended_at)

    def test_end_unknown_404(self):
        response = self.client.post(
            reverse("api_navigation_end", args=[uuid.uuid4()])
        )
        self.assertEqual(response.status_code, 404)

    def test_end_blocks_position_checks(self):
        session = JourneySession.objects.create()
        self.client.post(reverse("api_navigation_end", args=[session.pk]))
        response = self.client.post(
            reverse("api_navigation_position", args=[session.pk]),
            data=json.dumps({"lat": LAT, "lng": LNG}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 410)
