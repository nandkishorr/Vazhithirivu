import json
from unittest.mock import patch

from django.test import Client, TestCase


class HealthzTests(TestCase):
    def test_healthz_returns_200_json(self):
        response = Client().get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.content), {"status": "ok"}
        )

    def test_healthz_rejects_post(self):
        response = Client().post("/healthz/")
        self.assertEqual(response.status_code, 405)


class ReadyzTests(TestCase):
    def test_readyz_returns_200_with_postgis(self):
        response = Client().get("/readyz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.content),
            {"status": "ok", "checks": {"database": "ok", "postgis": "ok"}},
        )

    def test_readyz_returns_503_without_leaking_exception(self):
        with patch(
            "django.db.connection.cursor",
            side_effect=RuntimeError("secret-db-error-marker"),
        ):
            response = Client().get("/readyz/")
        self.assertEqual(response.status_code, 503)
        body = json.loads(response.content)
        self.assertEqual(body["status"], "error")
        self.assertNotIn("secret-db-error-marker", response.content.decode())
