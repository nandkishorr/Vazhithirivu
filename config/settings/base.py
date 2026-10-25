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
    GOOGLE_OAUTH_CLIENT_ID=(str, ""),
    GOOGLE_OAUTH_CLIENT_SECRET=(str, ""),
    EMAIL_BACKEND=(str, "django.core.mail.backends.smtp.EmailBackend"),
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
    ROUTE_DETOUR_ENABLED=(bool, True),
    ROUTE_DETOUR_VIA_OFFSET_M=(float, 300.0),
    ROUTE_DETOUR_MAX_CALLS=(int, 2),
    REPORT_FRESH_MINUTES=(int, 15),
    REPORT_STALE_MINUTES=(int, 60),
    REPORT_CONFLICT_WINDOW_MINUTES=(int, 5),
    REPORT_DUPLICATE_WINDOW_MINUTES=(int, 2),
    REPORT_MIN_FLIP_SECONDS=(int, 30),
    REPORT_MAX_PER_HOUR=(int, 20),
    REPORT_RETENTION_DAYS=(int, 30),
    RAILWAY_LINK_MAX_NEIGHBORS=(int, 3),
    RAILWAY_LINK_SNAP_M=(float, 30.0),
    RAILWAY_LINK_MAX_DISTANCE_M=(float, 15000.0),
    REDIS_URL=(str, ""),
    REALTIME_MAX_SUBSCRIPTIONS=(int, 500),
    REALTIME_SUBSCRIBE_MIN_SECONDS=(float, 1.0),
    SIM_TICK_SECONDS=(int, 5),
    SIM_DEFAULT_VEHICLES=(int, 60),
    SIM_MAX_VEHICLES=(int, 200),
    SIM_DEFAULT_DURATION_SECONDS=(int, 600),
    SIM_PATH_LENGTH_M=(float, 4000.0),
    SIM_HEARTBEAT_STALE_SECONDS=(int, 45),
    SIM_DWELL_RADIUS_M=(float, 20.0),
    SIM_DWELL_SECONDS=(int, 20),
    SIM_DWELL_MIN_USERS=(int, 1),
    SIM_PROMPT_TTL_SECONDS=(int, 180),
    SIM_QUEUE_GAP_M=(float, 7.0),
    SIM_QUEUE_SPACING_M=(float, 8.0),
    NAV_ALERT_RADIUS_M=(float, 300.0),
    NAV_NEARBY_RADIUS_M=(float, 600.0),
    NAV_NEARBY_LIMIT=(int, 50),
    NAV_MIN_UPDATE_SECONDS=(float, 10.0),
    NAV_MIN_UPDATE_DISTANCE_M=(float, 25.0),
    NAV_SESSION_MAX_HOURS=(int, 6),
    NAV_MAX_SESSIONS_PER_HOUR=(int, 30),
    NAV_SESSION_RETENTION_DAYS=(int, 7),
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
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "core",
    "railways",
    "incidents",
    "routing",
    "navigation",
    "simulator",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
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
                "core.context_processors.google_auth",
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

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

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

# Detour synthesis (ADR-020): when the provider offers a single route
# and a crossing blocks it, extra provider calls through a via point
# offset from the crossing surface the side-road route Google didn't
# offer. Each call counts against the per-client throttle.
ROUTE_DETOUR_ENABLED = env.bool("ROUTE_DETOUR_ENABLED")
ROUTE_DETOUR_VIA_OFFSET_M = env.float("ROUTE_DETOUR_VIA_OFFSET_M")
ROUTE_DETOUR_MAX_CALLS = env.int("ROUTE_DETOUR_MAX_CALLS")

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

EMAIL_BACKEND = env("EMAIL_BACKEND")

# Sign-in (see ADR-019). Username/password stays available for
# administrator-created accounts; Google sign-in self-registers users.
# Local public signup stays closed via the account adapter.
ACCOUNT_ADAPTER = "core.adapters.AccountAdapter"

GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = env("GOOGLE_OAUTH_CLIENT_SECRET")
GOOGLE_OAUTH_ENABLED = bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)

# The provider entry always exists so `{% provider_login_url "google" %}`
# resolves; the APP (credentials) is attached only when configured — the
# login page hides the button otherwise (see GOOGLE_OAUTH_ENABLED).
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
    }
}
if GOOGLE_OAUTH_ENABLED:
    SOCIALACCOUNT_PROVIDERS["google"]["APP"] = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "key": "",
    }

