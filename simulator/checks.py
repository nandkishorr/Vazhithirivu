from django.conf import settings
from django.core.checks import Error, register


@register()
def simulator_configuration(app_configs, **kwargs):
    problems = []
    default_v = settings.SIM_DEFAULT_VEHICLES
    max_v = settings.SIM_MAX_VEHICLES
    if not (1 <= default_v <= max_v <= 1000):
        problems.append(
            Error(
                "Invalid simulator fleet size: expected "
                "1 <= SIM_DEFAULT_VEHICLES <= SIM_MAX_VEHICLES <= 1000.",
                hint=(
                    f"Got default={default_v}, max={max_v}. Fix the SIM_* "
                    "values in .env (see .env.example)."
                ),
                id="simulator.E001",
            )
        )
    if not (
        settings.SIM_TICK_SECONDS > 0
        and settings.SIM_DEFAULT_DURATION_SECONDS > 0
        and settings.SIM_HEARTBEAT_STALE_SECONDS > 0
        and settings.SIM_PATH_LENGTH_M > 0
    ):
        problems.append(
            Error(
                "Invalid simulator timing/geometry values: SIM_TICK_SECONDS, "
                "SIM_DEFAULT_DURATION_SECONDS, SIM_HEARTBEAT_STALE_SECONDS "
                "and SIM_PATH_LENGTH_M must all be positive.",
                hint="Fix the SIM_* values in .env (see .env.example).",
                id="simulator.E002",
            )
        )
    if not (
        settings.SIM_DWELL_RADIUS_M > 0
        and settings.SIM_DWELL_SECONDS >= 0
        and settings.SIM_DWELL_MIN_USERS >= 1
        and settings.SIM_PROMPT_TTL_SECONDS > 0
        and settings.SIM_QUEUE_GAP_M > 0
        and settings.SIM_QUEUE_SPACING_M > 0
    ):
        problems.append(
            Error(
                "Invalid simulator inference/queue values: SIM_DWELL_RADIUS_M, "
                "SIM_PROMPT_TTL_SECONDS, SIM_QUEUE_GAP_M and "
                "SIM_QUEUE_SPACING_M must be positive, SIM_DWELL_SECONDS "
                "non-negative, SIM_DWELL_MIN_USERS at least 1.",
                hint="Fix the SIM_* values in .env (see .env.example).",
                id="simulator.E004",
            )
        )
    return problems
