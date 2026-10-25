"""Simulation engine: static-user spawning, ticking and run lifecycle.

Determinism: a run's users and gate schedule come entirely from its
``seed`` — replaying the same seed against the same imported OSM data
produces the same scenario.

Simulated users are *static* (ADR-021): each one is parked in a queue
slot on an approach to a crossing and never moves. While a gate is
physically closed the parked users count as *waiting*; their dwell is
what presence inference turns into a confirmation prompt.

Parking positions sit on *synthetic* LineStrings through real mapped
crossings: the road direction is approximated as perpendicular to the
nearest mapped track at the crossing node (roads cross tracks at right
angles at level crossings). They are demo geometry, not real road or
routing provider data, and are labelled as such everywhere they
surface.

Coordinates use an equirectangular approximation — accurate enough for
demo paths of a few kilometres around Kochi; the stored PostGIS
``position`` remains SRID 4326.
"""
import logging
import math
import random
import secrets
import signal
import sys
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.gis.geos import LineString, Point
from django.db import transaction
from django.utils import timezone

from incidents.updates import publish_crossing_status
from railways.models import RailwayCrossing, RailwayTrack

from . import updates
from .models import (
    SimulatedVehicle,
    SimulationEvent,
    SimulationGateEvent,
    SimulationPrompt,
    SimulationRun,
)
from .status import active_run, gate_states_for_run

logger = logging.getLogger(__name__)

_M_PER_DEG_LAT = 110540.0


class SimulatorError(Exception):
    """Invalid lifecycle action or configuration."""


# --- Geography helpers (equirectangular approximation) -----------------------


def _dist_m(a, b):
    mid_lat = math.radians((a[1] + b[1]) / 2)
    dx = (b[0] - a[0]) * 111320.0 * math.cos(mid_lat)
    dy = (b[1] - a[1]) * _M_PER_DEG_LAT
    return math.hypot(dx, dy)


def _bearing_deg(a, b):
    """Compass bearing of the segment a→b (0 = north)."""
    mid_lat = math.radians((a[1] + b[1]) / 2)
    dx = (b[0] - a[0]) * math.cos(mid_lat)
    dy = b[1] - a[1]
    if dx == 0 and dy == 0:
        return 0.0
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _offset_m(p, bearing_deg, dist_m):
    ang = math.radians(bearing_deg)
    d_lng = (
        dist_m
        * math.sin(ang)
        / (111320.0 * math.cos(math.radians(p[1])))
    )
    d_lat = dist_m * math.cos(ang) / _M_PER_DEG_LAT
    return (p[0] + d_lng, p[1] + d_lat)


def _point_segment_dist(p, a, b):
    """Distance from ``p`` to segment a→b in metres (equirectangular)."""
    cos_lat = math.cos(math.radians(p[1]))
    px, py = p[0] * 111320 * cos_lat, p[1] * _M_PER_DEG_LAT
    ax, ay = a[0] * 111320 * cos_lat, a[1] * _M_PER_DEG_LAT
    bx, by = b[0] * 111320 * cos_lat, b[1] * _M_PER_DEG_LAT
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    t = 0.0 if denom == 0 else max(
        0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / denom)
    )
    return math.hypot(px - (ax + t * abx), py - (ay + t * aby))


def _cum_lengths(coords):
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + _dist_m(coords[i - 1], coords[i]))
    return cum


def _position_and_heading(coords, cum, progress_m):
    """(lng, lat) and travel bearing at ``progress_m`` along the path."""
    if progress_m <= 0:
        heading = (
            _bearing_deg(coords[0], coords[1]) if len(coords) > 1 else 0.0
        )
        return coords[0], heading
    total = cum[-1]
    if progress_m >= total:
        heading = (
            _bearing_deg(coords[-2], coords[-1])
            if len(coords) > 1
            else 0.0
        )
        return coords[-1], heading
    i = 1
    while cum[i] < progress_m:
        i += 1
    seg = cum[i] - cum[i - 1]
    frac = (progress_m - cum[i - 1]) / seg if seg else 0.0
    point = (
        coords[i - 1][0] + (coords[i][0] - coords[i - 1][0]) * frac,
        coords[i - 1][1] + (coords[i][1] - coords[i - 1][1]) * frac,
    )
    return point, _bearing_deg(coords[i - 1], coords[i])


