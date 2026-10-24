import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from railways.models import RailwayCrossing
from railways.queries import BBoxError, crossings_in_bbox, parse_bbox

from .forms import CrossingReportForm
from .services import (
    RateLimited,
    ReportNotAllowed,
    create_report,
    derive_status,
    derive_statuses,
    public_recent_reports,
    status_label,
)

DISCLAIMER = (
    "Community-sourced and unverified; not official railway information. "
    "Absence of reports does not mean a gate is open."
)


def _get_reportable_crossing(pk):
    return get_object_or_404(
        RailwayCrossing, pk=pk, is_active=True, is_suppressed=False
    )


def _api_crossing_or_404(pk):
    try:
        return (
            RailwayCrossing.objects.get(
                pk=pk, is_active=True, is_suppressed=False
            ),
            None,
        )
    except RailwayCrossing.DoesNotExist:
        return None, JsonResponse({"error": "not_found"}, status=404)


def _status_payload(crossing, status, now):
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


def _status_brief(status, now):
    """The four status fields exposed by the bbox map endpoint."""
    payload = _status_payload(None, status, now)
    return {
        key: payload[key]
        for key in (
            "state",
            "label",
            "last_report_at",
            "last_report_age_seconds",
        )
    }


def _report_payload(report, now):
    return {
        "state": report.reported_state,
        "created_at": report.created_at.isoformat(),
        "age_seconds": max(0, int((now - report.created_at).total_seconds())),
        "source": report.source,
        "verified": False,
    }


def _policy_payload():
    return {
        "fresh_minutes": settings.REPORT_FRESH_MINUTES,
        "stale_minutes": settings.REPORT_STALE_MINUTES,
        "conflict_window_minutes": settings.REPORT_CONFLICT_WINDOW_MINUTES,
    }


def _render_detail(request, crossing, status_code=200):
    now = timezone.now()
    status = derive_status(crossing, now=now)
    reports = public_recent_reports(crossing, now=now)
    for report in reports:
        report.age_seconds = max(
            0, int((now - report.created_at).total_seconds())
        )
    return render(
        request,
        "incidents/crossing_detail.html",
        {
            "crossing": crossing,
            "status": status,
            "status_meta": status_label(status.state),
            "reports": reports,
            "report_form": CrossingReportForm(),
            "fresh_minutes": settings.REPORT_FRESH_MINUTES,
            "disclaimer": DISCLAIMER,
        },
        status=status_code,
    )


@require_safe
def crossing_detail(request, pk):
    crossing = _get_reportable_crossing(pk)
    return _render_detail(request, crossing)


@login_required
@require_POST
def crossing_report_submit(request, pk):
    crossing = _get_reportable_crossing(pk)
    form = CrossingReportForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please choose either open or closed.")
        return _render_detail(request, crossing, status_code=400)
    try:
        report, created = create_report(
            request.user, crossing, form.cleaned_data["state"]
        )
    except RateLimited as exc:
        messages.error(
            request,
            f"You're reporting too fast — try again in "
            f"{exc.retry_after_seconds} seconds.",
        )
    except ReportNotAllowed:
        messages.error(request, "This crossing does not accept reports.")
    else:
        if created:
            messages.success(request, "Thanks — your report was recorded.")
        else:
            messages.info(
                request, "You already reported this a moment ago."
            )
    return redirect("crossing_detail", pk=crossing.pk)


@never_cache
@require_safe
def api_crossings_in_bbox(request):
    """Crossings inside a bounded bbox, with derived community status.

    Two queries total regardless of result size (crossings + reports).
    """
    try:
        bbox = parse_bbox(
            request.GET.get("bbox"), settings.MAP_BBOX_MAX_SPAN_DEG
        )
    except BBoxError as exc:
        if exc.code == "bbox_too_large":
            return JsonResponse(
                {
                    "error": "bbox_too_large",
                    "max_span_degrees": settings.MAP_BBOX_MAX_SPAN_DEG,
                },
                status=400,
            )
        return JsonResponse({"error": "invalid_bbox"}, status=400)

    limit = settings.MAP_CROSSINGS_LIMIT
    crossings, truncated = crossings_in_bbox(bbox, limit)
    now = timezone.now()
    statuses = derive_statuses(crossings, now=now)
    return JsonResponse(
        {
            "bbox": list(bbox),
            "count": len(crossings),
            "limit": limit,
            "truncated": truncated,
            "crossings": [
                {
                    "id": c.pk,
                    "lat": round(c.location.y, 6),
                    "lng": round(c.location.x, 6),
                    "name": c.name,
                    "barrier": c.crossing_barrier,
                    "source": c.source,
                    "osm_type": c.osm_type,
                    "osm_id": c.osm_id,
                    "status": _status_brief(statuses[c.pk], now),
                }
                for c in crossings
            ],
            "official": False,
            "disclaimer": DISCLAIMER,
            "attribution": "Crossing locations © OpenStreetMap contributors",
        }
    )


@never_cache
@require_safe
def api_crossing_status(request, pk):
    crossing, error = _api_crossing_or_404(pk)
    if error:
        return error
    now = timezone.now()
    status = derive_status(crossing, now=now)
    reports = public_recent_reports(crossing, now=now)
    return JsonResponse(
        {
            "crossing": {
                "id": crossing.pk,
                "name": crossing.name or "",
                "source": crossing.source,
            },
            "status": _status_payload(crossing, status, now),
            "recent_reports": [
                _report_payload(r, now) for r in reports
            ],
            "policy": _policy_payload(),
            "official": False,
            "disclaimer": DISCLAIMER,
        }
    )


@require_http_methods(["POST"])
def api_crossing_reports(request, pk):
    crossing, error = _api_crossing_or_404(pk)
    if error:
        return error
    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "error": "authentication_required",
                "login_url": settings.LOGIN_URL,
            },
            status=401,
        )

    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "invalid_json"}, status=400)
        if not isinstance(data, dict):
            return JsonResponse({"error": "invalid_json"}, status=400)
    else:
        data = request.POST

    form = CrossingReportForm(data)
    if not form.is_valid():
        return JsonResponse(
            {"error": "validation_error", "fields": form.errors.get_json_data()},
            status=400,
        )

    try:
        report, created = create_report(
            request.user, crossing, form.cleaned_data["state"]
        )
    except RateLimited as exc:
        response = JsonResponse(
            {
                "error": "rate_limited",
                "retry_after_seconds": exc.retry_after_seconds,
            },
            status=429,
        )
        response["Retry-After"] = str(exc.retry_after_seconds)
        return response
    except (ReportNotAllowed, ValidationError):
        return JsonResponse({"error": "not_found"}, status=404)

    now = timezone.now()
    status = derive_status(crossing, now=now)
    return JsonResponse(
        {
            "created": created,
            "report": _report_payload(report, now),
            "status": _status_payload(crossing, status, now),
            "official": False,
            "disclaimer": DISCLAIMER,
        },
        status=201 if created else 200,
    )
