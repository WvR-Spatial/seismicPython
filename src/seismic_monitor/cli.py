"""Command line entry point.

Exit codes matter here: this runs unattended in CI, and the previous version
caught every exception and still exited 0, so a broken run looked like a
successful one and stale output stayed published.

    0  success
    1  a data source or rendering step failed
    2  bad invocation
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import DEFAULT_CITIES_PATH, DEFAULT_OUTPUT_DIR, USGS_FEEDS, Config
from .data import DataError
from .pipeline import run
from .theme import BASEMAPS

log = logging.getLogger("seismic_monitor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seismic-monitor",
        description=(
            "Build a seismic risk dashboard from the live USGS earthquake feed."
        ),
    )
    parser.add_argument(
        "--feed",
        choices=sorted(USGS_FEEDS),
        default="week",
        help="Which USGS summary feed to read (default: week).",
    )
    parser.add_argument(
        "--quakes-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Read a GeoJSON feed from disk instead of the network (offline runs, tests).",
    )
    parser.add_argument(
        "--cities",
        type=Path,
        default=DEFAULT_CITIES_PATH,
        help="Populated places GeoJSON (default: the vendored Natural Earth 1:10m layer).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where to write the site (default: ./site).",
    )
    parser.add_argument(
        "-m", "--min-magnitude",
        type=float,
        default=4.0,
        help="Minimum magnitude to map (default: 4.0).",
    )
    parser.add_argument(
        "-r", "--radius-km",
        type=float,
        default=50.0,
        help="Impact radius in kilometres, measured geodesically (default: 50).",
    )
    parser.add_argument(
        "--basemap",
        choices=sorted(BASEMAPS),
        default="esri-dark",
        help=(
            "Tile layer for the map (default: esri-dark). 'carto-dark' requires a "
            "CARTO_API_KEY environment variable; CARTO watermarks unauthenticated tiles."
        ),
    )
    parser.add_argument(
        "--max-chart-cities",
        type=int,
        default=15,
        help="How many places to show in the ranked chart (default: 15).",
    )
    parser.add_argument(
        "--chart-png",
        action="store_true",
        help=(
            "Also write a static risk_chart.png. Requires kaleido>=1 plus a local Chrome "
            "(`plotly_get_chrome`); off by default so scheduled builds stay lean."
        ),
    )
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="Exit non-zero when no populated place is affected (default: succeed).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Debug logging.",
    )
    return parser


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    if args.radius_km <= 0:
        log.error("--radius-km must be positive")
        return 2
    if args.quakes_file is not None and not args.quakes_file.exists():
        log.error("--quakes-file %s does not exist", args.quakes_file)
        return 2

    config = Config(
        feed=args.feed,
        quakes_path=args.quakes_file,
        cities_path=args.cities,
        output_dir=args.output_dir,
        min_magnitude=args.min_magnitude,
        radius_km=args.radius_km,
        max_chart_cities=args.max_chart_cities,
        basemap=args.basemap,
        chart_png=args.chart_png,
    )

    try:
        result = run(config)
    except DataError as exc:
        log.error("%s", exc)
        return 1
    except Exception:  # noqa: BLE001 - top level, logged with a traceback
        log.exception("Run failed")
        return 1

    digest = result["digest"]
    log.info(
        "Done: %d events at/above M%.1f, %d affected places, %s people in range",
        digest["events_above_threshold"],
        config.min_magnitude,
        digest["cities_affected"],
        f"{digest['population_exposed']:,}",
    )
    _emit_github_summary(digest, config)

    if args.fail_on_empty and digest["cities_affected"] == 0:
        log.error("No affected places and --fail-on-empty was set")
        return 1
    return 0


def _emit_github_summary(digest: dict, config: Config) -> None:
    """Write a short report to the GitHub Actions job summary, if we're in CI."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    strongest = digest.get("strongest_event") or {}
    lines = [
        "### Seismic Risk Monitor",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Feed | `{config.feed}` |",
        f"| Events in feed | {digest['events_in_feed']:,} |",
        f"| Events at/above M{config.min_magnitude:g} | {digest['events_above_threshold']:,} |",
        f"| Affected places | {digest['cities_affected']:,} |",
        f"| Population in range | {digest['population_exposed']:,} |",
        f"| Strongest event | {strongest.get('title') or '--'} |",
        "",
    ]
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
