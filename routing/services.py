"""Route planning service: provider call + crossing analysis + verdicts.

Safety rules encoded here (ADR-004/ADR-013):
- ``closed_reported`` crossings on/near the primary route are "blocking";
  unknown/stale states never produce warnings. Same-line inferred
  closures (ADR-020) block too — they are labelled as inference.
- Alternative routes are only evaluated when something blocks the primary.
- An alternative is ``verified`` only when every blocking crossing is
  farther than ``ROUTE_AVOID_CLEARANCE_M`` from its geometry and it has no
  closed crossing of its own. Nothing else may be called avoidance.
- When the provider returns a single route, ``_detour_candidates``
  synthesizes extra candidates through a via point offset from the
  blocked crossing; they go through the identical verification, so an
  unverified detour is never sold as avoidance.
"""
import math
from dataclasses import dataclass, field, replace

from django.conf import settings
from django.utils import timezone

from incidents import services as incident_services
from incidents.services import (
    STATE_CLOSED_INFERRED,
    STATE_CLOSED_REPORTED,
    STATE_CLOSED_SIMULATED,
    STATE_CONFLICTING,
)

# States that make a crossing "blocking" for route purposes. A simulated
# or same-line-inferred closure blocks exactly like a reported one —
# each is labelled for what it is, never as a direct report.
BLOCKING_STATES = (
    STATE_CLOSED_REPORTED,
    STATE_CLOSED_SIMULATED,
    STATE_CLOSED_INFERRED,
)
from railways.models import RailwayCrossing

from .analysis import crossings_along_route, distances_to_crossings
from .providers import RoutingError, Waypoint
from .throttle import allow_request


@dataclass(frozen=True)
class RouteCrossingStatus:
    crossing: object  # analysis.RouteCrossing
    status: object  # incidents CrossingStatus


@dataclass(frozen=True)
class RouteOption:
    id: str
    is_primary: bool
    candidate: object  # providers.RouteCandidate
    crossings: tuple  # RouteCrossingStatus…
    counts: dict
    verification: str | None = None  # verified|passes|uncertain|unverifiable
    verification_detail: str = ""
    avoided_clearance_m: float | None = None
    delta_duration_s: int | None = None
    delta_distance_m: int | None = None

    @property
    def delta_label(self):
        parts = []
        if self.delta_duration_s is not None:
            minutes = round(self.delta_duration_s / 60)
            if minutes:
                parts.append(
                    f"{'+' if minutes > 0 else '−'}{abs(minutes)} min"
                )
        if self.delta_distance_m is not None:
            km = self.delta_distance_m / 1000
            if round(km, 1):
                parts.append(
                    f"{'+' if km > 0 else '−'}{abs(km):.1f} km"
                )
        return ", ".join(parts) or "about the same time and distance"


@dataclass(frozen=True)
class RoutePlan:
    ok: bool
    error: str | None
    routes: tuple
    blocking: tuple  # RouteCrossingStatus on the primary route that block
    warning_level: str | None
    has_verified_alternative: bool
    computed_at: object
    provider_name: str = ""
    attribution: str = ""
    traffic_aware: bool = False
    # Route shown/selected first: the primary, or the first *verified*
    # alternative when the primary is blocked (ADR-021) — the suggested
    # route never passes a closed crossing it could avoid.
    preferred_route_id: str = "r0"

    @property
    def alternatives(self):
        return self.routes[1:]

    @property
    def passing_alternatives(self):
        return [r for r in self.alternatives if r.verification == "passes"]

    @property
    def blocking_names(self):
        parts = []
        for e in self.blocking:
            name = e.crossing.name or "Unnamed level crossing"
            if e.status.simulation:
                name += " (simulated)"
            elif getattr(e.status, "inference", None):
                name += " (likely — same line)"
            parts.append(name)
        return ", ".join(parts)

    @property
    def blocking_all_simulated(self):
        return bool(self.blocking) and all(
            e.status.simulation for e in self.blocking
        )

    @property
    def blocking_all_inferred(self):
        return bool(self.blocking) and all(
            getattr(e.status, "inference", None) for e in self.blocking
        )


def _error_plan(code, now, provider_name="", attribution="", traffic_aware=False):
    return RoutePlan(
        ok=False,
        error=code,
        routes=(),
        blocking=(),
        warning_level=None,
        has_verified_alternative=False,
        computed_at=now,
        provider_name=provider_name,
        attribution=attribution,
        traffic_aware=traffic_aware,
    )


def _delta(primary_val, alt_val):
    if primary_val is None or alt_val is None:
        return None
    return alt_val - primary_val