# --- Vehicle path construction -----------------------------------------------


def _nearest_track_bearing(track_geoms, point, max_dist_m=500.0):
    """Bearing of the track segment nearest to ``point`` (or ``None``)."""
    best = None
    for coords in track_geoms:
        for i in range(1, len(coords)):
            a, b = coords[i - 1], coords[i]
            # Cheap bbox precheck before the real distance computation.
            if (
                min(a[0], b[0]) - 0.006 > point[0]
                or max(a[0], b[0]) + 0.006 < point[0]
                or min(a[1], b[1]) - 0.006 > point[1]
                or max(a[1], b[1]) + 0.006 < point[1]
            ):
                continue
            d = _point_segment_dist(point, a, b)
            if best is None or d < best[0]:
                best = (d, _bearing_deg(a, b))
    if best is not None and best[0] <= max_dist_m:
        return best[1]
    return None


def _build_path(rng, crossing_xy, road_bearing, length_m):
    """5-vertex path through the crossing along ``road_bearing``.

    The middle vertex is exactly the crossing point (the parked user is
    positioned relative to it); other vertices get small perpendicular
    jitter so paths look road-like rather than perfectly straight.
    """
    coords = []
    for frac in (-0.5, -0.25, 0.0, 0.25, 0.5):
        base = _offset_m(crossing_xy, road_bearing, frac * length_m)
        if frac != 0.0:
            base = _offset_m(base, road_bearing + 90.0, rng.uniform(-25, 25))
        coords.append(base)
    return coords


def _reference_geometries():
    crossings = list(
        RailwayCrossing.objects.filter(
            is_active=True, is_suppressed=False
        ).only("pk", "location", "name")
    )
    tracks = [
        list(t.geometry.coords)
        for t in RailwayTrack.objects.filter(is_active=True).only(
            "geometry"
        )
    ]
    return crossings, tracks


def spawn_vehicles(run, rng):
    """Create ``config["vehicles"]`` static simulated users for ``run``.

    Users never move (ADR-021): each one parks in a queue slot just
    short of a gate, alternating approach sides so the demo shows a
    queue on both approaches. Assignment is round-robin across the
    run's gated crossings, or a seeded random crossing when no gate is
    scheduled. While the gate is physically closed the parked users
    count as *waiting* — their dwell is what presence inference
    detects.
    """
    crossings, track_geoms = _reference_geometries()
    if not crossings:
        raise SimulatorError(
            "No active crossings are mapped — import OSM data first "
            "(see RUNBOOK 'OSM import')."
        )
    base_length = settings.SIM_PATH_LENGTH_M
    gap = settings.SIM_QUEUE_GAP_M
    spacing = settings.SIM_QUEUE_SPACING_M

    by_id = {c.pk: c for c in crossings}
    gate_ids = [
        spec["crossing_id"]
        for spec in run.config.get("gates") or []
        if spec.get("crossing_id") in by_id
    ]
    side_toggle = {}
    queue_rank = {}

    vehicles = []
    for i in range(run.vehicle_count):
        crossing = (
            by_id[gate_ids[i % len(gate_ids)]]
            if gate_ids
            else rng.choice(crossings)
        )
        cx, cy = crossing.location.x, crossing.location.y
        track_bearing = _nearest_track_bearing(track_geoms, (cx, cy))
        # Roads cross tracks at right angles; without a track we still
        # emit a plausible direction through the crossing.
        road_bearing = (
            ((track_bearing or 0.0) + 90.0 + rng.uniform(-12, 12)) % 360.0
            if track_bearing is not None
            else rng.uniform(0, 360)
        )
        length = base_length * rng.uniform(0.7, 1.3)
        coords = _build_path(rng, (cx, cy), road_bearing, length)
        cum = _cum_lengths(coords)
        total = cum[-1]
        crossing_progress = cum[2]  # the middle vertex is the crossing
        side = side_toggle.get(crossing.pk, 1)
        side_toggle[crossing.pk] = -side
        rank = queue_rank.get((crossing.pk, side), 0)
        queue_rank[(crossing.pk, side)] = rank + 1
        offset = gap + rank * spacing + rng.uniform(0.0, 6.0)
        progress = (
            crossing_progress - offset
            if side == 1
            else crossing_progress + offset
        )
        progress = min(max(progress, 2.0), total - 2.0)
        position, _ = _position_and_heading(coords, cum, progress)
        vehicles.append(
            SimulatedVehicle(
                run=run,
                index=i,
                label=f"Sim user {i + 1:02d}",
                path=LineString(coords, srid=4326),
                path_length_m=total,
                progress_m=progress,
                direction=side,
                speed_mps=0.0,
                position=Point(position, srid=4326),
                crossing=crossing,
                crossing_progress_m=crossing_progress,
                waiting=False,
            )
        )
    SimulatedVehicle.objects.bulk_create(vehicles)
    return vehicles


