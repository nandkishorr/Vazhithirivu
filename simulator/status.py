"""Simulated gate-state overlay for the shared status pipeline.

Registered into ``incidents.services`` at app ready (ADR-015): the
incidents app asks this module for per-crossing overlays, and only an
*active* (running/paused) run contributes gate state. The moment a run
stops or finishes, its gates stop overlaying — simulated status can
never linger after a demo ends.
"""
from django.db.models import Max

from .models import SimulationGateEvent, SimulationRun


def active_run():
    """The currently active run, or ``None``.

    ``active_slot`` guarantees at most one running/paused row; order by
    recency so a data-level anomaly still resolves deterministically.
    """
    return (
        SimulationRun.objects.filter(
            status__in=SimulationRun.ACTIVE_STATUSES
        )
        .order_by("-started_at", "-pk")
        .first()
    )


def _latest_events(queryset):
    """The newest gate event per crossing (events insert in tick order)."""
    last_pks = list(
        queryset.values("crossing_id").annotate(last_pk=Max("pk"))
        .values_list("last_pk", flat=True)
    )
    return list(SimulationGateEvent.objects.filter(pk__in=last_pks))


def gate_states_for_run(run):
    """Latest gate state per crossing for ``run`` → ``{pk: "open"|"closed"}``."""
    return {
        event.crossing_id: event.gate_state
        for event in _latest_events(run.gate_events.all())
    }


def active_gate_overrides(crossings, now=None):
    """Status-overlay provider (see ``incidents.services``).

    Returns ``{crossing_pk: {"gate_state", "run_id", "label", "since"}}``
    for crossings with gate events in the *active* run. No active run →
    ``{}``, so the overlay costs little more than one existence query
    when the simulator is off.
    """
    pks = [c.pk for c in crossings]
    if not pks:
        return {}
    run = active_run()
    if run is None:
        return {}
    events = _latest_events(
        SimulationGateEvent.objects.filter(run=run, crossing_id__in=pks)
    )
    return {
        event.crossing_id: {
            "gate_state": event.gate_state,
            "run_id": run.pk,
            "label": run.label,
            "since": event.occurred_at,
        }
        for event in events
    }
