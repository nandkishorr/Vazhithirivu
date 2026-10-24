import os
import subprocess
from pathlib import Path

from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parent.parent.parent

VALID_SECRET = "x" * 60


def run_django(env_overrides, argv):
    """Run a Python command with a scrubbed env (no inherited Django vars, no .env)."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "DJANGO_READ_DOT_ENV": "0",
        "DATABASE_URL": "postgis://u:p@localhost:5432/db",
    }
    env.update(env_overrides)
    return subprocess.run(
        ["python", *argv],
        capture_output=True,
        text=True,
        cwd=BASE_DIR,
        env=env,
    )


def run_check(env_overrides, extra_args=None):
    return run_django(
        env_overrides, ["manage.py", "check", *(extra_args or [])]
    )


class ProdSettingsTests(SimpleTestCase):
    def test_prod_fails_without_secret_key(self):
        result = run_check(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.prod",
                "DJANGO_ALLOWED_HOSTS": "example.com",
            }
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_prod_fails_with_insecure_secret_key(self):
        for key in ("django-insecure-abcdef", "change-me"):
            result = run_check(
                {
                    "DJANGO_SETTINGS_MODULE": "config.settings.prod",
                    "DJANGO_SECRET_KEY": key,
                    "DJANGO_ALLOWED_HOSTS": "example.com",
                }
            )
            self.assertNotEqual(result.returncode, 0, msg=key)
            self.assertIn("ImproperlyConfigured", result.stderr)

    def test_prod_fails_without_allowed_hosts(self):
        result = run_check(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.prod",
                "DJANGO_SECRET_KEY": VALID_SECRET,
            }
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_ALLOWED_HOSTS", result.stderr)

    def test_prod_check_deploy_passes(self):
        result = run_check(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.prod",
                "DJANGO_SECRET_KEY": VALID_SECRET,
                "DJANGO_ALLOWED_HOSTS": "example.com",
                "DJANGO_SECURE_HSTS_SECONDS": "31536000",
            },
            extra_args=["--deploy"],
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout: {result.stdout}\nstderr: {result.stderr}",
        )

    def test_non_postgis_database_url_rejected(self):
        for url in ("postgres://u:p@localhost:5432/db", "sqlite:///db.sqlite3"):
            result = run_check(
                {
                    "DJANGO_SETTINGS_MODULE": "config.settings.dev",
                    "DJANGO_SECRET_KEY": VALID_SECRET,
                    "DATABASE_URL": url,
                }
            )
            self.assertNotEqual(result.returncode, 0, msg=url)
            self.assertIn("ImproperlyConfigured", result.stderr)

    def test_dev_env_parsing(self):
        result = run_django(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.dev",
                "DJANGO_DEBUG": "false",
                "DJANGO_ALLOWED_HOSTS": "example.com,test.example.com",
            },
            [
                "-c",
                "import django; django.setup(); "
                "from django.conf import settings; "
                "assert settings.DEBUG is False; "
                "assert settings.ALLOWED_HOSTS == ['example.com', 'test.example.com']",
            ],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
