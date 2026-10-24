from django.contrib import admin
from django.utils import timezone

from .models import CrossingReport


@admin.register(CrossingReport)
class CrossingReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "crossing",
        "reported_state",
        "source",
        "created_at",
        "expires_at",
        "moderation_status",
        "reporter",
    )
    list_filter = ("reported_state", "source", "moderation_status")
    readonly_fields = (
        "crossing",
        "reported_state",
        "source",
        "reporter",
        "created_at",
        "expires_at",
        "moderated_by",
        "moderated_at",
    )
    fields = readonly_fields + ("moderation_status", "moderation_note")
    actions = ("hide_reports", "restore_reports")

    def has_add_permission(self, request):
        # Reports are created only through incidents.services.create_report.
        return False

    def save_model(self, request, obj, form, change):
        if change and "moderation_status" in form.changed_data:
            obj.moderated_by = request.user
            obj.moderated_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.action(description="Hide selected reports")
    def hide_reports(self, request, queryset):
        self._moderate(queryset, request.user, CrossingReport.MODERATION_HIDDEN)

    @admin.action(description="Restore selected reports")
    def restore_reports(self, request, queryset):
        self._moderate(queryset, request.user, CrossingReport.MODERATION_VISIBLE)

    def _moderate(self, queryset, moderator, status):
        queryset.update(
            moderation_status=status,
            moderated_by=moderator,
            moderated_at=timezone.now(),
        )
