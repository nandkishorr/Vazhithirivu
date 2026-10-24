from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, []),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    DJANGO_LOG_LEVEL=(str, "INFO"),
    GOOGLE_MAPS_BROWSER_KEY=(str, ""),
    GOOGLE_MAPS_SERVER_KEY=(str, ""),
    GOOGLE_MAPS_MAP_ID=(str, ""),
    MAP_DEFAULT_LAT=(float, 9.9312),
    MAP_DEFAULT_LNG=(float, 76.2673),
    MAP_DEFAULT_ZOOM=(int, 13),
    REPORT_FRESH_MINUTES=(int, 15),
    REPORT_STALE_MINUTES=(int, 60),
    REPORT_CONFLICT_WINDOW_MINUTES=(int, 5),
    REPORT_DUPLICATE_WINDOW_MINUTES=(int, 2),
    REPORT_MIN_FLIP_SECONDS=(int, 30),
    REPORT_MAX_PER_HOUR=(int, 20),
    REPORT_RETENTION_DAYS=(int, 30),
)

# .env is optional: real environment variables always take precedence.
# Set DJANGO_READ_DOT_ENV=0 to skip loading .env entirely (used by tests).
if env.bool("DJANGO_READ_DOT_ENV", default=True):
    environ.Env.read_env(BASE_DIR / ".env")

# Required in production; dev/test environments override this with a default.
SECRET_KEY = env("DJANGO_SECRET_KEY", default=None)
DEBUG = env.bool("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "core",
    "railways",
    "incidents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}
if (
    DATABASES["default"]["ENGINE"]
    != "django.contrib.gis.db.backends.postgis"
):
    raise ImproperlyConfigured(
        "DATABASE_URL must use a PostGIS backend (e.g. postgis://user:pass@host:5432/dbname)"
    )

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

GOOGLE_MAPS_BROWSER_KEY = env("GOOGLE_MAPS_BROWSER_KEY")
GOOGLE_MAPS_SERVER_KEY = env("GOOGLE_MAPS_SERVER_KEY")

GOOGLE_MAPS_MAP_ID = env("GOOGLE_MAPS_MAP_ID")

MAP_DEFAULT_LAT = env.float("MAP_DEFAULT_LAT")
MAP_DEFAULT_LNG = env.float("MAP_DEFAULT_LNG")
MAP_DEFAULT_ZOOM = env.int("MAP_DEFAULT_ZOOM")

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

# Community crossing-report policy (incidents app; see ADR-011).
REPORT_FRESH_MINUTES = env.int("REPORT_FRESH_MINUTES")
REPORT_STALE_MINUTES = env.int("REPORT_STALE_MINUTES")
REPORT_CONFLICT_WINDOW_MINUTES = env.int("REPORT_CONFLICT_WINDOW_MINUTES")
REPORT_DUPLICATE_WINDOW_MINUTES = env.int("REPORT_DUPLICATE_WINDOW_MINUTES")
REPORT_MIN_FLIP_SECONDS = env.int("REPORT_MIN_FLIP_SECONDS")
REPORT_MAX_PER_HOUR = env.int("REPORT_MAX_PER_HOUR")
REPORT_RETENTION_DAYS = env.int("REPORT_RETENTION_DAYS")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {
        "handlers": ["console"],
        "level": env("DJANGO_LOG_LEVEL"),
    },
}
