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


def publish_tick(run, vehicles, gate_states, now=None):
    """Push one coarse tick: vehicle positions + full gate-state map."""
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
                "simulated": True,
            },
        },
    )


def build_snapshot(run, vehicles, gate_states, now=None):
    """Payload sent to a client right after subscribing to a run."""
    now = now or timezone.now()
    return {
        "type": "sim.snapshot",
        "run": run_payload(run),
        "at": now.isoformat(),
        "vehicles": vehicles,
        "gates": {str(pk): state for pk, state in gate_states.items()},
        "simulated": True,
    }
