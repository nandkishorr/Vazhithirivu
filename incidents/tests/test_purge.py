from datetime import timedelta
from io import StringIO

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from incidents.models import CrossingReport
from railways.models import RailwayCrossing


class PurgeCommandTests(TestCase):
    def setUp(self):
        self.crossing = RailwayCrossing.objects.create(
            source="manual",
            osm_type="",
            osm_id=None,
            location=Point(76.25, 9.95, srid=4326),
            railway_value="level_crossing",
        )

    def _report(self, age_days):
        created = timezone.now() - timedelta(days=age_days)
        return CrossingReport.objects.create(
            crossing=self.crossing,
            reported_state="closed",
            created_at=created,
            expires_at=created + timedelta(minutes=15),
        )

    def test_old_reports_deleted_recent_kept(self):
        self._report(age_days=45)
        recent = self._report(age_days=1)
        call_command("purge_crossing_reports", stdout=StringIO())
        remaining = list(CrossingReport.objects.values_list("pk", flat=True))
        self.assertEqual(remaining, [recent.pk])

    def test_dry_run_deletes_nothing(self):
        self._report(age_days=45)
        call_command("purge_crossing_reports", "--dry-run", stdout=StringIO())
        self.assertEqual(CrossingReport.objects.count(), 1)
