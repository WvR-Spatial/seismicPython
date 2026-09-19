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

MAPBOX_ATTRIBUTION = (
    '&copy; <a href="https://www.mapbox.com/about/maps/" target="_blank" '
    'rel="noopener">Mapbox</a> '
    '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" '
    'rel="noopener">OpenStreetMap</a> '
    '<a href="https://www.mapbox.com/map-feedback/" target="_blank" '
    'rel="noopener"><strong>Improve this map</strong></a>'
)

def _mapbox(style: str, label: str) -> dict[str, str]:
    return {
        "url": (
            f"https://api.mapbox.com/styles/v1/mapbox/{style}/tiles/256/"
            "{z}/{x}/{y}@2x?access_token={token}"
        ),
        "attr": MAPBOX_ATTRIBUTION,
        "name": f"{label} (Mapbox)",
        "max_zoom": "22",
        "token_env": "MAPBOX_TOKEN",
    }


#: Basemaps, keyed by the CLI ``--basemap`` value.
#:
#: ``token_env`` names the environment variable holding that provider's access
#: token. A basemap that needs one and cannot find it falls back to
#: :data:`DEFAULT_BASEMAP` rather than rendering broken or watermarked tiles.
#:
#: Note what is *not* here: ``tile.openstreetmap.org``. The OSM Foundation's Tile
#: Usage Policy does not permit their servers to be used as a general basemap by
#: a third-party application -- it requires a distinctive User-Agent, a valid
#: Referer, local caching, and forbids automated or bulk fetching, and a
#: published dashboard serving arbitrary visitors gets flagged as misuse. OSM
#: data still underpins the Mapbox styles; Mapbox serves the tiles and carries
#: the attribution.
#:
#: CARTO's raster basemaps (``dark_matter``, ``positron``) now require an API key
#: and stamp an "API KEY REQUIRED" watermark across unauthenticated tiles, which
#: is why the keyless fallback is Esri's dark canvas rather than CARTO's.
BASEMAPS: dict[str, dict[str, str]] = {
    "mapbox-dark": _mapbox("dark-v11", "Dark"),
    "mapbox-satellite": _mapbox("satellite-streets-v12", "Satellite"),
    "mapbox-outdoors": _mapbox("outdoors-v12", "Terrain"),
    "mapbox-light": _mapbox("light-v11", "Light"),
    "mapbox-streets": _mapbox("streets-v12", "Streets"),
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
    "carto-dark": {
        "url": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key={token}",
        "attr": "&copy; OpenStreetMap contributors &copy; CARTO",
        "name": "Dark matter (CARTO)",
        "max_zoom": "20",
        "token_env": "CARTO_API_KEY",
    },
}

#: Preferred basemap. Needs MAPBOX_TOKEN; without it the build silently uses
#: DEFAULT_BASEMAP so a local run with no credentials still produces a usable map.
PREFERRED_BASEMAP = "mapbox-dark"

#: Keyless basemap used whenever a token-bearing basemap has no token.
DEFAULT_BASEMAP = "esri-dark"

#: Extra base layers offered in the layer switcher alongside the chosen one.
#: Satellite gives physical context for a remote epicentre and terrain shows the
#: relief that usually explains why the seismicity is there. One Mapbox token
#: covers every style, so these cost nothing extra to offer.
MAPBOX_ALTERNATES = ("mapbox-satellite", "mapbox-outdoors")

#: Alternates for the keyless fallback, so the switcher is never a single entry.
KEYLESS_ALTERNATES = ("esri-light",)
