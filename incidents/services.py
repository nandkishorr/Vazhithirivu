"""Deterministic community-report status logic (ADR-011).

Derived states are computed from visible community reports only; absence
of reports is never interpreted as an open gate.
"""
import math
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import CrossingReport

STATE_CLOSED_REPORTED = "closed_reported"
STATE_OPEN_REPORTED = "open_reported"
STATE_CONFLICTING = "conflicting"
STATE_STALE = "stale"
STATE_UNKNOWN = "unknown"

STATUS_META = {
    STATE_CLOSED_REPORTED: {
        "label": "Reported closed",
        "description": "Recent community reports say this crossing is closed.",
    },
    STATE_OPEN_REPORTED: {
        "label": "Reported open",
        "description": "Recent community reports say this crossing is open.",
    },
    STATE_CONFLICTING: {
        "label": "Conflicting reports",
        "description": "Recent community reports disagree about this crossing.",
    },
    STATE_STALE: {
        "label": "Report outdated",
        "description": "The most recent report is too old to rely on.",
    },
    STATE_UNKNOWN: {
        "label": "Status unknown",
        "description": "No recent community reports for this crossing.",
    },
}


class ReportNotAllowed(Exception):
    """The user/crossing combination may not accept a report."""


class RateLimited(Exception):
    """The user is reporting too fast or too often."""

    def __init__(self, retry_after_seconds):
        super().__init__(f"Try again in {retry_after_seconds} seconds")
        self.retry_after_seconds = max(1, int(math.ceil(retry_after_seconds)))


@dataclass(frozen=True)
class CrossingStatus:
    state: str
    as_of: object
    last_report_at: object
    last_reported_state: object
    supporting_reports: int
    opposing_reports: int
    fresh_until: object

    @property
    def age(self):
        """Human age of the newest report, e.g. "12 min ago" ("" if none)."""
        if self.last_report_at is None or self.as_of is None:
            return ""
        seconds = (self.as_of - self.last_report_at).total_seconds()
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{round(seconds / 60)} min ago"
        return f"{round(seconds / 3600)} h ago"


def status_label(state):
    """Human label/description for a derived state (same text as the badge)."""
    return STATUS_META.get(state, STATUS_META[STATE_UNKNOWN])


def _visible_community_reports(crossing, now):
    return (
        CrossingReport.objects.filter(
            crossing=crossing,
            source=CrossingReport.SOURCE_COMMUNITY,
            moderation_status=CrossingReport.MODERATION_VISIBLE,
            created_at__lte=now,
        )
        .order_by("-created_at")
    )


def _reporter_key(report):
    if report.reporter_id is None:
        return f"deleted:{report.pk}"
    return report.reporter_id


def _derive_from_reports(reports, now):
    """Derive status from visible community reports, newest first.

    ``reports`` is the same list ``derive_status`` builds as ``recent``:
    reports with ``created_at`` in ``(now - stale, now]``.
    """
    recent = reports
    if not recent:
        return CrossingStatus(
            state=STATE_UNKNOWN,
            as_of=now,
            last_report_at=None,
            last_reported_state=None,
            supporting_reports=0,
            opposing_reports=0,
            fresh_until=None,
        )

    fresh = [r for r in recent if r.expires_at > now]
    newest_recent = recent[0]
    if not fresh:
        return CrossingStatus(
            state=STATE_STALE,
            as_of=now,
            last_report_at=newest_recent.created_at,
            last_reported_state=newest_recent.reported_state,
            supporting_reports=0,
            opposing_reports=0,
            fresh_until=None,
        )

    # Keep only the newest report per reporter.
    seen = set()
    deduped = []
    for report in fresh:
        key = _reporter_key(report)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(report)

    newest = deduped[0]
    conflict_since = newest.created_at - timedelta(
        minutes=settings.REPORT_CONFLICT_WINDOW_MINUTES
    )
    window = [r for r in deduped if r.created_at >= conflict_since]
    states = {r.reported_state for r in window}
    if len(states) > 1:
        supporting = sum(
            1 for r in window if r.reported_state == newest.reported_state
        )
        return CrossingStatus(
            state=STATE_CONFLICTING,
            as_of=now,
            last_report_at=newest.created_at,
            last_reported_state=newest.reported_state,
            supporting_reports=supporting,
            opposing_reports=len(window) - supporting,
            fresh_until=max(r.expires_at for r in window),
        )

    # All window reports agree. Count only reports newer than the last
    # opposite-state report (an older opposite report is a genuine gate
    # transition, not a conflict).
    opposite = [r for r in deduped if r.reported_state != newest.reported_state]
    cutoff = opposite[0].created_at if opposite else None
    supporting = [
        r
        for r in deduped
        if r.reported_state == newest.reported_state
        and (cutoff is None or r.created_at > cutoff)
    ]
    state = (
        STATE_CLOSED_REPORTED
        if newest.reported_state == CrossingReport.STATE_CLOSED
        else STATE_OPEN_REPORTED
    )
    return CrossingStatus(
        state=state,
        as_of=now,
        last_report_at=newest.created_at,
        last_reported_state=newest.reported_state,
        supporting_reports=len(supporting),
        opposing_reports=0,
        fresh_until=max(r.expires_at for r in supporting),
    )


