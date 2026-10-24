"""Republish derived crossing status after report writes (ADR-014).

``on_commit`` ensures only durable changes produce a push, and covering
both save and delete means moderation (hide/restore) and retention
purges republish exactly like new reports do.
"""
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import CrossingReport


@receiver(post_save, sender=CrossingReport)
@receiver(post_delete, sender=CrossingReport)
def _push_status_on_report_change(sender, instance, **kwargs):
    crossing_id = instance.crossing_id
    transaction.on_commit(lambda: _publish(crossing_id))


def _publish(crossing_id):
    # Imported lazily so tests can patch incidents.updates.
    from . import updates

    updates.publish_crossing_status(crossing_id)
