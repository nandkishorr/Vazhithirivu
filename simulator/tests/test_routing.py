"""Demo flow proof: simulated gate blocks a route; alternatives verified."""
from unittest.mock import patch

from django.contrib.gis.geos import LineString, Point
from django.test import TestCase

from incidents.models import CrossingReport
from railways.models import RailwayCrossing, RailwayTrack
from routing.providers import RouteCandidate, Waypoint
from routing.services import plan_route
from simulator import engine
from simulator.models import SimulationGateEvent

LNG, LAT = 76.30, 10.00


def ew(offset=0.0):
    return LineString(
        (LNG - 0.01, LAT + offset), (LNG + 0.01, LAT + offset), srid=4326
    )


def ns():
    return LineString(
        (LNG, LAT - 0.01), (LNG, LAT + 0.01), srid=4326
    )


def candidate(index, geometry, labels=("DEFAULT_ROUTE",)):
    return RouteCandidate(
        index=index,
        geometry=geometry,
        distance_m=6000,
        duration_s=600,
        static_duration_s=600,
        description="",
        labels=labels,
        warnings=(),
    )


class FakeProvider:
    name = "fake"
    attribution = "Fake routes"
    traffic_aware = False

    def __init__(self, routes):
        self._routes = routes

    def compute_routes(self, origin, destination, intermediates=None):
        if intermediates:
            return []
        return list(self._routes)


class SimulatedBlockingTests(TestCase):
    def setUp(self):
        self.crossing = RailwayCrossing.objects.create(
            location=Point(LNG, LAT, srid=4326),
            railway_value="level_crossing",
            source="manual",
            name="Sim crossing",
        )
        RailwayTrack.objects.create(
            geometry=ns(), railway_value="rail", source="manual"
        )
        self.run = engine.start_run(vehicles=3, seed=61, duration_seconds=600)
        SimulationGateEvent.objects.create(
            run=self.run,
            crossing=self.crossing,
            gate_state="closed",
            tick=1,
        )
        patcher = patch("routing.providers.get_provider")
        self.mock_get_provider = patcher.start()
        self.addCleanup(patcher.stop)

    def _plan(self, routes):
        self.mock_get_provider.return_value = FakeProvider(routes)
        return plan_route(
            Waypoint(address="a"), Waypoint(address="b"), "sim-test"
        )

    def test_simulated_close_blocks_route_and_labels(self):
        plan = self._plan(
            [candidate(0, ew()), candidate(1, ew(0.00135), labels=())]
        )
        self.assertTrue(plan.ok)
        self.assertEqual(plan.warning_level, "closed_on_route")
        self.assertEqual(len(plan.blocking), 1)
        entry = plan.blocking[0]
        self.assertEqual(entry.status.state, "closed_simulated")
        self.assertTrue(entry.status.simulation)
        self.assertIn("(simulated)", plan.blocking_names)
        self.assertTrue(plan.blocking_all_simulated)
        # The verification flow still runs against the simulated block.
        self.assertEqual(plan.routes[1].verification, "verified")

    def test_simulated_block_writes_no_reports(self):
        self._plan([candidate(0, ew())])
        self.assertEqual(CrossingReport.objects.count(), 0)

    def test_overlay_gone_after_stop_unblocks_route(self):
        engine.stop_run(self.run)
        plan = self._plan([candidate(0, ew())])
        self.assertIsNone(plan.warning_level)
        self.assertEqual(plan.blocking, ())
