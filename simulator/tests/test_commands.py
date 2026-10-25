"""Management command lifecycle: start/tick/pause/resume/stop/reset."""
from io import StringIO

from django.contrib.gis.geos import LineString, Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from incidents.models import CrossingReport
from railways.models import RailwayCrossing, RailwayTrack
from simulator.models import (
    SimulatedVehicle,
    SimulationGateEvent,
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


class CommandTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        make_track()
        self.out = StringIO()

    def cmd(self, *args):
        return call_command("simulator", *args, stdout=self.out)

    @override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
    def test_start_tick_gate_stop_reset(self):
        self.cmd(
            "start",
            "--vehicles",
            "4",
            "--seed",
            "51",
            "--duration",
            "120",
            "--gate",
            f"{self.crossing.pk}:2:4",
            "--auto-confirm",
        )
        run = SimulationRun.objects.get()
        self.assertEqual(run.status, "running")
        self.assertEqual(SimulatedVehicle.objects.count(), 4)
        self.assertEqual(run.seed, 51)
        self.assertEqual(
            run.config["gates"],
            [{"crossing_id": self.crossing.pk, "close_tick": 2, "open_tick": 4}],
        )
        self.cmd("tick", "--n", "2")
        run.refresh_from_db()
        self.assertEqual(run.ticks, 2)
        self.assertEqual(
            SimulationGateEvent.objects.get().gate_state, "closed"
        )
        self.cmd("stop")
        run.refresh_from_db()
        self.assertEqual(run.status, "stopped")
        self.assertIsNone(run.active_slot)
        self.cmd("reset")
        self.assertEqual(SimulationRun.objects.count(), 0)
        self.assertEqual(SimulationGateEvent.objects.count(), 0)
        self.assertEqual(CrossingReport.objects.count(), 0)
        self.assertEqual(RailwayCrossing.objects.count(), 1)

    def test_second_start_fails_without_force(self):
        self.cmd("start", "--vehicles", "2", "--seed", "1")
        with self.assertRaises(CommandError):
            call_command("simulator", "start", "--vehicles", "2")
        self.cmd("start", "--vehicles", "2", "--seed", "2", "--force")
        self.assertEqual(SimulationRun.objects.filter(status="running").count(), 1)

    def test_pause_resume_tick_guards(self):
        self.cmd("start", "--vehicles", "2", "--seed", "1")
        self.cmd("pause")
        with self.assertRaises(CommandError):
            call_command("simulator", "tick")
        self.cmd("resume")
        self.cmd("tick")
        run = SimulationRun.objects.get()
        self.assertEqual(run.ticks, 1)

    def test_random_gates_resolve(self):
        self.cmd(
            "start",
            "--vehicles",
            "2",
            "--seed",
            "7",
            "--random-gates",
            "1",
        )
        run = SimulationRun.objects.get()
        gates = run.config["gates"]
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0]["crossing_id"], self.crossing.pk)
        self.assertEqual(gates[0]["close_tick"], 3)
        self.assertEqual(gates[0]["open_tick"], 30)

    def test_status_and_no_active_errors(self):
        with self.assertRaises(CommandError):
            call_command("simulator", "stop")
        self.cmd("status")
        self.assertIn("No simulation runs", self.out.getvalue())
        self.cmd("start", "--vehicles", "2", "--seed", "1")
        self.out.truncate(0)
        self.cmd("status")
        self.assertIn('"status": "running"', self.out.getvalue())
