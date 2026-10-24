import logging

from django.conf import settings
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)

CROSSING_MAP_LIMIT = 5000


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
    if settings.GOOGLE_MAPS_BROWSER_KEY:
        map_config = {
            "key": settings.GOOGLE_MAPS_BROWSER_KEY,
            "mapId": settings.GOOGLE_MAPS_MAP_ID,
            "center": [settings.MAP_DEFAULT_LAT, settings.MAP_DEFAULT_LNG],
            "zoom": settings.MAP_DEFAULT_ZOOM,
            "region": "IN",
            "language": "en",
        }

    crossings = None
    crossing_count = 0
    if map_config is not None:
        from railways.models import RailwayCrossing

        qs = (
            RailwayCrossing.objects.filter(is_active=True, is_suppressed=False)
            .order_by("id")
            .only(
                "id",
                "location",
                "name",
                "crossing_barrier",
                "source",
                "osm_type",
                "osm_id",
            )
        )
        crossing_count = qs.count()
        crossings = [
            {
                "id": c.pk,
                "lat": c.location.y,
                "lng": c.location.x,
                "name": c.name,
                "barrier": c.crossing_barrier,
                "source": c.source,
                "osm_type": c.osm_type,
                "osm_id": c.osm_id,
            }
            for c in qs[:CROSSING_MAP_LIMIT]
        ]

    return render(
        request,
        "core/home.html",
        {
            "origin": request.GET.get("origin", ""),
            "destination": destination or "",
            "route_state": route_state,
            "map_config": map_config,
            "crossings": crossings,
            "crossing_count": crossing_count,
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
