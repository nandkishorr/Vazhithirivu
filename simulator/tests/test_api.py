"""HTTP surface: /api/simulation/ and sim labels in the crossings API."""
from django.contrib.gis.geos import LineString, Point
from django.test import TestCase, override_settings
from django.urls import reverse

from railways.models import RailwayCrossing, RailwayTrack
from simulator import engine
from simulator.models import SimulationGateEvent, SimulationPrompt

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


class SimulationApiTests(TestCase):
    def test_inactive(self):
        response = self.client.get(reverse("api_simulation_state"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["active"])
        self.assertTrue(data["simulated"])
        self.assertIn("not real traffic", data["disclaimer"])

    def test_active_run_payload(self):
        make_crossing()
        make_track()
        run = engine.start_run(vehicles=4, seed=21, duration_seconds=300)
        SimulationGateEvent.objects.create(
            run=run, crossing=RailwayCrossing.objects.get(), gate_state="closed", tick=1
        )
        response = self.client.get(reverse("api_simulation_state"))
        data = response.json()
        self.assertTrue(data["active"])
        self.assertTrue(data["simulated"])
        self.assertEqual(data["run"]["id"], run.pk)
        self.assertEqual(len(data["vehicles"]), 4)
        self.assertEqual(data["gates"], {str(RailwayCrossing.objects.get().pk): "closed"})
        self.assertIn("not real traffic", data["disclaimer"])
        engine.stop_run(run)
        data = self.client.get(reverse("api_simulation_state")).json()
        self.assertFalse(data["active"])


@override_settings(SIM_DWELL_SECONDS=0, SIM_DWELL_RADIUS_M=100)
class SimulationPromptApiTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        make_track()
        self.run = engine.start_run(
            vehicles=8,
            seed=41,
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
        engine.tick_run(self.run)
        self.prompt = SimulationPrompt.objects.get()

    def _confirm(self):
        return self.client.post(
            reverse("api_simulation_prompt_confirm", args=[self.prompt.pk])
        )

    def _dismiss(self):
        return self.client.post(
            reverse("api_simulation_prompt_dismiss", args=[self.prompt.pk])
        )

    def test_state_payload_lists_pending_prompt(self):
        data = self.client.get(reverse("api_simulation_state")).json()
        self.assertEqual(len(data["prompts"]), 1)
        prompt = data["prompts"][0]
        self.assertEqual(prompt["id"], self.prompt.pk)
        self.assertEqual(prompt["crossing_id"], self.crossing.pk)
        self.assertGreaterEqual(prompt["waiting_users"], 1)
        self.assertEqual(prompt["state"], "pending")
        self.assertTrue(prompt["simulated"])
        self.assertIn("confirm", prompt["confirm_url"])
        self.assertIn("dismiss", prompt["dismiss_url"])

    def test_confirm_marks_gate_simulated_closed(self):
        response = self._confirm()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["prompt"]["state"], "confirmed")
        self.assertEqual(
            body["gates"], {str(self.crossing.pk): "closed"}
        )
        event = SimulationGateEvent.objects.get()
        self.assertEqual(event.gate_state, "closed")
        # The shared status endpoint shows the confirmed closure.
        status = self.client.get(
            reverse("api_crossing_status", args=[self.crossing.pk])
        ).json()["status"]
        self.assertEqual(status["state"], "closed_simulated")
        # No pending prompts remain in the polling payload.
        data = self.client.get(reverse("api_simulation_state")).json()
        self.assertEqual(data["prompts"], [])

    def test_confirm_twice_is_conflict(self):
        self._confirm()
        response = self._confirm()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"], "not_resolvable")

    def test_dismiss_keeps_gate_unsurfaced(self):
        response = self._dismiss()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["prompt"]["state"], "dismissed")
        self.assertEqual(SimulationGateEvent.objects.count(), 0)

    def test_unknown_prompt_404(self):
        response = self.client.post(
            reverse("api_simulation_prompt_confirm", args=[99999])
        )
        self.assertEqual(response.status_code, 404)

    def test_get_method_not_allowed(self):
        response = self.client.get(
            reverse("api_simulation_prompt_confirm", args=[self.prompt.pk])
        )
        self.assertEqual(response.status_code, 405)


class BboxSimLabelTests(TestCase):
    def setUp(self):
        self.crossing = make_crossing()
        make_track()
        self.bbox = f"{LNG - 0.01},{LAT - 0.01},{LNG + 0.01},{LAT + 0.01}"

    def test_bbox_marks_simulated_status(self):
        run = engine.start_run(vehicles=2, seed=22)
        SimulationGateEvent.objects.create(
            run=run, crossing=self.crossing, gate_state="closed", tick=1
        )
        response = self.client.get(f"/api/crossings/?bbox={self.bbox}")
        data = response.json()
        status = data["crossings"][0]["status"]
        self.assertEqual(status["state"], "closed_simulated")
        self.assertTrue(status["simulated"])
        self.assertEqual(status["simulation"]["run_id"], run.pk)
        self.assertEqual(status["simulation"]["gate_state"], "closed")
        self.assertEqual(status["community_state"], "unknown")

    def test_bbox_normal_when_no_run(self):
        response = self.client.get(f"/api/crossings/?bbox={self.bbox}")
        status = response.json()["crossings"][0]["status"]
        self.assertEqual(status["state"], "unknown")
        self.assertFalse(status["simulated"])
        self.assertNotIn("simulation", status)

    def test_single_status_endpoint_marks_simulated(self):
        run = engine.start_run(vehicles=2, seed=23)
        SimulationGateEvent.objects.create(
            run=run, crossing=self.crossing, gate_state="closed", tick=1
        )
        response = self.client.get(
            reverse("api_crossing_status", args=[self.crossing.pk])
        )
        status = response.json()["status"]
        self.assertEqual(status["state"], "closed_simulated")
        self.assertTrue(status["simulated"])
