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
    if bool(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")) != bool(
        getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    ):
        warnings.append(
            Warning(
                "Google sign-in is only half configured; the button will "
                "stay hidden until both credentials are set.",
                hint="Set GOOGLE_OAUTH_CLIENT_ID and "
                "GOOGLE_OAUTH_CLIENT_SECRET in .env (see .env.example).",
                id="core.W003",
            )
        )
    return warnings
