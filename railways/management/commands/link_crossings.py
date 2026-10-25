from django.core.management.base import BaseCommand

from railways.topology import rebuild_crossing_links


class Command(BaseCommand):
    help = (
        "Rebuild the same-line crossing links (CrossingLink) from active "
        "track geometry and crossings. Idempotent; run after imports and "
        "after adding manual crossings."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-neighbors",
            type=int,
            default=None,
            help="Links to keep per crossing (default: setting).",
        )
        parser.add_argument(
            "--snap-tolerance-m",
            type=float,
            default=None,
            help="Max metres a crossing may sit from a track vertex.",
        )
        parser.add_argument(
            "--max-distance-m",
            type=float,
            default=None,
            help="Max along-track metres a neighbour may be.",
        )

    def handle(self, *args, **opts):
        counts = rebuild_crossing_links(
            max_neighbors=opts["max_neighbors"],
            snap_tolerance_m=opts["snap_tolerance_m"],
            max_distance_m=opts["max_distance_m"],
        )
        self.stdout.write(
            "links rebuilt: "
            + ", ".join(f"{k}={v}" for k, v in counts.items())
        )
