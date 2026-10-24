from django.conf import settings
from django.core.checks import Warning, register


@register()
def google_maps_configuration(app_configs, **kwargs):
    warnings = []
    if not getattr(settings, "GOOGLE_MAPS_BROWSER_KEY", ""):
        warnings.append(
            Warning(
                "GOOGLE_MAPS_BROWSER_KEY is not set; the map will show a "
                "not-configured/unavailable state.",
                hint="Set GOOGLE_MAPS_BROWSER_KEY in .env (see .env.example).",
                id="core.W001",
            )
        )
    if not getattr(settings, "GOOGLE_MAPS_MAP_ID", ""):
        warnings.append(
            Warning(
                "GOOGLE_MAPS_MAP_ID is not set; cloud-based styling and "
                "advanced markers are disabled.",
                hint="Set GOOGLE_MAPS_MAP_ID in .env (see .env.example).",
                id="core.W002",
            )
        )
    return warnings
