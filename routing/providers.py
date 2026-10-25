"""Routing provider abstraction (ADR-004/ADR-013).

Google Routes has no point/segment exclusion mechanism, so crossing
avoidance is always verified afterwards against route geometry in
``routing.analysis`` — never assumed from the provider.
"""
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from django.conf import settings

from .polyline import decode, to_linestring

COMPUTE_ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

FIELD_MASK = (
    "routes.distanceMeters,routes.duration,routes.staticDuration,"
    "routes.routeLabels,routes.description,routes.polyline.encodedPolyline,"
    "routes.warnings"
)


class RoutingError(Exception):
    """Routing could not be completed. ``code`` is a stable machine code."""

    CODES = {
        "not_configured",
        "no_route",
        "quota",
        "auth",
        "timeout",
        "invalid_request",
        "provider_error",
    }

    def __init__(self, code, message=None):
        if code not in self.CODES:
            raise ValueError(f"Unknown routing error code: {code!r}")
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class Waypoint:
    place_id: str = ""
    address: str = ""
    # lat/lng arrive as GET params only from an explicit user action (the
    # opt-in "my location" fix or a map click); they are never stored.
    lat: float | None = None
    lng: float | None = None
    # ``via`` marks a pass-through intermediate used only for detour
    # synthesis (ADR-020) — never an origin/destination.
    via: bool = False

    def as_api(self):
        base = {}
        if self.place_id:
            base = {"placeId": self.place_id}
        elif self.lat is not None and self.lng is not None:
            base = {
                "location": {
                    "latLng": {"latitude": self.lat, "longitude": self.lng}
                }
            }
        else:
            base = {"address": self.address}
        if self.via:
            base["via"] = True
        return base


@dataclass(frozen=True)
class RouteCandidate:
    index: int
    geometry: object  # LineString or None
    distance_m: int | None
    duration_s: int | None
    static_duration_s: int | None
    description: str = ""
    labels: tuple = ()
    warnings: tuple = ()
    # True when this candidate was synthesized by the detour via-point
    # path rather than offered by the provider (ADR-020).
    synthesized: bool = False

    @property
    def distance_km(self):
        if self.distance_m is None:
            return None
        return f"{self.distance_m / 1000:.1f}"

    @property
    def duration_min(self):
        if self.duration_s is None:
            return None
        return max(1, round(self.duration_s / 60))


def _parse_seconds(value):
    """Parse Google's duration format ("672s") into int seconds."""
    if not isinstance(value, str) or not value.endswith("s"):
        return None
    try:
        return int(float(value[:-1]))
    except ValueError:
        return None


class GoogleRoutesProvider:
    """Google Routes API ``computeRoutes`` over stdlib urllib.

    Never logs or embeds the API key in error messages.
    """

    name = "google"
    attribution = "Routes by Google"
    supports_exclusion = False

    def __init__(self, api_key, timeout, routing_preference):
        self._api_key = api_key
        self._timeout = timeout
        self._traffic_aware = routing_preference == "TRAFFIC_AWARE"

    @property
    def traffic_aware(self):
        return self._traffic_aware

    def compute_routes(
        self, origin: Waypoint, destination: Waypoint, intermediates=None
    ):
        body = {
            "origin": origin.as_api(),
            "destination": destination.as_api(),
            "travelMode": "DRIVE",
            "polylineQuality": "HIGH_QUALITY",
            "languageCode": "en",
            "regionCode": "IN",
            "units": "METRIC",
        }
        # Google ignores computeAlternativeRoutes once intermediates are
        # present — a via call deterministically returns its own route.
        if intermediates:
            body["intermediates"] = [w.as_api() for w in intermediates]
        else:
            body["computeAlternativeRoutes"] = True
        if self._traffic_aware:
            body["routingPreference"] = "TRAFFIC_AWARE"

        request = urllib.request.Request(
            COMPUTE_ROUTES_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout
            ) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status == 400:
                code = "invalid_request"
            elif status in (401, 403):
                code = "auth"
            elif status == 429:
                code = "quota"
            else:
                code = "provider_error"
            raise RoutingError(code, f"Route provider returned HTTP {status}")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise RoutingError("timeout", "Route provider timed out")
            raise RoutingError("timeout", "Couldn't reach the route provider")
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            raise RoutingError(
                "provider_error", "Route provider returned invalid data"
            )

        routes = data.get("routes") or []
        if not routes:
            raise RoutingError("no_route", "No route found")
        return self._parse_candidates(routes)

    def _parse_candidates(self, routes):
        candidates = []
        for route in routes:
            polyline = (route.get("polyline") or {}).get("encodedPolyline")
            geometry = None
            if polyline:
                try:
                    geometry = to_linestring(decode(polyline))
                except (IndexError, ValueError):
                    geometry = None
            candidates.append(
                RouteCandidate(
                    index=-1,
                    geometry=geometry,
                    distance_m=route.get("distanceMeters"),
                    duration_s=_parse_seconds(route.get("duration")),
                    static_duration_s=_parse_seconds(
                        route.get("staticDuration")
                    ),
                    description=route.get("description") or "",
                    labels=tuple(route.get("routeLabels") or ()),
                    warnings=tuple(route.get("warnings") or ()),
                )
            )
        # Order so the DEFAULT_ROUTE-labelled candidate is index 0.
        candidates.sort(
            key=lambda c: 0 if "DEFAULT_ROUTE" in c.labels else 1
        )
        return [
            RouteCandidate(
                index=i,
                geometry=c.geometry,
                distance_m=c.distance_m,
                duration_s=c.duration_s,
                static_duration_s=c.static_duration_s,
                description=c.description,
                labels=c.labels,
                warnings=c.warnings,
            )
            for i, c in enumerate(candidates)
        ]


def get_provider():
    """Return the configured routing provider or raise ``not_configured``."""
    if (
        getattr(settings, "ROUTING_PROVIDER", "") == "google"
        and getattr(settings, "GOOGLE_MAPS_SERVER_KEY", "")
    ):
        return GoogleRoutesProvider(
            api_key=settings.GOOGLE_MAPS_SERVER_KEY,
            timeout=settings.ROUTING_TIMEOUT_SECONDS,
            routing_preference=settings.ROUTING_GOOGLE_ROUTING_PREFERENCE,
        )
    raise RoutingError("not_configured", "No routing provider is configured")
