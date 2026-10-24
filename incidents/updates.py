"""Realtime crossing-status pushes (ADR-014).

Reports are persisted first; every durable write then republishes the
server-derived status to WebSocket subscribers of that crossing. The
derived status — never the raw report — is what gets pushed, so the
server stays authoritative for freshness/conflict display rules.
"""
import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.utils import timezone

from railways.models import RailwayCrossing

from .payloads import (
    DISCLAIMER,
    effective_status_payload,
    policy_payload,
)
from .services import effective_status

logger = logging.getLogger(__name__)

# How long an identical push fingerprint is remembered. This only
# suppresses redundant republishes; correctness never relies on it.
DEDUP_TTL_SECONDS = 300


def group_name(crossing_id):
    return f"crossing.{crossing_id}"


def build_push_payload(crossing, now=None):
    """The server-derived status frame sent to subscribers."""
    now = now or timezone.now()
    status = effective_status(crossing, now=now)
    return {
        "type": "crossing.status",
        "crossing_id": crossing.pk,
        "status": effective_status_payload(status, now),
        "policy": policy_payload(),
        "as_of": now.isoformat(),
        "official": False,
        "disclaimer": DISCLAIMER,
    }


def publish_crossing_status(crossing_id, now=None):
    """Push the current derived status to a crossing's subscribers.

    No-op when no channel layer is configured or the crossing is not
    publicly reportable (inactive or suppressed). Pushes whose derived
    status is identical to the last pushed one are suppressed via the
    shared cache — e.g. a bulk purge deleting only reports outside the
    stale window produces no visible change and no push. A failed send
    is logged and never breaks the caller; clients still converge via
    their periodic fallback refresh.
    """
    layer = get_channel_layer()
    if layer is None:
        return
    crossing = (
        RailwayCrossing.objects.filter(
            pk=crossing_id, is_active=True, is_suppressed=False
        )
        .only("pk")
        .first()
    )
    if crossing is None:
        return
    payload = build_push_payload(crossing, now=now)
    fingerprint = json.dumps(
        {"status": payload["status"], "policy": payload["policy"]},
        sort_keys=True,
    )
    cache_key = f"rt:push:{crossing_id}"
    if cache.get(cache_key) == fingerprint:
        return
    try:
        async_to_sync(layer.group_send)(
            group_name(crossing_id),
            {"type": "crossing.status", "payload": payload},
        )
    except Exception:
        logger.warning(
            "Realtime push failed for crossing %s", crossing_id, exc_info=True
        )
        return
    cache.set(cache_key, fingerprint, DEDUP_TTL_SECONDS)
