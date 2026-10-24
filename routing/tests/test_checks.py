from django.test import SimpleTestCase, override_settings

from routing.checks import routing_configuration


@override_settings(GOOGLE_MAPS_SERVER_KEY="k")
class RoutingChecksTests(SimpleTestCase):
    def ids(self):
        return {p.id for p in routing_configuration(None)}

    def test_defaults_clean_when_key_set(self):
        self.assertEqual(self.ids(), set())

    @override_settings(GOOGLE_MAPS_SERVER_KEY="")
    def test_warning_without_key(self):
        self.assertIn("routing.W001", self.ids())

    @override_settings(ROUTE_CROSSING_ON_ROUTE_M=60)
    def test_e001_bad_thresholds(self):
        self.assertIn("routing.E001", self.ids())

    @override_settings(ROUTING_GOOGLE_ROUTING_PREFERENCE="BOGUS")
    def test_e002_bad_preference(self):
        self.assertIn("routing.E002", self.ids())
