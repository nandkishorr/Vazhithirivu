"""Engine tests: spawn determinism, ticking, queues, prompts, lifecycle."""
from django.contrib.gis.geos import LineString, Point
from django.test import TestCase, override_settings

from incidents.services import effective_status
from railways.models import RailwayCrossing, RailwayTrack
from simulator import engine
from simulator.engine import SimulatorError
from simulator.models import (
    SimulatedVehicle,
    SimulationEvent,
    SimulationGateEvent,
    SimulationPrompt,
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

    def test_users_park_near_gated_crossing(self):
        run = engine.start_run(
            vehicles=8,
            seed=7,
            duration_seconds=60,
            gates=[
                {
                    "crossing_id": self.crossing.pk,
                    "close_tick": 5,
                    "open_tick": None,
                }
            ],
        )
        for v in run.vehicles.all():
            self.assertEqual(v.crossing_id, self.crossing.pk)
            self.assertFalse(v.waiting)  # parked, not yet "waiting"
            self.assertEqual(v.speed_mps, 0.0)
            d = engine._dist_m(
                (v.position.x, v.position.y),
                (self.crossing.location.x, self.crossing.location.y),
            )
            self.assertLess(d, 60)  # queue slots sit just short of the gate


class TickTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.track = make_track()
        self.run = engine.start_run(
            vehicles=6, seed=5, duration_seconds=1000, tick_seconds=5
        )

    def test_users_never_move(self):
        """Static simulated users keep their parked position forever."""
        before = {
            v.index: (v.progress_m, tuple(v.position.coords))
            for v in self.run.vehicles.all()
        }
        engine.tick_run(self.run)
        engine.tick_run(self.run)
        self.run.refresh_from_db()
        self.assertEqual(self.run.ticks, 2)
        for v in self.run.vehicles.all():
            progress, pos = before[v.index]
            self.assertEqual(v.progress_m, progress)
            self.assertEqual(tuple(v.position.coords), pos)

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_gate_close_waits_users_then_prompt_confirm_open(self):
        """Physical gate → parked users wait → prompt → confirm → reopen."""
        engine.stop_run(self.run)
        run = engine.start_run(
            vehicles=8,
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
        # Every simulated user is parked at the gated crossing.
        parked = list(run.vehicles.all())
        self.assertEqual(len(parked), 8)
        self.assertTrue(
            all(v.crossing_id == self.crossing.pk for v in parked)
        )
        positions = {v.index: tuple(v.position.coords) for v in parked}

        engine.tick_run(run)  # tick 1: gate still open — parked only
        self.assertEqual(
            SimulationPrompt.objects.count(), 0
        )
        self.assertEqual(gate_states_for_run(run), {})
        self.assertTrue(
            all(not v.waiting and v.wait_ticks == 0 for v in parked)
        )

        engine.tick_run(run)  # tick 2: gate closes → dwell → prompt
        prompt = SimulationPrompt.objects.get()
        self.assertEqual(prompt.state, SimulationPrompt.STATE_PENDING)
        self.assertEqual(prompt.crossing_id, self.crossing.pk)
        self.assertEqual(prompt.truth_close_tick, 2)
        self.assertGreaterEqual(len(prompt.waiting_vehicle_indexes), 1)
        # Parked users count as waiting without ever moving.
        for v in run.vehicles.all():
            self.assertTrue(v.waiting)
            self.assertGreaterEqual(v.wait_ticks, 1)
            self.assertEqual(
                tuple(v.position.coords), positions[v.index]
            )
        # Unconfirmed: no surfaced status.
        self.assertEqual(gate_states_for_run(run), {})
        self.assertEqual(
            effective_status(self.crossing).state, "unknown"
        )

        engine.confirm_prompt(prompt, note="test confirm")
        self.assertEqual(
            gate_states_for_run(run), {self.crossing.pk: "closed"}
        )
        self.assertEqual(
            effective_status(self.crossing).state, "closed_simulated"
        )

        engine.tick_run(run)  # tick 3: users still parked, still waiting
        engine.tick_run(run)  # tick 4: physical reopen → auto "open"
        self.assertEqual(
            gate_states_for_run(run), {self.crossing.pk: "open"}
        )
        events = list(
            run.gate_events.order_by("tick").values_list(
                "tick", "gate_state"
            )
        )
        self.assertEqual(events, [(2, "closed"), (4, "open")])
        # The open gate clears the waiting flags; users stay parked.
        for v in run.vehicles.all():
            self.assertFalse(v.waiting)
            self.assertEqual(v.wait_ticks, 0)
            self.assertEqual(
                tuple(v.position.coords), positions[v.index]
            )

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


class PromptTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.track = make_track()

    def _gated_run(self, open_tick=None, auto=False, **kwargs):
        kwargs.setdefault("vehicles", 8)
        kwargs.setdefault("seed", 42)
        kwargs.setdefault("duration_seconds", 1000)
        kwargs.setdefault("tick_seconds", 5)
        return engine.start_run(
            gates=[
                {
                    "crossing_id": self.crossing.pk,
                    "close_tick": 1,
                    "open_tick": open_tick,
                }
            ],
            auto_confirm=auto,
            **kwargs,
        )

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_prompt_raised_once_per_closure(self):
        run = self._gated_run()
        engine.tick_run(run)
        self.assertEqual(SimulationPrompt.objects.count(), 1)
        engine.tick_run(run)
        # No second prompt for the same closure cycle.
        self.assertEqual(SimulationPrompt.objects.count(), 1)
        prompt = SimulationPrompt.objects.get()
        self.assertEqual(prompt.state, "pending")

    @override_settings(
        SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100, SIM_DWELL_MIN_USERS=99
    )
    def test_min_users_not_met_no_prompt(self):
        run = self._gated_run()
        engine.tick_run(run)
        engine.tick_run(run)
        self.assertEqual(SimulationPrompt.objects.count(), 0)

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_dwell_counter_resets_when_gate_reopens(self):
        run = self._gated_run(open_tick=3)
        engine.tick_run(run)  # close_tick=1 → parked users wait
        v = run.vehicles.first()
        v.refresh_from_db()
        self.assertTrue(v.waiting)
        self.assertGreaterEqual(v.wait_ticks, 1)
        pos = tuple(v.position.coords)
        engine.tick_run(run)
        engine.tick_run(run)  # reopen tick
        v.refresh_from_db()
        self.assertFalse(v.waiting)
        self.assertEqual(v.wait_ticks, 0)
        # Static users never move — same parked spot throughout.
        self.assertEqual(tuple(v.position.coords), pos)

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_dismiss_prompt_surfaces_nothing(self):
        run = self._gated_run()
        engine.tick_run(run)
        prompt = SimulationPrompt.objects.get()
        engine.dismiss_prompt(prompt)
        self.assertEqual(prompt.state, "dismissed")
        self.assertEqual(gate_states_for_run(run), {})
        self.assertEqual(
            effective_status(self.crossing).state, "unknown"
        )
        with self.assertRaises(SimulatorError):
            engine.confirm_prompt(prompt)

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_confirm_twice_fails(self):
        run = self._gated_run()
        engine.tick_run(run)
        prompt = SimulationPrompt.objects.get()
        engine.confirm_prompt(prompt)
        with self.assertRaises(SimulatorError):
            engine.confirm_prompt(prompt)

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_prompt_ttl_expires(self):
        from datetime import timedelta

        from django.utils import timezone

        run = self._gated_run()
        engine.tick_run(run)
        prompt = SimulationPrompt.objects.get()
        later = timezone.now() + timedelta(
            seconds=600 + 1  # > SIM_PROMPT_TTL_SECONDS
        )
        engine.tick_run(run, now=later)
        prompt.refresh_from_db()
        self.assertEqual(prompt.state, "expired")

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_gate_reopen_expires_unanswered_prompt(self):
        run = self._gated_run(open_tick=3)
        engine.tick_run(run)
        prompt = SimulationPrompt.objects.get()
        engine.tick_run(run)
        engine.tick_run(run)  # reopen tick
        prompt.refresh_from_db()
        self.assertEqual(prompt.state, "expired")
        self.assertIn("reopened", prompt.resolved_note)
        # Nobody confirmed → nothing ever surfaced.
        self.assertEqual(SimulationGateEvent.objects.count(), 0)

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_stop_run_expires_pending_prompt(self):
        run = self._gated_run()
        engine.tick_run(run)
        prompt = SimulationPrompt.objects.get()
        engine.stop_run(run)
        prompt.refresh_from_db()
        self.assertEqual(prompt.state, "expired")

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_auto_confirm_writes_gate_event(self):
        run = self._gated_run(open_tick=3, auto=True)
        engine.tick_run(run)
        self.assertEqual(
            gate_states_for_run(run), {self.crossing.pk: "closed"}
        )
        prompt = SimulationPrompt.objects.get()
        self.assertEqual(prompt.state, "confirmed")
        engine.tick_run(run)
        engine.tick_run(run)  # reopen
        self.assertEqual(
            gate_states_for_run(run), {self.crossing.pk: "open"}
        )


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
