import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


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
