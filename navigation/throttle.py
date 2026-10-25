"""Per-client hourly cap on session starts (Django cache, ADR-017).

Mirrors ``routing.throttle``: the locmem cache is per-process, which is
adequate as a quota guard; Redis-backed when REDIS_URL is set.
"""
from django.conf import settings
from django.core.cache import cache


def _key(client_key):
    import datetime

    hour = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H")
    safe = "".join(
        ch if ch.isalnum() or ch in "-_." else "_" for ch in client_key
    )
    return f"navigation:start:{hour}:{safe}"


def allow_session_start(client_key):
    """Reserve one session start for ``client_key`` this clock hour."""
    limit = settings.NAV_MAX_SESSIONS_PER_HOUR
    key = _key(client_key or "anonymous")
    try:
        cache.add(key, 0, timeout=7200)
        return cache.incr(key) <= limit
    except Exception:
        return True
