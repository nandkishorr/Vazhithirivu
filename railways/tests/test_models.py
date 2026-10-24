from django.contrib.gis.geos import Point
from django.db import IntegrityError
from django.test import TestCase

from railways.models import RailwayCrossing


def crossing(**kwargs):
    defaults = {
        "source": "osm",
        "osm_type": "node",
        "osm_id": 1,
        "location": Point(76.25, 9.95, srid=4326),
        "railway_value": "level_crossing",
    }
    defaults.update(kwargs)
    return RailwayCrossing(**defaults)


class ConstraintTests(TestCase):
    def test_duplicate_osm_identity_rejected(self):
        crossing(osm_id=42).save()
        with self.assertRaises(IntegrityError):
            crossing(osm_id=42).save()

    def test_osm_source_requires_identity(self):
        with self.assertRaises(IntegrityError):
            crossing(osm_id=None, osm_type="").save()

    def test_manual_rows_may_have_null_osm_id(self):
        crossing(source="manual", osm_type="", osm_id=None).save()
        crossing(source="manual", osm_type="", osm_id=None).save()
        self.assertEqual(
            RailwayCrossing.objects.filter(source="manual").count(), 2
        )
