"""Route planning service: provider call + crossing analysis + verdicts.

Safety rules encoded here (ADR-004/ADR-013):
- ``closed_reported`` crossings on/near the primary route are "blocking";
  unknown/stale states never produce warnings.
- Alternative routes are only evaluated when something blocks the primary.
- An alternative is ``verified`` only when every blocking crossing is
  farther than ``ROUTE_AVOID_CLEARANCE_M`` from its geometry and it has no
  closed_reported crossing of its own. Nothing else may be called
  avoidance.
"""
from dataclasses import dataclass, field

from django.conf import settings
from django.utils import timezone

from incidents import services as incident_services
from incidents.services import STATE_CLOSED_REPORTED, STATE_CONFLICTING
from railways.models import RailwayCrossing

from .analysis import crossings_along_route, distances_to_crossings
from .providers import RoutingError
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

    @property
    def alternatives(self):
        return self.routes[1:]

    @property
    def passing_alternatives(self):
        return [r for r in self.alternatives if r.verification == "passes"]

    @property
    def blocking_names(self):
        return ", ".join(
            e.crossing.name or "Unnamed level crossing" for e in self.blocking
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
    statuses = incident_services.derive_statuses(
        list(crossings_by_id.values()), now=now
    )

    routes = []
    blocking = []
    for i, (candidate, rows) in enumerate(zip(candidates, per_candidate)):
        entries = tuple(
            RouteCrossingStatus(crossing=r, status=statuses[r.crossing_id])
            for r in rows
            if r.crossing_id in statuses
        )
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
        if i == 0:
            blocking = [
                e
                for e in entries
                if e.status.state == STATE_CLOSED_REPORTED
            ]

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
                if e.status.state == STATE_CLOSED_REPORTED
            ]
            if own_closed:
                verification = "passes"
                detail = (
                    "This route also has a crossing reported closed: "
                    + ", ".join(own_closed)
                )
            elif min_clearance <= near_m:
                verification = "passes"
                detail = "This route still passes a reported-closed crossing."
            elif missing:
                verification = "unverifiable"
                detail = (
                    "We couldn't measure this route's distance from every "
                    "reported-closed crossing, so avoidance can't be verified."
                )
            elif min_clearance <= clearance_m:
                verification = "uncertain"
                detail = (
                    "This route stays only about "
                    f"{min_clearance:.0f} m from a reported-closed crossing "
                    "— too close to confirm it avoids it."
                )
            else:
                verification = "verified"
                detail = (
                    "Checked: this route stays more than "
                    f"{round(min_clearance):.0f} m from every "
                    "reported-closed crossing on the original route "
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
    )
