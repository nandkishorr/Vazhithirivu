import os
import tempfile
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest import mock

import osmium
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase

from railways import importer
from railways.models import OsmImportRun, RailwayCrossing, RailwayTrack

FIXTURES = Path(__file__).parent / "fixtures"
V1 = FIXTURES / "sample_v1.osm"
V2 = FIXTURES / "sample_v2.osm"


def run_cmd(*args):
    out = StringIO()
    call_command("import_osm_railways", *args, stdout=out)
    return out.getvalue()


def import_v1(*extra):
    return run_cmd("--source", str(V1), *extra)


class ImportTests(TransactionTestCase):
    def test_field_mapping_and_run_row(self):
        import_v1("--source-url", "https://example.test/sample.osm")

        self.assertEqual(RailwayCrossing.objects.count(), 3)
        self.assertEqual(RailwayTrack.objects.count(), 2)

        c1 = RailwayCrossing.objects.get(osm_id=1)
        self.assertEqual(c1.osm_type, "node")
        self.assertEqual(c1.osm_version, 3)
        self.assertEqual(
            c1.osm_timestamp, datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        )
        self.assertEqual(c1.name, "Test Crossing A")
        self.assertEqual(c1.railway_value, "level_crossing")
        self.assertEqual(c1.crossing_barrier, "full")
        self.assertEqual(c1.tags["railway"], "level_crossing")
        self.assertEqual(c1.tags["crossing:barrier"], "full")
        self.assertAlmostEqual(c1.location.x, 76.25)
        self.assertAlmostEqual(c1.location.y, 9.95)
        self.assertEqual(c1.location.srid, 4326)
        self.assertEqual(c1.source, "osm")
        self.assertTrue(c1.is_active)

        t100 = RailwayTrack.objects.get(osm_id=100)
        self.assertEqual(t100.osm_type, "way")
        self.assertEqual(t100.railway_value, "rail")
        self.assertEqual(t100.usage, "main")
        self.assertEqual(t100.service, "")
        self.assertEqual(t100.name, "Test Line North")
        self.assertEqual(t100.geometry.srid, 4326)
        coords = list(t100.geometry.coords)
        self.assertEqual(len(coords), 4)
        self.assertAlmostEqual(coords[0][0], 76.2410)
        self.assertAlmostEqual(coords[0][1], 9.9410)
        self.assertAlmostEqual(coords[3][0], 76.2440)

        run = OsmImportRun.objects.get()
        self.assertEqual(run.status, "succeeded")
        self.assertEqual(len(run.file_sha256), 64)
        self.assertGreater(run.file_size, 0)
        self.assertEqual(run.source_url, "https://example.test/sample.osm")
        self.assertIsNotNone(run.coverage_bbox)
        minx, miny, maxx, maxy = run.coverage_bbox.extent
        self.assertEqual((minx, miny, maxx, maxy), (76.2, 9.9, 76.3, 10.0))
        self.assertEqual(
            run.filters,
            {
                "crossing_railway_values": ["level_crossing"],
                "track_railway_values": ["light_rail", "narrow_gauge", "rail"],
            },
        )
        c = run.counts
        self.assertEqual(c["created"], {"crossing": 3, "track": 2})
        self.assertEqual(c["skipped"]["crossing_not_node"], 1)
        self.assertEqual(c["skipped"]["track_invalid_geometry"], 1)

    def test_idempotent_reimport(self):
        import_v1()
        run2_out = import_v1()
        self.assertEqual(RailwayCrossing.objects.count(), 3)
        self.assertEqual(RailwayTrack.objects.count(), 2)

        run1, run2 = OsmImportRun.objects.order_by("started_at")
        self.assertEqual(run2.counts["created"], {"crossing": 0, "track": 0})
        self.assertEqual(run2.counts["updated"], {"crossing": 3, "track": 2})

        c1 = RailwayCrossing.objects.get(osm_id=1)
        self.assertEqual(c1.first_seen_run_id, run1.pk)
        self.assertEqual(c1.last_seen_run_id, run2.pk)

    def test_refresh_without_reconcile_keeps_removed(self):
        import_v1()
        run_cmd("--source", str(V2))

        # Removed objects stay active without --reconcile.
        self.assertTrue(RailwayCrossing.objects.get(osm_id=3).is_active)
        self.assertTrue(RailwayTrack.objects.get(osm_id=101).is_active)

        moved = RailwayCrossing.objects.get(osm_id=2)
        self.assertAlmostEqual(moved.location.x, 76.2610)
        self.assertAlmostEqual(moved.location.y, 9.9610)
        self.assertEqual(moved.osm_version, 2)

        new = RailwayCrossing.objects.get(osm_id=6)
        self.assertEqual(new.name, "Test Crossing New")
        self.assertEqual(RailwayCrossing.objects.count(), 4)

    def test_reconcile_deactivates_and_reimport_reactivates(self):
        import_v1()
        run_cmd(
            "--source", str(V2), "--reconcile", "--max-deactivate-fraction", "1.0"
        )

        gone_crossing = RailwayCrossing.objects.get(osm_id=3)
        self.assertFalse(gone_crossing.is_active)
        self.assertIsNotNone(gone_crossing.deactivated_at)
        gone_track = RailwayTrack.objects.get(osm_id=101)
        self.assertFalse(gone_track.is_active)

        run2 = OsmImportRun.objects.latest("started_at")
        self.assertEqual(run2.status, "succeeded")
        self.assertEqual(
            run2.counts["deactivated"], {"crossing": 1, "track": 1}
        )

        # Re-importing v1 reactivates the soft-deleted rows (no duplicates).
        import_v1()
        run3 = OsmImportRun.objects.latest("started_at")
        self.assertEqual(run3.counts["reactivated"], {"crossing": 1, "track": 1})
        self.assertTrue(RailwayCrossing.objects.get(osm_id=3).is_active)
        self.assertIsNone(RailwayCrossing.objects.get(osm_id=3).deactivated_at)
        # Crossing 6 (added in v2) stays: re-importing v1 is not a reconcile.
        self.assertEqual(RailwayCrossing.objects.count(), 4)
        self.assertEqual(RailwayTrack.objects.count(), 2)

    def test_reconcile_requires_bbox(self):
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "nobounds.osm")
            text = V1.read_text().replace(
                '  <bounds minlat="9.90" minlon="76.20" maxlat="10.00" maxlon="76.30"/>\n',
                "",
            )
            assert "<bounds" not in text
            Path(dst).write_text(text)
            with self.assertRaises(CommandError):
                run_cmd("--source", dst, "--reconcile")
        self.assertEqual(OsmImportRun.objects.count(), 0)
        self.assertEqual(RailwayCrossing.objects.count(), 0)

    def test_reconcile_scoped_to_run_filters(self):
        import_v1()
        # Re-import with a narrower track filter: rail tracks are outside the
        # reconcile scope, not "missing".
        run_cmd(
            "--source",
            str(V1),
            "--reconcile",
            "--track-values",
            "light_rail",
            "--max-deactivate-fraction",
            "1.0",
        )
        self.assertTrue(RailwayTrack.objects.get(osm_id=100).is_active)
        self.assertTrue(RailwayTrack.objects.get(osm_id=101).is_active)
        run2 = OsmImportRun.objects.latest("started_at")
        self.assertEqual(run2.status, "succeeded")
        self.assertEqual(
            run2.counts["deactivated"], {"crossing": 0, "track": 0}
        )

    def test_reconcile_deactivates_value_changed_out_of_filter(self):
        import_v1()
        # Same extract, but way 101 got retagged railway=abandoned upstream:
        # the stored row keeps railway_value='rail' and is deactivated.
        with tempfile.TemporaryDirectory() as d:
            dst = os.path.join(d, "retagged.osm")
            text = V1.read_text().replace(
                '<tag k="railway" v="rail"/>\n    <tag k="service" v="siding"/>',
                '<tag k="railway" v="abandoned"/>\n'
                '    <tag k="service" v="siding"/>',
            )
            assert 'v="abandoned"' in text
            Path(dst).write_text(text)
            run_cmd(
                "--source",
                dst,
                "--reconcile",
                "--max-deactivate-fraction",
                "1.0",
            )
        track = RailwayTrack.objects.get(osm_id=101)
        self.assertFalse(track.is_active)
        self.assertIsNotNone(track.deactivated_at)
        self.assertEqual(track.railway_value, "rail")
        self.assertTrue(RailwayTrack.objects.get(osm_id=100).is_active)

    def test_reconcile_scope_limited_to_bbox(self):
        import_v1()
        outside = RailwayCrossing.objects.create(
            source="osm",
            osm_type="node",
            osm_id=555,
            location=Point(77.0, 9.5, srid=4326),  # outside fixture bounds
            railway_value="level_crossing",
        )
        run_cmd(
            "--source", str(V2), "--reconcile", "--max-deactivate-fraction", "1.0"
        )
        outside.refresh_from_db()
        self.assertTrue(outside.is_active)

    def test_reconcile_safety_threshold_aborts(self):
        import_v1()
        with self.assertRaises(CommandError) as ctx:
            run_cmd(
                "--source",
                str(V2),
                "--reconcile",
                "--max-deactivate-fraction",
                "0.01",
            )
        self.assertIn("deactivation candidates", str(ctx.exception))
        self.assertTrue(RailwayCrossing.objects.get(osm_id=3).is_active)
        self.assertTrue(RailwayTrack.objects.get(osm_id=101).is_active)
        run2 = OsmImportRun.objects.latest("started_at")
        self.assertEqual(run2.status, "failed")
        self.assertIn("deactivation candidates", run2.error)

    def test_manual_and_suppressed_rows_untouched(self):
        import_v1()
        manual = RailwayCrossing.objects.create(
            source="manual",
            osm_type="",
            osm_id=None,
            location=Point(76.255, 9.955, srid=4326),
            railway_value="level_crossing",
            name="Manual Fix",
        )
        suppressed = RailwayCrossing.objects.get(osm_id=1)
        suppressed.is_suppressed = True
        suppressed.suppression_reason = "not a real crossing"
        suppressed.admin_notes = "verified on site"
        suppressed.save()

        run_cmd(
            "--source", str(V2), "--reconcile", "--max-deactivate-fraction", "1.0"
        )

        manual.refresh_from_db()
        self.assertEqual(manual.name, "Manual Fix")
        self.assertTrue(manual.is_active)
        self.assertIsNone(manual.last_seen_run_id)

        suppressed.refresh_from_db()
        self.assertTrue(suppressed.is_suppressed)
        self.assertEqual(suppressed.suppression_reason, "not a real crossing")
        self.assertEqual(suppressed.admin_notes, "verified on site")

    def test_failure_mid_import_is_restartable(self):
        real_flush = importer.flush_batch
        calls = {"n": 0}

        def flaky(model, objs, run, counts):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return real_flush(model, objs, run, counts)

        with mock.patch.object(importer, "flush_batch", side_effect=flaky):
            with self.assertRaises(CommandError):
                import_v1("--batch-size", "1")

        run = OsmImportRun.objects.get()
        self.assertEqual(run.status, "failed")
        self.assertIn("boom", run.error)
        # First batch persisted; no reconciliation happened.
        self.assertEqual(RailwayCrossing.objects.count(), 1)
        self.assertFalse(
            RailwayCrossing.objects.filter(is_active=False).exists()
        )

        # Rerunning the same file completes cleanly with no duplicates.
        import_v1()
        self.assertEqual(RailwayCrossing.objects.count(), 3)
        self.assertEqual(RailwayTrack.objects.count(), 2)
        run2 = OsmImportRun.objects.latest("started_at")
        self.assertEqual(run2.status, "succeeded")

    def test_advisory_lock_conflict(self):
        with mock.patch.object(
            importer, "acquire_import_lock", return_value=False
        ):
            with self.assertRaises(CommandError):
                import_v1()
        self.assertEqual(OsmImportRun.objects.count(), 0)

    def test_dry_run_writes_nothing(self):
        out = import_v1("--dry-run")
        self.assertIn("dry-run", out)
        self.assertEqual(OsmImportRun.objects.count(), 0)
        self.assertEqual(RailwayCrossing.objects.count(), 0)
        self.assertEqual(RailwayTrack.objects.count(), 0)

    def test_bbox_filtering(self):
        import_v1("--bbox", "76.24,9.94,76.26,9.97")
        self.assertEqual(
            sorted(RailwayCrossing.objects.values_list("osm_id", flat=True)),
            [1, 2],
        )
        self.assertEqual(
            list(RailwayTrack.objects.values_list("osm_id", flat=True)), [100]
        )
        run = OsmImportRun.objects.get()
        self.assertEqual(run.counts["skipped"]["outside_bbox"], 2)
        minx, miny, maxx, maxy = run.coverage_bbox.extent
        self.assertEqual((minx, miny, maxx, maxy), (76.24, 9.94, 76.26, 9.97))

    def test_custom_filter_values(self):
        import_v1("--track-values", "abandoned")
        self.assertEqual(RailwayCrossing.objects.count(), 3)
        self.assertEqual(
            list(RailwayTrack.objects.values_list("osm_id", flat=True)), [103]
        )
        self.assertEqual(
            RailwayTrack.objects.get().railway_value, "abandoned"
        )

    def test_invalid_bbox_rejected(self):
        with self.assertRaises(CommandError):
            import_v1("--bbox", "76.5,9.9,76.2,10.0")
        with self.assertRaises(CommandError):
            import_v1("--bbox", "not,a,bbox")
        self.assertEqual(RailwayCrossing.objects.count(), 0)

    def test_pbf_import_matches_xml(self):
        with tempfile.TemporaryDirectory() as d:
            pbf = os.path.join(d, "sample.osm.pbf")
            writer = osmium.SimpleWriter(pbf)
            for o in osmium.FileProcessor(str(V1)):
                writer.add(o)
            writer.close()
            run_cmd("--source", pbf)

        self.assertEqual(RailwayCrossing.objects.count(), 3)
        self.assertEqual(RailwayTrack.objects.count(), 2)
        t100 = RailwayTrack.objects.get(osm_id=100)
        self.assertEqual(len(list(t100.geometry.coords)), 4)