def _detour_via_points(candidate, blocking):
    """Via points offset sideways from the blocking crossings.

    Forcing a route through a point ``ROUTE_DETOUR_VIA_OFFSET_M`` metres
    perpendicular to the route line at the blocked crossing is the
    standard way to make the provider surface the road around a blocked
    segment it didn't offer on its own. Returns up to
    ``ROUTE_DETOUR_MAX_CALLS`` ``via`` waypoints (Google returns a
    single route per via call).
    """
    geometry = candidate.geometry
    total_m = candidate.distance_m
    if geometry is None or not total_m:
        return []
    offset_m = settings.ROUTE_DETOUR_VIA_OFFSET_M
    ordered = sorted(
        blocking,
        key=lambda e: 0 if e.crossing.match == "on_route" else 1,
    )
    points = []
    seen = set()
    for entry in ordered:
        frac = min(1.0, max(0.0, entry.crossing.along_m / total_m))
        window = min(0.05, 100.0 / total_m)  # ~100 m tangent sample
        p1 = geometry.interpolate_normalized(max(0.0, frac - window))
        p2 = geometry.interpolate_normalized(min(1.0, frac + window))
        if p1.equals(p2):
            continue
        lat = (p1.y + p2.y) / 2
        dx = (p2.x - p1.x) * math.cos(math.radians(lat))
        dy = p2.y - p1.y
        bearing = math.atan2(dx, dy)
        base = geometry.interpolate_normalized(frac)
        for sign in (1, -1):
            angle = bearing + sign * math.pi / 2
            via_lat = base.y + math.cos(angle) * offset_m / 111320.0
            via_lng = base.x + math.sin(angle) * offset_m / (
                111320.0 * math.cos(math.radians(base.y))
            )
            key = (round(via_lat, 4), round(via_lng, 4))
            if key in seen:
                continue
            seen.add(key)
            points.append(
                Waypoint(
                    lat=round(via_lat, 6),
                    lng=round(via_lng, 6),
                    via=True,
                )
            )
            if len(points) >= settings.ROUTE_DETOUR_MAX_CALLS:
                return points
    return points


