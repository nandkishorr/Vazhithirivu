import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class JourneySession(models.Model):
    """An opt-in navigation session for a real user (ADR-017).

    The row is an unguessable capability token that scopes position
    checks to a permitted session. It deliberately stores no
    coordinates, route data or user identity — positions arrive in
    request bodies, are answered transiently and never persisted.
    """

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )
    created_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    last_position_check_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"JourneySession {self.id}"

    @property
    def expires_at(self):
        return self.created_at + timedelta(
            hours=settings.NAV_SESSION_MAX_HOURS
        )

    def is_active(self, now=None):
        now = now or timezone.now()
        return self.ended_at is None and self.expires_at > now
