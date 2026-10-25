"""Simulation WebSocket consumer: subscribe, snapshot, tick, idle."""
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.gis.geos import LineString, Point
from django.test import TransactionTestCase

from config.asgi import application
from railways.models import RailwayCrossing, RailwayTrack
from simulator import engine, updates

LNG, LAT = 76.30, 10.00


class ConsumerTests(TransactionTestCase):
    def setUp(self):
        self.crossing = RailwayCrossing.objects.create(
            location=Point(LNG, LAT, srid=4326),
            railway_value="level_crossing",
            source="manual",
        )
        RailwayTrack.objects.create(
            geometry=LineString(
                (LNG, LAT - 0.01), (LNG, LAT + 0.01), srid=4326
            ),
            railway_value="rail",
            source="manual",
        )

    async def connect(self):
        comm = WebsocketCommunicator(
            application,
            "/ws/simulation/",
            headers=[(b"origin", b"http://localhost")],
        )
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        return comm

    async def test_idle_when_no_run(self):
        comm = await self.connect()
        await comm.send_json_to({"type": "subscribe"})
        msg = await comm.receive_json_from(timeout=5)
        self.assertEqual(msg["type"], "sim.idle")
        self.assertFalse(msg["active"])
        self.assertTrue(msg["simulated"])
        await comm.disconnect()

    async def test_snapshot_then_tick_delivery(self):
        run = await sync_to_async(engine.start_run)(
            vehicles=3, seed=31, duration_seconds=600
        )
        comm = await self.connect()
        await comm.send_json_to({"type": "subscribe"})
        msg = await comm.receive_json_from(timeout=5)
        self.assertEqual(msg["type"], "sim.snapshot")
        self.assertEqual(msg["run"]["id"], run.pk)
        self.assertEqual(len(msg["vehicles"]), 3)
        self.assertTrue(msg["simulated"])
        # A tick frame reaches the socket.
        await get_channel_layer().group_send(
            updates.group_name(run.pk),
            {"type": "sim.tick", "payload": {"type": "sim.tick", "n": 1}},
        )
        msg = await comm.receive_json_from(timeout=5)
        self.assertEqual(msg["n"], 1)
        await comm.disconnect()

    async def test_control_broadcast_reaches_client(self):
        comm = await self.connect()
        await comm.send_json_to({"type": "subscribe"})  # -> sim.idle
        await comm.receive_json_from(timeout=5)
        run = await sync_to_async(engine.start_run)(
            vehicles=2, seed=32, duration_seconds=600
        )
        msg = await comm.receive_json_from(timeout=5)
        self.assertEqual(msg["type"], "sim.run.started")
        self.assertEqual(msg["run"]["id"], run.pk)
        await comm.disconnect()

    async def test_prompt_broadcast_reaches_client(self):
        run = await sync_to_async(engine.start_run)(
            vehicles=8,
            seed=33,
            duration_seconds=600,
            tick_seconds=5,
            gates=[
                {
                    "crossing_id": self.crossing.pk,
                    "close_tick": 1,
                    "open_tick": None,
                }
            ],
        )
        comm = await self.connect()
        await comm.send_json_to({"type": "subscribe"})
        snapshot = await comm.receive_json_from(timeout=5)
        self.assertEqual(snapshot["type"], "sim.snapshot")
        self.assertEqual(snapshot["prompts"], [])
        # Ticks queue the staged users; after SIM_DWELL_SECONDS worth of
        # ticks the prompt is raised and broadcast.
        for _ in range(4):
            await sync_to_async(engine.tick_run)(run)
        seen_prompt = False
        for _ in range(6):
            msg = await comm.receive_json_from(timeout=5)
            if msg["type"] == "sim.prompt":
                seen_prompt = True
                self.assertEqual(
                    msg["prompt"]["crossing_id"], self.crossing.pk
                )
                self.assertEqual(msg["prompt"]["state"], "pending")
                self.assertTrue(msg["simulated"])
                break
        self.assertTrue(seen_prompt)
        await comm.disconnect()

    async def test_invalid_messages(self):
        comm = await self.connect()
        for bad in ({"type": "nope"}, "x", {"type": "subscribe", "run_id": "a"}):
            await comm.send_json_to(bad)
            msg = await comm.receive_json_from(timeout=5)
            self.assertEqual(msg["type"], "error", bad)
        await comm.disconnect()
