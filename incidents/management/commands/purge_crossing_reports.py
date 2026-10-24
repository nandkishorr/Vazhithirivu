from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from incidents.models import CrossingReport


class Command(BaseCommand):
    help = (
        "Delete crossing reports older than the retention window "
        "(hidden reports included). Run manually or from cron; it is "
        "intentionally not scheduled inside the app."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=settings.REPORT_RETENTION_DAYS,
            help="Delete reports older than this many days "
            "(default: REPORT_RETENTION_DAYS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many reports would be deleted without deleting.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        queryset = CrossingReport.objects.filter(created_at__lt=cutoff)
        count = queryset.count()
        if options["dry_run"]:
            self.stdout.write(
                f"Dry run: {count} report(s) older than {days} days "
                f"would be deleted."
            )
            return
        deleted, _ = queryset.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} report(s) older than {days} days."
            )
        )
