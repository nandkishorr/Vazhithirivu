from .base import *  # noqa: F401,F403

DEBUG = env.bool("DJANGO_DEBUG", default=True)
SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-dev-only-change-me")
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"]
)

# No SMTP server in dev: outgoing mail (e.g. allauth password reset)
# prints to the console instead of failing with a connection error.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
