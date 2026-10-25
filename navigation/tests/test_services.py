"""Session lifecycle services, config checks and the purge command."""
from datetime import timedelta
from io import StringIO

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from navigation.checks import navigation_configuration
from navigation.models import JourneySession
from navigation.services import (
    TooSoon,
    end_session,
    get_session,
    nearby_crossings,
    record_position_check,
    start_session,
)
from railways.models import RailwayCrossing


class SessionServiceTests(TestCase):
    def test_start_and_get_session(self):
        session = start_session()
        self.assertIsNone(session.ended_at)
        self.assertEqual(get_session(session.pk).pk, session.pk)
        self.assertIsNone(get_session("00000000-0000-0000-0000-0000000000000000"))

    def test_end_session_idempotent(self):
        session = start_session()
        end_session(session)
        first = session.ended_at
        self.assertIsNotNone(first)
        end_session(session)
        self.assertEqual(session.ended_at, first)

    def test_is_active_rules(self):
        now = timezone.now()
        session = start_session(now=now)
        self.assertTrue(session.is_active(now))
        session.ended_at = now
        self.assertFalse(session.is_active(now))
        expired = JourneySession(
            created_at=now - timedelta(hours=7)
        )
        self.assertFalse(expired.is_active(now))

    def test_record_position_check_too_soon(self):
        now = timezone.now()
        session = start_session(now=now)
        record_position_check(session, now=now)
        with self.assertRaises(TooSoon) as ctx:
            record_position_check(
                session, now=now + timedelta(seconds=1)
            )
        self.assertGreater(ctx.exception.retry_after_seconds, 0)
        record_position_check(
            session,
            now=now + timedelta(seconds=11),
        )

    @override_settings(NAV_NEARBY_LIMIT=2)
    def test_nearby_crossings_nearest_first_and_capped(self):
        for i, offset in enumerate((0.004, 0.001, 0.003, 0.002)):
            RailwayCrossing.objects.create(
                source="manual",
                osm_type="",
                osm_id=None,
                location=Point(76.30 + offset, 10.0, srid=4326),
                railway_value="level_crossing",
            )
        rows = nearby_crossings(10.0, 76.30)
        self.assertEqual(len(rows), 2)  # NAV_NEARBY_LIMIT
        self.assertEqual(
            [round(d) for _, d, _ in rows],
            sorted(round(d) for _, d, _ in rows),
        )
        for crossing, dist, status in rows:
            self.assertIsNotNone(status.state)


class NavigationConfigCheckTests(TestCase):
    @override_settings(NAV_ALERT_RADIUS_M=700.0, NAV_NEARBY_RADIUS_M=600.0)
    def test_alert_radius_above_nearby_is_error(self):
        problems = navigation_configuration(None)
        self.assertTrue(
            any(p.id == "navigation.E001" for p in problems)
        )

    @override_settings(NAV_MIN_UPDATE_SECONDS=0)
    def test_bad_limits_error(self):
        problems = navigation_configuration(None)
        self.assertTrue(
            any(p.id == "navigation.E002" for p in problems)
        )

    def test_defaults_clean(self):
        self.assertEqual(navigation_configuration(None), [])


class PurgeNavigationSessionsTests(TestCase):
    def test_purge_deletes_old_keeps_recent(self):
        now = timezone.now()
        old = JourneySession.objects.create(
            created_at=now - timedelta(days=40)
        )
        recent = JourneySession.objects.create(created_at=now)
        out = StringIO()
        call_command("purge_navigation_sessions", days=30, stdout=out)
        self.assertFalse(
            JourneySession.objects.filter(pk=old.pk).exists()
        )
        self.assertTrue(
            JourneySession.objects.filter(pk=recent.pk).exists()
        )
        self.assertIn("Deleted 1 session", out.getvalue())

    def test_dry_run_deletes_nothing(self):
        JourneySession.objects.create(
            created_at=timezone.now() - timedelta(days=40)
        )
        call_command(
            "purge_navigation_sessions", days=30, dry_run=True, stdout=StringIO()
        )
        self.assertEqual(JourneySession.objects.count(), 1)
