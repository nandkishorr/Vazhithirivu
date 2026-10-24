import json
import re

from django.contrib.staticfiles.finders import find
from django.template import Context, Template
from django.test import Client, SimpleTestCase, TestCase, override_settings

from core.checks import google_maps_configuration


class HomeTests(TestCase):
    def test_home_shell(self):
        response = Client().get("/")
        self.assertEqual(response.status_code, 200)
        for needle in (
            "Vazhithirivu",
            'lang="ml"',
            "വഴിത്തിരിവ്",
            "Smart routes. Smarter crossings.",
            "Skip to route panel",
            "Early preview",
            'id="route-panel"',
            'aria-label="Map"',
            "css/app.css",
            "js/map.js",
            "js/app.js",
            "Use my location",
            'type="button"',
            "Location not shared",
            "No crossing selected",
            "hasn't been imported yet",
            "aren't official railway information",
        ):
            self.assertContains(response, needle)

    @override_settings(DEBUG=True, GOOGLE_MAPS_BROWSER_KEY="", GOOGLE_MAPS_MAP_ID="")
    def test_no_key_renders_not_configured_state(self):
        response = Client().get("/")
        self.assertContains(response, "Google Maps isn't configured")
        self.assertContains(response, "GOOGLE_MAPS_BROWSER_KEY")
        self.assertNotContains(response, "maps.googleapis.com")
        self.assertNotContains(response, "importLibrary")

    @override_settings(
        GOOGLE_MAPS_BROWSER_KEY="test-browser-key",
        GOOGLE_MAPS_MAP_ID="test-map-id",
        GOOGLE_MAPS_SERVER_KEY="server-secret-xyz",
    )
    def test_with_key_renders_loader_and_config(self):
        response = Client().get("/")
        self.assertContains(response, 'id="map"')
        self.assertContains(response, 'id="map-config"')
        self.assertContains(response, "importLibrary")
        self.assertContains(response, "test-browser-key")
        self.assertNotContains(response, "server-secret-xyz")

        match = re.search(
            r'<script id="map-config" type="application/json">(.*?)</script>',
            response.content.decode(),
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        config = json.loads(match.group(1))
        self.assertEqual(config["key"], "test-browser-key")
        self.assertEqual(config["mapId"], "test-map-id")
        self.assertEqual(config["center"], [9.9312, 76.2673])
        self.assertEqual(config["zoom"], 13)
        self.assertContains(response, 'gmpx-place-picker id="origin-picker"')
        self.assertContains(response, 'gmpx-place-picker id="destination-picker"')
        self.assertContains(response, "extended-component-library")
        self.assertContains(response, 'type="hidden" name="origin"')
        self.assertContains(response, 'type="hidden" name="destination"')

    @override_settings(GOOGLE_MAPS_BROWSER_KEY="")
    def test_without_key_renders_plain_inputs(self):
        response = Client().get("/")
        self.assertNotContains(response, "gmpx-place-picker")
        self.assertContains(response, 'name="origin"')
        self.assertContains(response, 'name="destination"')

    def test_blank_destination_warns(self):
        response = Client().get("/?destination=")
        self.assertContains(response, "Add a destination")

    def test_destination_echoes_escaped(self):
        # No origin and no browser key: the destination is echoed escaped
        # and the missing-origin hint is shown (no provider call happens).
        response = Client().get("/?destination=Ernakulam")
        self.assertContains(response, "Add a starting point")
        self.assertContains(response, "Ernakulam")

    def test_destination_xss_escaped(self):
        response = Client().get("/?destination=<script>alert(1)</script>")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_post_not_allowed(self):
        self.assertEqual(Client().post("/").status_code, 405)

    def test_location_card_privacy_and_retry(self):
        response = Client().get("/")
        self.assertContains(response, "isn't sent to or stored by")
        self.assertContains(response, "data-loc-error-body")
        self.assertEqual(
            response.content.decode().count("data-locate-retry"), 2
        )


class BadgeTests(SimpleTestCase):
    def render_tag(self, tag, key):
        template = Template(
            "{% load ui %}{% " + tag + " key %}"
        )
        return template.render(Context({"key": key}))

    def test_status_badge_labels(self):
        expected = {
            "open": "Reported open",
            "closed": "Reported closed",
            "unknown": "Status unknown",
            "stale": "Report outdated",
            "conflicting": "Conflicting reports",
            "open_reported": "Reported open",
            "closed_reported": "Reported closed",
        }
        for key, label in expected.items():
            with self.subTest(key=key):
                html = self.render_tag("status_badge", key)
                self.assertIn(label, html)
                self.assertIn('aria-hidden="true"', html)

    def test_status_badge_fallback_is_never_open(self):
        for key in (None, "", "bogus", "OPEN"):
            with self.subTest(key=key):
                html = self.render_tag("status_badge", key)
                self.assertIn("Status unknown", html)
                self.assertNotIn("Reported open", html)

    def test_source_badge_labels(self):
        expected = {
            "osm": "OpenStreetMap reference",
            "community": "Community report · unverified",
            "manual": "Manually added reference",
            "simulated": "Simulated",
        }
        for key, label in expected.items():
            with self.subTest(key=key):
                self.assertIn(label, self.render_tag("source_badge", key))

    def test_source_badge_unknown(self):
        self.assertIn("Unknown source", self.render_tag("source_badge", "bogus"))


class GoogleMapsCheckTests(SimpleTestCase):
    @override_settings(GOOGLE_MAPS_BROWSER_KEY="", GOOGLE_MAPS_MAP_ID="")
    def test_warnings_when_blank(self):
        ids = {w.id for w in google_maps_configuration(None)}
        self.assertEqual(ids, {"core.W001", "core.W002"})

    @override_settings(
        GOOGLE_MAPS_BROWSER_KEY="key", GOOGLE_MAPS_MAP_ID="map-id"
    )
    def test_no_warnings_when_set(self):
        self.assertEqual(google_maps_configuration(None), [])


class UiGalleryTests(SimpleTestCase):
    @override_settings(DEBUG=True)
    def test_gallery_ok_in_debug(self):
        response = Client().get("/ui/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demo content")

    @override_settings(DEBUG=False)
    def test_gallery_404_without_debug(self):
        self.assertEqual(Client().get("/ui/").status_code, 404)


class StaticFilesTests(SimpleTestCase):
    def test_js_files_found(self):
        self.assertTrue(find("js/map.js"))
        self.assertTrue(find("js/app.js"))
