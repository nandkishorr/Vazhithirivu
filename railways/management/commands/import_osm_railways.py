from django.core.management.base import BaseCommand, CommandError

from railways.importer import ImportFilters, parse_bbox, run_import


class Command(BaseCommand):
    help = (
        "Import railway crossings and tracks from a local OSM PBF/XML "
        "extract into PostGIS. Idempotent; safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            help="Path to a local .osm.pbf or .osm file (no downloads).",
        )
        parser.add_argument(
            "--source-url",
            default="",
            help="Optional provenance URL recorded on the import run.",
        )
        parser.add_argument(
            "--bbox",
            default=None,
            metavar="MINLON,MINLAT,MAXLON,MAXLAT",
            help=(
                "Only import features inside this box; also used as the "
                "reconciliation scope."
            ),
        )
        parser.add_argument(
            "--location-index",
            default="flex_mem",
            help=(
                "osmium node-location index type. Default flex_mem is fine "
                "for regional extracts; for the full India extract use e.g. "
                "dense_file_array,/tmp/osm-node-locations.idx"
            ),
        )
        parser.add_argument("--batch-size", type=int, default=2000)
        parser.add_argument(
            "--reconcile",
            action="store_true",
            help=(
                "After a fully successful import, soft-delete active OSM "
                "rows inside the coverage bbox that were not seen. Needs "
                "--bbox or a file with header bounds."
            ),
        )
        parser.add_argument(
            "--max-deactivate-fraction",
            type=float,
            default=0.2,
            help="Safety limit for --reconcile (fraction of in-scope rows).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and count only; writes nothing (no run row).",
        )
        parser.add_argument(
            "--crossing-values",
            default=None,
            help="Comma list overriding the crossing railway= values.",
        )
        parser.add_argument(
            "--track-values",
            default=None,
            help="Comma list overriding the track railway= values.",
        )

    def handle(self, *args, **opts):
        defaults = ImportFilters()
        crossing_values = (
            frozenset(v.strip() for v in opts["crossing_values"].split(",") if v.strip())
            if opts["crossing_values"]
            else defaults.crossing_railway_values
        )
        track_values = (
            frozenset(v.strip() for v in opts["track_values"].split(",") if v.strip())
            if opts["track_values"]
            else defaults.track_railway_values
        )
        filters = ImportFilters(
            crossing_railway_values=crossing_values,
            track_railway_values=track_values,
        )
        if not crossing_values and not track_values:
            raise CommandError("at least one filter value set must be non-empty")

        bbox = parse_bbox(opts["bbox"]) if opts["bbox"] else None
        if opts["batch_size"] < 1:
            raise CommandError("--batch-size must be >= 1")
        if not (0 < opts["max_deactivate_fraction"] <= 1):
            raise CommandError("--max-deactivate-fraction must be in (0, 1]")

        result = run_import(
            opts["source"],
            filters=filters,
            bbox=bbox,
            batch_size=opts["batch_size"],
            reconcile=opts["reconcile"],
            max_deactivate_fraction=opts["max_deactivate_fraction"],
            dry_run=opts["dry_run"],
            location_index=opts["location_index"],
            source_url=opts["source_url"],
        )

        c = result.counts
        self.stdout.write(f"import {result.status} (run id: {result.run_id})")
        for section in ("parsed", "created", "updated", "reactivated", "deactivated"):
            if section in c:
                self.stdout.write(
                    f"  {section}: "
                    + ", ".join(f"{k}={v}" for k, v in c[section].items())
                )
        if c.get("skipped"):
            self.stdout.write(
                "  skipped: "
                + ", ".join(
                    f"{reason}={n}" for reason, n in sorted(c["skipped"].items())
                )
            )
