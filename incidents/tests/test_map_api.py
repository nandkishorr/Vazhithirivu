from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from incidents.models import CrossingReport
from railways.models import RailwayCrossing

BBOX = "76.0,9.0,77.0,10.0"
NOW = timezone.now()


def make_crossing(**kwargs):
    defaults = {
        "source": "osm",
        "osm_type": "node",
        "osm_id": 1,
        "location": Point(76.5, 9.5, srid=4326),
        "railway_value": "level_crossing",
    }
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


def make_report(crossing, user, state, age_seconds=0, moderation="visible"):
    created = NOW - timedelta(seconds=age_seconds)
    return CrossingReport.objects.create(
        crossing=crossing,
        reporter=user,
        reported_state=state,
        source=CrossingReport.SOURCE_COMMUNITY,
        created_at=created,
        expires_at=created + timedelta(minutes=settings.REPORT_FRESH_MINUTES),
        moderation_status=moderation,
    )


class CrossingsInBboxApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user("reporter-xyz")

    def test_payload_shape_and_states(self):
        unknown_c = make_crossing(osm_id=11, name="A crossing")
        closed_c = make_crossing(osm_id=12)
        make_report(closed_c, self.user, "closed", age_seconds=60)
        stale_c = make_crossing(osm_id=13)
        make_report(stale_c, self.user, "open", age_seconds=20 * 60)

        response = self.client.get("/api/crossings/", {"bbox": BBOX})
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["bbox"], [76.0, 9.0, 77.0, 10.0])
        self.assertEqual(data["count"], 3)
        self.assertEqual(data["limit"], settings.MAP_CROSSINGS_LIMIT)
        self.assertIs(data["truncated"], False)
        self.assertIs(data["official"], False)
        self.assertIn("not official", data["disclaimer"])
        self.assertIn("OpenStreetMap contributors", data["attribution"])

        self.assertEqual(len(data["crossings"]), 3)
        by_id = {c["id"]: c for c in data["crossings"]}
        self.assertEqual(
            set(by_id), {unknown_c.pk, closed_c.pk, stale_c.pk}
        )

        entry = by_id[unknown_c.pk]
        self.assertEqual(
            set(entry),
            {
                "id",
                "lat",
                "lng",
                "name",
                "barrier",
                "source",
                "osm_type",
                "osm_id",
                "status",
            },
        )
        self.assertAlmostEqual(entry["lat"], 9.5)
        self.assertAlmostEqual(entry["lng"], 76.5)
        self.assertEqual(entry["name"], "A crossing")
        self.assertEqual(
            set(entry["status"]),
            {
                "state",
                "label",
                "last_report_at",
                "last_report_age_seconds",
            },
        )

        self.assertEqual(by_id[unknown_c.pk]["status"]["state"], "unknown")
        self.assertEqual(
            by_id[closed_c.pk]["status"]["state"], "closed_reported"
        )
        self.assertEqual(
            by_id[closed_c.pk]["status"]["label"], "Reported closed"
        )
        self.assertEqual(by_id[stale_c.pk]["status"]["state"], "stale")

    def test_hidden_reports_ignored_and_reporter_absent(self):
        crossing = make_crossing(osm_id=21)
        make_report(
            crossing,
            self.user,
            "closed",
            age_seconds=60,
            moderation="hidden",
        )
        response = self.client.get("/api/crossings/", {"bbox": BBOX})
        data = response.json()
        self.assertEqual(
            data["crossings"][0]["status"]["state"], "unknown"
        )
        body = response.content.decode()
        self.assertNotIn("reporter", body)
        self.assertNotIn("reporter-xyz", body)

    def test_inactive_suppressed_outside_excluded(self):
        make_crossing(osm_id=31, is_active=False)
        make_crossing(osm_id=32, is_suppressed=True)
        make_crossing(osm_id=33, location=Point(75.0, 9.5, srid=4326))
        response = self.client.get("/api/crossings/", {"bbox": BBOX})
        self.assertEqual(response.json()["count"], 0)
        self.assertEqual(response.json()["crossings"], [])

    def test_missing_and_invalid_bbox(self):
        for params in ({}, {"bbox": ""}, {"bbox": "a,b,c,d"}, {"bbox": "1,2,3"}):
            with self.subTest(params=params):
                response = self.client.get("/api/crossings/", params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"error": "invalid_bbox"})

    def test_too_large_bbox(self):
        response = self.client.get("/api/crossings/", {"bbox": "0,0,2,2"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "error": "bbox_too_large",
                "max_span_degrees": settings.MAP_BBOX_MAX_SPAN_DEG,
            },
        )

    def test_post_not_allowed(self):
        self.assertEqual(
            self.client.post("/api/crossings/", {"bbox": BBOX}).status_code,
            405,
        )

    @override_settings(MAP_CROSSINGS_LIMIT=2)
    def test_limit_truncates(self):
        for i in range(3):
            make_crossing(osm_id=40 + i)
        response = self.client.get("/api/crossings/", {"bbox": BBOX})
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["limit"], 2)
        self.assertIs(data["truncated"], True)
        self.assertEqual(len(data["crossings"]), 2)

    def test_never_cached(self):
        response = self.client.get("/api/crossings/", {"bbox": BBOX})
        cache_control = response["Cache-Control"]
        self.assertIn("no-cache", cache_control)
        self.assertIn("no-store", cache_control)

    def test_crossing_name_round_trips_via_json(self):
        make_crossing(osm_id=50, name="</script><b>x")
        response = self.client.get("/api/crossings/", {"bbox": BBOX})
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            response.json()["crossings"][0]["name"], "</script><b>x"
        )

    def test_query_count_is_constant(self):
        for i in range(3):
            c = make_crossing(osm_id=60 + i)
            make_report(c, self.user, "closed", age_seconds=60)

        with CaptureQueriesContext(connection) as ctx3:
            response = self.client.get("/api/crossings/", {"bbox": BBOX})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 3)

        for i in range(5):
            c = make_crossing(osm_id=70 + i)
            make_report(c, self.user, "open", age_seconds=60)

        with CaptureQueriesContext(connection) as ctx8:
            response = self.client.get("/api/crossings/", {"bbox": BBOX})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 8)

        self.assertEqual(len(ctx3), len(ctx8))
        self.assertLessEqual(len(ctx8), 3)