# --- Run lifecycle ------------------------------------------------------------


def interrupt_stale_runs(now=None):
    """Mark active runs whose heartbeat went quiet as stopped.

    A crashed/killed simulator service leaves a ``running`` row behind;
    this is the recovery path (same pattern as the OSM importer).
    """
    now = now or timezone.now()
    stale_before = timedelta(
        seconds=settings.SIM_HEARTBEAT_STALE_SECONDS
    )
    cutoff = now - stale_before
    stale = SimulationRun.objects.filter(
        status__in=SimulationRun.ACTIVE_STATUSES,
        heartbeat_at__lt=cutoff,
    )
    count = stale.update(
        status=SimulationRun.STATUS_STOPPED,
        active_slot=None,
        finished_at=now,
        error="interrupted: heartbeat lost",
    )
    return count


def _log(run, tick, kind, detail=None, now=None):
    SimulationEvent.objects.create(
        run=run,
        tick=tick,
        kind=kind,
        detail=detail or {},
        occurred_at=now or timezone.now(),
    )


def _resolve_gates(rng, gates, crossings):
    """Validate explicit gate specs; resolve ``"random"`` crossing picks."""
    resolved = []
    crossing_ids = [c.pk for c in crossings]
    known = set(crossing_ids)
    random_picks = sum(1 for g in gates if g.get("crossing_id") == "random")
    if random_picks:
        random_ids = (
            rng.sample(crossing_ids, min(random_picks, len(crossing_ids)))
            if crossing_ids
            else []
        )
    else:
        random_ids = []
    random_iter = iter(random_ids)
    invalid = []
    for g in gates:
        spec = dict(g)
        if spec.get("crossing_id") == "random":
            pick = next(random_iter, None)
            if pick is None:
                continue
            spec["crossing_id"] = pick
        if spec.get("crossing_id") not in known:
            invalid.append(spec.get("crossing_id"))
            continue
        close_tick = int(spec.get("close_tick") or 0)
        if close_tick <= 0:
            invalid.append(spec.get("crossing_id"))
            continue
        open_tick = spec.get("open_tick")
        spec["close_tick"] = close_tick
        spec["open_tick"] = int(open_tick) if open_tick else None
        resolved.append(spec)
    if invalid:
        raise SimulatorError(
            "Gate crossings not usable (inactive/missing or bad "
            f"close_tick): {invalid}"
        )
    return resolved


def build_gate_specs(explicit, random_count, close_tick, open_tick):
    """Normalise CLI/options into gate dicts for the run config."""
    specs = [dict(g) for g in explicit]
    for _ in range(random_count):
        specs.append(
            {
                "crossing_id": "random",
                "close_tick": close_tick,
                "open_tick": open_tick,
            }
        )
    return specs