def plan_route(origin, destination, client_key, now=None):
    """Compute routes and evaluate each against mapped crossings."""
    now = now or timezone.now()

    if not allow_request(client_key):
        return _error_plan("rate_limited", now)

    from .providers import get_provider

    try:
        provider = get_provider()
    except RoutingError as exc:
        return _error_plan(exc.code, now)

    try:
        candidates = provider.compute_routes(origin, destination)
    except RoutingError as exc:
        return _error_plan(
            exc.code,
            now,
            provider_name=provider.name,
            attribution=provider.attribution,
            traffic_aware=getattr(provider, "traffic_aware", False),
        )

    # Analyse every candidate's crossings; one bulk status call covers all.
    per_candidate = []
    all_ids = []
    for candidate in candidates:
        if candidate.geometry is None:
            rows = []
        else:
            rows = crossings_along_route(candidate.geometry)
        per_candidate.append(rows)
        all_ids.extend(r.crossing_id for r in rows)

    crossings_by_id = {
        c.pk: c
        for c in RailwayCrossing.objects.filter(pk__in=set(all_ids))
    }
    statuses = incident_services.effective_statuses(
        list(crossings_by_id.values()), now=now
    )

    def entries_for(rows):
        return tuple(
            RouteCrossingStatus(crossing=r, status=statuses[r.crossing_id])
            for r in rows
            if r.crossing_id in statuses
        )

    entries_list = [entries_for(rows) for rows in per_candidate]
    blocking = (
        [e for e in entries_list[0] if e.status.state in BLOCKING_STATES]
        if entries_list
        else []
    )

    # The provider offered no alternatives and the route is blocked:
    # synthesize detour candidates through a via point offset sideways
    # from each blocking crossing (ADR-020). They get the identical
    # crossing analysis and avoidance verification — a detour that still
    # passes the blocked crossing simply comes out ``passes``.
    if blocking and len(candidates) == 1 and settings.ROUTE_DETOUR_ENABLED:
        for via in _detour_via_points(candidates[0], blocking):
            if not allow_request(client_key):
                break
            try:
                detours = provider.compute_routes(
                    origin, destination, intermediates=[via]
                )
            except RoutingError:
                continue
            if not detours:
                continue
            cand = replace(
                detours[0],
                index=len(candidates),
                synthesized=True,
                description=detours[0].description or "Detour via side roads",
            )
            # Identical geometry to an existing candidate adds nothing —
            # both via points often resolve to the same road.
            if cand.geometry is not None and any(
                c.geometry is not None and c.geometry.equals(cand.geometry)
                for c in candidates
            ):
                continue
            rows = (
                crossings_along_route(cand.geometry)
                if cand.geometry is not None
                else []
            )
            new_ids = [
                r.crossing_id
                for r in rows
                if r.crossing_id not in crossings_by_id
            ]
            if new_ids:
                extra = {
                    c.pk: c
                    for c in RailwayCrossing.objects.filter(pk__in=new_ids)
                }
                crossings_by_id.update(extra)
                statuses.update(
                    incident_services.effective_statuses(
                        list(extra.values()), now=now
                    )
                )
            candidates.append(cand)
            per_candidate.append(rows)
            entries_list.append(entries_for(rows))

    routes = []
    for i, (candidate, entries) in enumerate(zip(candidates, entries_list)):
        counts = {}
        for entry in entries:
            counts[entry.status.state] = counts.get(entry.status.state, 0) + 1
        route = RouteOption(
            id=f"r{i}",
            is_primary=(i == 0),
            candidate=candidate,
            crossings=entries,
            counts=counts,
            delta_duration_s=(
                _delta(routes[0].candidate.duration_s, candidate.duration_s)
                if i > 0
                else None
            ),
            delta_distance_m=(
                _delta(routes[0].candidate.distance_m, candidate.distance_m)
                if i > 0
                else None
            ),
        )
        routes.append(route)

    # Warning level reflects the primary route only.
    warning_level = None
    if any(e.crossing.match == "on_route" for e in blocking):
        warning_level = "closed_on_route"
    elif blocking:
        warning_level = "closed_near_route"
    elif any(
        e.status.state == STATE_CONFLICTING and e.crossing.match == "on_route"
        for e in routes[0].crossings
    ):
        warning_level = "conflicting_on_route"

    # Alternatives are verified only when something blocks the primary.
    near_m = settings.ROUTE_CROSSING_NEAR_M
    clearance_m = settings.ROUTE_AVOID_CLEARANCE_M
    has_verified = False
    if blocking:
        # Honest wording for what actually blocks the route.
        if all(e.status.simulation for e in blocking):
            blocking_word = "simulated-closed"
        elif all(getattr(e.status, "inference", None) for e in blocking):
            blocking_word = "likely-closed"
        else:
            blocking_word = "reported-closed"
        blocking_ids = [e.crossing.crossing_id for e in blocking]
        primary = routes[0]
        updated = [primary]
        for route in routes[1:]:
            candidate = route.candidate
            if candidate.geometry is None:
                updated.append(
                    RouteOption(
                        **{**route.__dict__, "verification": "unverifiable"}
                    )
                )
                continue
            distances = distances_to_crossings(
                candidate.geometry, blocking_ids
            )
            # A blocking crossing with no distance (row vanished between
            # queries) must fail closed: we cannot verify avoidance.
            missing = [cid for cid in blocking_ids if cid not in distances]
            min_clearance = min(
                (distances[cid] for cid in blocking_ids if cid in distances),
                default=float("inf"),
            )
            own_closed = [
                e.crossing.name or "Unnamed level crossing"
                for e in route.crossings
                if e.status.state in BLOCKING_STATES
            ]
            if own_closed:
                verification = "passes"
                detail = (
                    f"This route also has a {blocking_word} crossing: "
                    + ", ".join(own_closed)
                )
            elif min_clearance <= near_m:
                verification = "passes"
                detail = (
                    f"This route still passes a {blocking_word} crossing."
                )
            elif missing:
                verification = "unverifiable"
                detail = (
                    "We couldn't measure this route's distance from every "
                    f"{blocking_word} crossing, so avoidance can't be verified."
                )
            elif min_clearance <= clearance_m:
                verification = "uncertain"
                detail = (
                    "This route stays only about "
                    f"{min_clearance:.0f} m from a {blocking_word} crossing "
                    "— too close to confirm it avoids it."
                )
            else:
                verification = "verified"
                detail = (
                    "Checked: this route stays more than "
                    f"{round(min_clearance):.0f} m from every "
                    f"{blocking_word} crossing on the original route "
                    "(by route geometry)."
                )
                has_verified = True
            updated.append(
                RouteOption(
                    **{
                        **route.__dict__,
                        "verification": verification,
                        "verification_detail": detail,
                        "avoided_clearance_m": min_clearance,
                        "delta_duration_s": _delta(
                            primary.candidate.duration_s,
                            candidate.duration_s,
                        ),
                        "delta_distance_m": _delta(
                            primary.candidate.distance_m,
                            candidate.distance_m,
                        ),
                    }
                )
            )
        routes = updated

    return RoutePlan(
        ok=True,
        error=None,
        routes=tuple(routes),
        blocking=tuple(blocking),
        warning_level=warning_level,
        has_verified_alternative=has_verified,
        computed_at=now,
        provider_name=provider.name,
        attribution=provider.attribution,
        traffic_aware=getattr(provider, "traffic_aware", False),
        preferred_route_id=next(
            (r.id for r in routes[1:] if r.verification == "verified"),
            "r0",
        ),
    )
