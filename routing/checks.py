from django.conf import settings
from django.core.checks import Error, Warning, register

ALLOWED_PREFERENCES = ("TRAFFIC_UNAWARE", "TRAFFIC_AWARE")


@register()
def routing_configuration(app_configs, **kwargs):
    problems = []
    on_route = getattr(settings, "ROUTE_CROSSING_ON_ROUTE_M", 0)
    near = getattr(settings, "ROUTE_CROSSING_NEAR_M", 0)
    track = getattr(settings, "ROUTE_TRACK_MATCH_M", 0)
    clearance = getattr(settings, "ROUTE_AVOID_CLEARANCE_M", 0)
    if not (0 < on_route <= near < clearance and track > 0):
        problems.append(
            Error(
                "Route-crossing distance thresholds are inconsistent: "
                "expected 0 < ROUTE_CROSSING_ON_ROUTE_M <= "
                "ROUTE_CROSSING_NEAR_M < ROUTE_AVOID_CLEARANCE_M and "
                "ROUTE_TRACK_MATCH_M > 0.",
                hint="Adjust the ROUTE_* settings (see .env.example).",
                id="routing.E001",
            )
        )
    if (
        getattr(settings, "ROUTING_GOOGLE_ROUTING_PREFERENCE", "")
        not in ALLOWED_PREFERENCES
    ):
        problems.append(
            Error(
                "ROUTING_GOOGLE_ROUTING_PREFERENCE must be TRAFFIC_UNAWARE "
                "or TRAFFIC_AWARE.",
                hint="TRAFFIC_AWARE bills the Pro SKU; TRAFFIC_UNAWARE is "
                "the Essentials default.",
                id="routing.E002",
            )
        )
    if not getattr(settings, "GOOGLE_MAPS_SERVER_KEY", ""):
        problems.append(
            Warning(
                "GOOGLE_MAPS_SERVER_KEY is not set; route planning will "
                "report 'not configured'.",
                hint="Set GOOGLE_MAPS_SERVER_KEY in .env with the Routes "
                "API enabled (see .env.example).",
                id="routing.W001",
            )
        )
    return problems
