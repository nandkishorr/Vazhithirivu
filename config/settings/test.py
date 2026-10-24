from .dev import *  # noqa: F401,F403

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Tests must never reach a live routing provider: even if .env carries a
# real key, provider tests construct GoogleRoutesProvider themselves and
# mock urlopen.
GOOGLE_MAPS_SERVER_KEY = ""
