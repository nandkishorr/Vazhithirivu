"""WebSocket consumer for crossing status pushes (ADR-014).

Clients subscribe by crossing ID only — the same public statuses the
map already shows. There is no channel for private data or other
users' locations: a connection can only ever join ``crossing.<pk>``
groups for active, non-suppressed crossings.
"""
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.utils import timezone

from railways.models import RailwayCrossing

from .payloads import DISCLAIMER, policy_payload, status_payload
from .services import derive_statuses
from .updates import group_name


class CrossingStatusConsumer(AsyncJsonWebsocketConsumer):
    """Pushes server-derived crossing statuses to subscribed clients."""

    async def connect(self):
        self.subscribed_ids = set()
        self._last_subscribe_at = 0.0
        await self.accept()

    async def disconnect(self, code):
        layer = self.channel_layer
        if layer is not None:
            for pk in getattr(self, "subscribed_ids", ()):
                await layer.group_discard(group_name(pk), self.channel_name)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict) or content.get("type") != "subscribe":
            await self.send_json({"type": "error", "code": "invalid_message"})
            return
        ids = content.get("crossing_ids")
        if (
            not isinstance(ids, list)
            or len(ids) > settings.REALTIME_MAX_SUBSCRIPTIONS
        ):
            await self.send_json(
                {"type": "error", "code": "invalid_crossing_ids"}
            )
            return
        if any(
            not isinstance(pk, int) or isinstance(pk, bool) for pk in ids
        ):
            await self.send_json(
                {"type": "error", "code": "invalid_crossing_ids"}
            )
            return
        requested = set(ids)

        now = time.monotonic()
        elapsed = now - self._last_subscribe_at
        min_interval = settings.REALTIME_SUBSCRIBE_MIN_SECONDS
        if elapsed < min_interval:
            await self.send_json(
                {
                    "type": "error",
                    "code": "rate_limited",
                    "retry_after_seconds": round(min_interval - elapsed, 3),
                }
            )
            return
        self._last_subscribe_at = now

        # Suppressed/inactive IDs are silently dropped: the response does
        # not reveal which of the requested IDs exist but are hidden.
        valid = await self._reportable_ids(requested)
        for pk in self.subscribed_ids - valid:
            await self.channel_layer.group_discard(
                group_name(pk), self.channel_name
            )
        for pk in valid - self.subscribed_ids:
            await self.channel_layer.group_add(
                group_name(pk), self.channel_name
            )
        self.subscribed_ids = valid
        await self.send_json(await self._snapshot(valid))

    async def crossing_status(self, event):
        """Forward a channel-layer ``crossing.status`` event as JSON."""
        await self.send_json(event["payload"])

    @database_sync_to_async
    def _reportable_ids(self, requested):
        return set(
            RailwayCrossing.objects.filter(
                pk__in=requested, is_active=True, is_suppressed=False
            ).values_list("pk", flat=True)
        )

    @database_sync_to_async
    def _snapshot(self, crossing_ids):
        """Current statuses for the whole subscription in one query."""
        now = timezone.now()
        crossings = RailwayCrossing.objects.filter(pk__in=crossing_ids)
        statuses = derive_statuses(crossings, now=now)
        return {
            "type": "status.snapshot",
            "statuses": {
                str(pk): status_payload(status, now)
                for pk, status in statuses.items()
            },
            "policy": policy_payload(),
            "as_of": now.isoformat(),
            "official": False,
            "disclaimer": DISCLAIMER,
        }
