import json

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.test import Client, TestCase
from django.urls import reverse

from incidents.models import CrossingReport
from railways.models import RailwayCrossing


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


class CrossingDetailViewTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.user = get_user_model().objects.create_user(
            "watcher", password="pass1234"
        )
        self.url = reverse("crossing_detail", args=[self.crossing.pk])

    def test_anon_detail_shows_unknown_and_sign_in(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Status unknown")
        self.assertContains(response, "not official railway information")
        self.assertContains(response, "Sign in to report")
        self.assertNotContains(response, "csrfmiddlewaretoken")

    def test_logged_in_detail_shows_report_form(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, 'value="closed"')
        self.assertContains(response, 'value="open"')

    def test_anon_html_post_redirects_to_login(self):
        response = self.client.post(
            reverse("crossing_report_submit", args=[self.crossing.pk]),
            {"state": "closed"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_html_post_success_redirects_with_message(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("crossing_report_submit", args=[self.crossing.pk]),
            {"state": "closed"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], self.url
        )
        self.assertEqual(CrossingReport.objects.count(), 1)
        detail = self.client.get(self.url)
        self.assertContains(detail, "your report was recorded")

    def test_suppressed_crossing_404(self):
        crossing = make_crossing(is_suppressed=True)
        self.assertEqual(
            self.client.get(
                reverse("crossing_detail", args=[crossing.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("api_crossing_status", args=[crossing.pk])
            ).status_code,
            404,
        )
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.post(
                reverse("api_crossing_reports", args=[crossing.pk]),
                {"state": "closed"},
            ).status_code,
            404,
        )

    def test_login_page_renders(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)


class ApiTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.user = get_user_model().objects.create_user(
            "apiuser", password="pass1234"
        )
        self.status_url = reverse(
            "api_crossing_status", args=[self.crossing.pk]
        )
        self.reports_url = reverse(
            "api_crossing_reports", args=[self.crossing.pk]
        )

    def test_status_json_shape_and_privacy(self):
        self.client.force_login(self.user)
        self.client.post(self.reports_url, {"state": "closed"})
        response = self.client.get(self.status_url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["official"])
        self.assertIn("unverified", payload["disclaimer"])
        self.assertEqual(payload["status"]["state"], "closed_reported")
        self.assertEqual(len(payload["recent_reports"]), 1)
        body = json.dumps(payload)
        self.assertNotIn("apiuser", body)
        self.assertNotIn("reporter", body)
        self.assertNotIn("@", body)

    def test_anon_api_post_401(self):
        response = self.client.post(self.reports_url, {"state": "closed"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["error"], "authentication_required"
        )

    def test_csrf_enforced_on_api_post(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(self.reports_url, {"state": "closed"})
        self.assertEqual(response.status_code, 403)

        detail = client.get(
            reverse("crossing_detail", args=[self.crossing.pk])
        )
        token = detail.cookies["csrftoken"].value
        response = client.post(
            self.reports_url,
            {"state": "closed"},
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 201)

    def test_invalid_state_400(self):
        self.client.force_login(self.user)
        response = self.client.post(self.reports_url, {"state": "maybe"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "validation_error")

    def test_invalid_json_400(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.reports_url,
            "not-json{",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_json")

    def test_unknown_crossing_404(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api_crossing_reports", args=[999999]),
            {"state": "closed"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "not_found")

    def test_rate_limited_429(self):
        self.client.force_login(self.user)
        self.client.post(self.reports_url, {"state": "closed"})
        response = self.client.post(self.reports_url, {"state": "open"})
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)
        self.assertEqual(response.json()["error"], "rate_limited")

    def test_get_on_reports_endpoint_405(self):
        self.assertEqual(self.client.get(self.reports_url).status_code, 405)

    def test_duplicate_returns_200(self):
        self.client.force_login(self.user)
        self.client.post(self.reports_url, {"state": "closed"})
        response = self.client.post(self.reports_url, {"state": "closed"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["created"])
