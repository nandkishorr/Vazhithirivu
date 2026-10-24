import logging

from django.conf import settings
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@require_safe
def home(request):
    destination = request.GET.get("destination")
    if destination is None:
        route_state = None
    elif not destination.strip():
        route_state = "empty"
    else:
        route_state = "unavailable"

    map_config = None
    has_crossings = False
    if settings.GOOGLE_MAPS_BROWSER_KEY:
        map_config = {
            "key": settings.GOOGLE_MAPS_BROWSER_KEY,
            "mapId": settings.GOOGLE_MAPS_MAP_ID,
            "center": [settings.MAP_DEFAULT_LAT, settings.MAP_DEFAULT_LNG],
            "zoom": settings.MAP_DEFAULT_ZOOM,
            "region": "IN",
            "language": "en",
            "crossingsUrl": reverse("api_crossings"),
            "crossingsMinZoom": settings.MAP_CROSSINGS_MIN_ZOOM,
            "bboxMaxSpan": settings.MAP_BBOX_MAX_SPAN_DEG,
        }
        from railways.models import RailwayCrossing

        has_crossings = RailwayCrossing.objects.filter(
            is_active=True, is_suppressed=False
        ).exists()

    return render(
        request,
        "core/home.html",
        {
            "origin": request.GET.get("origin", ""),
            "destination": destination or "",
            "route_state": route_state,
            "map_config": map_config,
            "has_crossings": has_crossings,
            "debug": settings.DEBUG,
        },
    )


@require_safe
def ui_gallery(request):
    if not settings.DEBUG:
        raise Http404
    return render(request, "core/ui_gallery.html")


@never_cache
@require_safe
def healthz(request):
    return JsonResponse({"status": "ok"})


@never_cache
@require_safe
def readyz(request):
    checks = {}
    ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception:
        logger.exception("readyz: database check failed")
        checks["database"] = "error"
        ok = False

    if ok:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT PostGIS_Lib_Version()")
                cursor.fetchone()
            checks["postgis"] = "ok"
        except Exception:
            logger.exception("readyz: postgis check failed")
            checks["postgis"] = "error"
            ok = False
    else:
        checks["postgis"] = "error"

    status = 200 if ok else 503
    body = {"status": "ok" if ok else "error", "checks": checks}
    return JsonResponse(body, status=status)
