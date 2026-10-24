from django.apps import AppConfig


class SimulatorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "simulator"

    def ready(self):
        from incidents.services import register_status_overlay

        from . import checks  # noqa: F401
        from .status import active_gate_overrides

        register_status_overlay(active_gate_overrides)
