"""Risk analysis: geodesic impact zones and the cities that fall inside them."""

from __future__ import annotations

import logging

import geopandas as gpd
import pandas as pd

from .geodesy import GEOD, geodesic_circle, split_antimeridian

log = logging.getLogger(__name__)

WGS84 = "EPSG:4326"


def build_risk_zones(
    quakes: gpd.GeoDataFrame,
    *,
    min_magnitude: float,
    radius_m: float,
    segments: int = 180,
) -> gpd.GeoDataFrame:
    """Geodesic impact polygons for every event at or above ``min_magnitude``."""
    if quakes.empty:
        return _empty_like(quakes)

    significant = quakes[quakes["mag"] >= min_magnitude].copy()
    log.info(
        "%d of %d events are at or above M%.1f",
        len(significant),
        len(quakes),
        min_magnitude,
    )
    if significant.empty:
        return _empty_like(quakes)

    geometries = [
        split_antimeridian(
            geodesic_circle(point.x, point.y, radius_m, segments=segments)
        )
        for point in significant.geometry
    ]

    zones = significant.copy()
    zones["epicentre_lon"] = significant.geometry.x.to_numpy()
    zones["epicentre_lat"] = significant.geometry.y.to_numpy()
    zones = zones.set_geometry(gpd.GeoSeries(geometries, index=zones.index, crs=WGS84))

    invalid = ~zones.geometry.is_valid
    if invalid.any():
        log.warning("Repairing %d invalid impact polygons", int(invalid.sum()))
        zones.loc[invalid, "geometry"] = zones.loc[invalid, "geometry"].buffer(0)

    return zones


def _empty_like(quakes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    columns = list(quakes.columns) + ["epicentre_lon", "epicentre_lat"]
    return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=WGS84)


def find_impacted_cities(
    cities: gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Spatially join cities to impact zones.

    Returns ``(pairs, summary)``:

    * ``pairs``   - one row per city/event combination, with the geodesic
      distance from the city to that epicentre.
    * ``summary`` - one row per *city*, carrying the strongest event that
      reaches it, the nearest one, and how many events do.

    The original code returned the raw join, so a city inside three overlapping
    zones appeared three times and was counted three times in the chart.
    """
    empty_pairs = gpd.GeoDataFrame(columns=list(cities.columns), geometry="geometry", crs=WGS84)
    if cities.empty or zones.empty:
        return empty_pairs, empty_pairs.copy()

    pairs = gpd.sjoin(cities, zones, how="inner", predicate="intersects", rsuffix="quake")
    if pairs.empty:
        log.info("No populated places fall inside any impact zone")
        return empty_pairs, empty_pairs.copy()

    pairs = pairs.drop(columns=["index_quake"], errors="ignore").reset_index(drop=True)

    _, _, distances = GEOD.inv(
        pairs.geometry.x.to_numpy(),
        pairs.geometry.y.to_numpy(),
        pairs["epicentre_lon"].to_numpy(),
        pairs["epicentre_lat"].to_numpy(),
    )
    pairs["distance_km"] = distances / 1000.0

    summary = _summarise(pairs)
    log.info(
        "%d populated places affected by %d events (%d city-event pairs)",
        len(summary),
        pairs["id"].nunique(),
        len(pairs),
    )
    return pairs, summary


def _summarise(pairs: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Collapse city-event pairs to one row per city."""
    strongest = pairs.sort_values(
        ["mag", "distance_km"], ascending=[False, True]
    ).drop_duplicates(subset="city_id", keep="first")

    nearest = (
        pairs.sort_values("distance_km", ascending=True)
        .drop_duplicates(subset="city_id", keep="first")
        .set_index("city_id")
    )

    counts = pairs.groupby("city_id").agg(
        event_count=("id", "nunique"),
        max_magnitude=("mag", "max"),
        min_distance_km=("distance_km", "min"),
    )

    summary = strongest.set_index("city_id").join(counts)
    summary["nearest_event_title"] = nearest["title"]
    summary["nearest_event_km"] = nearest["distance_km"]
    summary["nearest_event_mag"] = nearest["mag"]

    summary = summary.reset_index()
    summary = summary.sort_values(
        ["max_magnitude", "pop_max"], ascending=[False, False]
    ).reset_index(drop=True)
    return gpd.GeoDataFrame(summary, geometry="geometry", crs=WGS84)


def summarise_run(
    quakes: gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
    summary: gpd.GeoDataFrame,
    *,
    min_magnitude: float,
    radius_km: float,
) -> dict:
    """A small JSON-serialisable digest of the run, for the landing page."""
    population = int(summary["pop_max"].sum()) if not summary.empty else 0
    strongest = None
    if not zones.empty:
        row = zones.loc[zones["mag"].idxmax()]
        strongest = {
            "magnitude": float(row["mag"]),
            "title": row.get("title"),
            "place": row.get("place"),
            "url": row.get("url"),
            "time_utc": _iso(row.get("time_utc")),
        }

    return {
        "events_in_feed": int(len(quakes)),
        "events_above_threshold": int(len(zones)),
        "cities_affected": int(len(summary)),
        "population_exposed": population,
        "countries_affected": (
            int(summary["adm0name"].nunique())
            if not summary.empty and "adm0name" in summary
            else 0
        ),
        "strongest_event": strongest,
        "min_magnitude": min_magnitude,
        "radius_km": radius_km,
        "feed_window": {
            "earliest_utc": _iso(quakes["time_utc"].min()) if not quakes.empty else None,
            "latest_utc": _iso(quakes["time_utc"].max()) if not quakes.empty else None,
        },
    }


def _iso(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")
