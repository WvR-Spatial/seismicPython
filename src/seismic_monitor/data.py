"""Loading the two inputs: the live USGS feed and the vendored cities layer."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from shapely.geometry import Point
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"

USER_AGENT = (
    "seismic-risk-monitor/2.0 (+https://github.com/WvR-Spatial/seismicPython)"
)


class DataError(RuntimeError):
    """Raised when an input cannot be loaded or is structurally unusable."""


def _session(retries: int) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_quakes(
    url: str,
    *,
    timeout: int = 30,
    retries: int = 3,
    local_path: Path | None = None,
) -> gpd.GeoDataFrame:
    """Fetch the USGS GeoJSON feed (or read it from ``local_path``).

    Raises :class:`DataError` on any failure. The old version returned an empty
    frame and carried on, which meant a network outage silently published an
    empty map.
    """
    if local_path is not None:
        log.info("Reading quake feed from %s", local_path)
        payload = json.loads(Path(local_path).read_text(encoding="utf-8"))
    else:
        log.info("Fetching quake feed: %s", url)
        try:
            with _session(retries) as session:
                response = session.get(url, timeout=timeout)
                response.raise_for_status()
                payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise DataError(f"Could not fetch the USGS feed: {exc}") from exc

    return _quakes_to_frame(payload)


def _quakes_to_frame(payload: dict) -> gpd.GeoDataFrame:
    features = payload.get("features")
    if features is None:
        raise DataError("Feed payload has no 'features' member")

    rows = []
    for feature in features:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        depth_km = float(coords[2]) if len(coords) > 2 and coords[2] is not None else None
        mag = props.get("mag")
        rows.append(
            {
                "id": feature.get("id"),
                "mag": float(mag) if mag is not None else None,
                "place": props.get("place"),
                "title": props.get("title"),
                "time": props.get("time"),
                "url": props.get("url"),
                "tsunami": int(props.get("tsunami") or 0),
                "sig": props.get("sig"),
                "depth_km": depth_km,
                "lon": lon,
                "lat": lat,
                "geometry": Point(lon, lat),
            }
        )

    if not rows:
        log.warning("Feed contained no usable features")
        return gpd.GeoDataFrame(
            columns=["id", "mag", "place", "title", "time", "url", "geometry"],
            geometry="geometry",
            crs=WGS84,
        )

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)
    gdf = gdf.dropna(subset=["mag"])
    gdf["time_utc"] = pd.to_datetime(gdf["time"], unit="ms", utc=True, errors="coerce")
    log.info("Loaded %d events with a magnitude", len(gdf))
    return gdf


def load_cities(path: Path) -> gpd.GeoDataFrame:
    """Load the vendored Natural Earth populated places layer."""
    path = Path(path)
    if not path.exists():
        raise DataError(
            f"Cities dataset not found at {path}. "
            "Run `python tools/vendor_cities.py` to rebuild it."
        )

    log.info("Loading cities from %s", path)
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84)
    elif gdf.crs.to_string() != WGS84:
        gdf = gdf.to_crs(WGS84)

    required = {"name", "pop_max"}
    missing = required - set(gdf.columns)
    if missing:
        raise DataError(f"Cities dataset is missing columns: {sorted(missing)}")

    gdf["pop_max"] = pd.to_numeric(gdf["pop_max"], errors="coerce").fillna(0).astype(int)
    if "city_id" not in gdf.columns:
        gdf["city_id"] = gdf.index.astype(int)

    log.info("Loaded %d populated places", len(gdf))
    return gdf
