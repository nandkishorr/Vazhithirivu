"""Simulator-owned tables (ADR-015).

Every simulator record is scoped to a :class:`SimulationRun`. These
tables are the only place simulated state lives — the simulator never
writes ``CrossingReport`` rows and never mutates ``railways`` reference
rows. Deleting a run cascades to all of its simulated data.
"""
from django.contrib.gis.db import models
from django.db.models import Q
from django.utils import timezone


class SimulationRun(models.Model):
    """One demo simulation: config, lifecycle and a heartbeat.

    At most one run may be active (``running``/``paused``) at a time;
    ``active_slot`` enforces that at the database level — it is ``1``
    while a run is active and ``NULL`` otherwise.
    """

    STATUS_RUNNING = "running"
    STATUS_PAUSED = "paused"
    STATUS_STOPPED = "stopped"
    STATUS_FINISHED = "finished"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "running"),
        (STATUS_PAUSED, "paused"),
        (STATUS_STOPPED, "stopped"),
        (STATUS_FINISHED, "finished"),
        (STATUS_FAILED, "failed"),
    ]
    ACTIVE_STATUSES = (STATUS_RUNNING, STATUS_PAUSED)

    label = models.CharField(max_length=120, blank=True)
    seed = models.BigIntegerField()
    # Validated config: {"vehicles": int, "duration_seconds": int,
    # "tick_seconds": int, "gates": [{"crossing_id", "close_tick",
    # "open_tick"}]}.
    config = models.JSONField(default=dict)
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_RUNNING
    )
    active_slot = models.PositiveSmallIntegerField(
        null=True, blank=True, unique=True
    )
    ticks = models.IntegerField(default=0)
    heartbeat_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at", "-pk"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"SimulationRun #{self.pk} ({self.status}) {self.label}"

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def tick_seconds(self):
        return int(self.config.get("tick_seconds") or 5)

    @property
    def duration_seconds(self):
        return int(self.config.get("duration_seconds") or 0)

    @property
    def vehicle_count(self):
        return int(self.config.get("vehicles") or 0)


class SimulatedVehicle(models.Model):
    """A static simulated *user device* parked near a crossing.

    "Vehicle" is historical — simulated users never move (ADR-021).
    ``path`` is simulation-generated geometry (through a real crossing,
    roughly perpendicular to the mapped track) used only to place the
    parked position on a road-like approach — not real road or provider
    route data.

    While the physical gate at its crossing is closed, the parked user
    counts as ``waiting`` and ``wait_ticks`` accumulates; dwell
    detection on those waiting users raises confirmation prompts
    (ADR-018).
    """

    run = models.ForeignKey(
        SimulationRun, on_delete=models.CASCADE, related_name="vehicles"
    )
    index = models.IntegerField()
    label = models.CharField(max_length=40)
    path = models.LineStringField()
    path_length_m = models.FloatField()
    progress_m = models.FloatField()
    direction = models.SmallIntegerField(default=1)  # approach side: +1/-1
    speed_mps = models.FloatField()
    position = models.PointField()
    # The mapped crossing this path passes through and where it sits on
    # the path (the parked slot the user occupies near the gate).
    crossing = models.ForeignKey(
        "railways.RailwayCrossing",
        on_delete=models.PROTECT,
        related_name="simulated_vehicles",
        null=True,
        blank=True,
    )
    crossing_progress_m = models.FloatField(null=True, blank=True)
    # Queue state: ``waiting`` = held at the gate; ``wait_ticks`` counts
    # consecutive ticks spent waiting while the gate is closed.
    waiting = models.BooleanField(default=False)
    wait_ticks = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["run", "index"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "index"], name="simulatedvehicle_run_index"
            ),
            models.CheckConstraint(
                condition=Q(direction__in=[-1, 1]),
                name="simulatedvehicle_direction_valid",
            ),
        ]

    def __str__(self):
        return f"{self.label} (run {self.run_id})"