def start_run(
    *,
    label="",
    vehicles=None,
    duration_seconds=None,
    seed=None,
    tick_seconds=None,
    gates=None,
    auto_confirm=False,
    force=False,
    now=None,
):
    """Create and activate a simulation run.

    Only one run may be active; ``force`` stops the current one first.
    ``auto_confirm`` resolves every raised prompt instantly (demo
    without a click); the default requires a human to confirm in the
    web app.
    """
    now = now or timezone.now()
    interrupt_stale_runs(now)
    existing = active_run()
    if existing is not None:
        if not force:
            raise SimulatorError(
                f"Run #{existing.pk} is already {existing.status}. "
                "Stop it first or pass force=True."
            )
        stop_run(existing, note="superseded by a new run", now=now)

    vehicles = (
        settings.SIM_DEFAULT_VEHICLES if vehicles is None else int(vehicles)
    )
    if not 1 <= vehicles <= settings.SIM_MAX_VEHICLES:
        raise SimulatorError(
            f"vehicles must be between 1 and {settings.SIM_MAX_VEHICLES}"
            " (each one is a static simulated user)"
        )
    duration_seconds = (
        settings.SIM_DEFAULT_DURATION_SECONDS
        if duration_seconds is None
        else int(duration_seconds)
    )
    if duration_seconds <= 0:
        raise SimulatorError("duration_seconds must be positive")
    tick_seconds = (
        settings.SIM_TICK_SECONDS
        if tick_seconds is None
        else int(tick_seconds)
    )
    if tick_seconds <= 0:
        raise SimulatorError("tick_seconds must be positive")
    seed = secrets.randbelow(2**31) if seed is None else int(seed)

    rng = random.Random(seed)
    crossings, _ = _reference_geometries()
    resolved_gates = _resolve_gates(rng, gates or [], crossings)

    # The run row persists even if spawning fails — a failed run is the
    # audit trail (same pattern as OsmImportRun).
    run = SimulationRun.objects.create(
        label=label or f"Sim run {seed}",
        seed=seed,
        config={
            "vehicles": vehicles,
            "duration_seconds": duration_seconds,
            "tick_seconds": tick_seconds,
            "seed": seed,
            "gates": resolved_gates,
            "auto_confirm": bool(auto_confirm),
        },
        status=SimulationRun.STATUS_RUNNING,
        active_slot=1,
        heartbeat_at=now,
        started_at=now,
    )
    try:
        spawn_vehicles(run, rng)
    except Exception as exc:
        run.status = SimulationRun.STATUS_FAILED
        run.active_slot = None
        run.finished_at = timezone.now()
        run.error = str(exc)
        run.save(
            update_fields=[
                "status",
                "active_slot",
                "finished_at",
                "error",
            ]
        )
        raise
    _log(
        run,
        0,
        "run_started",
        {"vehicles": vehicles, "duration_seconds": duration_seconds},
        now=now,
    )
    transaction.on_commit(lambda: updates.publish_run_event(run, "started"))
    return run


def vehicle_frames(run):
    """Static user positions for sim payloads (id/label/lat/lng/dir)."""
    frames = []
    for v in run.vehicles.all():
        coords = list(v.path.coords)
        _, heading = _position_and_heading(
            coords, _cum_lengths(coords), v.progress_m
        )
        if v.direction < 0:
            heading = (heading + 180.0) % 360.0
        frames.append(
            {
                "id": f"veh-{v.index:03d}",
                "label": v.label,
                "lat": round(v.position.y, 6),
                "lng": round(v.position.x, 6),
                "dir": round(heading, 1),
                "wait": bool(v.waiting),
                "crossing": v.crossing_id,
            }
        )
    return frames


# --- Gate truth + presence inference (ADR-018) --------------------------------
#
# ``config["gates"]`` is the *physical* gate schedule for the demo world:
# it marks the users parked at the crossing as waiting. It never reaches
# the status overlay directly — a ``SimulationGateEvent`` row (what the
# overlay reads) is only written when a human confirms a raised prompt
# (or ``auto_confirm`` does it), or when a physically reopened gate is
# surfaced automatically after a confirmed closure.


def gate_truth(run, tick):
    """Physical gate state → ``{crossing_id: "closed"}`` (absent = open)."""
    truth = {}
    for spec in run.config.get("gates") or []:
        close_tick = spec.get("close_tick") or 0
        open_tick = spec.get("open_tick")
        if (
            close_tick
            and tick >= close_tick
            and (open_tick is None or tick < open_tick)
        ):
            truth[spec["crossing_id"]] = "closed"
    return truth


def pending_prompts(run):
    """The run's unresolved SimulationPrompts (for sim payloads)."""
    return list(
        run.prompts.filter(state=SimulationPrompt.STATE_PENDING)
        .select_related("crossing")
        .order_by("created_at", "pk")
    )


def _dwell_ticks_needed(run):
    dwell = settings.SIM_DWELL_SECONDS
    if dwell <= 0:
        return 1
    return max(1, math.ceil(dwell / max(1, run.tick_seconds)))


