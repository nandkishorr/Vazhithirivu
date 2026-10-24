from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .status import active_run, gate_states_for_run
from .updates import run_payload

SIM_DISCLAIMER = (
    "Simulated demo data — vehicles and gate states are not real traffic "
    "and not official railway information."
)


@never_cache
@require_safe
def api_simulation_state(request):
    """Current simulation snapshot (polling fallback for the WS channel)."""
    now = timezone.now()
    run = active_run()
    if run is None:
        return JsonResponse(
            {
                "active": False,
                "as_of": now.isoformat(),
                "simulated": True,
                "disclaimer": SIM_DISCLAIMER,
            }
        )
    from .engine import vehicle_frames

    return JsonResponse(
        {
            "active": True,
            "run": run_payload(run),
            "as_of": now.isoformat(),
            "vehicles": vehicle_frames(run),
            "gates": {
                str(pk): state
                for pk, state in gate_states_for_run(run).items()
            },
            "simulated": True,
            "disclaimer": SIM_DISCLAIMER,
        }
    )
