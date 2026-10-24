"""WebSocket consumer for simulation frames (ADR-015).

Read-only and anonymous-safe: simulated vehicles/gates are public demo
data. Every connection joins ``sim.control`` for lifecycle broadcasts;
``{"type":"subscribe","run_id":…}`` (optional — defaults to the active
run) joins ``sim.run.<pk>`` and gets a ``sim.snapshot`` followed by
coarse ``sim.tick`` frames. There is nothing else to subscribe to.
"""
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from . import updates
from .models import SimulationRun
from .status import active_run, gate_states_for_run


class SimulationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.run_group = None
        await self.channel_layer.group_add(
            updates.CONTROL_GROUP, self.channel_name
        )
        await self.accept()

    async def disconnect(self, code):
        if self.channel_layer is None:
            return
        await self.channel_layer.group_discard(
            updates.CONTROL_GROUP, self.channel_name
        )
        if self.run_group:
            await self.channel_layer.group_discard(
                self.run_group, self.channel_name
            )

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict) or content.get("type") not in (
            "subscribe",
            "unsubscribe",
        ):
            await self.send_json(
                {"type": "error", "code": "invalid_message"}
            )
            return
        if content.get("type") == "unsubscribe":
            await self._leave_run_group()
            await self.send_json(
                {"type": "sim.idle", "active": False, "simulated": True}
            )
            return

        run_id = content.get("run_id")
        if run_id is not None and (
            not isinstance(run_id, int) or isinstance(run_id, bool)
        ):
            await self.send_json(
                {"type": "error", "code": "invalid_run_id"}
            )
            return
        snapshot = await self._snapshot(run_id)
        if snapshot is None:
            await self._leave_run_group()
            await self.send_json(
                {
                    "type": "sim.idle",
                    "active": False,
                    "simulated": True,
                    "as_of": timezone.now().isoformat(),
                }
            )
            return
        group, payload = snapshot
        await self._leave_run_group()
        await self.channel_layer.group_add(group, self.channel_name)
        self.run_group = group
        await self.send_json(payload)

    async def _leave_run_group(self):
        if self.run_group:
            await self.channel_layer.group_discard(
                self.run_group, self.channel_name
            )
            self.run_group = None

    async def sim_tick(self, event):
        await self.send_json(event["payload"])

    async def sim_run(self, event):
        await self.send_json(event["payload"])

    @database_sync_to_async
    def _snapshot(self, run_id):
        """Resolve the target run and build its snapshot payload."""
        if run_id is None:
            run = active_run()
        else:
            run = SimulationRun.objects.filter(pk=run_id).first()
        if run is None:
            return None
        from .engine import vehicle_frames

        payload = updates.build_snapshot(
            run, vehicle_frames(run), gate_states_for_run(run)
        )
        return updates.group_name(run.pk), payload