def _detect_prompts(run, vehicles, truth, tick, now):
    """Raise pending SimulationPrompts where simulated users are stuck.

    A prompt fires once per run+crossing+closure: ``SIM_DWELL_MIN_USERS``
    waiting users within ``SIM_DWELL_RADIUS_M`` for at least
    ``SIM_DWELL_SECONDS`` worth of ticks.
    """
    created = []
    gated = [
        spec
        for spec in run.config.get("gates") or []
        if truth.get(spec.get("crossing_id")) == "closed"
    ]
    if not gated:
        return created
    radius = settings.SIM_DWELL_RADIUS_M
    need_ticks = _dwell_ticks_needed(run)
    min_users = max(1, settings.SIM_DWELL_MIN_USERS)
    crossings = RailwayCrossing.objects.in_bulk(
        spec["crossing_id"] for spec in gated
    )
    for spec in gated:
        cid = spec["crossing_id"]
        crossing = crossings.get(cid)
        if crossing is None:
            continue
        waiting = [
            v
            for v in vehicles
            if v.crossing_id == cid
            and v.waiting
            and v.wait_ticks >= need_ticks
            and _dist_m(
                (v.position.x, v.position.y),
                (crossing.location.x, crossing.location.y),
            )
            <= radius
        ]
        if len(waiting) < min_users:
            continue
        if run.prompts.filter(
            crossing_id=cid, truth_close_tick=spec["close_tick"]
        ).exists():
            continue
        prompt = SimulationPrompt.objects.create(
            run=run,
            crossing=crossing,
            truth_close_tick=spec["close_tick"],
            detected_tick=tick,
            waiting_vehicle_indexes=[v.index for v in waiting],
            state=SimulationPrompt.STATE_PENDING,
            created_at=now,
        )
        _log(
            run,
            tick,
            "prompt_raised",
            {
                "crossing_id": cid,
                "prompt_id": prompt.pk,
                "waiting_users": [v.index for v in waiting],
            },
            now=now,
        )
        created.append(prompt)
    return created


def confirm_prompt(prompt, note="confirmed", now=None):
    """Resolve a pending prompt → ``closed`` SimulationGateEvent.

    This is the human-in-the-loop step: only a confirmed prompt surfaces
    the simulated closure into the shared status overlay.
    """
    now = now or timezone.now()
    run = prompt.run
    if prompt.state != SimulationPrompt.STATE_PENDING:
        raise SimulatorError(
            f"Prompt #{prompt.pk} is already {prompt.state}."
        )
    if not run.is_active:
        raise SimulatorError("The simulation run is no longer active.")
    event = SimulationGateEvent.objects.create(
        run=run,
        crossing=prompt.crossing,
        gate_state=SimulationGateEvent.STATE_CLOSED,
        tick=run.ticks,
        occurred_at=now,
    )
    prompt.state = SimulationPrompt.STATE_CONFIRMED
    prompt.resolved_at = now
    prompt.resolved_note = note
    prompt.save(update_fields=["state", "resolved_at", "resolved_note"])
    _log(
        run,
        run.ticks,
        "prompt_confirmed",
        {"crossing_id": prompt.crossing_id, "prompt_id": prompt.pk},
        now=now,
    )
    transaction.on_commit(
        lambda: (
            updates.publish_prompt_resolved(prompt),
            publish_crossing_status(prompt.crossing_id),
        )
    )
    return event


def _resolve_prompt(prompt, state, note, now):
    prompt.state = state
    prompt.resolved_at = now
    prompt.resolved_note = note
    prompt.save(update_fields=["state", "resolved_at", "resolved_note"])
    transaction.on_commit(lambda: updates.publish_prompt_resolved(prompt))


def dismiss_prompt(prompt, note="dismissed", now=None):
    """Resolve a pending prompt without surfacing any gate state."""
    now = now or timezone.now()
    if prompt.state != SimulationPrompt.STATE_PENDING:
        raise SimulatorError(
            f"Prompt #{prompt.pk} is already {prompt.state}."
        )
    if not prompt.run.is_active:
        raise SimulatorError("The simulation run is no longer active.")
    _resolve_prompt(prompt, SimulationPrompt.STATE_DISMISSED, note, now)
    _log(
        prompt.run,
        prompt.run.ticks,
        "prompt_dismissed",
        {"crossing_id": prompt.crossing_id, "prompt_id": prompt.pk},
        now=now,
    )
    return prompt


