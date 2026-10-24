"""Simulation engine: vehicle spawning, ticking and run lifecycle.

Determinism: a run's vehicles and gate schedule come entirely from its
``seed`` — replaying the same seed against the same imported OSM data
produces the same scenario.

Vehicle paths are *synthetic* LineStrings through real mapped crossings:
the road direction is approximated as perpendicular to the nearest
mapped track at the crossing node (roads cross tracks at right angles
at level crossings). They are demo geometry, not real road or routing
provider data, and are labelled as such everywhere they surface.

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

    The middle vertex is exactly the crossing point (vehicles traverse
    it); other vertices get small perpendicular jitter so paths look
    road-like rather than perfectly straight.
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
    """Create ``config["vehicles"]`` vehicles for ``run`` deterministically."""
    crossings, track_geoms = _reference_geometries()
    if not crossings:
        raise SimulatorError(
            "No active crossings are mapped — import OSM data first "
            "(see RUNBOOK 'OSM import')."
        )
    base_length = settings.SIM_PATH_LENGTH_M
    min_speed = settings.SIM_VEHICLE_MIN_SPEED_MPS
    max_speed = settings.SIM_VEHICLE_MAX_SPEED_MPS
    vehicles = []
    for i in range(run.vehicle_count):
        crossing = rng.choice(crossings)
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
        progress = rng.uniform(0, total)
        position, _ = _position_and_heading(coords, cum, progress)
        vehicles.append(
            SimulatedVehicle(
                run=run,
                index=i,
                label=f"Sim vehicle {i + 1:02d}",
                path=LineString(coords, srid=4326),
                path_length_m=total,
                progress_m=progress,
                direction=rng.choice([-1, 1]),
                speed_mps=rng.uniform(min_speed, max_speed),
                position=Point(position, srid=4326),
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
    force=False,
    now=None,
):
    """Create and activate a simulation run.

    Only one run may be active; ``force`` stops the current one first.
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
    """Current vehicle positions for sim payloads (id/label/lat/lng/dir)."""
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
            }
        )
    return frames


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


@transaction.atomic
def tick_run(run, now=None):
    """Advance ``run`` by one tick: vehicles, due gate events, publish.

    Returns a summary dict. No-op (returns ``None``) when the run is not
    ``running``.
    """
    now = now or timezone.now()
    if run.status != SimulationRun.STATUS_RUNNING:
        return None
    tick = run.ticks + 1
    tick_seconds = run.tick_seconds

    vehicles = list(run.vehicles.all())
    for v in vehicles:
        v.progress_m += v.direction * v.speed_mps * tick_seconds
        if v.progress_m > v.path_length_m:
            v.progress_m = 2 * v.path_length_m - v.progress_m
            v.direction = -1
        elif v.progress_m < 0:
            v.progress_m = -v.progress_m
            v.direction = 1
        coords = list(v.path.coords)
        position, _ = _position_and_heading(
            coords, _cum_lengths(coords), v.progress_m
        )
        v.position = Point(position, srid=4326)
    SimulatedVehicle.objects.bulk_update(
        vehicles, ["progress_m", "direction", "position"]
    )

    gate_changes = []
    for spec in run.config.get("gates") or []:
        state = None
        if tick == spec.get("close_tick"):
            state = SimulationGateEvent.STATE_CLOSED
        elif tick == spec.get("open_tick"):
            state = SimulationGateEvent.STATE_OPEN
        if state is None:
            continue
        crossing_id = spec["crossing_id"]
        SimulationGateEvent.objects.create(
            run=run,
            crossing_id=crossing_id,
            gate_state=state,
            tick=tick,
            occurred_at=now,
        )
        _log(
            run,
            tick,
            f"gate_{state}",
            {"crossing_id": crossing_id},
            now=now,
        )
        gate_changes.append(crossing_id)

    run.ticks = tick
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
    run.save(update_fields=update_fields)

    gate_states = gate_states_for_run(run)
    frames = vehicle_frames(run)

    def _publish():
        updates.publish_tick(run, frames, gate_states, now=now)
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
