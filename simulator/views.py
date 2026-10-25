from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

from . import engine
from .engine import SimulatorError
from .models import SimulationPrompt
from .status import active_run, gate_states_for_run
from .updates import prompt_payload, run_payload

SIM_DISCLAIMER = (
    "Simulated demo data — simulated users and gate states are not real "
    "traffic and not official railway information."
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
            "prompts": [
                prompt_payload(p) for p in engine.pending_prompts(run)
            ],
            "simulated": True,
            "disclaimer": SIM_DISCLAIMER,
        }
    )


def _resolve_prompt_view(pk, action):
    """Confirm/dismiss a pending prompt of the *active* run.

    These endpoints are CSRF-exempt on purpose: they mutate only
    simulator-owned demo rows, never community reports or reference
    data, and carry no user identity.
    """
    try:
        with transaction.atomic():
            prompt = SimulationPrompt.objects.select_for_update().get(pk=pk)
            if action == "confirm":
                engine.confirm_prompt(prompt, note="confirmed via web app")
            else:
                engine.dismiss_prompt(prompt, note="dismissed via web app")
    except SimulationPrompt.DoesNotExist:
        return JsonResponse(
            {"error": "not_found", "simulated": True}, status=404
        )
    except SimulatorError as exc:
        return JsonResponse(
            {"error": "not_resolvable", "detail": str(exc), "simulated": True},
            status=409,
        )
    body = {"prompt": prompt_payload(prompt), "simulated": True}
    if action == "confirm":
        body["gates"] = {str(prompt.crossing_id): "closed"}
    return JsonResponse(body)


@require_POST
@csrf_exempt
def api_simulation_prompt_confirm(request, pk):
    """Human confirmation: mark the crossing gate simulated-closed."""
    return _resolve_prompt_view(pk, "confirm")


@require_POST
@csrf_exempt
def api_simulation_prompt_dismiss(request, pk):
    """Dismiss a prompt: the gate stays without simulated status."""
    return _resolve_prompt_view(pk, "dismiss")
