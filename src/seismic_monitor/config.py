"""Runtime configuration for the seismic risk monitor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Repository root, resolved from this file: src/seismic_monitor/config.py -> ../../..
REPO_ROOT = Path(__file__).resolve().parents[2]

#: USGS summary feeds, keyed by the CLI ``--feed`` value.
#: See https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php
USGS_FEEDS: dict[str, str] = {
    "hour": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
    "day": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
    "week": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson",
    "month": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson",
    "significant_month": (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson"
    ),
}

DEFAULT_CITIES_PATH = REPO_ROOT / "data" / "ne_10m_populated_places.geojson"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "site"


@dataclass(frozen=True)
class Config:
    """Everything the pipeline needs to run, in one immutable object."""

    feed: str = "week"
    quakes_path: Path | None = None
    """Read the quake feed from this local GeoJSON file instead of the network."""

    cities_path: Path = DEFAULT_CITIES_PATH
    output_dir: Path = DEFAULT_OUTPUT_DIR

    min_magnitude: float = 4.0
    radius_km: float = 50.0
    """Impact radius, applied as a true geodesic distance on the WGS84 ellipsoid."""

    circle_segments: int = 180
    """Vertices per geodesic circle. 180 keeps the max chord error under ~0.02%."""

    max_chart_cities: int = 15
    http_timeout: int = 30
    http_retries: int = 3

    chart_png: bool = False
    """Also write a static PNG of the chart. Needs `kaleido` and a local Chrome."""

    basemap: str = "mapbox-dark"
    """Tile layer key -- see ``theme.BASEMAPS``.

    Mapbox styles need an access token (``--mapbox-token`` or ``MAPBOX_TOKEN``);
    without one the build falls back to the keyless Esri dark canvas.
    """

    mapbox_token: str | None = None
    """Mapbox public access token. Never read from, or stored in, the repository."""

    site_title: str = "Seismic Risk Monitor"
    repo_url: str = "https://github.com/WvR-Spatial/seismicPython"

    extra: dict = field(default_factory=dict)

    @property
    def quakes_url(self) -> str:
        try:
            return USGS_FEEDS[self.feed]
        except KeyError as exc:  # pragma: no cover - guarded by argparse choices
            raise ValueError(
                f"Unknown feed {self.feed!r}; expected one of {sorted(USGS_FEEDS)}"
            ) from exc

    @property
    def radius_m(self) -> float:
        return self.radius_km * 1000.0
