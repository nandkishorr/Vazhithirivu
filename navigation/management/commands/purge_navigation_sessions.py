from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from navigation.models import JourneySession


class Command(BaseCommand):
    help = (
        "Delete journey sessions older than the retention window. Run "
        "manually or from cron; it is intentionally not scheduled inside "
        "the app."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=settings.NAV_SESSION_RETENTION_DAYS,
            help="Delete sessions older than this many days "
            "(default: NAV_SESSION_RETENTION_DAYS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many sessions would be deleted without "
            "deleting.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        queryset = JourneySession.objects.filter(created_at__lt=cutoff)
        count = queryset.count()
        if options["dry_run"]:
            self.stdout.write(
                f"Dry run: {count} session(s) older than {days} days "
                f"would be deleted."
            )
            return
        deleted, _ = queryset.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} session(s) older than {days} days."
            )
        )