def derive_status(crossing, now=None):
    """Derive a crossing's current community-reported status."""
    now = now or timezone.now()
    stale_after = now - timedelta(minutes=settings.REPORT_STALE_MINUTES)
    recent = list(
        _visible_community_reports(crossing, now).filter(
            created_at__gt=stale_after
        )
    )
    return _derive_from_reports(recent, now)


def derive_statuses(crossings, now=None):
    """Bulk-derive statuses for many crossings in one query.

    Returns ``{crossing_pk: CrossingStatus}`` with an entry for every
    input crossing (``unknown`` when it has no reports). Empty input
    returns ``{}`` without touching the database.
    """
    now = now or timezone.now()
    crossings = list(crossings)
    if not crossings:
        return {}
    stale_after = now - timedelta(minutes=settings.REPORT_STALE_MINUTES)
    reports = CrossingReport.objects.filter(
        crossing_id__in=[c.pk for c in crossings],
        source=CrossingReport.SOURCE_COMMUNITY,
        moderation_status=CrossingReport.MODERATION_VISIBLE,
        created_at__lte=now,
        created_at__gt=stale_after,
    ).order_by("crossing_id", "-created_at")
    grouped = {c.pk: [] for c in crossings}
    for report in reports:
        grouped[report.crossing_id].append(report)
    return {
        c.pk: _derive_from_reports(grouped[c.pk], now) for c in crossings
    }


@transaction.atomic
def create_report(user, crossing, state, now=None):
    """Create a community report, or return an existing duplicate.

    Returns ``(report, created)``. Raises ``ReportNotAllowed``,
    ``RateLimited`` or ``ValidationError``.
    """
    now = now or timezone.now()

    if user is None or not user.is_authenticated or not user.is_active:
        raise ReportNotAllowed("Only signed-in users can submit reports.")
    if not crossing.is_active or crossing.is_suppressed:
        raise ReportNotAllowed("This crossing does not accept reports.")
    if state not in (CrossingReport.STATE_OPEN, CrossingReport.STATE_CLOSED):
        raise ValidationError({"state": "State must be 'open' or 'closed'."})

    # Serialize report creation per user (no Redis needed).
    user = get_user_model().objects.select_for_update().get(pk=user.pk)

    duplicate_since = now - timedelta(
        minutes=settings.REPORT_DUPLICATE_WINDOW_MINUTES
    )
    duplicate = (
        CrossingReport.objects.filter(
            reporter=user,
            crossing=crossing,
            reported_state=state,
            moderation_status=CrossingReport.MODERATION_VISIBLE,
            created_at__gte=duplicate_since,
        )
        .order_by("-created_at")
        .first()
    )
    if duplicate is not None:
        return duplicate, False

    latest = (
        CrossingReport.objects.filter(reporter=user, crossing=crossing)
        .order_by("-created_at")
        .first()
    )
    min_flip = settings.REPORT_MIN_FLIP_SECONDS
    if (
        latest is not None
        and latest.reported_state != state
        and (now - latest.created_at).total_seconds() < min_flip
    ):
        wait = min_flip - (now - latest.created_at).total_seconds()
        raise RateLimited(wait)

    hour_ago = now - timedelta(hours=1)
    recent_user_reports = CrossingReport.objects.filter(
        reporter=user, created_at__gte=hour_ago
    ).order_by("created_at")
    if recent_user_reports.count() >= settings.REPORT_MAX_PER_HOUR:
        oldest = recent_user_reports.first()
        retry = (oldest.created_at + timedelta(hours=1) - now).total_seconds()
        raise RateLimited(max(1, retry))

    report = CrossingReport.objects.create(
        crossing=crossing,
        reported_state=state,
        source=CrossingReport.SOURCE_COMMUNITY,
        reporter=user,
        created_at=now,
        expires_at=now + timedelta(minutes=settings.REPORT_FRESH_MINUTES),
    )
    return report, True


def public_recent_reports(crossing, now=None, limit=20):
    """Visible community reports from the stale window, anonymised."""
    now = now or timezone.now()
    stale_after = now - timedelta(minutes=settings.REPORT_STALE_MINUTES)
    return list(
        _visible_community_reports(crossing, now).filter(
            created_at__gt=stale_after
        )[:limit]
    )
