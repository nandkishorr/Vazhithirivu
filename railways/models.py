from django.contrib.gis.db import models
from django.db.models import Q


class OsmImportRun(models.Model):
    """One execution of the OSM railway import.

    Records provenance (file hash/size/timestamp), the effective filters,
    the reconciliation scope and per-kind counts for auditability.
    """

    STATUS_RUNNING = "running"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "running"),
        (STATUS_SUCCEEDED, "succeeded"),
        (STATUS_FAILED, "failed"),
    ]

    source_path = models.CharField(max_length=500)
    source_url = models.CharField(max_length=500, blank=True)
    file_sha256 = models.CharField(max_length=64)
    file_size = models.BigIntegerField()
    source_timestamp = models.DateTimeField(null=True, blank=True)
    coverage_bbox = models.PolygonField(null=True, blank=True)
    filters = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    counts = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    reconcile = models.BooleanField(default=False)
    batch_size = models.IntegerField(default=2000)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"OsmImportRun #{self.pk} ({self.status}) {self.source_path}"


class OsmReferenceFeature(models.Model):
    """Shared identity/traceability fields for OSM reference features.

    ``source='osm'`` rows are managed exclusively by the importer;
    ``source='manual'`` rows are admin-created corrections the importer
    never touches.
    """

    SOURCE_OSM = "osm"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_OSM, "osm"),
        (SOURCE_MANUAL, "manual"),
    ]

    OSM_TYPE_CHOICES = [
        ("node", "node"),
        ("way", "way"),
        ("relation", "relation"),
    ]

    source = models.CharField(
        max_length=10, choices=SOURCE_CHOICES, default=SOURCE_OSM
    )
    osm_type = models.CharField(
        max_length=8, choices=OSM_TYPE_CHOICES, blank=True
    )
    osm_id = models.BigIntegerField(null=True, blank=True)
    osm_version = models.IntegerField(null=True, blank=True)
    osm_timestamp = models.DateTimeField(null=True, blank=True)
    tags = models.JSONField(default=dict, blank=True)
    name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    first_seen_run = models.ForeignKey(
        OsmImportRun,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="%(class)s_first_seen",
    )
    last_seen_run = models.ForeignKey(
        OsmImportRun,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="%(class)s_last_seen",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager()

    class Meta:
        abstract = True

    def __str__(self):
        label = self.name or f"{self.osm_type}/{self.osm_id}"
        return f"{label} [{self.source}]"


class RailwayCrossing(OsmReferenceFeature):
    """An OSM-mapped level crossing point (reference data only — no live
    gate state, per ADR-003)."""

    location = models.PointField()
    railway_value = models.CharField(max_length=64)
    crossing_barrier = models.CharField(max_length=64, blank=True)
    is_suppressed = models.BooleanField(default=False)
    suppression_reason = models.TextField(blank=True)
    admin_notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["osm_type", "osm_id"],
                name="railwaycrossing_unique_osm_identity",
            ),
            models.CheckConstraint(
                condition=Q(source="manual")
                | (Q(osm_id__isnull=False) & ~Q(osm_type="")),
                name="railwaycrossing_osm_identity_required",
            ),
        ]
        indexes = [models.Index(fields=["is_active"])]


class RailwayTrack(OsmReferenceFeature):
    """An OSM-mapped railway way imported as a LineString."""

    geometry = models.LineStringField()
    railway_value = models.CharField(max_length=64)
    usage = models.CharField(max_length=64, blank=True)
    service = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["osm_type", "osm_id"],
                name="railwaytrack_unique_osm_identity",
            ),
            models.CheckConstraint(
                condition=Q(source="manual")
                | (Q(osm_id__isnull=False) & ~Q(osm_type="")),
                name="railwaytrack_osm_identity_required",
            ),
        ]
        indexes = [models.Index(fields=["is_active"])]
