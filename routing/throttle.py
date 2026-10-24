"""Per-client hourly throttle for routing provider calls (Django cache).

Provider calls cost money, so only requests that actually reach the
provider are counted. The local-memory cache is per-process — adequate at
this scale; swap the cache backend to Redis if multi-worker quota
enforcement is needed.
"""
from django.conf import settings
from django.core.cache import cache


def _key(client_key):
    import datetime

    hour = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H")
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in client_key)
    return f"routing:provider:{hour}:{safe}"


def allow_request(client_key):
    """Reserve one provider call for ``client_key`` this clock hour.

    Returns ``True`` when the call may proceed. Not atomic across
    processes on the locmem backend — acceptable for a quota guard.
    """
    limit = settings.ROUTING_MAX_REQUESTS_PER_HOUR
    key = _key(client_key or "anonymous")
    try:
        cache.add(key, 0, timeout=7200)
        return cache.incr(key) <= limit
    except Exception:
        return True
