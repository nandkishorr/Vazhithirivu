"""Same-line status propagation tests (ADR-020).

A live closed/open state on a crossing is surfaced on its consecutive
same-line neighbours as ``*_inferred`` — never as a direct report.
Links (CrossingLink rows) are seeded directly here; topology building
is covered in railways/tests/test_topology.py.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from incidents import services
from incidents.models import CrossingReport
from incidents.payloads import effective_status_brief
from railways.models import CrossingLink, RailwayCrossing

NOW = timezone.now()


def make_crossing(lon=76.25, lat=9.95, **kwargs):
    defaults = {
        "source": "manual",
        "osm_type": "",
        "osm_id": None,
        "location": Point(lon, lat, srid=4326),
        "railway_value": "level_crossing",
    }
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


def make_report(crossing, user, state, age_seconds=0):
    created = NOW - timedelta(seconds=age_seconds)
    return CrossingReport.objects.create(
        crossing=crossing,
        reporter=user,
        reported_state=state,
        source=CrossingReport.SOURCE_COMMUNITY,
        created_at=created,
        expires_at=created + timedelta(minutes=settings.REPORT_FRESH_MINUTES),
        moderation_status=CrossingReport.MODERATION_VISIBLE,
    )


def link(from_crossing, to_crossing, rank=1, distance_m=500):
    return CrossingLink.objects.create(
        from_crossing=from_crossing,
        to_crossing=to_crossing,
        rank=rank,
        distance_m=distance_m,
    )


class PropagationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("reporter")
        self.a = make_crossing(76.25, 9.95, name="Gate A")
        self.b = make_crossing(76.26, 9.95, name="Gate B")
        self.c = make_crossing(76.27, 9.95, name="Gate C")
        self.d = make_crossing(76.28, 9.95, name="Gate D")
        link(self.b, self.a, rank=1)
        link(self.c, self.b, rank=1, distance_m=600)
        link(self.c, self.d, rank=2, distance_m=1100)
        link(self.d, self.c, rank=1)

    def status(self, crossing):
        return services.effective_status(crossing, now=NOW)

    def test_closed_report_propagates_to_linked_crossing(self):
        make_report(self.a, self.user, "closed")
        status = self.status(self.b)
        self.assertEqual(status.state, services.STATE_CLOSED_INFERRED)
        self.assertTrue(status.inferred)
        self.assertEqual(status.inference["from_crossing_id"], self.a.pk)
        self.assertEqual(status.inference["from_name"], "Gate A")
        self.assertFalse(status.inference["simulated"])

    def test_closed_propagates_one_hop_only(self):
        make_report(self.a, self.user, "closed")
        # B links to A (inferred) — C links to B and D. B's inferred
        # state is never a propagation source, so C sees nothing from it.
        self.assertEqual(self.status(self.b).state, "closed_inferred")
        self.assertEqual(self.status(self.c).state, services.STATE_UNKNOWN)

    def test_open_report_propagates_open_inferred(self):
        make_report(self.a, self.user, "open")
        self.assertEqual(
            self.status(self.b).state, services.STATE_OPEN_INFERRED
        )

    def test_direct_report_outranks_inference(self):
        make_report(self.a, self.user, "closed")
        make_report(self.b, self.user, "open")
        self.assertEqual(
            self.status(self.b).state, services.STATE_OPEN_REPORTED
        )

    def test_closed_source_wins_over_open_source(self):
        make_report(self.d, self.user, "open")
        make_report(self.b, self.user, "closed")
        # C links to B (rank 1, closed) and D (rank 2, open).
        status = self.status(self.c)
        self.assertEqual(status.state, services.STATE_CLOSED_INFERRED)
        self.assertEqual(status.inference["from_crossing_id"], self.b.pk)

    def test_inferred_state_fills_stale_crossing(self):
        make_report(self.a, self.user, "closed")
        # Past REPORT_FRESH_MINUTES but inside REPORT_STALE_MINUTES.
        make_report(self.b, self.user, "open", age_seconds=30 * 60)
        status = self.status(self.b)
        self.assertEqual(status.state, services.STATE_CLOSED_INFERRED)
        self.assertEqual(status.community.state, services.STATE_STALE)

    def test_no_links_means_no_inference(self):
        make_report(self.a, self.user, "closed")
        lonely = make_crossing(76.5, 9.99)
        self.assertEqual(
            self.status(lonely).state, services.STATE_UNKNOWN
        )

    def test_bulk_call_resolves_sources_outside_the_set(self):
        make_report(self.a, self.user, "closed")
        statuses = services.effective_statuses([self.b], now=NOW)
        self.assertEqual(
            statuses[self.b.pk].state, services.STATE_CLOSED_INFERRED
        )

    def test_brief_payload_exposes_inference(self):
        make_report(self.a, self.user, "closed")
        brief = effective_status_brief(self.status(self.b), NOW)
        self.assertEqual(brief["state"], "closed_inferred")
        self.assertTrue(brief["inferred"])
        self.assertEqual(
            brief["inference"]["from_crossing_id"], self.a.pk
        )
        self.assertEqual(brief["inference"]["source_state"], "closed_reported")

    def test_derive_statuses_stays_community_only(self):
        make_report(self.a, self.user, "closed")
        statuses = services.derive_statuses([self.b], now=NOW)
        self.assertEqual(statuses[self.b.pk].state, services.STATE_UNKNOWN)

    def test_suppressed_source_not_used(self):
        make_report(self.a, self.user, "closed")
        self.a.is_suppressed = True
        self.a.save()
        # A suppressed crossing is never a propagation source.
        self.assertEqual(self.status(self.b).state, services.STATE_UNKNOWN)


class SimulatedSourceTests(TestCase):
    """closed_simulated sources propagate, labelled as inference."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("reporter")
        self.a = make_crossing(76.25, 9.95)
        self.b = make_crossing(76.26, 9.95)
        link(self.b, self.a, rank=1)

    def test_simulated_closure_propagates_as_simulated_inference(self):
        overlay = {
            self.a.pk: {
                "gate_state": "closed",
                "run_id": 7,
                "label": "demo",
            }
        }
        # Restore whatever provider was registered (the simulator
        # registers its own at app-ready) — clearing it would leak
        # into other tests.
        previous = services._status_overlay_provider
        services.register_status_overlay(lambda crossings, now: overlay)
        try:
            status = services.effective_status(self.b, now=NOW)
            self.assertEqual(
                status.state, services.STATE_CLOSED_INFERRED
            )
            self.assertTrue(status.inference["simulated"])
            self.assertEqual(
                status.inference["source_state"], "closed_simulated"
            )
        finally:
            services.register_status_overlay(previous)
