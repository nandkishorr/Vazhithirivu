from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class CrossingReport(models.Model):
    """A single community report about a level crossing's gate state.

    Reports are incident data, kept separate from the OSM reference
    geometry on ``RailwayCrossing`` (ADR-011). They expire quickly and are
    never official railway information.
    """

    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = (
        (STATE_OPEN, "Open"),
        (STATE_CLOSED, "Closed"),
    )

    SOURCE_COMMUNITY = "community"
    SOURCE_CHOICES = (
        (SOURCE_COMMUNITY, "Community report"),
    )

    MODERATION_VISIBLE = "visible"
    MODERATION_HIDDEN = "hidden"
    MODERATION_CHOICES = (
        (MODERATION_VISIBLE, "Visible"),
        (MODERATION_HIDDEN, "Hidden"),
    )

    crossing = models.ForeignKey(
        "railways.RailwayCrossing",
        on_delete=models.PROTECT,
        related_name="reports",
    )
    reported_state = models.CharField(max_length=8, choices=STATE_CHOICES)
    source = models.CharField(
        max_length=16, choices=SOURCE_CHOICES, default=SOURCE_COMMUNITY
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="crossing_reports",
    )
    # Not auto_now_add so services/tests can set the effective time.
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    moderation_status = models.CharField(
        max_length=8,
        choices=MODERATION_CHOICES,
        default=MODERATION_VISIBLE,
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderation_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["crossing", "created_at"]),
            models.Index(fields=["reporter", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_at__gt=models.F("created_at")),
                name="crossingreport_expires_after_created",
            ),
            models.CheckConstraint(
                condition=Q(reported_state__in=["open", "closed"]),
                name="crossingreport_state_valid",
            ),
            models.CheckConstraint(
                condition=Q(moderation_status__in=["visible", "hidden"]),
                name="crossingreport_moderation_valid",
            ),
        ]

    def __str__(self):
        return (
            f"{self.reported_state} report on crossing {self.crossing_id} "
            f"at {self.created_at:%Y-%m-%d %H:%M}"
        )
