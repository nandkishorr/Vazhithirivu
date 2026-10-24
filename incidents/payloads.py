"""Shared JSON payload builders for the HTTP API and realtime pushes."""
from django.conf import settings

from .services import status_label

DISCLAIMER = (
    "Community-sourced and unverified; not official railway information. "
    "Absence of reports does not mean a gate is open."
)


def status_payload(status, now):
    """Full derived-status payload (single-crossing API + WS pushes)."""
    age = None
    if status.last_report_at is not None:
        age = max(0, int((now - status.last_report_at).total_seconds()))
    return {
        "state": status.state,
        "label": status_label(status.state)["label"],
        "last_report_at": (
            status.last_report_at.isoformat() if status.last_report_at else None
        ),
        "last_report_age_seconds": age,
        "last_reported_state": status.last_reported_state,
        "supporting_reports": status.supporting_reports,
        "opposing_reports": status.opposing_reports,
        "fresh_until": (
            status.fresh_until.isoformat() if status.fresh_until else None
        ),
    }


def status_brief(status, now):
    """The four status fields exposed by the bbox map endpoint."""
    payload = status_payload(status, now)
    return {
        key: payload[key]
        for key in (
            "state",
            "label",
            "last_report_at",
            "last_report_age_seconds",
        )
    }


def effective_status_payload(effective, now):
    """Full payload for an ``EffectiveStatus`` (community + overlay).

    Always carries ``simulated`` so clients can label demo data; when a
    simulation overlays the crossing, the original community state is
    preserved under ``community_state``.
    """
    payload = status_payload(effective.community, now)
    payload["state"] = effective.state
    payload["label"] = status_label(effective.state)["label"]
    payload["simulated"] = effective.simulation is not None
    if effective.simulation is not None:
        payload["simulation"] = {
            "run_id": effective.simulation.get("run_id"),
            "label": effective.simulation.get("label") or "",
            "gate_state": effective.simulation.get("gate_state"),
        }
        payload["community_state"] = effective.community.state
    return payload


def effective_status_brief(effective, now):
    """Brief variant for the bbox endpoint, including sim provenance."""
    payload = effective_status_payload(effective, now)
    return {
        key: payload[key]
        for key in (
            "state",
            "label",
            "last_report_at",
            "last_report_age_seconds",
            "simulated",
            "simulation",
            "community_state",
        )
        if key in payload
    }


def report_payload(report, now):
    return {
        "state": report.reported_state,
        "created_at": report.created_at.isoformat(),
        "age_seconds": max(0, int((now - report.created_at).total_seconds())),
        "source": report.source,
        "verified": False,
    }


def policy_payload():
    return {
        "fresh_minutes": settings.REPORT_FRESH_MINUTES,
        "stale_minutes": settings.REPORT_STALE_MINUTES,
        "conflict_window_minutes": settings.REPORT_CONFLICT_WINDOW_MINUTES,
    }
