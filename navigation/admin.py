from django.contrib import admin

from .models import JourneySession


@admin.register(JourneySession)
class JourneySessionAdmin(admin.ModelAdmin):
    """View-only audit of journey sessions (they hold no user data)."""

    list_display = (
        "id",
        "created_at",
        "ended_at",
        "last_position_check_at",
    )
    readonly_fields = list_display
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
