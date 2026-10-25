"""Realtime simulation frames (ADR-015).

Vehicle positions and gate states are pushed in coarse ticks to the
``sim.run.<pk>`` group; lifecycle announcements go to ``sim.control``
so browsers can attach/detach as runs come and go. Everything here is
clearly labelled simulated data — payloads always carry
``"simulated": true``.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

CONTROL_GROUP = "sim.control"


def group_name(run_id):
    return f"sim.run.{run_id}"


def run_payload(run):
    return {
        "id": run.pk,
        "label": run.label or f"Run {run.pk}",
        "status": run.status,
        "tick": run.ticks,
        "vehicle_count": run.vehicle_count,
        "duration_seconds": run.duration_seconds,
        "tick_seconds": run.tick_seconds,
        "started_at": run.started_at.isoformat() if run.started_at else None,
    }


def _send(group, message):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(group, message)
    except Exception:
        logger.warning("Simulation push to %s failed", group, exc_info=True)


def publish_run_event(run, kind):
    """Broadcast a lifecycle event: started|paused|resumed|stopped|finished."""
    _send(
        CONTROL_GROUP,
        {
            "type": "sim.run",
            "payload": {
                "type": f"sim.run.{kind}",
                "run": run_payload(run),
                "simulated": True,
                "as_of": timezone.now().isoformat(),
            },
        },
    )


def prompt_payload(prompt):
    """Public payload for a SimulationPrompt (API, WS, snapshot)."""
    crossing = prompt.crossing
    return {
        "id": prompt.pk,
        "crossing_id": prompt.crossing_id,
        "crossing_name": crossing.name or "Unnamed level crossing",
        "crossing_lat": round(crossing.location.y, 6),
        "crossing_lng": round(crossing.location.x, 6),
        "waiting_users": len(prompt.waiting_vehicle_indexes or []),
        "detected_tick": prompt.detected_tick,
        "state": prompt.state,
        "detected_at": prompt.created_at.isoformat(),
        "confirm_url": reverse(
            "api_simulation_prompt_confirm", args=[prompt.pk]
        ),
        "dismiss_url": reverse(
            "api_simulation_prompt_dismiss", args=[prompt.pk]
        ),
        "simulated": True,
    }


def publish_tick(run, vehicles, gate_states, prompts=None, now=None):
    """Push one coarse tick: vehicle positions + gate map + prompts."""
    now = now or timezone.now()
    _send(
        group_name(run.pk),
        {
            "type": "sim.tick",
            "payload": {
                "type": "sim.tick",
                "run": run_payload(run),
                "at": now.isoformat(),
                "vehicles": vehicles,
                "gates": {
                    str(pk): state for pk, state in gate_states.items()
                },
                "prompts": [
                    prompt_payload(p) for p in (prompts or [])
                ],
                "simulated": True,
            },
        },
    )


def publish_prompt(prompt):
    """Broadcast a newly raised confirmation prompt to all sim clients."""
    _send(
        CONTROL_GROUP,
        {
            "type": "sim.prompt",
            "payload": {
                "type": "sim.prompt",
                "prompt": prompt_payload(prompt),
                "as_of": timezone.now().isoformat(),
                "simulated": True,
            },
        },
    )


def publish_prompt_resolved(prompt):
    """Broadcast that a prompt was confirmed/dismissed/expired."""
    _send(
        CONTROL_GROUP,
        {
            "type": "sim.prompt",
            "payload": {
                "type": "sim.prompt.resolved",
                "prompt_id": prompt.pk,
                "crossing_id": prompt.crossing_id,
                "state": prompt.state,
                "as_of": timezone.now().isoformat(),
                "simulated": True,
            },
        },
    )


def build_snapshot(run, vehicles, gate_states, prompts=None, now=None):
    """Payload sent to a client right after subscribing to a run."""
    now = now or timezone.now()
    return {
        "type": "sim.snapshot",
        "run": run_payload(run),
        "at": now.isoformat(),
        "vehicles": vehicles,
        "gates": {str(pk): state for pk, state in gate_states.items()},
        "prompts": [prompt_payload(p) for p in (prompts or [])],
        "simulated": True,
    }
