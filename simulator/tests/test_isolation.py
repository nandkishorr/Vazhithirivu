"""Isolation proofs: the simulator cannot touch real/reference data."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import LineString, Point
from django.test import TestCase, override_settings
from django.utils import timezone

from incidents.models import CrossingReport
from railways.models import (
    OsmImportRun,
    RailwayCrossing,
    RailwayTrack,
)
from simulator import engine
from simulator.models import (
    SimulatedVehicle,
    SimulationEvent,
    SimulationGateEvent,
    SimulationPrompt,
    SimulationRun,
)

LNG, LAT = 76.30, 10.00


def make_crossing(**kwargs):
    defaults = dict(
        location=Point(LNG, LAT, srid=4326),
        railway_value="level_crossing",
        source="manual",
    )
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


def make_track():
    return RailwayTrack.objects.create(
        geometry=LineString((LNG, LAT - 0.01), (LNG, LAT + 0.01), srid=4326),
        railway_value="rail",
        source="manual",
    )


class IsolationTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        make_track()
        self.user = get_user_model().objects.create_user(
            "reporter", password="x"
        )
        now = timezone.now()
        self.report = CrossingReport.objects.create(
            crossing=self.crossing,
            reporter=self.user,
            reported_state="closed",
            source=CrossingReport.SOURCE_COMMUNITY,
            created_at=now,
            expires_at=now + timedelta(minutes=settings.REPORT_FRESH_MINUTES),
        )

    def _snapshot_real_data(self):
        return {
            "reports": CrossingReport.objects.count(),
            "crossings": RailwayCrossing.objects.count(),
            "tracks": RailwayTrack.objects.count(),
            "users": get_user_model().objects.count(),
            "import_runs": OsmImportRun.objects.count(),
            "crossing_row": RailwayCrossing.objects.get(pk=self.crossing.pk),
        }

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_run_writes_no_community_reports(self):
        before = self._snapshot_real_data()
        run = engine.start_run(
            vehicles=5,
            seed=11,
            duration_seconds=1000,
            gates=[
                {
                    "crossing_id": self.crossing.pk,
                    "close_tick": 1,
                    "open_tick": None,
                }
            ],
        )
        engine.tick_run(run)
        engine.tick_run(run)
        # Even the presence-inference path — prompt + confirm — stays
        # inside simulator-owned tables.
        prompt = SimulationPrompt.objects.get()
        engine.confirm_prompt(prompt)
        engine.stop_run(run)
        after = self._snapshot_real_data()
        self.assertEqual(before["reports"], after["reports"])
        self.assertEqual(before["crossings"], after["crossings"])
        self.assertEqual(before["tracks"], after["tracks"])
        self.assertEqual(before["users"], after["users"])
        # The crossing row itself is unchanged (no live state written).
        self.assertEqual(
            before["crossing_row"].is_suppressed,
            after["crossing_row"].is_suppressed,
        )
        self.assertEqual(
            before["crossing_row"].location,
            after["crossing_row"].location,
        )
        # Sim rows exist and are simulation-owned.
        self.assertEqual(SimulatedVehicle.objects.count(), 5)
        self.assertEqual(SimulationGateEvent.objects.count(), 1)
        self.assertEqual(prompt.state, "confirmed")
        self.assertTrue(
            SimulationEvent.objects.filter(kind="run_started").exists()
        )

    def test_reset_deletes_only_simulator_rows(self):
        run = engine.start_run(
            vehicles=4,
            seed=12,
            duration_seconds=100,
            gates=[{"crossing_id": self.crossing.pk, "close_tick": 1}],
        )
        engine.tick_run(run)
        engine.stop_run(run)
        before = self._snapshot_real_data()
        result = engine.reset_simulation()
        self.assertGreater(result["deleted"], 0)
        self.assertEqual(SimulationRun.objects.count(), 0)
        self.assertEqual(SimulatedVehicle.objects.count(), 0)
        self.assertEqual(SimulationGateEvent.objects.count(), 0)
        self.assertEqual(SimulationEvent.objects.count(), 0)
        after = self._snapshot_real_data()
        # Every real/real-user table is byte-identical in count.
        for key in ("reports", "crossings", "tracks", "users", "import_runs"):
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(after["crossing_row"].location, before["crossing_row"].location)
        # The community report survives with its data intact.
        report = CrossingReport.objects.get(pk=self.report.pk)
        self.assertEqual(report.reported_state, "closed")
        self.assertEqual(report.reporter_id, self.user.pk)

    def test_reset_refuses_while_active(self):
        engine.start_run(vehicles=2, seed=13)
        from simulator.engine import SimulatorError

        with self.assertRaises(SimulatorError):
            engine.reset_simulation()

    def test_stopped_run_reset_still_keeps_reports(self):
        run = engine.start_run(vehicles=2, seed=14)
        engine.stop_run(run)
        engine.reset_simulation()
        self.assertEqual(CrossingReport.objects.count(), 1)

    def test_cascade_scoped_to_run(self):
        run1 = engine.start_run(vehicles=3, seed=15)
        engine.stop_run(run1)
        run2 = engine.start_run(vehicles=3, seed=16)
        engine.stop_run(run2)
        run1.delete()
        self.assertEqual(SimulatedVehicle.objects.count(), 3)  # run2's
        self.assertEqual(SimulationRun.objects.count(), 1)
        self.assertEqual(CrossingReport.objects.count(), 1)
