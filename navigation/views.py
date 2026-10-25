import json

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from incidents.payloads import DISCLAIMER, effective_status_brief

from .services import (
    ALERT_STATES,
    TooSoon,
    end_session,
    get_session,
    nearby_crossings,
    record_position_check,
    start_session,
)
from .throttle import allow_session_start

LOCATION_POLICY = (
    "Positions are sent only while a journey is active, used for a "
    "single proximity check each and never stored."
)


def _session_payload(session):
    return {
        "id": str(session.pk),
        "started_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "ended": session.ended_at is not None,
    }


def _config_payload():
    return {
        "alert_radius_m": settings.NAV_ALERT_RADIUS_M,
        "nearby_radius_m": settings.NAV_NEARBY_RADIUS_M,
        "min_update_seconds": settings.NAV_MIN_UPDATE_SECONDS,
        "min_update_distance_m": settings.NAV_MIN_UPDATE_DISTANCE_M,
    }


def _active_session(session_id, now):
    session = get_session(session_id)
    if session is None:
        return None, JsonResponse({"error": "not_found"}, status=404)
    if not session.is_active(now):
        return None, JsonResponse({"error": "session_ended"}, status=410)
    return session, None


def _parse_position(request):
    """Return ``(lat, lng)`` from a JSON body or raise ``ValueError``."""
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("invalid_json") from None
    if not isinstance(data, dict):
        raise ValueError("invalid_json")
    try:
        lat = float(data.get("lat"))
        lng = float(data.get("lng"))
    except (TypeError, ValueError):
        raise ValueError("invalid_position") from None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("invalid_position")
    return lat, lng


@never_cache
@require_POST
def api_navigation_start(request):
    """Begin an opt-in journey session (ADR-017)."""
    client_key = request.META.get("REMOTE_ADDR") or "anonymous"
    if not allow_session_start(client_key):
        return JsonResponse({"error": "rate_limited"}, status=429)
    session = start_session()
    return JsonResponse(
        {
            "session": _session_payload(session),
            "config": _config_payload(),
            "location_policy": LOCATION_POLICY,
            "official": False,
            "disclaimer": DISCLAIMER,
        },
        status=201,
    )


@never_cache
@require_POST
def api_navigation_position(request, session_id):
    """One transient position check inside an active session.

    The coordinates answer this request only — nothing about the
    position is written to the database.
    """
    now = timezone.now()
    session, error = _active_session(session_id, now)
    if error:
        return error
    try:
        lat, lng = _parse_position(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    try:
        record_position_check(session, now=now)
    except TooSoon as exc:
        response = JsonResponse(
            {
                "error": "too_fast",
                "retry_after_seconds": exc.retry_after_seconds,
            },
            status=429,
        )
        response["Retry-After"] = str(exc.retry_after_seconds)
        return response

    alert_m = settings.NAV_ALERT_RADIUS_M
    crossings = []
    alerts = []
    for crossing, distance_m, status in nearby_crossings(lat, lng, now=now):
        entry = {
            "id": crossing.pk,
            "name": crossing.name or "",
            "lat": round(crossing.location.y, 6),
            "lng": round(crossing.location.x, 6),
            "distance_m": round(distance_m, 1),
            "alert": (
                status.state in ALERT_STATES and distance_m <= alert_m
            ),
            "status": effective_status_brief(status, now),
        }
        crossings.append(entry)
        if entry["alert"]:
            alerts.append(entry)
    return JsonResponse(
        {
            "as_of": now.isoformat(),
            "alert_radius_m": alert_m,
            "nearby_radius_m": settings.NAV_NEARBY_RADIUS_M,
            "crossings": crossings,
            "alerts": alerts,
            "official": False,
            "disclaimer": DISCLAIMER,
            "attribution": (
                "Crossing locations © OpenStreetMap contributors"
            ),
        }
    )


@never_cache
@require_POST
def api_navigation_end(request, session_id):
    """End a session; idempotent so a racing client stays consistent."""
    session = get_session(session_id)
    if session is None:
        return JsonResponse({"error": "not_found"}, status=404)
    end_session(session)
    return JsonResponse({"ended": True, "session": _session_payload(session)})
