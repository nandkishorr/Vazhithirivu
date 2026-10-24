"""Realtime crossing-status pushes: publish, signals, consumer rules."""
from unittest.mock import patch

from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.test import TestCase, TransactionTestCase, override_settings

from config.asgi import application
from incidents.updates import group_name, publish_crossing_status
from railways.models import RailwayCrossing

WS_PATH = "/ws/crossings/"
WS_HEADERS = [(b"origin", b"http://localhost")]


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


class FakeLayer:
    """Channel-layer stub: records group_send calls."""

    def __init__(self):
        self.sent = []

    async def group_send(self, group, message):
        self.sent.append((group, message))


class PublishTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        self.layer = FakeLayer()
        patcher = patch(
            "incidents.updates.get_channel_layer", return_value=self.layer
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def last_payload(self):
        return self.layer.sent[-1][1]["payload"]

    def test_pushes_derived_status_with_provenance(self):
        publish_crossing_status(self.crossing.pk)
        self.assertEqual(len(self.layer.sent), 1)
        group, message = self.layer.sent[0]
        self.assertEqual(group, group_name(self.crossing.pk))
        self.assertEqual(message["type"], "crossing.status")
        payload = message["payload"]
        self.assertEqual(payload["type"], "crossing.status")
        self.assertEqual(payload["crossing_id"], self.crossing.pk)
        self.assertEqual(payload["status"]["state"], "unknown")
        self.assertFalse(payload["official"])
        self.assertIn("not official", payload["disclaimer"])
        self.assertIn("as_of", payload)
        self.assertIn("stale_minutes", payload["policy"])

    def test_identical_status_is_coalesced(self):
        publish_crossing_status(self.crossing.pk)
        publish_crossing_status(self.crossing.pk)
        self.assertEqual(len(self.layer.sent), 1)

    def test_changed_status_pushes_again(self):
        user = get_user_model().objects.create_user("r", password="pw")
        publish_crossing_status(self.crossing.pk)
        publish_crossing_status(self.crossing.pk)
        # A real report changes the derived status -> a second push.
        from incidents.services import create_report

        create_report(user, self.crossing, "closed")
        publish_crossing_status(self.crossing.pk)
        self.assertEqual(len(self.layer.sent), 2)
        self.assertEqual(
            self.last_payload()["status"]["state"], "closed_reported"
        )

    def test_inactive_or_suppressed_crossing_not_published(self):
        publish_crossing_status(self.crossing.pk)
        self.crossing.is_suppressed = True
        self.crossing.save()
        publish_crossing_status(self.crossing.pk)
        self.assertEqual(len(self.layer.sent), 1)

    def test_no_layer_is_a_no_op(self):
        with patch(
            "incidents.updates.get_channel_layer", return_value=None
        ):
            publish_crossing_status(self.crossing.pk)  # must not raise

    def test_send_failure_does_not_raise(self):
        async def boom(group, message):
            raise RuntimeError("layer down")

        self.layer.group_send = boom
        publish_crossing_status(self.crossing.pk)  # must not raise
        # A failed send is not recorded as "last pushed", so the next
        # attempt still goes out even though the status is unchanged.
        publish_crossing_status(self.crossing.pk)
        self.assertEqual(len(self.layer.sent), 0)


class SignalTests(TransactionTestCase):
    """post_save/post_delete -> on_commit -> publish."""

    def setUp(self):
        self.crossing = make_crossing()
        self.user = get_user_model().objects.create_user("r", password="pw")
        self.layer = FakeLayer()
        patcher = patch(
            "incidents.updates.get_channel_layer", return_value=self.layer
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_new_report_publishes_after_commit(self):
        from incidents.services import create_report

        create_report(self.user, self.crossing, "closed")
        self.assertEqual(len(self.layer.sent), 1)
        group, message = self.layer.sent[0]
        self.assertEqual(group, group_name(self.crossing.pk))
        self.assertEqual(
            message["payload"]["status"]["state"], "closed_reported"
        )

    def test_moderation_change_republishes(self):
        from incidents.services import create_report

        report, _ = create_report(self.user, self.crossing, "closed")
        report.moderation_status = report.MODERATION_HIDDEN
        report.save()
        self.assertEqual(len(self.layer.sent), 2)
        self.assertEqual(
            self.layer.sent[1][1]["payload"]["status"]["state"], "unknown"
        )

    def test_report_delete_republishes(self):
        from incidents.services import create_report

        report, _ = create_report(self.user, self.crossing, "closed")
        self.assertEqual(len(self.layer.sent), 1)
        report.delete()
        # The status reverts to unknown -> a changed status is pushed.
        self.assertEqual(len(self.layer.sent), 2)
        self.assertEqual(
            self.layer.sent[1][1]["payload"]["status"]["state"], "unknown"
        )

    def test_suppressed_crossing_publishes_nothing(self):
        self.crossing.is_suppressed = True
        self.crossing.save()
        from incidents.services import create_report

        with self.assertRaises(Exception):
            create_report(self.user, self.crossing, "closed")
        self.assertEqual(self.layer.sent, [])


@override_settings(REALTIME_SUBSCRIBE_MIN_SECONDS=0)
class ConsumerTests(TransactionTestCase):
    """Subscribe/validate/deliver rules over a real ASGI app."""

    def setUp(self):
        self.crossing = make_crossing()
        self.hidden = make_crossing(is_suppressed=True)

    async def connect(self):
        communicator = WebsocketCommunicator(
            application, WS_PATH, headers=WS_HEADERS
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        return communicator

    async def test_subscribe_sends_snapshot(self):
        communicator = await self.connect()
        await communicator.send_json_to(
            {"type": "subscribe", "crossing_ids": [self.crossing.pk]}
        )
        message = await communicator.receive_json_from(timeout=5)
        self.assertEqual(message["type"], "status.snapshot")
        self.assertIn(str(self.crossing.pk), message["statuses"])
        self.assertEqual(
            message["statuses"][str(self.crossing.pk)]["state"], "unknown"
        )
        self.assertFalse(message["official"])
        self.assertIn("not official", message["disclaimer"])
        self.assertIn("as_of", message)
        await communicator.disconnect()

    async def test_group_event_is_forwarded(self):
        communicator = await self.connect()
        await communicator.send_json_to(
            {"type": "subscribe", "crossing_ids": [self.crossing.pk]}
        )
        await communicator.receive_json_from(timeout=5)  # snapshot
        payload = {
            "type": "crossing.status",
            "crossing_id": self.crossing.pk,
            "status": {"state": "closed_reported"},
        }
        await get_channel_layer().group_send(
            group_name(self.crossing.pk),
            {"type": "crossing.status", "payload": payload},
        )
        message = await communicator.receive_json_from(timeout=5)
        self.assertEqual(message["crossing_id"], self.crossing.pk)
        self.assertEqual(
            message["status"]["state"], "closed_reported"
        )
        await communicator.disconnect()

    async def test_unsubscribed_crossing_gets_nothing(self):
        communicator = await self.connect()
        await communicator.send_json_to(
            {"type": "subscribe", "crossing_ids": [self.crossing.pk]}
        )
        await communicator.receive_json_from(timeout=5)
        other = await sync_to_async(make_crossing)()
        await get_channel_layer().group_send(
            group_name(other.pk),
            {"type": "crossing.status", "payload": {"type": "x"}},
        )
        self.assertTrue(await communicator.receive_nothing())
        await communicator.disconnect()

    async def test_resubscribe_replaces_subscription(self):
        communicator = await self.connect()
        await communicator.send_json_to(
            {"type": "subscribe", "crossing_ids": [self.crossing.pk]}
        )
        await communicator.receive_json_from(timeout=5)
        await communicator.send_json_to(
            {"type": "subscribe", "crossing_ids": []}
        )
        await communicator.receive_json_from(timeout=5)  # empty snapshot
        await get_channel_layer().group_send(
            group_name(self.crossing.pk),
            {"type": "crossing.status", "payload": {"type": "x"}},
        )
        self.assertTrue(await communicator.receive_nothing())
        await communicator.disconnect()

    async def test_suppressed_crossing_is_not_subscribable(self):
        communicator = await self.connect()
        await communicator.send_json_to(
            {"type": "subscribe", "crossing_ids": [self.hidden.pk]}
        )
        message = await communicator.receive_json_from(timeout=5)
        self.assertEqual(message["type"], "status.snapshot")
        self.assertEqual(message["statuses"], {})
        await get_channel_layer().group_send(
            group_name(self.hidden.pk),
            {"type": "crossing.status", "payload": {"type": "x"}},
        )
        self.assertTrue(await communicator.receive_nothing())
        await communicator.disconnect()

    async def test_invalid_messages_get_errors(self):
        communicator = await self.connect()
        for bad in (
            {"type": "nope"},
            "not a dict",
            {"type": "subscribe", "crossing_ids": "abc"},
            {"type": "subscribe", "crossing_ids": [1.5, "x"]},
        ):
            await communicator.send_json_to(bad)
            message = await communicator.receive_json_from(timeout=5)
            self.assertEqual(message["type"], "error", bad)
            self.assertIn(
                message["code"], ("invalid_message", "invalid_crossing_ids")
            )
        await communicator.disconnect()

    @override_settings(REALTIME_MAX_SUBSCRIPTIONS=2)
    async def test_too_many_ids_rejected(self):
        communicator = await self.connect()
        await communicator.send_json_to(
            {"type": "subscribe", "crossing_ids": [1, 2, 3]}
        )
        message = await communicator.receive_json_from(timeout=5)
        self.assertEqual(
            message, {"type": "error", "code": "invalid_crossing_ids"}
        )
        await communicator.disconnect()

    @override_settings(REALTIME_SUBSCRIBE_MIN_SECONDS=999)
    async def test_rapid_resubscribe_is_rate_limited(self):
        communicator = await self.connect()
        await communicator.send_json_to(
            {"type": "subscribe", "crossing_ids": [self.crossing.pk]}
        )
        message = await communicator.receive_json_from(timeout=5)
        self.assertEqual(message["type"], "status.snapshot")
        await communicator.send_json_to(
            {"type": "subscribe", "crossing_ids": []}
        )
        message = await communicator.receive_json_from(timeout=5)
        self.assertEqual(message["type"], "error")
        self.assertEqual(message["code"], "rate_limited")
        self.assertIn("retry_after_seconds", message)
        await communicator.disconnect()
