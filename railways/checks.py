from django.conf import settings
from django.core.checks import Error, register


@register()
def railway_link_configuration(app_configs, **kwargs):
    neighbors = getattr(settings, "RAILWAY_LINK_MAX_NEIGHBORS", 0)
    snap = getattr(settings, "RAILWAY_LINK_SNAP_M", 0)
    distance = getattr(settings, "RAILWAY_LINK_MAX_DISTANCE_M", 0)
    if not (0 < neighbors <= 10 and snap > 0 and distance > 0):
        return [
            Error(
                "Invalid same-line link settings: expected "
                "0 < RAILWAY_LINK_MAX_NEIGHBORS <= 10, "
                "RAILWAY_LINK_SNAP_M > 0 and "
                "RAILWAY_LINK_MAX_DISTANCE_M > 0.",
                hint=(
                    f"Got neighbors={neighbors}, snap={snap}, "
                    f"distance={distance}. Fix the RAILWAY_LINK_* values "
                    "in .env (see .env.example)."
                ),
                id="railways.E001",
            )
        ]
    return []
