from django.conf import settings
from django.core.checks import Error, register


@register()
def navigation_configuration(app_configs, **kwargs):
    problems = []
    alert = settings.NAV_ALERT_RADIUS_M
    nearby = settings.NAV_NEARBY_RADIUS_M
    if not (0 < alert <= nearby):
        problems.append(
            Error(
                "Invalid navigation radii: expected "
                "0 < NAV_ALERT_RADIUS_M <= NAV_NEARBY_RADIUS_M.",
                hint=(
                    f"Got alert={alert}, nearby={nearby}. Fix the NAV_* "
                    "values in .env (see .env.example)."
                ),
                id="navigation.E001",
            )
        )
    if not (
        settings.NAV_MIN_UPDATE_SECONDS >= 1
        and settings.NAV_MIN_UPDATE_DISTANCE_M >= 0
        and settings.NAV_SESSION_MAX_HOURS >= 1
        and settings.NAV_MAX_SESSIONS_PER_HOUR >= 1
        and settings.NAV_NEARBY_LIMIT >= 1
        and settings.NAV_SESSION_RETENTION_DAYS >= 1
    ):
        problems.append(
            Error(
                "Invalid navigation limits: NAV_MIN_UPDATE_SECONDS, "
                "NAV_SESSION_MAX_HOURS, NAV_MAX_SESSIONS_PER_HOUR, "
                "NAV_NEARBY_LIMIT and NAV_SESSION_RETENTION_DAYS must be "
                ">= 1, and NAV_MIN_UPDATE_DISTANCE_M must be >= 0.",
                hint="Fix the NAV_* values in .env (see .env.example).",
                id="navigation.E002",
            )
        )
    return problems
