"""The end-to-end run, kept free of argument parsing and process concerns."""

from __future__ import annotations

import logging
from pathlib import Path

from .analysis import build_risk_zones, find_impacted_cities, summarise_run
from .config import Config
from .data import fetch_quakes, load_cities
from .render import render_all

log = logging.getLogger(__name__)


def run(config: Config) -> dict:
    """Fetch, analyse and render. Raises on failure; never fails silently."""
    quakes = fetch_quakes(
        config.quakes_url,
        timeout=config.http_timeout,
        retries=config.http_retries,
        local_path=config.quakes_path,
    )
    cities = load_cities(config.cities_path)

    zones = build_risk_zones(
        quakes,
        min_magnitude=config.min_magnitude,
        radius_m=config.radius_m,
        segments=config.circle_segments,
    )
    pairs, summary = find_impacted_cities(cities, zones)

    digest = summarise_run(
        quakes,
        zones,
        summary,
        min_magnitude=config.min_magnitude,
        radius_km=config.radius_km,
    )
    paths = render_all(zones, pairs, summary, digest, config)

    log.info("Wrote %d files to %s", len(paths), Path(config.output_dir).resolve())
    return {"digest": digest, "paths": paths, "summary": summary, "zones": zones}
