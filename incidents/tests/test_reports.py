from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from incidents import services
from incidents.models import CrossingReport
from railways.models import RailwayCrossing

NOW = timezone.now()


def make_crossing(**kwargs):
    defaults = {
        "source": "manual",
        "osm_type": "",
        "osm_id": None,
        "location": Point(76.25, 9.95, srid=4326),
        "railway_value": "level_crossing",
    }
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


class CreateReportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("reporter")
        self.crossing = make_crossing()

    def test_create_sets_source_and_expiry(self):
        report, created = services.create_report(
            self.user, self.crossing, "closed", now=NOW
        )
        self.assertTrue(created)
        self.assertEqual(report.source, "community")
        self.assertEqual(report.reporter, self.user)
        self.assertEqual(report.created_at, NOW)
        self.assertEqual(
            report.expires_at,
            NOW + timedelta(minutes=settings.REPORT_FRESH_MINUTES),
        )

    def test_duplicate_within_window_returns_existing(self):
        report, created = services.create_report(
            self.user, self.crossing, "closed", now=NOW
        )
        again, again_created = services.create_report(
            self.user, self.crossing, "closed", now=NOW + timedelta(seconds=30)
        )
        self.assertFalse(again_created)
        self.assertEqual(again.pk, report.pk)
        self.assertEqual(CrossingReport.objects.count(), 1)

    def test_flip_within_min_seconds_is_rate_limited(self):
        services.create_report(self.user, self.crossing, "closed", now=NOW)
        with self.assertRaises(services.RateLimited):
            services.create_report(
                self.user, self.crossing, "open", now=NOW + timedelta(seconds=10)
            )

    def test_hourly_limit(self):
        # 170s spacing: above the 2-minute duplicate window, and all 20
        # reports stay inside the 1-hour window when the 21st is created.
        for i in range(settings.REPORT_MAX_PER_HOUR):
            services.create_report(
                self.user,
                self.crossing,
                "closed",
                now=NOW + timedelta(seconds=i * 170),
            )
        with self.assertRaises(services.RateLimited) as ctx:
            services.create_report(
                self.user,
                self.crossing,
                "closed",
                now=NOW + timedelta(seconds=20 * 170),
            )
        self.assertGreater(ctx.exception.retry_after_seconds, 0)

    def test_inactive_crossing_rejected(self):
        crossing = make_crossing(is_active=False)
        with self.assertRaises(services.ReportNotAllowed):
            services.create_report(self.user, crossing, "closed", now=NOW)

    def test_suppressed_crossing_rejected(self):
        crossing = make_crossing(is_suppressed=True)
        with self.assertRaises(services.ReportNotAllowed):
            services.create_report(self.user, crossing, "closed", now=NOW)

    def test_anonymous_user_rejected(self):
        with self.assertRaises(services.ReportNotAllowed):
            services.create_report(
                AnonymousUser(), self.crossing, "closed", now=NOW
            )
