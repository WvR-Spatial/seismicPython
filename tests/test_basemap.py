"""Basemap selection and access-token handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from seismic_monitor import theme
from seismic_monitor.config import Config
from seismic_monitor.pipeline import run
from seismic_monitor.render import resolve_token

CITIES = Path(__file__).resolve().parents[1] / "data" / "ne_10m_populated_places.geojson"

FAKE_TOKEN = "pk.test0000000000000000000000000000000000000000000000000000000000"


def build(tmp_path, feed_path, **overrides) -> str:
    config = Config(
        quakes_path=feed_path,
        cities_path=CITIES,
        output_dir=tmp_path / "site",
        **overrides,
    )
    run(config)
    return (Path(config.output_dir) / "seismic_risk_map.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _no_ambient_tokens(monkeypatch):
    """Never let a developer's real token leak into an assertion."""
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)
    monkeypatch.delenv("CARTO_API_KEY", raising=False)


def test_mapbox_is_the_default_basemap() -> None:
    assert Config().basemap == "mapbox-dark"
    assert theme.PREFERRED_BASEMAP == "mapbox-dark"


def test_token_comes_from_config_then_environment(monkeypatch) -> None:
    assert resolve_token("mapbox-dark", Config()) is None

    monkeypatch.setenv("MAPBOX_TOKEN", "from-env")
    assert resolve_token("mapbox-dark", Config()) == "from-env"

    # An explicit token wins over the environment.
    assert resolve_token("mapbox-dark", Config(mapbox_token="explicit")) == "explicit"

    # Keyless basemaps report no token at all.
    assert resolve_token("esri-dark", Config(mapbox_token="explicit")) is None


def test_mapbox_tiles_are_used_when_a_token_is_available(tmp_path, feed_path) -> None:
    html = build(tmp_path, feed_path, mapbox_token=FAKE_TOKEN)
    assert "api.mapbox.com/styles/v1/mapbox/dark-v11" in html
    assert FAKE_TOKEN in html
    assert "Improve this map" in html, "Mapbox attribution is required by their terms"


def test_environment_token_is_picked_up(tmp_path, feed_path, monkeypatch) -> None:
    monkeypatch.setenv("MAPBOX_TOKEN", FAKE_TOKEN)
    html = build(tmp_path, feed_path)
    assert "api.mapbox.com" in html
    assert FAKE_TOKEN in html


def test_without_a_token_it_falls_back_instead_of_breaking(tmp_path, feed_path) -> None:
    """A tokenless Mapbox layer 401s on every tile -- a blank map, silently."""
    html = build(tmp_path, feed_path)
    assert "api.mapbox.com" not in html
    assert "server.arcgisonline.com" in html


def test_the_token_placeholder_never_reaches_the_output(tmp_path, feed_path) -> None:
    for kwargs in ({}, {"mapbox_token": FAKE_TOKEN}, {"basemap": "carto-dark"}):
        html = build(tmp_path / str(len(kwargs)), feed_path, **kwargs)
        assert "%7Btoken%7D" not in html
        assert "{token}" not in html
        assert "access_token=&" not in html
        assert not html.rstrip().endswith("access_token=")


def test_a_keyless_alternative_layer_is_always_offered(tmp_path, feed_path) -> None:
    html = build(tmp_path, feed_path, mapbox_token=FAKE_TOKEN)
    assert "tile.openstreetmap.org" in html


def test_every_mapbox_style_resolves(tmp_path, feed_path) -> None:
    for index, key in enumerate(k for k in theme.BASEMAPS if k.startswith("mapbox-")):
        html = build(tmp_path / f"m{index}", feed_path, basemap=key, mapbox_token=FAKE_TOKEN)
        assert "api.mapbox.com" in html


def test_carto_still_needs_its_own_key(tmp_path, feed_path) -> None:
    """A Mapbox token must not be used to authenticate a CARTO layer."""
    html = build(tmp_path, feed_path, basemap="carto-dark", mapbox_token=FAKE_TOKEN)
    assert "cartocdn.com" not in html
    assert "server.arcgisonline.com" in html


def test_unknown_basemap_falls_back_quietly(tmp_path, feed_path) -> None:
    html = build(tmp_path, feed_path, basemap="not-a-basemap")
    assert "server.arcgisonline.com" in html


def test_no_token_is_written_into_the_exported_data(tmp_path, feed_path) -> None:
    config = Config(
        quakes_path=feed_path,
        cities_path=CITIES,
        output_dir=tmp_path / "site",
        mapbox_token=FAKE_TOKEN,
    )
    run(config)
    for name in ("summary.json", "impacted_cities.csv", "impact_zones.geojson", "index.html"):
        text = (Path(config.output_dir) / name).read_text(encoding="utf-8")
        assert FAKE_TOKEN not in text, f"{name} leaked the access token"