def _expire_pending_prompts(run, now, note):
    """Mark every pending prompt of ``run`` expired."""
    for prompt in run.prompts.filter(state=SimulationPrompt.STATE_PENDING):
        _resolve_prompt(prompt, SimulationPrompt.STATE_EXPIRED, note, now)


def _affected_crossings(run):
    """Crossing ids with gate events in ``run`` (for status republish)."""
    return list(
        run.gate_events.order_by()
        .values_list("crossing_id", flat=True)
        .distinct()
    )


def _republish_gates(run):
    for crossing_id in _affected_crossings(run):
        publish_crossing_status(crossing_id)


def _update_dwell(vehicles, truth):
    """Refresh dwell counters for the (static) simulated users.

    Users never move (ADR-021): a parked user counts as *waiting* —
    the darkened "stopped at the gate" pin — only while its crossing's
    physical gate is closed, and ``wait_ticks`` accumulates for presence
    inference. An open gate clears both so a later closure cycle
    re-detects dwell from zero.
    """
    for v in vehicles:
        if v.crossing_id is not None and truth.get(v.crossing_id) == "closed":
            v.waiting = True
            v.wait_ticks += 1
        else:
            v.waiting = False
            v.wait_ticks = 0


@transaction.atomic
def tick_run(run, now=None):
    """Advance ``run`` by one tick: dwell, inference, publish.

    Gate specs describe the physical world (they mark the parked
    simulated users as waiting);
    surfaced status only changes through confirmed prompts and the
    automatic reopen. Returns a summary dict; no-op (``None``) when the
    run is not ``running``.
    """
    now = now or timezone.now()
    if run.status != SimulationRun.STATUS_RUNNING:
        return None
    tick = run.ticks + 1
    tick_seconds = run.tick_seconds
    run.ticks = tick  # set early so prompt/event rows record this tick

    truth = gate_truth(run, tick)
    vehicles = list(run.vehicles.all())
    _update_dwell(vehicles, truth)
    SimulatedVehicle.objects.bulk_update(vehicles, ["waiting", "wait_ticks"])

    # Presence inference → confirmation prompts. Auto-confirm resolves
    # them immediately through the same code path a human click takes.
    new_prompts = _detect_prompts(run, vehicles, truth, tick, now)
    if run.config.get("auto_confirm"):
        for prompt in new_prompts:
            confirm_prompt(prompt, note="auto-confirmed", now=now)

    # Physical gate transitions: log them, expire unanswered prompts on
    # reopen, and surface an "open" event after a confirmed closure —
    # the queue visibly disperses, no second confirmation needed.
    gate_changes = []
    for spec in run.config.get("gates") or []:
        cid = spec["crossing_id"]
        close_tick = spec.get("close_tick") or 0
        open_tick = spec.get("open_tick")
        if tick == close_tick:
            _log(run, tick, "gate_closed", {"crossing_id": cid}, now=now)
        if open_tick is None or tick != open_tick:
            continue
        _log(run, tick, "gate_open", {"crossing_id": cid}, now=now)
        for prompt in run.prompts.filter(
            crossing_id=cid,
            truth_close_tick=close_tick,
            state=SimulationPrompt.STATE_PENDING,
        ):
            _resolve_prompt(
                prompt,
                SimulationPrompt.STATE_EXPIRED,
                "gate reopened before confirmation",
                now,
            )
        latest = (
            run.gate_events.filter(crossing_id=cid).order_by("-pk").first()
        )
        if latest is not None and latest.gate_state == "closed":
            SimulationGateEvent.objects.create(
                run=run,
                crossing_id=cid,
                gate_state=SimulationGateEvent.STATE_OPEN,
                tick=tick,
                occurred_at=now,
            )
            gate_changes.append(cid)

    # Unanswered prompts expire so a missed one can't nag forever.
    ttl = settings.SIM_PROMPT_TTL_SECONDS
    for prompt in run.prompts.filter(
        state=SimulationPrompt.STATE_PENDING,
        created_at__lte=now - timedelta(seconds=ttl),
    ):
        _resolve_prompt(
            prompt, SimulationPrompt.STATE_EXPIRED, "prompt timed out", now
        )

    run.heartbeat_at = now
    update_fields = ["ticks", "heartbeat_at"]
    finished = bool(
        run.duration_seconds and tick * tick_seconds >= run.duration_seconds
    )
    if finished:
        run.status = SimulationRun.STATUS_FINISHED
        run.active_slot = None
        run.finished_at = now
        update_fields += ["status", "active_slot", "finished_at"]
        _log(run, tick, "run_finished", now=now)
        _expire_pending_prompts(run, now, "run finished")
    run.save(update_fields=update_fields)

    gate_states = gate_states_for_run(run)
    frames = vehicle_frames(run)
    prompts = pending_prompts(run)

    def _publish():
        updates.publish_tick(run, frames, gate_states, prompts, now=now)
        for prompt in new_prompts:
            if prompt.state == SimulationPrompt.STATE_PENDING:
                updates.publish_prompt(prompt)
        for cid in gate_changes:
            publish_crossing_status(cid)
        if finished:
            updates.publish_run_event(run, "finished")
            _republish_gates(run)

    transaction.on_commit(_publish)
    return {
        "tick": tick,
        "vehicles": len(frames),
        "gate_changes": gate_changes,
        "prompts": [p.pk for p in new_prompts],
        "finished": finished,
    }


