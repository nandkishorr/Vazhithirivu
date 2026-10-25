from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import (
    SimulatedVehicle,
    SimulationEvent,
    SimulationGateEvent,
    SimulationPrompt,
    SimulationRun,
)

_ALL_FIELDS = (
    "label",
    "seed",
    "config",
    "status",
    "active_slot",
    "ticks",
    "heartbeat_at",
    "created_at",
    "started_at",
    "finished_at",
    "error",
)


@admin.register(SimulationRun)
class SimulationRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "label",
        "status",
        "ticks",
        "seed",
        "started_at",
        "finished_at",
    )
    list_filter = ("status",)
    search_fields = ("label", "=seed")

    def get_readonly_fields(self, request, obj=None):
        return _ALL_FIELDS

    def has_add_permission(self, request):
        return False


@admin.register(SimulatedVehicle)
class SimulatedVehicleAdmin(GISModelAdmin):
    list_display = ("id", "run", "index", "label", "crossing", "waiting")
    list_filter = ("run",)

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(SimulationGateEvent)
class SimulationGateEventAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "crossing", "gate_state", "tick")
    list_filter = ("run", "gate_state")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(SimulationPrompt)
class SimulationPromptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "run",
        "crossing",
        "state",
        "detected_tick",
        "created_at",
        "resolved_at",
    )
    list_filter = ("run", "state")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(SimulationEvent)
class SimulationEventAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "tick", "kind", "occurred_at")
    list_filter = ("run", "kind")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False
