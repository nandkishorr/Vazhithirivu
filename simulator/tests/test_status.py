"""Status overlay: simulated gates merge into effective statuses."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import LineString, Point
from django.test import TestCase
from django.utils import timezone

from incidents import services
from incidents.models import CrossingReport
from railways.models import RailwayCrossing, RailwayTrack
from simulator import engine
from simulator.models import SimulationGateEvent, SimulationRun
from simulator.status import active_gate_overrides

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


def make_run(**kwargs):
    return engine.start_run(
        vehicles=2, seed=3, duration_seconds=600, **kwargs
    )


def close_gate(run, crossing, tick=1, state="closed"):
    return SimulationGateEvent.objects.create(
        run=run, crossing=crossing, gate_state=state, tick=tick
    )


def community_report(crossing, user, state):
    now = timezone.now()
    return CrossingReport.objects.create(
        crossing=crossing,
        reporter=user,
        reported_state=state,
        source=CrossingReport.SOURCE_COMMUNITY,
        created_at=now,
        expires_at=now + timedelta(minutes=settings.REPORT_FRESH_MINUTES),
    )


class OverlayTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.other = make_crossing(location=Point(LNG + 0.01, LAT, srid=4326))
        make_track()

    def test_no_run_means_pure_community_status(self):
        effective = services.effective_status(self.crossing)
        self.assertEqual(effective.state, "unknown")
        self.assertIsNone(effective.simulation)
        self.assertFalse(effective.simulated)

    def test_simulated_close_overlays_unknown(self):
        run = make_run()
        close_gate(run, self.crossing)
        effective = services.effective_status(self.crossing)
        self.assertEqual(effective.state, "closed_simulated")
        self.assertTrue(effective.simulated)
        self.assertEqual(effective.simulation["run_id"], run.pk)
        self.assertEqual(effective.simulation["gate_state"], "closed")
        # The community status underneath is untouched.
        self.assertEqual(effective.community.state, "unknown")
        other = services.effective_status(self.other)
        self.assertEqual(other.state, "unknown")

    def test_simulated_open_overlays(self):
        run = make_run()
        close_gate(run, self.crossing, state="open")
        self.assertEqual(
            services.effective_status(self.crossing).state,
            "open_simulated",
        )

    def test_latest_gate_event_wins(self):
        run = make_run()
        close_gate(run, self.crossing, tick=1, state="closed")
        close_gate(run, self.crossing, tick=3, state="open")
        self.assertEqual(
            services.effective_status(self.crossing).state,
            "open_simulated",
        )

    def test_community_closed_outranks_simulated_open(self):
        user = get_user_model().objects.create_user("r", password="x")
        community_report(self.crossing, user, "closed")
        run = make_run()
        close_gate(run, self.crossing, state="open")
        effective = services.effective_status(self.crossing)
        self.assertEqual(effective.state, "closed_reported")
        # Provenance is still carried for labelling.
        self.assertEqual(effective.simulation["gate_state"], "open")
        self.assertEqual(effective.community.state, "closed_reported")

    def test_stopped_run_drops_overlay(self):
        run = make_run()
        close_gate(run, self.crossing)
        engine.stop_run(run)
        effective = services.effective_status(self.crossing)
        self.assertEqual(effective.state, "unknown")
        self.assertIsNone(effective.simulation)

    def test_finished_run_drops_overlay(self):
        run = make_run()
        run.status = SimulationRun.STATUS_FINISHED
        run.active_slot = None
        run.save()
        close_gate(run, self.crossing)
        self.assertEqual(
            services.effective_status(self.crossing).state, "unknown"
        )

    def test_paused_run_keeps_overlay(self):
        run = make_run()
        close_gate(run, self.crossing)
        engine.pause_run(run)
        self.assertEqual(
            services.effective_status(self.crossing).state,
            "closed_simulated",
        )

    def test_events_from_older_run_do_not_leak(self):
        run1 = make_run()
        close_gate(run1, self.crossing)
        engine.stop_run(run1)
        make_run()  # run2 has no gate events
        self.assertEqual(
            services.effective_status(self.crossing).state, "unknown"
        )

    def test_overlay_empty_for_empty_input(self):
        self.assertEqual(active_gate_overrides([]), {})

    def test_derive_status_stays_community_only(self):
        run = make_run()
        close_gate(run, self.crossing)
        # The pure community derivation never sees simulator rows.
        self.assertEqual(
            services.derive_status(self.crossing).state, "unknown"
        )