class SimulationGateEvent(models.Model):
    """A simulated gate open/close at a mapped crossing.

    Reference to the crossing is read-only (PROTECT); the event never
    mutates the crossing row. The derived simulated status reads only
    events belonging to the currently active run.
    """

    STATE_OPEN = "open"
    STATE_CLOSED = "closed"
    STATE_CHOICES = [
        (STATE_OPEN, "open"),
        (STATE_CLOSED, "closed"),
    ]

    run = models.ForeignKey(
        SimulationRun, on_delete=models.CASCADE, related_name="gate_events"
    )
    crossing = models.ForeignKey(
        "railways.RailwayCrossing",
        on_delete=models.PROTECT,
        related_name="simulation_gate_events",
    )
    gate_state = models.CharField(max_length=8, choices=STATE_CHOICES)
    tick = models.IntegerField()
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["crossing", "tick", "pk"]
        indexes = [
            models.Index(fields=["run", "tick"]),
            models.Index(fields=["crossing", "tick"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(gate_state__in=["open", "closed"]),
                name="simulationgateevent_state_valid",
            ),
        ]

    def __str__(self):
        return (
            f"gate {self.gate_state} on crossing {self.crossing_id} "
            f"(run {self.run_id}, tick {self.tick})"
        )


class SimulationPrompt(models.Model):
    """A "is the gate closed?" confirmation raised by presence inference.

    When enough simulated users dwell near a crossing whose (hidden) gate
    is closed, a pending prompt is broadcast to the web app. A human
    click resolves it: ``confirmed`` writes a closed
    :class:`SimulationGateEvent` (the only way scheduled gates reach the
    status overlay); ``dismissed``/``expired`` write nothing. One prompt
    per run+crossing+closure — a resolved prompt is never re-raised for
    the same closure cycle.
    """

    STATE_PENDING = "pending"
    STATE_CONFIRMED = "confirmed"
    STATE_DISMISSED = "dismissed"
    STATE_EXPIRED = "expired"
    STATE_CHOICES = [
        (STATE_PENDING, "pending"),
        (STATE_CONFIRMED, "confirmed"),
        (STATE_DISMISSED, "dismissed"),
        (STATE_EXPIRED, "expired"),
    ]
    RESOLVED_STATES = (STATE_CONFIRMED, STATE_DISMISSED, STATE_EXPIRED)

    run = models.ForeignKey(
        SimulationRun, on_delete=models.CASCADE, related_name="prompts"
    )
    crossing = models.ForeignKey(
        "railways.RailwayCrossing",
        on_delete=models.PROTECT,
        related_name="simulation_prompts",
    )
    # The gate-spec close tick that produced this inference — part of the
    # dedup key so a later closure cycle can prompt again.
    truth_close_tick = models.IntegerField()
    detected_tick = models.IntegerField()
    # Indexes of the SimulatedVehicle rows counted as waiting users.
    waiting_vehicle_indexes = models.JSONField(default=list, blank=True)
    state = models.CharField(
        max_length=10, choices=STATE_CHOICES, default=STATE_PENDING
    )
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["run", "-created_at", "-pk"]
        indexes = [models.Index(fields=["run", "state"])]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "crossing", "truth_close_tick"],
                name="simulationprompt_run_crossing_close_tick",
            ),
            models.CheckConstraint(
                condition=Q(
                    state__in=[
                        "pending",
                        "confirmed",
                        "dismissed",
                        "expired",
                    ]
                ),
                name="simulationprompt_state_valid",
            ),
        ]

    def __str__(self):
        return (
            f"prompt {self.state} on crossing {self.crossing_id} "
            f"(run {self.run_id}, tick {self.detected_tick})"
        )


class SimulationEvent(models.Model):
    """Audit/demo-feed log for a run (lifecycle, gate events)."""

    run = models.ForeignKey(
        SimulationRun, on_delete=models.CASCADE, related_name="events"
    )
    tick = models.IntegerField(default=0)
    kind = models.CharField(max_length=32)
    detail = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["run", "tick", "pk"]
        indexes = [models.Index(fields=["run", "tick"])]

    def __str__(self):
        return f"{self.kind} (run {self.run_id}, tick {self.tick})"
