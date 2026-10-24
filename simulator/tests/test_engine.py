"""Engine tests: spawn determinism, ticking, gates, lifecycle."""
from django.contrib.gis.geos import LineString, Point
from django.test import TestCase

from incidents.services import effective_status
from railways.models import RailwayCrossing, RailwayTrack
from simulator import engine
from simulator.engine import SimulatorError
from simulator.models import (
    SimulatedVehicle,
    SimulationEvent,
    SimulationGateEvent,
    SimulationRun,
)
from simulator.status import active_run, gate_states_for_run

LNG, LAT = 76.30, 10.00


def make_crossing(**kwargs):
    defaults = dict(
        location=Point(LNG, LAT, srid=4326),
        railway_value="level_crossing",
        source="manual",
        name="Test crossing",
    )
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


def make_track(**kwargs):
    defaults = dict(
        geometry=LineString(
            (LNG, LAT - 0.01), (LNG, LAT + 0.01), srid=4326
        ),
        railway_value="rail",
        source="manual",
    )
    defaults.update(kwargs)
    return RailwayTrack.objects.create(**defaults)


class SpawnTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.track = make_track()

    def test_same_seed_same_fleet(self):
        run1 = engine.start_run(vehicles=8, seed=42, duration_seconds=60)
        engine.stop_run(run1)
        run2 = engine.start_run(vehicles=8, seed=42, duration_seconds=60)
        v1 = list(run1.vehicles.order_by("index"))
        v2 = list(run2.vehicles.order_by("index"))
        self.assertEqual(len(v1), len(v2))
        for a, b in zip(v1, v2):
            self.assertEqual(tuple(a.path.coords), tuple(b.path.coords))
            self.assertEqual(a.progress_m, b.progress_m)
            self.assertEqual(a.speed_mps, b.speed_mps)
            self.assertEqual(a.direction, b.direction)

    def test_different_seed_different_fleet(self):
        run1 = engine.start_run(vehicles=8, seed=1, duration_seconds=60)
        engine.stop_run(run1)
        run2 = engine.start_run(vehicles=8, seed=2, duration_seconds=60)
        paths1 = {tuple(v.path.coords) for v in run1.vehicles.all()}
        paths2 = {tuple(v.path.coords) for v in run2.vehicles.all()}
        self.assertNotEqual(paths1, paths2)

    def test_vehicle_path_passes_through_a_crossing(self):
        engine.start_run(vehicles=5, seed=9, duration_seconds=60)
        crossing_points = {
            (c.location.x, c.location.y)
            for c in RailwayCrossing.objects.all()
        }
        for v in SimulatedVehicle.objects.all():
            self.assertIn(tuple(v.path.coords[2]), crossing_points)

    def test_no_crossings_fails_run(self):
        RailwayCrossing.objects.all().update(is_active=False)
        with self.assertRaises(SimulatorError):
            engine.start_run(vehicles=3, seed=1)
        run = SimulationRun.objects.first()
        self.assertEqual(run.status, SimulationRun.STATUS_FAILED)
        self.assertIsNone(run.active_slot)


class TickTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.track = make_track()
        self.run = engine.start_run(
            vehicles=6, seed=5, duration_seconds=1000, tick_seconds=5
        )

    def test_tick_advances_positions(self):
        before = {
            v.index: (v.progress_m, tuple(v.position.coords))
            for v in self.run.vehicles.all()
        }
        engine.tick_run(self.run)
        self.run.refresh_from_db()
        self.assertEqual(self.run.ticks, 1)
        moved = 0
        for v in self.run.vehicles.all():
            progress, pos = before[v.index]
            expected = progress + v.direction * v.speed_mps * 5
            self.assertAlmostEqual(v.progress_m, expected, places=4)
            if tuple(v.position.coords) != pos:
                moved += 1
        self.assertEqual(moved, len(before))

    def test_vehicle_bounces_at_path_end(self):
        v = self.run.vehicles.first()
        v.progress_m = v.path_length_m - 1
        v.direction = 1
        v.speed_mps = 10
        v.save()
        engine.tick_run(self.run)
        v.refresh_from_db()
        self.assertEqual(v.direction, -1)
        self.assertLess(v.progress_m, v.path_length_m)

    def test_gate_close_then_open_on_schedule(self):
        engine.stop_run(self.run)
        run = engine.start_run(
            vehicles=3,
            seed=6,
            duration_seconds=1000,
            tick_seconds=5,
            gates=[
                {
                    "crossing_id": self.crossing.pk,
                    "close_tick": 2,
                    "open_tick": 4,
                }
            ],
        )
        engine.tick_run(run)
        self.assertEqual(
            engine.gate_states_for_run(run), {}
        )
        engine.tick_run(run)
        self.assertEqual(
            gate_states_for_run(run), {self.crossing.pk: "closed"}
        )
        engine.tick_run(run)
        engine.tick_run(run)
        self.assertEqual(
            gate_states_for_run(run), {self.crossing.pk: "open"}
        )
        events = list(
            run.gate_events.order_by("tick").values_list(
                "tick", "gate_state"
            )
        )
        self.assertEqual(events, [(2, "closed"), (4, "open")])

    def test_run_finishes_at_duration(self):
        engine.stop_run(self.run)
        run = engine.start_run(
            vehicles=2, seed=7, duration_seconds=10, tick_seconds=5
        )
        engine.tick_run(run)
        summary = engine.tick_run(run)
        run.refresh_from_db()
        self.assertTrue(summary["finished"])
        self.assertEqual(run.status, SimulationRun.STATUS_FINISHED)
        self.assertIsNone(run.active_slot)
        self.assertIsNotNone(run.finished_at)

    def test_paused_run_does_not_tick(self):
        engine.pause_run(self.run)
        result = engine.tick_run(self.run)
        self.assertIsNone(result)
        self.assertEqual(self.run.ticks, 0)


class LifecycleTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.track = make_track()

    def test_only_one_active_run(self):
        run = engine.start_run(vehicles=2, seed=1, duration_seconds=60)
        self.assertEqual(active_run().pk, run.pk)
        with self.assertRaises(SimulatorError):
            engine.start_run(vehicles=2, seed=2)
        engine.stop_run(run)

    def test_force_replaces_active_run(self):
        run1 = engine.start_run(vehicles=2, seed=1, duration_seconds=60)
        run2 = engine.start_run(vehicles=2, seed=2, force=True)
        run1.refresh_from_db()
        self.assertEqual(run1.status, SimulationRun.STATUS_STOPPED)
        self.assertEqual(active_run().pk, run2.pk)

    def test_active_slot_unique(self):
        self.assertIsNotNone(
            SimulationRun.objects.create(
                seed=1, status="running", active_slot=1
            )
        )
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SimulationRun.objects.create(
                    seed=2, status="paused", active_slot=1
                )

    def test_pause_resume_stop(self):
        run = engine.start_run(vehicles=2, seed=1, duration_seconds=60)
        engine.pause_run(run)
        self.assertEqual(run.status, "paused")
        self.assertEqual(active_run().pk, run.pk)  # pause keeps the slot
        engine.resume_run(run)
        self.assertEqual(run.status, "running")
        engine.stop_run(run)
        self.assertEqual(run.status, "stopped")
        self.assertIsNone(run.active_slot)
        self.assertIsNone(active_run())

    def test_stale_running_run_is_interrupted(self):
        from datetime import timedelta

        from django.utils import timezone

        run = engine.start_run(vehicles=2, seed=1, duration_seconds=60)
        SimulationRun.objects.filter(pk=run.pk).update(
            heartbeat_at=timezone.now() - timedelta(hours=1)
        )
        count = engine.interrupt_stale_runs()
        self.assertEqual(count, 1)
        run.refresh_from_db()
        self.assertEqual(run.status, "stopped")
        self.assertIn("interrupted", run.error)

    def test_events_logged(self):
        run = engine.start_run(vehicles=2, seed=1, duration_seconds=60)
        kinds = list(run.events.values_list("kind", flat=True))
        self.assertIn("run_started", kinds)
        engine.stop_run(run)
        kinds = list(run.events.values_list("kind", flat=True))
        self.assertIn("run_stopped", kinds)
        self.assertTrue(
            SimulationEvent.objects.filter(run=run).exists()
        )
