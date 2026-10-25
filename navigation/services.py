"""Navigation session lifecycle and proximity checks (ADR-017).

A journey session scopes position checks to an explicit, stoppable,
time-bounded permission. Positions themselves are never stored — they
answer one query each and are gone.
"""
import math
import uuid

from django.conf import settings
from django.utils import timezone

from incidents.services import (
    STATE_CLOSED_INFERRED,
    STATE_CLOSED_REPORTED,
    STATE_CLOSED_SIMULATED,
    effective_statuses,
)
from railways.queries import crossings_near_point

from .models import JourneySession

# States that raise a "closed gate ahead" alert. Same rule as routing:
# a simulated or same-line-inferred closure alerts exactly like a
# reported one — each is labelled for what it is in the payload.
ALERT_STATES = (
    STATE_CLOSED_REPORTED,
    STATE_CLOSED_SIMULATED,
    STATE_CLOSED_INFERRED,
)


class TooSoon(Exception):
    """A position check arrived inside the per-session min interval."""

    def __init__(self, retry_after_seconds):
        super().__init__(f"Try again in {retry_after_seconds} seconds")
        self.retry_after_seconds = max(
            1, int(math.ceil(retry_after_seconds))
        )


def start_session(now=None):
    return JourneySession.objects.create(created_at=now or timezone.now())


def get_session(session_id):
    try:
        pk = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
    except (ValueError, AttributeError, TypeError):
        return None
    return JourneySession.objects.filter(pk=pk).first()


def end_session(session, now=None):
    """End a session; idempotent — ending an ended session is a no-op."""
    if session.ended_at is None:
        session.ended_at = now or timezone.now()
        session.save(update_fields=["ended_at"])
    return session


def record_position_check(session, now=None):
    """Stamp the check time or raise :class:`TooSoon` if inside the
    per-session minimum interval."""
    now = now or timezone.now()
    min_seconds = settings.NAV_MIN_UPDATE_SECONDS
    last = session.last_position_check_at
    if last is not None:
        elapsed = (now - last).total_seconds()
        if elapsed < min_seconds:
            raise TooSoon(min_seconds - elapsed)
    session.last_position_check_at = now
    session.save(update_fields=["last_position_check_at"])


def nearby_crossings(lat, lng, now=None):
    """Crossings near a position with effective statuses + distances.

    Returns ``[(crossing, distance_m, EffectiveStatus), …]`` nearest
    first, bounded by ``NAV_NEARBY_RADIUS_M``/``NAV_NEARBY_LIMIT``.
    One spatial pair + one status query (+ overlay) per call.
    """
    now = now or timezone.now()
    rows = crossings_near_point(
        lat,
        lng,
        settings.NAV_NEARBY_RADIUS_M,
        settings.NAV_NEARBY_LIMIT,
    )
    statuses = effective_statuses([c for c, _ in rows], now=now)
    return [(c, dist, statuses[c.pk]) for c, dist in rows]