# Google's email_verified claim is trustworthy, so a Google sign-in whose
# verified email matches an existing account (e.g. one created by an
# administrator) logs into that account and links the Google identity.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True

# Community crossing-report policy (incidents app; see ADR-011).
REPORT_FRESH_MINUTES = env.int("REPORT_FRESH_MINUTES")
REPORT_STALE_MINUTES = env.int("REPORT_STALE_MINUTES")
REPORT_CONFLICT_WINDOW_MINUTES = env.int("REPORT_CONFLICT_WINDOW_MINUTES")
REPORT_DUPLICATE_WINDOW_MINUTES = env.int("REPORT_DUPLICATE_WINDOW_MINUTES")
REPORT_MIN_FLIP_SECONDS = env.int("REPORT_MIN_FLIP_SECONDS")
REPORT_MAX_PER_HOUR = env.int("REPORT_MAX_PER_HOUR")
REPORT_RETENTION_DAYS = env.int("REPORT_RETENTION_DAYS")

# Same-line crossing topology (railways app; see ADR-020).
# RAILWAY_LINK_MAX_NEIGHBORS is how many consecutive crossings on the
# same rail line a status propagates to ("up to 3 crosses"). Rebuild
# links with `manage.py link_crossings` after changing these.
RAILWAY_LINK_MAX_NEIGHBORS = env.int("RAILWAY_LINK_MAX_NEIGHBORS")
RAILWAY_LINK_SNAP_M = env.float("RAILWAY_LINK_SNAP_M")
RAILWAY_LINK_MAX_DISTANCE_M = env.float("RAILWAY_LINK_MAX_DISTANCE_M")

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

# Optional traffic/crossing simulator (simulator app; see ADR-015). The
# app is always installed but inert until a run is started; simulated
# state lives only in simulator_* tables and is labelled everywhere.
SIM_TICK_SECONDS = env.int("SIM_TICK_SECONDS")
SIM_DEFAULT_VEHICLES = env.int("SIM_DEFAULT_VEHICLES")
SIM_MAX_VEHICLES = env.int("SIM_MAX_VEHICLES")
SIM_DEFAULT_DURATION_SECONDS = env.int("SIM_DEFAULT_DURATION_SECONDS")
SIM_PATH_LENGTH_M = env.float("SIM_PATH_LENGTH_M")
SIM_HEARTBEAT_STALE_SECONDS = env.int("SIM_HEARTBEAT_STALE_SECONDS")

# Opt-in journey/navigation sessions (navigation app; see ADR-017).
# Sessions scope position checks; positions themselves are never stored.
NAV_ALERT_RADIUS_M = env.float("NAV_ALERT_RADIUS_M")
NAV_NEARBY_RADIUS_M = env.float("NAV_NEARBY_RADIUS_M")
NAV_NEARBY_LIMIT = env.int("NAV_NEARBY_LIMIT")
NAV_MIN_UPDATE_SECONDS = env.float("NAV_MIN_UPDATE_SECONDS")
NAV_MIN_UPDATE_DISTANCE_M = env.float("NAV_MIN_UPDATE_DISTANCE_M")
NAV_SESSION_MAX_HOURS = env.int("NAV_SESSION_MAX_HOURS")
NAV_MAX_SESSIONS_PER_HOUR = env.int("NAV_MAX_SESSIONS_PER_HOUR")
NAV_SESSION_RETENTION_DAYS = env.int("NAV_SESSION_RETENTION_DAYS")
# Presence inference (ADR-018/ADR-021): static simulated users parked
# near a closed gate raise a confirmation prompt instead of flipping
# status directly. Radius/dwell are demo-compressed — a real deployment
# would use minutes. Queue gap/spacing place the parked users.
SIM_DWELL_RADIUS_M = env.float("SIM_DWELL_RADIUS_M")
SIM_DWELL_SECONDS = env.int("SIM_DWELL_SECONDS")
SIM_DWELL_MIN_USERS = env.int("SIM_DWELL_MIN_USERS")
SIM_PROMPT_TTL_SECONDS = env.int("SIM_PROMPT_TTL_SECONDS")
SIM_QUEUE_GAP_M = env.float("SIM_QUEUE_GAP_M")
SIM_QUEUE_SPACING_M = env.float("SIM_QUEUE_SPACING_M")

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
