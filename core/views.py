import logging
import re

from django.conf import settings
from django.db import connection
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,300}$")


def _parse_coord(value, lo, hi):
    try:
        coord = float(value)
    except (TypeError, ValueError):
        return None
    return coord if lo <= coord <= hi else None


def _waypoint(place_id, address, lat_raw=None, lng_raw=None):
    from routing.providers import Waypoint

    safe_id = place_id if PLACE_ID_RE.match(place_id or "") else ""
    # Opt-in "my location" origin (ADR-005): coords are only honoured when
    # no place was picked and are never stored.
    lat = lng = None
    if not safe_id:
        lat = _parse_coord(lat_raw, -90, 90)
        lng = _parse_coord(lng_raw, -180, 180)
        if lat is None or lng is None:
            lat = lng = None
    return Waypoint(
        place_id=safe_id, address=(address or "")[:300], lat=lat, lng=lng
    )


@require_safe
def home(request):
    destination = request.GET.get("destination")
    origin = request.GET.get("origin", "")
    route_state = None
    route_plan = None
    route_data = None
    if destination is not None:
        if not destination.strip():
            route_state = "empty"
        elif not origin.strip():
            route_state = "missing_origin"
        elif not settings.GOOGLE_MAPS_BROWSER_KEY:
            # Google route content must be shown on a Google map.
            route_state = "unavailable"
        else:
            route_state = "planned"
            from routing.services import plan_route

            client_key = request.META.get("REMOTE_ADDR") or "anonymous"
            route_plan = plan_route(
                _waypoint(
                    request.GET.get("origin_place_id", ""),
                    origin,
                    request.GET.get("origin_lat"),
                    request.GET.get("origin_lng"),
                ),
                _waypoint(
                    request.GET.get("destination_place_id", ""),
                    destination,
                ),
                client_key=client_key,
            )
            route_data = _route_data(route_plan)

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
            "crossingsWsUrl": "%s://%s/ws/crossings/"
            % ("wss" if request.is_secure() else "ws", request.get_host()),
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
            "route_plan": route_plan,
            "route_data": route_data,
            "origin_place_id": request.GET.get("origin_place_id", ""),
            "destination_place_id": request.GET.get(
                "destination_place_id", ""
            ),
            "origin_lat": request.GET.get("origin_lat", ""),
            "origin_lng": request.GET.get("origin_lng", ""),
            "map_config": map_config,
            "has_crossings": has_crossings,
            "debug": settings.DEBUG,
        },
    )


def _route_data(plan):
    """JSON-safe route payload for the map; never includes secrets."""
    if plan is None or not plan.ok:
        return None
    routes = []
    for route in plan.routes:
        coords = []
        if route.candidate.geometry is not None:
            coords = [
                [round(lat, 6), round(lng, 6)]
                for lng, lat in route.candidate.geometry.coords
            ]
        routes.append(
            {
                "id": route.id,
                "primary": route.is_primary,
                "verification": route.verification,
                "coords": coords,
                "crossings": [
                    {
                        "id": e.crossing.crossing_id,
                        "lat": round(e.crossing.lat, 6),
                        "lng": round(e.crossing.lng, 6),
                        "state": e.status.state,
                        "match": e.crossing.match,
                        "name": e.crossing.name,
                    }
                    for e in route.crossings
                ],
            }
        )
    return {
        "routes": routes,
        "blocking": [
            e.crossing.name or "Unnamed level crossing" for e in plan.blocking
        ],
    }


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