def _end_active(run, status, kind, note="", now=None):
    now = now or timezone.now()
    run.status = status
    run.active_slot = None
    run.finished_at = now
    if note:
        run.error = note
    run.save(
        update_fields=["status", "active_slot", "finished_at", "error"]
    )
    _log(run, run.ticks, kind, {"note": note} if note else {}, now=now)
    _expire_pending_prompts(run, now, "run ended")
    updates.publish_run_event(run, kind.split("_", 1)[-1])
    # The overlay ends with the active status — republish every gated
    # crossing so clients see the state revert.
    _republish_gates(run)
    return run


def stop_run(run, note="stopped", now=None):
    """Stop an active run; gates revert immediately (overlay ends)."""
    if run is None or not run.is_active:
        return run
    return _end_active(run, SimulationRun.STATUS_STOPPED, "run_stopped", note, now)


def fail_run(run, note, now=None):
    if run is None or not run.is_active:
        return run
    return _end_active(run, SimulationRun.STATUS_FAILED, "run_failed", note, now)


def pause_run(run, now=None):
    if run is None or run.status != SimulationRun.STATUS_RUNNING:
        return run
    now = now or timezone.now()
    run.status = SimulationRun.STATUS_PAUSED
    run.save(update_fields=["status"])
    _log(run, run.ticks, "run_paused", now=now)
    updates.publish_run_event(run, "paused")
    return run


def resume_run(run, now=None):
    if run is None or run.status != SimulationRun.STATUS_PAUSED:
        return run
    now = now or timezone.now()
    run.status = SimulationRun.STATUS_RUNNING
    run.heartbeat_at = now
    run.save(update_fields=["status", "heartbeat_at"])
    _log(run, run.ticks, "run_resumed", now=now)
    updates.publish_run_event(run, "resumed")
    return run


def reset_simulation(now=None):
    """Delete all simulator-owned rows. Refuses while a run is active.

    Only ``simulator_*`` tables are touched — community reports,
    reference geometry and user records are never deleted here.
    """
    interrupt_stale_runs(now)
    if active_run() is not None:
        raise SimulatorError(
            "A simulation run is still active. Stop it before resetting."
        )
    # Deleting runs cascades to vehicles, gate events and events.
    deleted, detail = SimulationRun.objects.all().delete()
    return {"deleted": deleted, "by_model": detail}


def drive_run(run, interval=None):
    """Drive ``run`` until it leaves the active state (service loop)."""
    sleep_s = interval if interval is not None else run.tick_seconds
    sleep_s = max(0.5, float(sleep_s))
    while True:
        run.refresh_from_db(fields=["status", "config", "ticks"])
        if run.status == SimulationRun.STATUS_PAUSED:
            # A paused run still holds the active slot; keep the
            # heartbeat fresh so it isn't treated as a crashed service.
            run.heartbeat_at = timezone.now()
            run.save(update_fields=["heartbeat_at"])
            time.sleep(1.0)
            continue
        if run.status != SimulationRun.STATUS_RUNNING:
            return run.status
        tick_run(run)
        time.sleep(sleep_s)


def install_sigterm_handler():
    """Translate SIGTERM into SystemExit so the service exits cleanly."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
