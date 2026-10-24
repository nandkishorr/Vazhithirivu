from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from incidents import services
from incidents.models import CrossingReport
from railways.models import RailwayCrossing

NOW = timezone.now()


def make_crossing(**kwargs):
    defaults = {
        "source": "manual",
        "osm_type": "",
        "osm_id": None,
        "location": Point(76.25, 9.95, srid=4326),
        "railway_value": "level_crossing",
    }
    defaults.update(kwargs)
    return RailwayCrossing.objects.create(**defaults)


def make_report(crossing, user, state, age_seconds=0, moderation="visible"):
    created = NOW - timedelta(seconds=age_seconds)
    return CrossingReport.objects.create(
        crossing=crossing,
        reporter=user,
        reported_state=state,
        source=CrossingReport.SOURCE_COMMUNITY,
        created_at=created,
        expires_at=created + timedelta(minutes=settings.REPORT_FRESH_MINUTES),
        moderation_status=moderation,
    )


class DeriveStatusTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.alice = get_user_model().objects.create_user("alice")
        self.bob = get_user_model().objects.create_user("bob")

    def test_no_reports_is_unknown(self):
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_UNKNOWN)
        self.assertIsNone(status.last_report_at)
        self.assertIsNone(status.last_reported_state)
        self.assertEqual(status.supporting_reports, 0)
        self.assertIsNone(status.fresh_until)

    def test_single_fresh_closed(self):
        make_report(self.crossing, self.alice, "closed", age_seconds=60)
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_CLOSED_REPORTED)
        self.assertEqual(status.supporting_reports, 1)
        self.assertEqual(status.opposing_reports, 0)
        self.assertEqual(status.last_reported_state, "closed")

    def test_report_20_minutes_old_is_stale(self):
        report = make_report(
            self.crossing, self.alice, "closed", age_seconds=20 * 60
        )
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_STALE)
        self.assertEqual(status.last_report_at, report.created_at)
        self.assertEqual(status.last_reported_state, "closed")
        self.assertEqual(status.supporting_reports, 0)

    def test_report_61_minutes_old_is_unknown(self):
        make_report(self.crossing, self.alice, "closed", age_seconds=61 * 60)
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_UNKNOWN)
        self.assertIsNone(status.last_report_at)

    def test_exactly_fresh_minutes_old_is_stale(self):
        # expires_at > now is strict, so an exactly-15-minute-old report
        # has just expired.
        make_report(
            self.crossing,
            self.alice,
            "closed",
            age_seconds=settings.REPORT_FRESH_MINUTES * 60,
        )
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_STALE)

    def test_only_hidden_reports_is_unknown(self):
        make_report(
            self.crossing,
            self.alice,
            "closed",
            age_seconds=60,
            moderation="hidden",
        )
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_UNKNOWN)

    def test_conflicting_reports_within_window(self):
        make_report(self.crossing, self.alice, "closed", age_seconds=120)
        make_report(self.crossing, self.bob, "open", age_seconds=60)
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_CONFLICTING)
        self.assertEqual(status.supporting_reports, 1)
        self.assertEqual(status.opposing_reports, 1)

    def test_older_opposite_report_is_transition_not_conflict(self):
        make_report(self.crossing, self.alice, "closed", age_seconds=12 * 60)
        make_report(self.crossing, self.bob, "open", age_seconds=2 * 60)
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_OPEN_REPORTED)
        self.assertEqual(status.supporting_reports, 1)
        self.assertEqual(status.opposing_reports, 0)

    def test_same_user_flip_is_deduped_not_conflicting(self):
        make_report(self.crossing, self.alice, "closed", age_seconds=120)
        make_report(self.crossing, self.alice, "open", age_seconds=60)
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_OPEN_REPORTED)
        self.assertEqual(status.supporting_reports, 1)
        self.assertEqual(status.opposing_reports, 0)

    def test_two_users_agree(self):
        make_report(self.crossing, self.alice, "closed", age_seconds=120)
        make_report(self.crossing, self.bob, "closed", age_seconds=60)
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_CLOSED_REPORTED)
        self.assertEqual(status.supporting_reports, 2)

    def test_same_user_repeat_counted_once(self):
        make_report(self.crossing, self.alice, "closed", age_seconds=120)
        make_report(self.crossing, self.alice, "closed", age_seconds=60)
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.supporting_reports, 1)

    def test_other_crossing_reports_ignored(self):
        other = make_crossing()
        make_report(other, self.alice, "closed", age_seconds=60)
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_UNKNOWN)

    def test_future_dated_report_ignored(self):
        make_report(self.crossing, self.alice, "closed", age_seconds=-300)
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_UNKNOWN)

    def test_deleted_reporter_still_counts(self):
        report = make_report(self.crossing, self.alice, "closed", age_seconds=60)
        report.reporter = None
        report.save()
        status = services.derive_status(self.crossing, now=NOW)
        self.assertEqual(status.state, services.STATE_CLOSED_REPORTED)
        self.assertEqual(status.supporting_reports, 1)


class DeriveStatusesTests(TestCase):
    def setUp(self):
        self.alice = get_user_model().objects.create_user("alice2")
        self.bob = get_user_model().objects.create_user("bob2")

    def test_empty_input_no_queries(self):
        with self.assertNumQueries(0):
            self.assertEqual(services.derive_statuses([]), {})

    def test_parity_with_derive_status_in_one_query(self):
        unknown_c = make_crossing()
        closed_c = make_crossing()
        make_report(closed_c, self.alice, "closed", age_seconds=60)
        open_c = make_crossing()
        make_report(open_c, self.alice, "open", age_seconds=60)
        stale_c = make_crossing()
        make_report(stale_c, self.alice, "closed", age_seconds=20 * 60)
        conflict_c = make_crossing()
        make_report(conflict_c, self.alice, "closed", age_seconds=120)
        make_report(conflict_c, self.bob, "open", age_seconds=60)
        hidden_c = make_crossing()
        make_report(
            hidden_c, self.alice, "closed", age_seconds=60,
            moderation="hidden",
        )
        crossings = [
            unknown_c, closed_c, open_c, stale_c, conflict_c, hidden_c,
        ]

        with self.assertNumQueries(1):
            statuses = services.derive_statuses(crossings, now=NOW)

        self.assertEqual(set(statuses), {c.pk for c in crossings})
        for c in crossings:
            with self.subTest(crossing=c.pk):
                self.assertEqual(
                    statuses[c.pk], services.derive_status(c, now=NOW)
                )

        states = {c.pk: statuses[c.pk].state for c in crossings}
        self.assertEqual(states[unknown_c.pk], services.STATE_UNKNOWN)
        self.assertEqual(states[closed_c.pk], services.STATE_CLOSED_REPORTED)
        self.assertEqual(states[open_c.pk], services.STATE_OPEN_REPORTED)
        self.assertEqual(states[stale_c.pk], services.STATE_STALE)
        self.assertEqual(states[conflict_c.pk], services.STATE_CONFLICTING)
        self.assertEqual(states[hidden_c.pk], services.STATE_UNKNOWN)
