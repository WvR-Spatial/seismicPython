"""Shared visual tokens.

One place for the palette so the map, the chart and the landing page read as a
single system. Colours are taken from a validated dark-mode palette:
``#d95926`` (orange) and ``#3987e5`` (blue) clear the CVD-separation, chroma and
contrast gates against the ``#1a1a19`` surface.
"""

from __future__ import annotations

# Surfaces and ink
SURFACE_0 = "#121211"  # page background
SURFACE_1 = "#1a1a19"  # card / chart surface
SURFACE_2 = "#262624"  # raised surface, borders
TEXT_PRIMARY = "#ffffff"
TEXT_SECONDARY = "#c3c2b7"
TEXT_MUTED = "#8a8a80"

# Entities. Hazard (events and their impact zones) is orange; cities are blue.
# Two different things, two hues -- never a value-ramp across nominal cities.
HAZARD = "#d95926"
HAZARD_BRIGHT = "#ffae6b"
CITY = "#3987e5"

# Single-hue sequential ramp for the epicentre density layer. Bright reads as
# "more" on a dark basemap; one hue throughout, never a rainbow.
HEAT_GRADIENT = {
    0.30: "#5c2110",
    0.55: "#a83f1c",
    0.80: HAZARD,
    1.00: HAZARD_BRIGHT,
}

FONT_STACK = (
    "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)
MONO_STACK = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

#: Basemaps, keyed by the CLI ``--basemap`` value.
#:
#: CARTO's raster basemaps (``dark_matter``, ``positron``) now require an API key
#: and stamp an "API KEY REQUIRED" watermark across unauthenticated tiles, which
#: is why the default here is Esri's keyless dark canvas. Set ``CARTO_API_KEY``
#: and pass ``--basemap carto-dark`` to go back to CARTO.
BASEMAPS: dict[str, dict[str, str]] = {
    "esri-dark": {
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        "attr": "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
        "name": "Dark canvas (Esri)",
        "max_zoom": "16",
    },
    "esri-light": {
        "url": (
            "https://server.arcgisonline.com/ArcGIS/rest/services/"
            "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        ),
        "attr": "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
        "name": "Light canvas (Esri)",
        "max_zoom": "16",
    },
    "osm": {
        "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attr": "&copy; OpenStreetMap contributors",
        "name": "OpenStreetMap",
        "max_zoom": "19",
    },
    "carto-dark": {
        "url": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "attr": "&copy; OpenStreetMap contributors &copy; CARTO",
        "name": "Dark matter (CARTO)",
        "max_zoom": "20",
    },
}

DEFAULT_BASEMAP = "esri-dark"
#: Always offered as an alternative layer, so a tile outage never leaves a blank map.
FALLBACK_BASEMAP = "osm"
