# Icon path data from Lucide (https://lucide.dev), ISC license.
# See DATA_SOURCES.md for attribution details.
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

_ICONS = {
    "circle-check": '<circle cx="12" cy="12" r="10"/><path d="m16 9-5.5 5.5L8 12"/>',
    "circle-x": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "circle-help": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "map": '<path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z"/><path d="M15 5.764v15"/><path d="M9 3.236v15"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><path d="M16 3.128a4 4 0 0 1 0 7.744"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/>',
    "flask-conical": '<path d="M14 2v6a2 2 0 0 0 .245.96l5.51 10.08A2 2 0 0 1 18 22H6a2 2 0 0 1-1.755-2.96l5.51-10.08A2 2 0 0 0 10 8V2"/><path d="M6.453 15h11.094"/><path d="M8.5 2h7"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "octagon-x": '<path d="m15 9-6 6"/><path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"/><path d="m9 9 6 6"/>',
    "inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "cloud-off": '<path d="M10.94 5.274A7 7 0 0 1 15.71 10h1.79a4.5 4.5 0 0 1 4.222 6.057"/><path d="M18.796 18.81A4.5 4.5 0 0 1 17.5 19H9A7 7 0 0 1 5.79 5.78"/><path d="m2 2 20 20"/>',
    "locate-fixed": '<line x1="2" x2="5" y1="12" y2="12"/><line x1="19" x2="22" y1="12" y2="12"/><line x1="12" x2="12" y1="2" y2="5"/><line x1="12" x2="12" y1="19" y2="22"/><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3"/>',
    "map-pin-off": '<path d="M12.75 7.09a3 3 0 0 1 2.16 2.16"/><path d="M17.072 17.072c-1.634 2.17-3.527 3.912-4.471 4.727a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 1.432-4.568"/><path d="m2 2 20 20"/><path d="M8.475 2.818A8 8 0 0 1 20 10c0 1.183-.31 2.377-.81 3.533"/><path d="M9.13 9.13a3 3 0 0 0 3.74 3.74"/>',
    "route": '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>',
    "train-track": '<path d="M2 17 17 2"/><path d="m2 14 8 8"/><path d="m5 11 8 8"/><path d="m8 8 8 8"/><path d="m11 5 8 8"/><path d="m14 2 8 8"/><path d="M7 22 22 7"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "search": '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
}

_SVG_OPEN = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" aria-hidden="true" focusable="false"'
)


@register.simple_tag
def icon(name, **kwargs):
    css_class = kwargs.get("class", "size-4")
    inner = _ICONS.get(name)
    if inner is None:
        inner = _ICONS["circle-help"]
    return format_html('{} class="{}">{}</svg>', mark_safe(_SVG_OPEN), css_class, mark_safe(inner))


_STATUS_BADGES = {
    "open": {
        "label": "Reported open",
        "icon": "circle-check",
        "classes": "bg-green-50 text-green-800 ring-green-600/20",
        "description": "A community report says this crossing was recently open.",
    },
    "closed": {
        "label": "Reported closed",
        "icon": "circle-x",
        "classes": "bg-red-50 text-red-800 ring-red-600/20",
        "description": "A community report says this crossing was recently closed.",
    },
    "unknown": {
        "label": "Status unknown",
        "icon": "circle-help",
        "classes": "bg-amber-50 text-amber-800 ring-amber-600/20",
        "description": "No reliable information about this crossing's status.",
    },
    "stale": {
        "label": "Report outdated",
        "icon": "clock",
        "classes": "bg-amber-50 text-amber-800 ring-amber-600/20",
        "description": "The most recent report is too old to rely on.",
    },
    "conflicting": {
        "label": "Conflicting reports",
        "icon": "triangle-alert",
        "classes": "bg-amber-50 text-amber-800 ring-amber-600/20",
        "description": "Recent reports disagree about this crossing's status.",
    },
}


# Derived community-report states render with the same badges.
_STATUS_BADGES["closed_reported"] = _STATUS_BADGES["closed"]
_STATUS_BADGES["open_reported"] = _STATUS_BADGES["open"]


@register.inclusion_tag("components/status_badge.html")
def status_badge(key):
    return {"badge": _STATUS_BADGES.get(key) or _STATUS_BADGES["unknown"]}


_SOURCE_BADGES = {
    "osm": {
        "label": "OpenStreetMap reference",
        "icon": "map",
        "classes": "bg-slate-50 text-slate-700 ring-slate-600/20",
    },
    "community": {
        "label": "Community report · unverified",
        "icon": "users",
        "classes": "bg-sky-50 text-sky-800 ring-sky-600/20",
    },
    "manual": {
        "label": "Manually added reference",
        "icon": "map",
        "classes": "bg-slate-50 text-slate-700 ring-slate-600/20",
    },
    "simulated": {
        "label": "Simulated",
        "icon": "flask-conical",
        "classes": "bg-violet-50 text-violet-800 ring-violet-600/20",
    },
}

_UNKNOWN_SOURCE = {
    "label": "Unknown source",
    "icon": "circle-help",
    "classes": "bg-slate-50 text-slate-700 ring-slate-600/20",
}


@register.inclusion_tag("components/source_badge.html")
def source_badge(key):
    return {"badge": _SOURCE_BADGES.get(key) or _UNKNOWN_SOURCE}
