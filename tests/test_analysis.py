from __future__ import annotations

import geopandas as gpd
import pytest

from seismic_monitor.analysis import build_risk_zones, find_impacted_cities, summarise_run
from seismic_monitor.data import fetch_quakes

RADIUS_M = 50_000.0


@pytest.fixture()
def quakes(feed_path):
    return fetch_quakes("", local_path=feed_path)


@pytest.fixture()
def zones(quakes):
    return build_risk_zones(quakes, min_magnitude=4.0, radius_m=RADIUS_M)


def test_feed_parsing_keeps_the_fields_the_map_needs(quakes) -> None:
    assert len(quakes) == 8
    for column in ("id", "mag", "place", "title", "url", "depth_km", "time_utc"):
        assert column in quakes.columns
    assert quakes["time_utc"].notna().all()
    assert quakes["depth_km"].notna().all()


def test_magnitude_threshold_is_applied(quakes) -> None:
    zones = build_risk_zones(quakes, min_magnitude=4.0, radius_m=RADIUS_M)
    assert len(zones) == 7  # the M3.1 Tokyo event is excluded
    assert zones["mag"].min() >= 4.0

    higher = build_risk_zones(quakes, min_magnitude=6.0, radius_m=RADIUS_M)
    assert len(higher) == 3


def test_no_qualifying_events_yields_an_empty_frame(quakes) -> None:
    zones = build_risk_zones(quakes, min_magnitude=9.9, radius_m=RADIUS_M)
    assert zones.empty
    assert zones.crs is not None


def test_every_zone_is_valid_and_within_map_bounds(zones) -> None:
    assert zones.geometry.is_valid.all()
    minx, miny, maxx, maxy = zones.total_bounds
    assert minx >= -180.0 and maxx <= 180.0
    assert miny >= -90.0 and maxy <= 90.0


def test_join_finds_the_expected_places(zones, tiny_cities) -> None:
    _, summary = find_impacted_cities(tiny_cities, zones)
    found = set(summary["name"])
    assert {"Istanbul", "Anchorage", "Eagle River", "Dateline Town"} == found
    assert "Palmer" not in found  # 70 km away
    assert "Perth" not in found


def test_each_city_appears_once_with_its_worst_event(zones, tiny_cities) -> None:
    """The old code returned the raw join, so a city in N zones appeared N times."""
    pairs, summary = find_impacted_cities(tiny_cities, zones)

    istanbul_pairs = pairs[pairs["name"] == "Istanbul"]
    assert len(istanbul_pairs) == 2, "fixture places two events within range"

    assert summary["city_id"].is_unique
    istanbul = summary.loc[summary["name"] == "Istanbul"].iloc[0]
    assert istanbul["event_count"] == 2
    assert istanbul["max_magnitude"] == pytest.approx(6.0)
    assert istanbul["nearest_event_km"] <= istanbul["min_distance_km"] + 1e-9


def test_distances_are_reported_and_bounded_by_the_radius(zones, tiny_cities) -> None:
    pairs, _ = find_impacted_cities(tiny_cities, zones)
    assert (pairs["distance_km"] <= 50.0 + 0.01).all()
    assert (pairs["distance_km"] >= 0.0).all()


def test_summary_is_sorted_worst_first(zones, tiny_cities) -> None:
    _, summary = find_impacted_cities(tiny_cities, zones)
    magnitudes = summary["max_magnitude"].tolist()
    assert magnitudes == sorted(magnitudes, reverse=True)


def test_empty_inputs_do_not_raise(zones, tiny_cities) -> None:
    empty = gpd.GeoDataFrame(columns=list(tiny_cities.columns), geometry="geometry", crs="EPSG:4326")
    pairs, summary = find_impacted_cities(empty, zones)
    assert pairs.empty and summary.empty


def test_digest_reports_the_run(quakes, zones, tiny_cities) -> None:
    _, summary = find_impacted_cities(tiny_cities, zones)
    digest = summarise_run(quakes, zones, summary, min_magnitude=4.0, radius_km=50.0)

    assert digest["events_in_feed"] == 8
    assert digest["events_above_threshold"] == 7
    assert digest["cities_affected"] == len(summary)
    assert digest["population_exposed"] == int(summary["pop_max"].sum())
    assert digest["strongest_event"]["magnitude"] == pytest.approx(7.0)
    assert digest["feed_window"]["earliest_utc"].endswith("Z")
