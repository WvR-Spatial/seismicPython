"""The geometry that the previous version got wrong."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from seismic_monitor.geodesy import GEOD, geodesic_circle, split_antimeridian

RADIUS_M = 50_000.0


@pytest.mark.parametrize("lat", [0.0, 35.0, 61.2, -45.0, 78.0])
def test_circle_vertices_sit_at_the_requested_distance(lat: float) -> None:
    circle = geodesic_circle(10.0, lat, RADIUS_M, segments=120)
    for x, y in circle.exterior.coords:
        _, _, distance = GEOD.inv(10.0, lat, x, y)
        assert distance == pytest.approx(RADIUS_M, rel=1e-6)


def test_mercator_buffer_is_wrong_and_geodesic_is_not() -> None:
    """The regression this rewrite exists for.

    A 50 km EPSG:3857 buffer at 61.2N covers roughly 24 km of ground. A place
    35 km from the epicentre is therefore missed by the projected buffer and
    caught by the geodesic one.
    """
    lon, lat = -149.90, 61.22
    town = Point(-149.2475, 61.22)

    _, _, separation = GEOD.inv(lon, lat, town.x, town.y)
    assert 30_000 < separation < 40_000  # sanity: the town really is ~35 km away

    mercator_zone = (
        gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
        .to_crs(3857)
        .buffer(RADIUS_M)
        .to_crs(4326)
        .iloc[0]
    )
    assert not mercator_zone.contains(town), "the old projected buffer under-covers"
    assert geodesic_circle(lon, lat, RADIUS_M).contains(town)


def test_circle_area_is_stable_across_latitudes() -> None:
    """Equal radii must give equal ground areas, whatever the latitude."""
    areas = []
    for lat in (0.0, 30.0, 60.0, 75.0):
        circle = geodesic_circle(0.0, lat, RADIUS_M, segments=360)
        area, _ = GEOD.geometry_area_perimeter(circle)
        areas.append(abs(area))
    reference = areas[0]
    for area in areas[1:]:
        assert area == pytest.approx(reference, rel=2e-3)


def test_circle_east_of_dateline_splits_into_two_pieces() -> None:
    circle = geodesic_circle(179.85, -16.5, RADIUS_M)
    assert circle.bounds[2] > 180.0, "unwrapped circle should overshoot 180"

    split = split_antimeridian(circle)
    assert isinstance(split, MultiPolygon)
    assert len(split.geoms) == 2
    minx, _, maxx, _ = split.bounds
    assert minx >= -180.0 and maxx <= 180.0


def test_circle_west_of_dateline_splits_into_two_pieces() -> None:
    split = split_antimeridian(geodesic_circle(-179.85, 51.5, RADIUS_M))
    assert isinstance(split, MultiPolygon)
    assert len(split.geoms) == 2
    assert split.bounds[0] >= -180.0 and split.bounds[2] <= 180.0


def test_split_preserves_area() -> None:
    circle = geodesic_circle(179.9, 0.0, RADIUS_M, segments=360)
    split = split_antimeridian(circle)
    before, _ = GEOD.geometry_area_perimeter(circle)
    after = sum(abs(GEOD.geometry_area_perimeter(g)[0]) for g in split.geoms)
    assert after == pytest.approx(abs(before), rel=1e-3)


def test_split_leaves_ordinary_circles_alone() -> None:
    circle = geodesic_circle(0.0, 0.0, RADIUS_M)
    assert split_antimeridian(circle) is circle


def test_a_city_across_the_dateline_is_caught() -> None:
    zone = split_antimeridian(geodesic_circle(179.80, -16.50, RADIUS_M))
    assert zone.intersects(Point(-179.95, -16.50))


def test_circle_enclosing_a_pole_is_a_valid_cap() -> None:
    circle = geodesic_circle(0.0, 89.9, 100_000.0)
    assert isinstance(circle, Polygon)
    assert circle.is_valid
    assert circle.bounds[0] == -180.0 and circle.bounds[2] == 180.0


def test_invalid_arguments_are_rejected() -> None:
    with pytest.raises(ValueError):
        geodesic_circle(0.0, 0.0, -1.0)
    with pytest.raises(ValueError):
        geodesic_circle(0.0, 0.0, RADIUS_M, segments=4)
