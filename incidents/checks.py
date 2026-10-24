from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def realtime_configuration(app_configs, **kwargs):
    problems = []
    layer_cfg = (settings.CHANNEL_LAYERS or {}).get("default") or {}
    backend = layer_cfg.get("BACKEND", "")
    if backend == "channels.layers.InMemoryChannelLayer":
        problems.append(
            Warning(
                "CHANNEL_LAYERS uses the in-memory backend: WebSocket "
                "status pushes only work inside a single server process.",
                hint=(
                    "Set REDIS_URL so pushes reach clients connected to "
                    "other workers/processes."
                ),
                id="incidents.W001",
            )
        )
    if (
        settings.REALTIME_MAX_SUBSCRIPTIONS < 1
        or settings.REALTIME_SUBSCRIBE_MIN_SECONDS <= 0
    ):
        problems.append(
            Error(
                "Invalid realtime limits: expected "
                "REALTIME_MAX_SUBSCRIPTIONS >= 1 and "
                "REALTIME_SUBSCRIBE_MIN_SECONDS > 0.",
                hint="Fix the REALTIME_* values in .env (see .env.example).",
                id="incidents.E002",
            )
        )
    return problems


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
