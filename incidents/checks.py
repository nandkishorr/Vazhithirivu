from django.conf import settings
from django.core.checks import Error, register


@register()
def report_policy_configuration(app_configs, **kwargs):
    fresh = settings.REPORT_FRESH_MINUTES
    stale = settings.REPORT_STALE_MINUTES
    conflict = settings.REPORT_CONFLICT_WINDOW_MINUTES
    if not (0 < conflict <= fresh < stale):
        return [
            Error(
                "Invalid report freshness policy: expected "
                "0 < REPORT_CONFLICT_WINDOW_MINUTES <= "
                "REPORT_FRESH_MINUTES < REPORT_STALE_MINUTES.",
                hint=(
                    f"Got conflict={conflict}, fresh={fresh}, stale={stale}. "
                    "Fix the REPORT_* values in .env (see .env.example)."
                ),
                id="incidents.E001",
            )
        ]
    return []
