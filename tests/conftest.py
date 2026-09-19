from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def feed_path() -> Path:
    return FIXTURES / "sample_feed.geojson"


@pytest.fixture(scope="session")
def feed_payload(feed_path: Path) -> dict:
    return json.loads(feed_path.read_text(encoding="utf-8"))


@pytest.fixture()
def tiny_cities() -> gpd.GeoDataFrame:
    """A handful of places, positioned relative to the fixture events.

    The Alaskan trio is the regression test for the Web Mercator bug: at 61.2N a
    naive EPSG:3857 buffer of "50 km" covers only ~24 km of ground, so a place
    35 km from the epicentre is inside a true geodesic zone and outside the
    projected one.
    """
    rows = [
        # Two fixture events sit within 50 km of this one -- the dedupe case.
        {"city_id": 1, "name": "Istanbul", "adm0name": "Turkey", "adm1name": "Istanbul",
         "iso_a2": "TR", "pop_max": 13710512, "geometry": Point(28.955, 41.013)},
        # On top of the Anchorage epicentre.
        {"city_id": 2, "name": "Anchorage", "adm0name": "United States of America",
         "adm1name": "Alaska", "iso_a2": "US", "pop_max": 275043,
         "geometry": Point(-149.90, 61.22)},
        # ~35 km east: inside a true 50 km circle, outside a naive Mercator one.
        {"city_id": 3, "name": "Eagle River", "adm0name": "United States of America",
         "adm1name": "Alaska", "iso_a2": "US", "pop_max": 24793,
         "geometry": Point(-149.2475, 61.22)},
        # ~70 km east: outside either.
        {"city_id": 4, "name": "Palmer", "adm0name": "United States of America",
         "adm1name": "Alaska", "iso_a2": "US", "pop_max": 7000,
         "geometry": Point(-148.60, 61.22)},
        # Just east of the date line, near the 179.8E event.
        {"city_id": 5, "name": "Dateline Town", "adm0name": "Fiji", "adm1name": "",
         "iso_a2": "FJ", "pop_max": 25000, "geometry": Point(-179.95, -16.50)},
        # Nowhere near anything in the fixture.
        {"city_id": 6, "name": "Perth", "adm0name": "Australia",
         "adm1name": "Western Australia", "iso_a2": "AU", "pop_max": 1968000,
         "geometry": Point(115.86, -31.95)},
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
