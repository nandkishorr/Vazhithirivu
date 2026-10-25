from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .models import (
    CrossingLink,
    OsmImportRun,
    RailwayCrossing,
    RailwayTrack,
)

_OSM_DERIVED_COMMON = (
    "source",
    "osm_type",
    "osm_id",
    "osm_version",
    "osm_timestamp",
    "tags",
    "name",
    "is_active",
    "deactivated_at",
    "first_seen_run",
    "last_seen_run",
)

_MANUAL_READONLY = ("first_seen_run", "last_seen_run", "deactivated_at")


class _OsmFeatureAdmin(GISModelAdmin):
    list_display = (
        "id",
        "name",
        "osm_type",
        "osm_id",
        "railway_value",
        "source",
        "is_active",
    )
    list_filter = ("source", "is_active", "railway_value")
    search_fields = ("name", "=osm_id")
    osm_readonly_fields = _OSM_DERIVED_COMMON

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.source == "osm":
            return self.osm_readonly_fields
        return _MANUAL_READONLY


@admin.register(RailwayCrossing)
class RailwayCrossingAdmin(_OsmFeatureAdmin):
    list_display = _OsmFeatureAdmin.list_display + ("is_suppressed",)
    list_filter = _OsmFeatureAdmin.list_filter + ("is_suppressed",)
    osm_readonly_fields = _OSM_DERIVED_COMMON + (
        "location",
        "railway_value",
        "crossing_barrier",
    )


@admin.register(RailwayTrack)
class RailwayTrackAdmin(_OsmFeatureAdmin):
    osm_readonly_fields = _OSM_DERIVED_COMMON + (
        "geometry",
        "railway_value",
        "usage",
        "service",
    )


@admin.register(CrossingLink)
class CrossingLinkAdmin(admin.ModelAdmin):
    """Derived same-line topology — rebuilt, never hand-edited."""

    list_display = ("id", "from_crossing", "to_crossing", "rank", "distance_m")
    list_filter = ("rank",)
    search_fields = ("=from_crossing__id", "=to_crossing__id")
    ordering = ("from_crossing_id", "rank")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OsmImportRun)
class OsmImportRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "source_path",
        "started_at",
        "finished_at",
        "file_sha256",
    )
    list_filter = ("status", "reconcile")
    search_fields = ("source_path", "file_sha256")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
