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
    MAP_CROSSINGS_LIMIT=(int, 500),
    MAP_BBOX_MAX_SPAN_DEG=(float, 1.5),
    MAP_CROSSINGS_MIN_ZOOM=(int, 12),
    ROUTING_PROVIDER=(str, "google"),
    ROUTING_TIMEOUT_SECONDS=(int, 8),
    ROUTING_GOOGLE_ROUTING_PREFERENCE=(str, "TRAFFIC_UNAWARE"),
    ROUTING_MAX_REQUESTS_PER_HOUR=(int, 60),
    ROUTE_CROSSING_ON_ROUTE_M=(float, 20.0),
    ROUTE_CROSSING_NEAR_M=(float, 50.0),
    ROUTE_TRACK_MATCH_M=(float, 30.0),
    ROUTE_AVOID_CLEARANCE_M=(float, 100.0),
    REPORT_FRESH_MINUTES=(int, 15),
    REPORT_STALE_MINUTES=(int, 60),
    REPORT_CONFLICT_WINDOW_MINUTES=(int, 5),
    REPORT_DUPLICATE_WINDOW_MINUTES=(int, 2),
    REPORT_MIN_FLIP_SECONDS=(int, 30),
    REPORT_MAX_PER_HOUR=(int, 20),
    REPORT_RETENTION_DAYS=(int, 30),
    REDIS_URL=(str, ""),
    REALTIME_MAX_SUBSCRIPTIONS=(int, 500),
    REALTIME_SUBSCRIBE_MIN_SECONDS=(float, 1.0),
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
    "daphne",
    "channels",
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
    "routing",
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
ASGI_APPLICATION = "config.asgi.application"

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

# Map crossing endpoint bounds (ADR-012).
MAP_CROSSINGS_LIMIT = env.int("MAP_CROSSINGS_LIMIT")
MAP_BBOX_MAX_SPAN_DEG = env.float("MAP_BBOX_MAX_SPAN_DEG")
MAP_CROSSINGS_MIN_ZOOM = env.int("MAP_CROSSINGS_MIN_ZOOM")

# Route planning (routing app; see ADR-013).
# TRAFFIC_AWARE bills the Google Routes Pro SKU; the default stays on
# Essentials (TRAFFIC_UNAWARE) and durations are labelled accordingly.
ROUTING_PROVIDER = env("ROUTING_PROVIDER")
ROUTING_TIMEOUT_SECONDS = env.int("ROUTING_TIMEOUT_SECONDS")
ROUTING_GOOGLE_ROUTING_PREFERENCE = env("ROUTING_GOOGLE_ROUTING_PREFERENCE")
ROUTING_MAX_REQUESTS_PER_HOUR = env.int("ROUTING_MAX_REQUESTS_PER_HOUR")
ROUTE_CROSSING_ON_ROUTE_M = env.float("ROUTE_CROSSING_ON_ROUTE_M")
ROUTE_CROSSING_NEAR_M = env.float("ROUTE_CROSSING_NEAR_M")
ROUTE_TRACK_MATCH_M = env.float("ROUTE_TRACK_MATCH_M")
ROUTE_AVOID_CLEARANCE_M = env.float("ROUTE_AVOID_CLEARANCE_M")

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

# Realtime crossing-status pushes (incidents app; see ADR-014). With
# REDIS_URL set, Redis backs both the WebSocket channel layer and the
# default cache, so pushes and throttles are shared across workers.
# Without it, a per-process in-memory layer/cache is used, which only
# works in a single-process server (dev runserver, tests).
REDIS_URL = env("REDIS_URL")
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "vz",
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

REALTIME_MAX_SUBSCRIPTIONS = env.int("REALTIME_MAX_SUBSCRIPTIONS")
REALTIME_SUBSCRIBE_MIN_SECONDS = env.float("REALTIME_SUBSCRIBE_MIN_SECONDS")

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
