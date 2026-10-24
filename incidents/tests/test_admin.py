from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from incidents.models import CrossingReport
from railways.models import RailwayCrossing


def make_crossing():
    return RailwayCrossing.objects.create(
        source="manual",
        osm_type="",
        osm_id=None,
        location=Point(76.25, 9.95, srid=4326),
        railway_value="level_crossing",
    )


def make_report(crossing, user):
    now = timezone.now()
    return CrossingReport.objects.create(
        crossing=crossing,
        reporter=user,
        reported_state="closed",
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )


class CrossingReportAdminTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_superuser(
            "admin", password="pass1234"
        )
        self.plain = get_user_model().objects.create_user(
            "plain", password="pass1234"
        )
        self.report = make_report(make_crossing(), self.plain)
        self.changelist = reverse("admin:incidents_crossingreport_changelist")

    def test_hide_action_sets_hidden_and_moderator(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            self.changelist,
            {
                "action": "hide_reports",
                "_selected_action": [self.report.pk],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.moderation_status, "hidden")
        self.assertEqual(self.report.moderated_by, self.staff)
        self.assertIsNotNone(self.report.moderated_at)

    def test_non_staff_redirected_to_admin_login(self):
        self.client.force_login(self.plain)
        response = self.client.get(self.changelist)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_add_view_forbidden(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("admin:incidents_crossingreport_add")
        )
        self.assertEqual(response.status_code, 403)
