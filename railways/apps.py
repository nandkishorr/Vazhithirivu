from django.apps import AppConfig


class RailwaysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "railways"

    def ready(self):
        from . import checks  # noqa: F401
