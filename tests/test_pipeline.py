"""End-to-end behaviour, including the CI contract: exit codes and outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seismic_monitor.cli import main
from seismic_monitor.config import Config
from seismic_monitor.data import DataError, fetch_quakes
from seismic_monitor.pipeline import run

CITIES = Path(__file__).resolve().parents[1] / "data" / "ne_10m_populated_places.geojson"

EXPECTED_FILES = [
    "index.html",
    "seismic_risk_map.html",
    "risk_chart.html",
    "summary.json",
    "impacted_cities.csv",
    "impact_zones.geojson",
]


@pytest.fixture()
def built(tmp_path, feed_path):
    config = Config(
        quakes_path=feed_path,
        cities_path=CITIES,
        output_dir=tmp_path / "site",
        min_magnitude=4.0,
        radius_km=50.0,
    )
    return config, run(config)


def test_run_writes_every_expected_file(built) -> None:
    config, _ = built
    for filename in EXPECTED_FILES:
        path = Path(config.output_dir) / filename
        assert path.exists(), f"{filename} was not written"
        assert path.stat().st_size > 0


def test_chart_html_is_not_bloated(built) -> None:
    """The old chart inlined plotly.js and weighed 4.5 MB."""
    config, _ = built
    size = (Path(config.output_dir) / "risk_chart.html").stat().st_size
    assert size < 400_000, f"chart is {size} bytes; plotly.js should load from the CDN"


def test_map_and_page_carry_a_generated_timestamp(built) -> None:
    """A page that rebuilds itself must say when it last did."""
    from datetime import datetime

    config, result = built
    stamp = datetime.fromisoformat(result["digest"]["generated_at_utc"].replace("Z", "+00:00"))
    human = stamp.strftime("%d %b %Y, %H:%M UTC")

    map_html = (Path(config.output_dir) / "seismic_risk_map.html").read_text(encoding="utf-8")
    assert "Generated" in map_html
    assert human in map_html

    index_html = (Path(config.output_dir) / "index.html").read_text(encoding="utf-8")
    assert human in index_html


def test_summary_json_round_trips(built) -> None:
    config, result = built
    payload = json.loads((Path(config.output_dir) / "summary.json").read_text())
    assert payload["events_above_threshold"] == result["digest"]["events_above_threshold"]
    assert payload["generated_at_utc"].endswith("Z")
    assert payload["radius_km"] == 50.0


def test_real_cities_layer_has_useful_coverage() -> None:
    """The 1:110m layer had 243 places, which made the analysis near-inert."""
    from seismic_monitor.data import load_cities

    cities = load_cities(CITIES)
    assert len(cities) > 7_000
    assert cities["pop_max"].max() > 10_000_000
    assert cities.crs.to_string() == "EPSG:4326"


def test_cli_succeeds_on_the_fixture(tmp_path, feed_path) -> None:
    code = main([
        "--quakes-file", str(feed_path),
        "--cities", str(CITIES),
        "--output-dir", str(tmp_path / "site"),
    ])
    assert code == 0
    assert (tmp_path / "site" / "index.html").exists()


def test_cli_rejects_a_missing_feed_file(tmp_path) -> None:
    assert main(["--quakes-file", str(tmp_path / "nope.geojson")]) == 2


def test_cli_rejects_a_negative_radius(tmp_path, feed_path) -> None:
    assert main(["--quakes-file", str(feed_path), "--radius-km", "-5"]) == 2


def test_cli_fails_loudly_when_the_feed_cannot_be_read(tmp_path, monkeypatch) -> None:
    """A network failure must exit non-zero, not publish an empty map."""
    import seismic_monitor.pipeline as pipeline

    def boom(*_args, **_kwargs):
        raise DataError("simulated outage")

    monkeypatch.setattr(pipeline, "fetch_quakes", boom)
    assert main(["--output-dir", str(tmp_path / "site")]) == 1
    assert not (tmp_path / "site" / "index.html").exists()


def test_fail_on_empty_flag(tmp_path, feed_path) -> None:
    code = main([
        "--quakes-file", str(feed_path),
        "--cities", str(CITIES),
        "--output-dir", str(tmp_path / "site"),
        "--min-magnitude", "9.9",
        "--fail-on-empty",
    ])
    assert code == 1


def test_missing_cities_file_is_an_explicit_error(tmp_path, feed_path) -> None:
    with pytest.raises(DataError, match="Cities dataset not found"):
        run(Config(
            quakes_path=feed_path,
            cities_path=tmp_path / "absent.geojson",
            output_dir=tmp_path / "site",
        ))


def test_malformed_feed_is_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.geojson"
    bad.write_text(json.dumps({"type": "FeatureCollection"}), encoding="utf-8")
    with pytest.raises(DataError, match="features"):
        fetch_quakes("", local_path=bad)
